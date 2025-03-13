import json
import re
import streamlit as st
import io
import zipfile
import pandas as pd
import ast
import concurrent.futures
import time
import os
import base64
from typing import Dict, List
from PIL import Image
import queue
import difflib

from gemini_client import (
    generate_code,
    analyze_execution_result,
    generate_extensive_report,
    configure_gemini,
    rank_solutions,
    generate_plan,
    analyze_files_context,
    improve_prompt
)
from docker_executor import (
    initialize_docker_image, execute_code_in_docker,
    background_clean_images, background_clean_containers
)
from code_formatter import clean_code

# Limpieza inicial de Docker
background_clean_images()
background_clean_containers()

# Configuración de caché
@st.cache_resource
def init_docker() -> str:
    return initialize_docker_image()

@st.cache_resource
def init_gemini() -> str:
    return configure_gemini()

st.set_page_config(layout="wide")

# Verificación inicial de Docker
docker_init_message = init_docker()
if "Error" in docker_init_message:
    st.error(docker_init_message, icon="❌")
    st.stop()

# Estilos CSS optimizados para fondo oscuro
st.markdown("""
<style>
body {
    font-family: 'Arial', sans-serif;
    background-color: #1e1e1e;
    color: #ddd;
}
.checklist {
    margin: 10px 0;
    padding: 15px;
    background-color: #2a2a2a;
    border-radius: 10px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.2);
}
.checklist-item {
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    color: #ddd;
}
.checklist-item .icon {
    margin-right: 10px;
    font-size: 18px;
}
.status-text {
    font-size: 14px;
    color: #007bff;
}
.my-progress-bar {
    background-color: #333;
    border-radius: 8px;
    height: 20px;
    margin: 10px 0;
}
.my-progress-bar-inner {
    height: 100%;
    background: linear-gradient(90deg, #00adb5, #006064);
    transition: width 0.5s ease-in-out;
}
.time-info {
    font-size: 14px;
    color: #666;
    margin-top: 5px;
}
.task-header {
    font-size: 18px;
    font-weight: bold;
    margin-bottom: 10px;
    color: #ffffff;
    background-color: #333;
    padding: 5px;
    border-radius: 5px;
}
.error-text {
    color: #dc3545;
    font-size: 13px;
}
.success-text {
    color: #28a745;
}
.pending-text {
    color: #666;
}
</style>
""", unsafe_allow_html=True)

# Inicialización del estado de la sesión
for key in [
    "attempts", "execution_history", "generated_files", "results_available",
    "formatted_report", "execution_result", "all_files", "parallel_results",
    "cleaned_code", "user_prompt", "checklist_data", "overall_start_time"
]:
    if key not in st.session_state:
        if key in ["execution_history", "parallel_results"]:
            st.session_state[key] = []
        elif key in ["generated_files", "execution_result", "all_files"]:
            st.session_state[key] = {}
        elif key == "results_available":
            st.session_state[key] = False
        elif key in ["formatted_report", "cleaned_code", "user_prompt"]:
            st.session_state[key] = ""
        elif key == "checklist_data":
            st.session_state[key] = {}
        elif key == "overall_start_time":
            st.session_state[key] = 0.0

def preview_file(file_name: str, content: bytes) -> None:
    """Previsualiza archivos según su tipo."""
    file_ext = file_name.split('.')[-1].lower()
    if file_ext == 'gif':
        try:
            image = Image.open(io.BytesIO(content))
            with io.BytesIO() as output:
                image.save(output, format='GIF', save_all=True, loop=0)
                gif_data = base64.b64encode(output.getvalue()).decode("utf-8")
            st.markdown(f'<img src="data:image/gif;base64,{gif_data}" alt="{file_name}" />', unsafe_allow_html=True)
        except Exception:
            st.image(content, caption=file_name)
    elif file_ext in ['png', 'jpg', 'jpeg', 'webp', 'tiff']:
        st.image(content, caption=file_name)
    elif file_ext == 'csv':
        try:
            df = pd.read_csv(io.BytesIO(content))
            st.dataframe(df)
        except Exception as e:
            st.error(f"Error al mostrar CSV: {e}")
    elif file_ext in ['xls', 'xlsx']:
        try:
            df = pd.read_excel(io.BytesIO(content))
            st.dataframe(df)
        except Exception as e:
            st.error(f"Error al mostrar Excel: {e}")
    elif file_ext in ['mp4', 'mov', 'avi', 'mkv', 'webm']:
        st.video(io.BytesIO(content))
    elif file_ext in ['mp3', 'wav', 'ogg', 'flac', 'm4a']:
        st.audio(io.BytesIO(content))
    elif file_ext == 'pdf':
        try:
            base64_pdf = base64.b64encode(content).decode('utf-8')
            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="700" height="900" type="application/pdf"></iframe>'
            st.markdown(pdf_display, unsafe_allow_html=True)
        except:
            st.warning("No se pudo previsualizar el PDF.")
    elif file_ext == 'py':
        st.code(content.decode('utf-8', errors='ignore'), language='python')
    elif file_ext == 'json':
        try:
            data = json.loads(content.decode('utf-8'))
            st.json(data)
        except Exception as e:
            st.text_area("Contenido JSON", content.decode('utf-8', errors='ignore'), height=300)
    else:
        try:
            text = content.decode('utf-8', errors='ignore')
            st.text_area("Contenido", text, height=300)
        except:
            st.warning("No se puede previsualizar este archivo.")

class FileBrowser:
    """Clase para navegar y descargar archivos generados."""
    def __init__(self, files_dict: Dict[str, bytes]):
        self.files_dict = files_dict

    def render(self) -> None:
        if not self.files_dict:
            st.info("No se han generado archivos aún.", icon="ℹ️")
            return
        for file_name, content in self.files_dict.items():
            with st.expander(f"📄 {file_name}", expanded=False):
                preview_file(file_name, content)
                st.download_button(
                    label="⬇️ Descargar",
                    data=content,
                    file_name=file_name,
                    key=f"dl_{file_name}"
                )

def get_elapsed_time(start_time: float) -> str:
    """Devuelve el tiempo transcurrido en formato mm:ss."""
    elapsed = int(time.time() - start_time)
    minutes, seconds = divmod(elapsed, 60)
    return f"{minutes:02d}:{seconds:02d}"

def render_checklist_md(checklist_data: Dict[int, Dict[str, str]]) -> str:
    """Genera markdown para la checklist con pasos predefinidos y estados."""
    checklist_md = ""
    for task_id in sorted(checklist_data.keys()):
        checklist_md += f"<div class='task-header'>Tarea {task_id}</div>\n"
        for step_name, status in checklist_data[task_id].items():
            if status.startswith("✅"):
                step_html = f"<div class='checklist-item success-text'><span class='icon'>✅</span>{step_name}: {status[2:]}</div>"
            elif status.startswith("❌"):
                step_html = f"<div class='checklist-item error-text'><span class='icon'>❌</span>{step_name}: {status[2:]}</div>"
            else:
                step_html = f"<div class='checklist-item pending-text'><span class='icon'>🔄️</span>{step_name}: Pendiente</div>"
            checklist_md += step_html + "\n"
        checklist_md += "\n"
    return f"<div class='checklist'>{checklist_md}</div>"

def initialize_checklist() -> Dict[int, Dict[str, str]]:
    """Inicializa la checklist con todos los pasos en estado pendiente."""
    steps = [
        "Guardar prompt original",
        "Analizar archivos",
        "Mejorar prompt",
        "Generar plan",
        "Generar código",
        "Limpiar y parsear código",
        "Ejecutar en Docker",
        "Analizar resultados"
    ]
    return {task_id: {step: "Pendiente" for step in steps} for task_id in range(1, 4)}

def update_checklist_status(checklist_data: Dict[int, Dict[str, str]], task_id: int, step: str, status: str):
    """Actualiza el estado de un paso específico en la checklist."""
    if task_id in checklist_data and step in checklist_data[task_id]:
        checklist_data[task_id][step] = status

def generate_and_execute(
    task_id: int,
    input_files: Dict[str, bytes],
    prompt: str,
    status_queue: queue.Queue,
    start_time: float,
    checklist_data: Dict[int, Dict[str, str]]
) -> Dict:
    """Genera y ejecuta código con múltiples intentos, enviando actualizaciones a la cola."""
    max_attempts = 5
    #temp_dir = os.path.join(os.getcwd(), f".temp/task_{task_id}")
    #os.makedirs(temp_dir, exist_ok=True)
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        attempt_start_time = time.time()
        elapsed_time = get_elapsed_time(start_time)
        status_queue.put((task_id, f"🔄 Intento {attempt}/{max_attempts} - Tiempo: {elapsed_time}"))
        update_checklist_status(checklist_data, task_id, "Analizar resultados", f"🔄 Intento {attempt}/{max_attempts} - Tiempo: {elapsed_time}")
        status_queue.put((task_id, "Actualizar checklist"))

        # Guardar prompt original
        #with open(os.path.join(temp_dir, "prompt_original.txt"), "w", encoding="utf-8") as f:
        #    f.write(prompt)
        update_checklist_status(checklist_data, task_id, "Guardar prompt original", f"✅ Completado - Tiempo: {get_elapsed_time(start_time)}")
        status_queue.put((task_id, "Actualizar checklist"))

        # Analizar archivos
        files_context = analyze_files_context(input_files)
        #with open(os.path.join(temp_dir, "files_analysis.txt"), "w", encoding="utf-8") as f:
        #    f.write(str(files_context))
        update_checklist_status(checklist_data, task_id, "Analizar archivos", f"✅ Completado - Tiempo: {get_elapsed_time(start_time)}")
        status_queue.put((task_id, "Actualizar checklist"))

        # Mejorar prompt
        improved_prompt = improve_prompt(prompt, input_files)
        #with open(os.path.join(temp_dir, "prompt_mejorado.txt"), "w", encoding="utf-8") as f:
        #    f.write(improved_prompt)
        update_checklist_status(checklist_data, task_id, "Mejorar prompt", f"✅ Completado - Tiempo: {get_elapsed_time(start_time)}")
        status_queue.put((task_id, "Actualizar checklist"))

        # Generar plan
        plan = generate_plan(improved_prompt, input_files)
        #with open(os.path.join(temp_dir, "plan.txt"), "w", encoding="utf-8") as f:
        #    f.write(plan)
        update_checklist_status(checklist_data, task_id, "Generar plan", f"✅ Completado - Tiempo: {get_elapsed_time(start_time)}")
        status_queue.put((task_id, "Actualizar checklist"))

        # Generar código
        response = generate_code(plan, input_files)
        code = response.get("code", "")
        dependencies = response.get("dependencies", "")
        if not code.strip():
            last_error = "Código generado vacío"
            update_checklist_status(checklist_data, task_id, "Generar código", f"❌ Error: {last_error} - Tiempo: {get_elapsed_time(start_time)}")
            status_queue.put((task_id, "Actualizar checklist"))
            continue
        update_checklist_status(checklist_data, task_id, "Generar código", f"✅ Completado - Tiempo: {get_elapsed_time(start_time)}")
        status_queue.put((task_id, "Actualizar checklist"))

        # Limpiar y parsear código
        try:
            cleaned_code = clean_code(code)
            ast.parse(cleaned_code)
            update_checklist_status(checklist_data, task_id, "Limpiar y parsear código", f"✅ Completado - Tiempo: {get_elapsed_time(start_time)}")
        except SyntaxError as e:
            last_error = f"Sintaxis inválida: {str(e)}"
            update_checklist_status(checklist_data, task_id, "Limpiar y parsear código", f"❌ Error: {last_error} - Tiempo: {get_elapsed_time(start_time)}")
            status_queue.put((task_id, "Actualizar checklist"))
            continue
        status_queue.put((task_id, "Actualizar checklist"))

        # Ejecutar en Docker
        try:
            execution_result = execute_code_in_docker(cleaned_code, input_files, dependencies)
            update_checklist_status(checklist_data, task_id, "Ejecutar en Docker", f"✅ Completado - Tiempo: {get_elapsed_time(start_time)}")
        except Exception as e:
            last_error = f"Ejecución fallida: {str(e)}"
            update_checklist_status(checklist_data, task_id, "Ejecutar en Docker", f"❌ Error: {last_error} - Tiempo: {get_elapsed_time(start_time)}")
            status_queue.put((task_id, "Actualizar checklist"))
            continue
        status_queue.put((task_id, "Actualizar checklist"))

        # Analizar resultados
        analysis = analyze_execution_result(execution_result)
        if analysis.get("error_type") == "OK":
            generated_files = execution_result["files"]
            all_files = input_files.copy()
            all_files.update({"script.py": cleaned_code.encode('utf-8')})
            all_files.update(generated_files)
            update_checklist_status(checklist_data, task_id, "Analizar resultados", f"✅ Completado en intento {attempt} - Tiempo: {get_elapsed_time(start_time)}")
            status_queue.put((task_id, "Actualizar checklist"))
            return {
                "task_id": task_id,
                "code": cleaned_code,
                "dependencies": dependencies,
                "execution_result": execution_result,
                "generated_files": generated_files,
                "all_files": all_files,
                "attempts": attempt,
                "is_successful": True
            }
        else:
            last_error = analysis.get("error_message", "Error desconocido")
            update_checklist_status(checklist_data, task_id, "Analizar resultados", f"❌ Error: {last_error} - Tiempo: {get_elapsed_time(start_time)}")
            status_queue.put((task_id, "Actualizar checklist"))

    # Si falla tras todos los intentos
    update_checklist_status(checklist_data, task_id, "Analizar resultados", f"❌ Falló tras {max_attempts} intentos. Último error: {last_error} - Tiempo: {get_elapsed_time(start_time)}")
    status_queue.put((task_id, "Actualizar checklist"))
    return {"task_id": task_id, "attempts": max_attempts, "execution_result": {}, "is_successful": False}

def find_best_match_file(referenced_name: str, files_dict: Dict[str, bytes]) -> str:
    """Encuentra el archivo con el nombre más similar al referenciado."""
    if not files_dict:
        return None
    best_match = difflib.get_close_matches(referenced_name, files_dict.keys(), n=1, cutoff=0.8)
    return best_match[0] if best_match else None

def process_report_content(report: str, files_dict: Dict[str, bytes]) -> List[Dict]:
    """Procesa el reporte para insertar previsualizaciones de archivos usando coincidencia flexible."""
    if not isinstance(report, str):
        return [{"type": "text", "content": "Reporte no válido."}]
    parts = []
    file_marker_regex = re.compile(r"\{(.+?)\}")  # Ajustado para coincidir con {nombre_archivo}
    last_end = 0
    for match in file_marker_regex.finditer(report):
        start, end = match.span()
        text_chunk = report[last_end:start].strip()
        if text_chunk:
            parts.append({"type": "text", "content": text_chunk})
        referenced_name = match.group(1)
        matched_file = find_best_match_file(referenced_name, files_dict)
        if matched_file:
            parts.append({"type": "file", "name": matched_file, "content": files_dict[matched_file]})
        else:
            parts.append({"type": "text", "content": f"[Archivo no encontrado: {referenced_name}]"})
        last_end = end
    if last_end < len(report):
        parts.append({"type": "text", "content": report[last_end:].strip()})
    return parts

def parallel_execution() -> None:
    """Ejecuta tareas en paralelo con una interfaz mejorada."""
    st.session_state.parallel_results = []
    num_executions = 3

    uploaded_files = st.session_state.get("user_files", [])
    input_files = {file.name: file.read() for file in uploaded_files} if uploaded_files else {}
    prompt = st.session_state["user_prompt"]

    st.session_state.overall_start_time = time.time()
    #temp_root = os.path.join(os.getcwd(), ".temp")
    #os.makedirs(temp_root, exist_ok=True)

    # Elementos de la interfaz
    progress_bar = st.empty()
    checklist_placeholder = st.empty()
    time_info = st.empty()

    # Inicializar checklist con todos los pasos
    st.session_state.checklist_data = initialize_checklist()
    checklist_placeholder.markdown(render_checklist_md(st.session_state.checklist_data), unsafe_allow_html=True)

    status_queue = queue.Queue()
    st.info("🚀 Ejecutando tareas en paralelo...")

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_executions) as executor:
        futures = {
            executor.submit(generate_and_execute, i+1, input_files, prompt, status_queue, st.session_state.overall_start_time, st.session_state.checklist_data): i+1
            for i in range(num_executions)
        }

        completed_tasks = 0
        while any(not future.done() for future in futures):
            try:
                task_id, message = status_queue.get(timeout=0.1)
                if message == "Actualizar checklist":
                    checklist_placeholder.markdown(render_checklist_md(st.session_state.checklist_data), unsafe_allow_html=True)
                # Actualizar barra de progreso
                completed_tasks = sum(1 for f in futures if f.done())
                percentage = int((completed_tasks / num_executions) * 100)
                progress_bar.markdown(f"<div class='my-progress-bar'><div class='my-progress-bar-inner' style='width:{percentage}%'></div></div>", unsafe_allow_html=True)
            except queue.Empty:
                pass
            time.sleep(0.1)

        results = [future.result() for future in futures]

    # Limpieza de Docker
    status_queue.put((0, "🧹 Limpiando Docker..."))
    background_clean_images()
    background_clean_containers()
    status_queue.put((0, "✅ Limpieza completada"))

    # Actualizar interfaz final
    while not status_queue.empty():
        task_id, message = status_queue.get()
        if message == "Actualizar checklist":
            checklist_placeholder.markdown(render_checklist_md(st.session_state.checklist_data), unsafe_allow_html=True)
    time_info.markdown(f"<div class='time-info'>Tiempo total: {get_elapsed_time(st.session_state.overall_start_time)}</div>", unsafe_allow_html=True)

    successful_results = [r for r in results if r.get("is_successful", False)]
    if not successful_results:
        st.error("❌ No se encontraron soluciones exitosas.")
        return

    st.info("🔍 Evaluando soluciones...")
    rankings = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures_rank = [executor.submit(rank_solutions, successful_results) for _ in range(2)]
        rankings = [future.result() for future in futures_rank]

    sum_rankings = [sum(ranks[i] for ranks in rankings) for i in range(len(successful_results))]
    best_index = sum_rankings.index(min(sum_rankings))
    best_result = successful_results[best_index]

    st.session_state.results_available = True
    st.session_state.generated_files = best_result["generated_files"]
    st.session_state.cleaned_code = best_result["code"]
    st.session_state.execution_result = best_result["execution_result"]
    st.session_state.all_files = best_result["all_files"]

    report = generate_extensive_report(prompt, "Plan basado en análisis científico. Salida del programa: " + best_result["execution_result"].get("stdout", ""), best_result["all_files"])
    st.session_state.formatted_report = report if isinstance(report, str) else "Reporte no generado."

    st.success(f"🏆 Mejor solución: Tarea {best_result['task_id']} (Ranking: {sum_rankings[best_index]})")
    st.session_state.parallel_results = results

# UI Principal
with st.container():
    st.subheader("Describe tu Tarea")
    st.text_area(
        "Escribe qué quieres que haga la solución científica:",
        key="user_prompt",
        height=150,
        placeholder="Ejemplo: 'Analizar datos JSON y generar un estudio completo.'"
    )

with st.container():
    st.subheader("Sube Archivos 📂 (Opcional)")
    st.file_uploader(
        "Archivos necesarios:",
        accept_multiple_files=True,
        key="user_files"
    )

with st.container():
    if st.button("🚀 Generar y Ejecutar"):
        parallel_execution()

if st.session_state.results_available:
    st.markdown("---")
    col_report, col_files = st.columns([5, 3])
    with col_report:
        st.subheader("📋 Reporte Científico")

        def display_processed_report(processed_report: List[Dict]) -> None:
            for item in processed_report:
                if item["type"] == "text":
                    st.markdown(item["content"], unsafe_allow_html=True)
                else:
                    st.subheader(item["name"])
                    preview_file(item["name"], item["content"])

        processed_report = process_report_content(st.session_state.formatted_report, st.session_state.generated_files)
        display_processed_report(processed_report)

    with col_files:
        st.subheader("📁 Archivos Generados")
        FileBrowser(st.session_state.generated_files).render()

        if st.session_state.generated_files:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zipf:
                for name, content in st.session_state.generated_files.items():
                    zipf.writestr(name, content if isinstance(content, bytes) else content.encode('utf-8'))
            zip_buffer.seek(0)
            st.download_button(
                "⬇️ Descargar Todo (ZIP)",
                zip_buffer,
                "generated_files.zip",
                "application/zip"
            )