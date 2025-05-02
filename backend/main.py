import asyncio
import uuid
import base64
import logging
import json
import ast
import os
import sys
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import socketio
import time

# Asegurar que el directorio backend esté en el path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

# Configura logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Inicialización ---
app = FastAPI(title="GeminiCodeExecution API")

# --- CORS (IMPORTANTE para desarrollo local) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, restringe a tu dominio frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket Setup ---
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", logger=True, engineio_logger=True)
socket_app = socketio.ASGIApp(sio, app)  # Monta Socket.IO sobre FastAPI de manera correcta

# Almacenamiento simple para tareas (en producción, usa algo más robusto como Redis)
active_tasks: Dict[str, Dict[str, Any]] = {}

# Variable global para controlar si Docker está disponible
docker_available = False
docker_error_message = "Docker no ha sido inicializado"

@app.on_event("startup")
async def startup_event():
    """Inicialización asíncrona al arrancar la aplicación"""
    global docker_available, docker_error_message
    
    # Importamos aquí para evitar problemas en la inicialización
    try:
        # Importar de forma relativa
        from backend.docker_executor import initialize_docker_image, get_docker_client
        from backend.gemini_client import configure_gemini
        
        # Configurar Gemini
        try:
            configure_gemini()
            logger.info("Gemini configurado correctamente")
        except Exception as e:
            logger.error(f"Error al configurar Gemini: {e}")
        
        # Verificar Docker
        docker_client = get_docker_client()
        if docker_client:
            docker_result = initialize_docker_image()
            if "Error:" in docker_result:
                docker_available = False
                docker_error_message = docker_result
                logger.error(docker_result)
            else:
                docker_available = True
                logger.info("Docker inicializado correctamente")
        else:
            docker_available = False
            docker_error_message = "No se pudo conectar con Docker. Verifica que esté instalado y en ejecución."
            logger.error(docker_error_message)
    except Exception as e:
        docker_available = False
        docker_error_message = f"Error al inicializar Docker: {e}"
        logger.error(docker_error_message)

# --- Manejo global de errores ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Error no manejado: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Error interno del servidor: {str(exc)}"}
    )

@sio.event
async def connect(sid, environ):
    logger.info(f"Cliente conectado: {sid}")
    await sio.emit('connection_established', {'status': 'connected', 'sid': sid}, room=sid)

@sio.event
async def disconnect(sid):
    logger.info(f"Cliente desconectado: {sid}")
    # Podrías limpiar tareas asociadas si es necesario

@sio.event
async def join_task_room(sid, task_id):
    """Permite al cliente suscribirse a actualizaciones de una tarea específica"""
    logger.info(f"Cliente {sid} se unió a la sala para la tarea {task_id}")
    sio.enter_room(sid, task_id)
    # Opcionalmente, enviar estado actual si ya existe
    if task_id in active_tasks and 'checklist' in active_tasks[task_id]:
        await sio.emit('checklist_update', active_tasks[task_id]['checklist'], room=task_id)
        # Si la tarea ya está completada, enviar el resultado final
        if active_tasks[task_id].get('status') == 'completed' and 'final_result' in active_tasks[task_id]:
            await sio.emit('task_completed', active_tasks[task_id]['final_result'], room=task_id)
        # Si la tarea ya falló, enviar el error
        elif active_tasks[task_id].get('status') == 'failed':
            await sio.emit('task_failed', {"taskId": task_id, "error": active_tasks[task_id].get('error', 'Error desconocido')}, room=task_id)

# --- Función de Ejecución Adaptada ---
async def run_single_generation_task(task_id: str, exec_index: int, prompt: str, input_files: Dict[str, bytes]):
    """Lógica adaptada para una sola tarea, emitiendo por WebSocket"""
    # Verificar si Docker está disponible
    if not docker_available:
        await sio.emit('task_failed', {
            "taskId": task_id, 
            "error": f"Docker no está disponible: {docker_error_message}"
        }, room=task_id)
        return {
            "exec_index": exec_index, 
            "is_successful": False, 
            "error": docker_error_message,
            "final_status": "❌ Docker no disponible"
        }
    
    # Importamos las funciones necesarias aquí para evitar problemas de inicialización
    try:
        # Usar importaciones absolutas para evitar problemas
        from backend.docker_executor import execute_code_in_docker
        from backend.gemini_client import analyze_execution_result, improve_prompt, analyze_files_context, generate_plan, generate_code
        from backend.code_formatter import clean_code
    except ImportError as e:
        error_msg = f"Error al importar módulos necesarios: {str(e)}"
        logger.error(error_msg)
        await sio.emit('task_failed', {
            "taskId": task_id, 
            "error": error_msg
        }, room=task_id)
        return {
            "exec_index": exec_index, 
            "is_successful": False, 
            "error": error_msg,
            "final_status": "❌ Error en importaciones"
        }
    
    max_attempts = 5
    last_error = ""
    checklist_data = {step: "Pendiente" for step in [
        "Guardar prompt original", "Analizar archivos", "Mejorar prompt", "Generar plan",
        "Generar código", "Limpiar y parsear código", "Ejecutar en Docker", "Analizar resultados"
    ]}

    async def update_status(step: str, status: str, is_error: bool = False):
        nonlocal checklist_data
        checklist_data[step] = status
        logger.info(f"Tarea {task_id}-{exec_index}: Paso '{step}' Estado: {status}")
        await sio.emit('checklist_update', {
            "taskId": task_id,
            "execIndex": exec_index,
            "step": step,
            "status": status,
            "isError": is_error
        }, room=task_id)
        await asyncio.sleep(0.01)  # Pequeña pausa para permitir envío

    start_time = asyncio.get_event_loop().time()
    def get_elapsed():
        elapsed = int(asyncio.get_event_loop().time() - start_time)
        m, s = divmod(elapsed, 60)
        return f"{m:02d}:{s:02d}"

    for attempt in range(1, max_attempts + 1):
        elapsed = get_elapsed()
        await update_status("Analizar resultados", f"🔄 Intento {attempt}/{max_attempts} - Tiempo: {elapsed}")

        try:
            # 1. Guardar prompt (implícito)
            await update_status("Guardar prompt original", f"✅ Completado - Tiempo: {elapsed}")

            # 2. Analizar archivos
            # Nota: Las llamadas a Gemini/Docker pueden ser bloqueantes
            loop = asyncio.get_event_loop()
            files_context = await loop.run_in_executor(None, analyze_files_context, input_files)
            await update_status("Analizar archivos", f"✅ Completado - Tiempo: {elapsed}")

            # 3. Mejorar prompt
            improved_prompt = await loop.run_in_executor(None, improve_prompt, prompt, input_files)
            await update_status("Mejorar prompt", f"✅ Completado - Tiempo: {elapsed}")

            # 4. Generar plan
            plan = await loop.run_in_executor(None, generate_plan, improved_prompt, input_files)
            await update_status("Generar plan", f"✅ Completado - Tiempo: {elapsed}")

            # 5. Generar código
            code_response = await loop.run_in_executor(None, generate_code, plan, input_files)
            code = code_response.get("code", "")
            dependencies = code_response.get("dependencies", "")
            if not code.strip():
                raise ValueError("Código generado vacío")
            await update_status("Generar código", f"✅ Completado - Tiempo: {elapsed}")

            # 6. Limpiar y parsear código
            cleaned_code = await loop.run_in_executor(None, clean_code, code)
            # AST parsing es rápido, se puede hacer directo
            try:
                ast.parse(cleaned_code)
                await update_status("Limpiar y parsear código", f"✅ Completado - Tiempo: {elapsed}")
            except SyntaxError as e:
                raise ValueError(f"Sintaxis inválida: {e}") from e

            # 7. Ejecutar en Docker
            execution_result = await loop.run_in_executor(None, execute_code_in_docker, cleaned_code, input_files, dependencies)
            await update_status("Ejecutar en Docker", f"✅ Completado - Tiempo: {elapsed}")

            # 8. Analizar resultados
            analysis = await loop.run_in_executor(None, analyze_execution_result, execution_result)
            if analysis.get("error_type") == "OK":
                generated_files = execution_result["files"]
                all_files = input_files.copy()
                all_files.update({"script.py": cleaned_code.encode('utf-8')})
                all_files.update(generated_files)

                await update_status("Analizar resultados", f"✅ Éxito en intento {attempt} - Tiempo: {elapsed}")
                return {
                    "exec_index": exec_index,
                    "code": cleaned_code,
                    "dependencies": dependencies,
                    "execution_result": execution_result,
                    "generated_files": {k: base64.b64encode(v).decode('utf-8') for k, v in generated_files.items()},
                    "all_files": {k: base64.b64encode(v).decode('utf-8') for k, v in all_files.items()},
                    "attempts": attempt,
                    "is_successful": True,
                    "final_status": f"✅ Éxito en intento {attempt}"
                }
            else:
                last_error = analysis.get("error_message", "Error desconocido")
                raise ValueError(last_error)

        except Exception as e:
            last_error = str(e)
            logger.error(f"Tarea {task_id}-{exec_index} Intento {attempt} falló: {last_error}")
            step_failed = "Analizar resultados"  # O el último paso que falló
            await update_status(step_failed, f"❌ Error: {last_error} - Tiempo: {elapsed}", is_error=True)
            if attempt == max_attempts:
                await update_status("Analizar resultados", f"❌ Falló tras {max_attempts} intentos. Último: {last_error} - Tiempo: {get_elapsed()}", is_error=True)
                return {
                    "exec_index": exec_index, 
                    "attempts": max_attempts, 
                    "execution_result": {}, 
                    "is_successful": False, 
                    "error": last_error, 
                    "final_status": f"❌ Falló tras {max_attempts} intentos"
                }
            await asyncio.sleep(1)  # Espera antes de reintentar

    # Si se sale del bucle sin éxito (esto no debería pasar con el return/raise dentro)
    return {
        "exec_index": exec_index, 
        "attempts": max_attempts, 
        "is_successful": False, 
        "error": last_error, 
        "final_status": f"❌ Falló tras {max_attempts} intentos"
    }


async def run_parallel_executions(task_id: str, prompt: str, input_files: Dict[str, bytes]):
    """Orquesta las ejecuciones paralelas y el ranking"""
    
    # Importamos las funciones aquí para evitar problemas de inicialización
    try:
        from backend.gemini_client import rank_solutions, generate_extensive_report
    except ImportError as e:
        error_msg = f"Error al importar módulos necesarios: {str(e)}"
        logger.error(error_msg)
        active_tasks[task_id] = {"status": "failed", "error": error_msg}
        await sio.emit('task_failed', {"taskId": task_id, "error": error_msg}, room=task_id)
        return
    
    num_executions = 3
    active_tasks[task_id] = {"status": "running", "results": [], "checklist": {i: {} for i in range(num_executions)}}

    # Lanzar tareas en paralelo
    tasks = [
        run_single_generation_task(task_id, i, prompt, input_files)
        for i in range(num_executions)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    successful_results = []
    final_statuses = {}
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            logger.error(f"Tarea {task_id}-{i} lanzó excepción: {res}")
            final_statuses[i] = f"❌ Error inesperado: {res}"
            # Podrías emitir un estado de error final aquí si no se hizo ya
        elif isinstance(res, dict):
            final_statuses[i] = res.get("final_status", "Estado desconocido")
            if res.get("is_successful"):
                successful_results.append(res)
        else:
            final_statuses[i] = "❌ Resultado inesperado"

    await sio.emit('execution_summary', {"taskId": task_id, "statuses": final_statuses}, room=task_id)

    if not successful_results:
        logger.error(f"Tarea {task_id}: No hay ejecuciones exitosas.")
        active_tasks[task_id]["status"] = "failed"
        active_tasks[task_id]["error"] = "No se encontraron soluciones exitosas."
        await sio.emit('task_failed', {"taskId": task_id, "error": "No se encontraron soluciones exitosas."}, room=task_id)
        return

    # Rankear soluciones
    try:
        loop = asyncio.get_event_loop()
        
        # Adaptación para ranking: necesitamos decodificar los archivos en base64
        ranking_input = []
        for r in successful_results:
            # Prepara la entrada para ranking que espera archivos en bytes
            generated_files_decoded = {k: base64.b64decode(v) for k, v in r['generated_files'].items()}
            # Añade lo que tu función rank_solutions necesita
            ranking_input.append({
                "generated_files": generated_files_decoded,
                "execution_result": r['execution_result'],
                "code": r['code'],
                "dependencies": r['dependencies'],
                "exec_index": r['exec_index']
            })
        
        # Ejecuta el ranking en un executor para no bloquear
        rankings = await loop.run_in_executor(None, rank_solutions, ranking_input)
        
        # Obtén el mejor resultado basado en los rankings
        best_rank_idx = rankings[0]  # Asumiendo que rankings devuelve índices en orden de preferencia
        best_result = None
        for res in successful_results:
            if res['exec_index'] == best_rank_idx:
                best_result = res
                break
        
        if not best_result:
            best_result = successful_results[0]  # Si algo falla, usa el primero
        
        logger.info(f"Tarea {task_id}: Mejor solución: índice {best_result['exec_index']}")

        # Generar Reporte Final
        # Decodifica los archivos necesarios para el reporte
        report_files = {k: base64.b64decode(v) for k, v in best_result['all_files'].items()}
        report_content = await loop.run_in_executor(None, generate_extensive_report, prompt, report_files)

        final_data = {
            "taskId": task_id,
            "bestExecIndex": best_result['exec_index'],
            "report": report_content,
            "generatedFiles": best_result['generated_files'],  # Ya están en base64
            "code": best_result['code'],
            "logs": {  # Simplificado, podrías querer logs más detallados
                "stdout": best_result['execution_result'].get('stdout', ''),
                "stderr": best_result['execution_result'].get('stderr', '')
            }
        }
        active_tasks[task_id]["status"] = "completed"
        active_tasks[task_id]["final_result"] = final_data
        await sio.emit('task_completed', final_data, room=task_id)

    except Exception as e:
        logger.exception(f"Tarea {task_id}: Error durante ranking o generación de reporte: {e}")
        active_tasks[task_id]["status"] = "failed"
        active_tasks[task_id]["error"] = f"Error en ranking/reporte: {e}"
        await sio.emit('task_failed', {"taskId": task_id, "error": f"Error en ranking/reporte: {e}"}, room=task_id)


# --- API Endpoint ---
@app.post("/execute")
async def execute_task(prompt: str = Form(...), files: List[UploadFile] = File(...)):
    # Verificar si Docker está disponible
    if not docker_available:
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Docker no está disponible: {docker_error_message}. Los servicios de ejecución de código están deshabilitados."
            }
        )
        
    task_id = str(uuid.uuid4())
    input_files = {}
    for file in files:
        content = await file.read()
        input_files[file.filename] = content

    logger.info(f"Recibida tarea {task_id}. Prompt: '{prompt[:50]}...', Archivos: {list(input_files.keys())}")

    # Ejecutar en segundo plano para no bloquear la respuesta HTTP
    asyncio.create_task(run_parallel_executions(task_id, prompt, input_files))

    return {"taskId": task_id, "message": "Tarea recibida, procesamiento iniciado."}

# Endpoint para verificar el estado del servidor
@app.get("/health")
async def health_check():
    return {
        "status": "ok", 
        "message": "Servidor funcionando correctamente",
        "docker_available": docker_available,
        "docker_status": "Disponible" if docker_available else docker_error_message
    }

# --- Punto de entrada ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Iniciando servidor en http://0.0.0.0:8080")
    uvicorn.run(socket_app, host="0.0.0.0", port=8080) 