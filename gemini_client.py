import os
import random
import time
from google import genai
from pydantic import BaseModel
from dotenv import load_dotenv
import re
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Modelos para estructurar respuestas JSON
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

# Variable global para almacenar las claves API que han fallado
failed_api_keys = set()

# Función para cargar las API keys desde .env
def load_api_keys():
    load_dotenv()
    keys = [
        os.environ.get(f"GEMINI_API_KEY{i}")
        for i in range(1, 7)
        if os.environ.get(f"GEMINI_API_KEY{i}")
    ]
    if not keys:
        raise ValueError("No se encontraron claves API en .env")
    return keys

# Función que retorna un cliente nuevo con una API key distinta, excluyendo las que hayan fallado
def get_client(exclude_keys: set | None = None) -> tuple[genai.Client, str]:
    global failed_api_keys
    if exclude_keys is None:
        exclude_keys = set()
    keys = load_api_keys()
    available_keys = [k for k in keys if k not in failed_api_keys and k not in exclude_keys]
    if not available_keys:
        raise ValueError("No hay API keys disponibles (todas fueron descartadas por errores).")
    api_key = random.choice(available_keys)
    return genai.Client(api_key=api_key), api_key

# Función auxiliar que realiza la petición y, en caso de error 429, rota la API key
def safe_generate_content(model: str, contents: str, config: dict, retries: int = 3):
    global failed_api_keys
    from google.genai.errors import ClientError
    used_keys = set()
    for attempt in range(retries):
        client, current_key = get_client(exclude_keys=used_keys)
        try:
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return response
        except ClientError as e:
            if "rate limit" in str(e).lower():
                used_keys.add(current_key)
                failed_api_keys.add(current_key)
                logging.warning(f"API key {current_key} failed due to rate limit. Attempting with another...")
                time.sleep(2 ** attempt)
                continue
            else:
                logging.error(f"ServiceError: {e}")
                raise e
        except Exception as e:
            logging.exception(f"Error inesperado: {e}")
            raise e
    raise Exception("Todos los API keys están agotados o retornaron error 429.")

# Función para configurar Gemini (inicialización)
def configure_gemini():
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

# Función para mejorar el prompt
def improve_prompt(prompt: str, files: dict) -> dict:
    file_info = "\n".join([
        f"Archivo: {name}\nContenido (primeros 500 caracteres): " +
        (content.decode('utf-8', errors='ignore')[:500] if isinstance(content, bytes) else content[:500])
        for name, content in files.items()
    ])
    contents = (
        "Ejemplo de prompt mejorado:\n"
        "Problema: Necesito un script en Python que lea un archivo CSV y genere un gráfico de barras usando matplotlib.\n"
        "Detalles adicionales: El archivo CSV tiene columnas 'fecha' y 'valor'.\n\n"
        f"Prompt original: {prompt}\nArchivos:\n{file_info}"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=("Mejora este prompt para que sea lo más claro y detallado posible, incluyendo ejemplos si es necesario. Also list the libraries that might be needed as dependencies:\n" + contents),
        config={
            "response_mime_type": "application/json",
            "response_schema": CodeResponse,
        },
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        logging.exception(f"Error en improve_prompt: {e}")
        return {"code": "", "dependencies": ""}

# Función para generar código a partir del prompt mejorado
def generate_code(improved_prompt: str, files: dict) -> dict:
    file_info = "\n".join([f"Archivo: {name}" for name in files.keys()])
    contents = (
        "Ejemplo:\n"
        "Si el prompt dice 'Generar un gráfico a partir de datos CSV', el código debe importar 'pandas' y 'matplotlib' y contener un bloque principal que realice la lectura y el gráfico.\n\n"
        f"Tarea: {improved_prompt}\nArchivos disponibles: {file_info}"
    )
    prompt = (
        "Genera código Python y una lista de dependencias en formato requirements.txt (una dependencia por línea, sin texto adicional) para resolver la siguiente tarea. "
        "El código debe ser robusto, incluir manejo de errores y ser lo más eficiente posible.\n"
        "Además, incluye comentarios explicativos en el código para facilitar su comprensión. Asegúrate de que el código sea compatible con las versiones más recientes de las bibliotecas utilizadas.\n" + contents
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": CodeResponse,
        },
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        logging.exception(f"Error en generate_code: {e}")
        return {"code": "", "dependencies": ""}

# Función para analizar el resultado de ejecución
def analyze_execution_result(execution_result: dict) -> dict:
    stdout = execution_result.get("stdout", "")
    stderr = execution_result.get("stderr", "")
    files = execution_result.get("files", {})
    max_chars = 1000
    truncated_stdout = stdout if len(stdout) <= max_chars else stdout[:max_chars] + "\n... (output truncated)"
    truncated_stderr = stderr if len(stderr) <= max_chars else stderr[:max_chars] + "\n... (error log truncated)"
    file_names = list(files.keys())
    summary = (
        f"stdout: {truncated_stdout}\n"
        f"stderr: {truncated_stderr}\n"
        f"archivos: {file_names}"
    )
    contents = (
        "Ejemplo:\n"
        "Si la ejecución fue exitosa, devuelve OK.\n"
        "Si ocurrió algún error, devuelve ERROR seguido de una breve descripción del problema y su posible causa.\n\n"
        f"Resultado de ejecución: {summary}"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=("Analiza el siguiente resultado de ejecución y devuelve 'OK' si fue exitoso o 'ERROR' si hubo problemas, "
                  "junto con una breve descripción del error:\n" + contents),
        config={
            "response_mime_type": "application/json",
            "response_schema": AnalysisResponse,
        },
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        logging.exception(f"Error en analyze_execution_result: {e}")
        return {"error_type": "ERROR", "error_message": "Error al analizar el resultado de la ejecución."}

# Función para generar una corrección (fix) en el código en base al historial y al error
def generate_fix(error_type: str, error_message: str, code: str, dependencies: str, history: list) -> dict:
    history_text = "\n".join([
        f"Intento {i+1}: Error: {item.get('error_type', '')} - {item.get('error_message', '')}\nCódigo:\n{item.get('code', '')}\n"
        for i, item in enumerate(history)
    ])
    if error_type == "ERROR" and "ImportError" in error_message:
        prompt_fix = (
            "Corrige el problema de dependencias en el código sin modificar el código. "
            "Utiliza el historial de intentos a continuación:\n"
            f"{history_text}\n"
            f"Error: {error_type} - {error_message}\n"
            f"Código actual:\n{code}\n"
            f"Dependencias actuales:\n{dependencies}\n\n"
            "Devuelve un JSON con dos campos: 'code' (el código Python sin cambios) y 'dependencies' (la lista corregida de dependencias en formato requirements.txt, una dependencia por línea)."
        )
    elif error_type == "ERROR":
        prompt_fix = (
            "Corrige el error en el código para que sea ejecutable sin errores. "
            "Utiliza el historial de intentos a continuación:\n"
            f"{history_text}\n"
            f"Error: {error_type} - {error_message}\n"
            f"Código actual:\n{code}\n\n"
            "Devuelve un JSON con dos campos: 'code' (el código Python corregido) y 'dependencies' (la lista de dependencias sin cambios)."
        )
    else:
        prompt_fix = (
            "Corrige el error en el código teniendo en cuenta el siguiente historial:\n"
            f"{history_text}\n"
            f"Error: {error_type} - {error_message}\n"
            f"Código actual:\n{code}\n"
            f"Dependencias actuales:\n{dependencies}\n\n"
            "Devuelve un JSON con dos campos: 'code' (el código Python corregido) y 'dependencies' (la lista de dependencias, sin cambios si no es necesario modificarlas)."
        )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt_fix,
        config={
            "response_mime_type": "application/json",
            "response_schema": FixResponse,
        },
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        logging.exception(f"Error en generate_fix: {e}")
        return {"code": code, "dependencies": dependencies}

# Función para mejorar el formato Markdown
def improve_markdown(content: str) -> str:
    content = re.sub(r'(#+)(\w)', r'\1 \2', content)
    content = re.sub(r'^-\s*([^\s])', r'- \1', content, flags=re.MULTILINE)
    content = re.sub(r'^\*\s*([^\s])', r'* \1', content, flags=re.MULTILINE)
    content = re.sub(r'(#+.+)\n([^#\n])', r'\1\n\n\2', content)
    content = re.sub(r'```([a-z]*)\n', r'```\1\n', content)
    content = re.sub(r'\n{3,}', r'\n\n', content)
    content = re.sub(r'[ \t]+\n', r'\n', content)
    content = re.sub(r'(\*\*[^*]+\*\*:)\s*([^\n])', r'\1 \2', content)
    return content

# Función para generar un reporte en Markdown
def generate_report(problem_description: str, code: str, stdout: str, files: dict) -> str:
    file_list = ""
    if files:
        for name in files.keys():
            if name != "script.py":
                file_list += f"- `{name}`\n"
                file_list += get_file_explanation(name) + "\n\n"
    else:
        file_list = "No hay archivos generados."
    contents = (
        "Genera un reporte en Markdown que incluya los siguientes puntos, en el orden indicado, "
        "con explicaciones detalladas y claras:\n"
        "1. **Introducción:** Explica claramente cuál era el problema o tarea a resolver. Proporciona un contexto amplio "
        "y explica la motivación detrás de la solución. Detalla el enfoque general utilizado y los objetivos específicos "
        "que se buscaban alcanzar. Escribe un párrafo de 5-7 oraciones para esta sección.\n"
        "2. **Archivos Generados:** Lista los archivos generados. Para cada archivo, indica su nombre y propósito.\n"
        "   - Para cada archivo, proporciona una explicación *detallada* de su contenido y su papel en la solución del problema. Hazlo en un párrafo de 6-8 oraciones.\n"
        "   - Excluye cualquier prefijo como 'Archivo:' o ': Este archivo'.\n"
        "   - **No incluyas puntos de separación entre la descripción del archivo y el siguiente elemento.**\n"
        "   - Inserta el nombre del archivo entre doble llaves: {{nombre_archivo}} para que sea procesado posteriormente.\n"
        "3. **Conclusiones:** Resume si el problema fue resuelto exitosamente. Indica los posibles problemas o mejoras "
        "que podrían realizarse.\n\n"
        f"Problema: {problem_description}\n"
        f"Archivos generados y sus descripciones:\n{file_list}\n\n"
        "IMPORTANTE: No incluyas el código fuente ni la salida de la ejecución en el reporte. "
        "Enfócate solo en explicar el problema, listar los archivos generados y sus propósitos, "
        "y presentar conclusiones claras y concisas. **No incluyas el punto al final de cada explicación del archivo**"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": MarkdownResponse,
        },
    )
    try:
        markdown_content = response.parsed.content
        improved_content = improve_markdown(markdown_content)
        return improved_content
    except Exception as e:
        logging.exception(f"Error al procesar el reporte: {e}")
        try:
            raw_text = response.text
            return improve_markdown(raw_text)
        except:
            return "Error en la generación del reporte. Por favor, intente nuevamente."

def get_file_explanation(filename: str) -> str:
    prompt = (
        f"Explica en un párrafo de 6-8 oraciones el propósito y el contenido probable del archivo '{filename}'. "
        "Asume que este archivo fue generado como parte de un proceso de automatización de tareas con Python para resolver un problema de programación. "
        "Considera que este archivo puede contener cualquier tipo de datos, incluyendo texto, imágenes, audio o video. "
        "No incluyas prefijos como 'Archivo:' o ': Este archivo'. **No incluyas puntos de separación entre la descripción del archivo y el siguiente elemento. No incluyas el punto al final del párrafo**"
    )
    try:
        response = safe_generate_content(
            model="gemini-2.0-flash-lite-001",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": MarkdownResponse,
            },
        )
        if response.parsed and response.parsed.content:
            return response.parsed.content
        else:
            return f"No se pudo obtener una explicación para el archivo '{filename}'."
    except Exception as e:
        logging.exception(f"Error al obtener la explicación del archivo: {e}")
        return f"No se pudo obtener una explicación para el archivo '{filename}' debido a un error."

def validate_requirements_format(requirements: str) -> str:
    prompt = (
        "Corrige y valida el siguiente contenido de un archivo requirements.txt. "
        "Asegúrate de que cada dependencia esté en una línea separada, sin texto adicional ni errores de formato. "
        f"Contenido original:\n{requirements}\n\n"
        "Devuelve un JSON con el campo 'dependencies' que contenga el contenido corregido y validado."
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": CodeResponse,
        },
    )
    try:
        result = response.parsed.dict()
        corrected = result.get("dependencies", "").strip()
        if corrected:
            return corrected
        else:
            return requirements
    except Exception as e:
        logging.exception(f"Error en validate_requirements_format: {e}")
        return requirements

def compare_solutions(solutions: list[dict]) -> int:
    contents = "Evalúa las siguientes soluciones y determina cuál es la mejor para resolver el problema original.\n\n"
    for i, sol in enumerate(solutions):
        file_info = ", ".join(sol['generated_files'].keys())
        contents += f"Solución {i}: Archivos generados: {file_info}\n"
    contents += "\nConsidera los siguientes criterios:\n- Relevancia y utilidad de los archivos generados.\n- Eficiencia.\n"
    contents += "Devuelve el índice de la mejor solución (empezando en 0) en un JSON con el campo 'best_solution_index'."
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": BestSolutionResponse,
        },
    )
    try:
        best_index = response.parsed.best_solution_index
        if 0 <= best_index < len(solutions):
            return best_index
        return 0
    except Exception as e:
        logging.exception(f"Error al comparar soluciones: {e}")
        return 0

def evaluate_execution(prompt: str, code: str, stdout: str, files: dict) -> int:
    contents = f"Evalúa esta solución:\nPrompt: {prompt}\nCódigo: {code}\nStdout: {stdout}\nArchivos: {', '.join(files.keys())}\n"
    contents += "Asigna un puntaje del 1 al 10 basado en su efectividad. Devuelve solo el puntaje en un JSON con el campo 'score'."
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": EvaluationResponse,
        },
    )
    try:
        return response.parsed.score
    except Exception as e:
        logging.exception(f"Error en evaluate_execution: {e}")
        return 5  # Puntaje por defecto

def rank_solutions(solutions: list[dict]) -> list[int]:
    contents = "Rankea las siguientes soluciones de mejor a peor según su efectividad:\n\n"
    for i, sol in enumerate(solutions):
        files = ", ".join(sol['generated_files'].keys())
        contents += f"Solución {i}: Archivos generados: {files}\n"
    contents += "\nDevuelve una lista de índices en orden de mejor a peor en un JSON con el campo 'order'."
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": {"type": "object", "properties": {"order": {"type": "array", "items": {"type": "integer"}}}},
        },
    )
    try:
        ordered_indices = response.parsed['order']
        rankings = [0] * len(solutions)
        for rank, idx in enumerate(ordered_indices, start=1):
            rankings[idx] = rank
        return rankings
    except Exception as e:
        logging.exception(f"Error en rank_solutions: {e}")
        return list(range(1, len(solutions) + 1))  # Rankings por defecto