import os
import random
import time
import logging
from typing import Dict, List, Set, Tuple, Optional
from dotenv import load_dotenv
from pydantic import BaseModel
import re
from google import genai

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Modelos Pydantic para estructurar respuestas JSON
class CodeResponse(BaseModel):
    code: str
    dependencies: str

class AnalysisResponse(BaseModel):
    error_type: str  # "OK" o "ERROR"
    error_message: str

class FixResponse(BaseModel):
    code: str
    dependencies: str

class MarkdownResponse(BaseModel):
    content: str

class EvaluationResponse(BaseModel):
    score: int

class BestSolutionResponse(BaseModel):
    best_solution_index: int

# Modelo Pydantic para rankear soluciones (en reemplazo de Schema)
class RankResponse(BaseModel):
    order: List[int]

# Variable global para claves API fallidas
failed_api_keys: Set[str] = set()

def load_api_keys() -> List[str]:
    """Carga las claves API desde el archivo .env."""
    load_dotenv()
    keys = [os.environ.get(f"GEMINI_API_KEY{i}") for i in range(1, 7) if os.environ.get(f"GEMINI_API_KEY{i}")]
    if not keys:
        raise ValueError("No se encontraron claves API en .env")
    return keys

def get_client(exclude_keys: Optional[Set[str]] = None) -> Tuple['genai.Client', str]:
    """Retorna un cliente Gemini con una clave API válida, excluyendo claves fallidas."""
    global failed_api_keys
    exclude_keys = exclude_keys or set()
    keys = load_api_keys()
    available_keys = [k for k in keys if k not in failed_api_keys and k not in exclude_keys]
    if not available_keys:
        raise ValueError("No hay claves API disponibles (todas descartadas por errores).")
    api_key = random.choice(available_keys)
    return genai.Client(api_key=api_key), api_key

def safe_generate_content(model: str, contents: str, config: Dict, retries: int = 3) -> 'genai.Response':
    """Genera contenido con reintentos y rotación de claves API en caso de error 429."""
    global failed_api_keys
    from google.genai.errors import ClientError
    used_keys: Set[str] = set()
    for attempt in range(retries):
        client, current_key = get_client(exclude_keys=used_keys)
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return response
        except ClientError as e:
            error_msg = str(e).lower()
            if "rate limit" in error_msg:
                used_keys.add(current_key)
                failed_api_keys.add(current_key)
                logging.warning(f"Clave API {current_key} falló por límite de tasa. Intentando con otra...")
                time.sleep(2 ** attempt)  # Backoff exponencial
                continue
            logging.error(f"Error de servicio: {e}")
            raise
        except Exception as e:
            logging.exception(f"Error inesperado: {e}")
            raise
    raise Exception(f"Todos los intentos fallaron tras {retries} reintentos.")

def configure_gemini() -> str:
    """Configura el cliente Gemini con una clave API válida."""
    try:
        client, api_key = get_client()
        genai.configure(api_key=api_key)
        logging.info("Gemini configurado exitosamente.")
        return "OK"
    except ValueError as e:
        logging.error(f"Error al configurar Gemini: {e}")
        return f"Error: {e}"
    except Exception as e:
        logging.exception(f"Error inesperado al configurar Gemini: {e}")
        return f"Error: {e}"

def improve_prompt(prompt: str, files: Dict[str, bytes]) -> Dict[str, str]:
    """Mejora un prompt incluyendo información de archivos y dependencias sugeridas."""
    file_info = "\n".join([
        f"Archivo: {name}\nContenido (primeros 500 caracteres): " +
        (content.decode('utf-8', errors='ignore')[:500] if isinstance(content, bytes) else content[:500])
        for name, content in files.items()
    ])
    contents = (
        "Ejemplo de prompt mejorado:\n"
        "Problema: Crear un script Python que lea un CSV y genere un gráfico de barras con matplotlib.\n"
        "Detalles: El CSV tiene columnas 'fecha' y 'valor'.\n\n"
        f"Prompt original: {prompt}\nArchivos:\n{file_info}"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=("Mejora este prompt para que sea claro y detallado, incluyendo ejemplos si es necesario. "
                  "Lista también las bibliotecas necesarias como dependencias:\n" + contents),
        config={"response_mime_type": "application/json", "response_schema": CodeResponse, "top_p": 0.95, "temperature": 1.0}
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        logging.exception(f"Error en improve_prompt: {e}")
        return {"code": "", "dependencies": ""}

def generate_code(improved_prompt: str, files: Dict[str, bytes]) -> Dict[str, str]:
    """Genera código Python y dependencias basadas en un prompt mejorado."""
    file_info = "\n".join([f"Archivo: {name}" for name in files.keys()])
    contents = (
        "Ejemplo:\n"
        "Prompt: 'Generar un gráfico a partir de datos CSV'. Código: importar pandas y matplotlib, leer CSV y graficar.\n\n"
        f"Tarea: {improved_prompt}\nArchivos disponibles: {file_info}"
    )
    prompt = (
        "Genera código Python y dependencias en formato requirements.txt (una por línea, sin texto adicional) para la tarea. "
        "El código debe ser robusto, con manejo de errores y comentarios explicativos. "
        "En las dependencias, lista SOLO las bibliotecas que necesitan instalarse con 'pip install', "
        "excluyendo módulos estándar de Python como io, os, sys, time, random, re, json, etc. "
        "Por ejemplo, si el código usa pandas y matplotlib, las dependencias deben ser:\n"
        "pandas\n"
        "matplotlib\n"
        "No incluyas 'io' ni otros módulos que vienen con Python por defecto:\n" + contents
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": CodeResponse, "top_p": 0.95, "temperature": 1.0}
    )
    try:
        result = response.parsed.dict()
        # Filtro opcional para módulos estándar
        standard_modules = {"io", "os", "sys", "time", "random", "re", "json", "csv", "math", "datetime"}
        dependencies = "\n".join(
            line for line in result["dependencies"].splitlines()
            if line.strip() and line.strip() not in standard_modules
        )
        return {"code": result["code"], "dependencies": dependencies}
    except Exception as e:
        logging.exception(f"Error en generate_code: {e}")
        return {"code": "", "dependencies": ""}

def analyze_execution_result(execution_result: Dict) -> Dict[str, str]:
    """Analiza el resultado de la ejecución y determina si fue exitosa o falló."""
    stdout = execution_result.get("stdout", "")
    stderr = execution_result.get("stderr", "")
    files = execution_result.get("files", {})
    truncated_stdout = stdout[:1000] + "\n... (truncado)" if len(stdout) > 1000 else stdout
    truncated_stderr = stderr[:1000] + "\n... (truncado)" if len(stderr) > 1000 else stderr
    file_names = list(files.keys())
    summary = f"stdout: {truncated_stdout}\nstderr: {truncated_stderr}\narchivos: {file_names}"
    contents = (
        "Ejemplo: Si la ejecución fue exitosa, devuelve OK. Si hay error, devuelve ERROR con descripción.\n\n"
        f"Resultado: {summary}"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=("Analiza el resultado y devuelve 'OK' si fue exitoso o 'ERROR' con una descripción:\n" + contents),
        config={"response_mime_type": "application/json", "response_schema": AnalysisResponse, "top_p": 0.95, "temperature": 1.0}
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        logging.exception(f"Error en analyze_execution_result: {e}")
        return {"error_type": "ERROR", "error_message": "Error al analizar el resultado."}

def generate_fix(error_type: str, error_message: str, code: str, dependencies: str, history: List[Dict]) -> Dict[str, str]:
    """Genera una corrección para el código basado en el error y el historial."""
    history_text = "\n".join([
        f"Intento {i+1}: Error: {item.get('error_type', '')} - {item.get('error_message', '')}\nCódigo:\n{item.get('code', '')}"
        for i, item in enumerate(history)
    ])
    if error_type == "ERROR" and "ImportError" in error_message:
        prompt_fix = (
            "Corrige las dependencias sin modificar el código, usando el historial:\n"
            f"{history_text}\nError: {error_type} - {error_message}\nCódigo:\n{code}\nDependencias:\n{dependencies}"
        )
    else:
        prompt_fix = (
            "Corrige el código para resolver el error, usando el historial:\n"
            f"{history_text}\nError: {error_type} - {error_message}\nCódigo:\n{code}\nDependencias:\n{dependencies}"
        )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt_fix,
        config={"response_mime_type": "application/json", "response_schema": FixResponse, "top_p": 0.95, "temperature": 1.0}
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        logging.exception(f"Error en generate_fix: {e}")
        return {"code": code, "dependencies": dependencies}

def improve_markdown(content: str) -> str:
    """Mejora el formato Markdown para mayor legibilidad."""
    content = re.sub(r'(#+)(\w)', r'\1 \2', content)
    content = re.sub(r'^-\s*([^\s])', r'- \1', content, flags=re.MULTILINE)
    content = re.sub(r'^\*\s*([^\s])', r'* \1', content, flags=re.MULTILINE)
    content = re.sub(r'(#+.+)\n([^#\n])', r'\1\n\n\2', content)
    content = re.sub(r'```([a-z]*)\n', r'```\1\n', content)
    content = re.sub(r'\n{3,}', r'\n\n', content)
    content = re.sub(r'[ \t]+\n', r'\n', content)
    return content.strip()

def generate_report(problem_description: str, code: str, stdout: str, files: Dict[str, bytes]) -> str:
    """Genera un reporte en Markdown sobre la solución."""
    file_list = "\n".join([f"- `{name}`\n{get_file_explanation(name)}" for name in files.keys() if name != "script.py"]) or "No hay archivos generados."
    contents = (
        "Genera un reporte en Markdown con:\n"
        "1. **Introducción:** Explica el problema, contexto y enfoque (5-7 oraciones).\n"
        "2. **Archivos Generados:** Lista los archivos y explica su propósito en detalle (6-8 oraciones por archivo).\n"
        "3. **Conclusiones:** Resume el éxito y posibles mejoras.\n\n"
        f"Problema: {problem_description}\nArchivos:\n{file_list}"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "application/json", "response_schema": MarkdownResponse, "top_p": 0.95, "temperature": 1.0}
    )
    try:
        return improve_markdown(response.parsed.content)
    except Exception as e:
        logging.exception(f"Error en generate_report: {e}")
        return "Error al generar el reporte."

def get_file_explanation(filename: str) -> str:
    """Obtiene una explicación detallada del propósito de un archivo."""
    prompt = (
        f"Explica en 6-8 oraciones el propósito y contenido probable de '{filename}' generado en un script Python. "
        "No uses prefijos como 'Archivo:' y omite el punto final al final del párrafo"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": MarkdownResponse, "top_p": 0.95, "temperature": 1.0}
    )
    return response.parsed.content if response.parsed.content else f"No se pudo explicar '{filename}'"

def rank_solutions(solutions: List[Dict]) -> List[int]:
    """Rankea soluciones de mejor a peor según su efectividad."""
    contents = "Rankea estas soluciones de mejor a peor:\n" + "\n".join([
        f"Solución {i}: Archivos: {', '.join(sol['generated_files'].keys())}" for i, sol in enumerate(solutions)
    ])
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents + "\nDevuelve una lista de índices en orden (mejor a peor) en 'order'.",
        config={
            "response_mime_type": "application/json",
            "response_schema": RankResponse,
            "top_p": 0.95,
            "temperature": 1.0
        }
    )
    try:
        order = response.parsed.dict().get('order', [])
        rankings = [0] * len(solutions)
        for rank, idx in enumerate(order, 1):
            rankings[idx] = rank
        return rankings
    except Exception as e:
        logging.exception(f"Error en rank_solutions: {e}")
        return list(range(1, len(solutions) + 1))
