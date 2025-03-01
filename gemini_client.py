import os
import random
from google import genai
from pydantic import BaseModel
from dotenv import load_dotenv

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

client = None
MODEL_NAME = "gemini-2.0-flash-001"  # Nombre del modelo

def configure_gemini():
    load_dotenv()
    keys = [os.environ.get(f"GEMINI_API_KEY{i}") for i in range(1, 7) if os.environ.get(f"GEMINI_API_KEY{i}")]
    if not keys:
        raise ValueError("No se encontraron claves API en .env")
    api_key = random.choice(keys)
    global client
    client = genai.Client(api_key=api_key)

def ensure_client():
    global client
    if client is None:
        configure_gemini()

def improve_prompt(prompt: str, files: dict) -> dict:
    ensure_client()
    file_info = "\n".join([
        f"Archivo: {name}\nContenido (primeros 500 caracteres): " + (
            content.decode('utf-8', errors='ignore')[:500] if isinstance(content, bytes) else content[:500]
        )
        for name, content in files.items()
    ])
    contents = (
        "Ejemplo de prompt mejorado:\n"
        "Problema: Necesito un script en Python que lea un archivo CSV y genere un gráfico de barras usando matplotlib.\n"
        "Detalles adicionales: El archivo CSV tiene columnas 'fecha' y 'valor'.\n\n"
        f"Prompt original: {prompt}\nArchivos:\n{file_info}"
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=f"Mejora este prompt para que sea lo más claro y detallado posible, incluyendo ejemplos si es necesario. Also list the libraries that might be needed as dependencies:\n{contents}",
        config={
            "response_mime_type": "application/json",
            "response_schema": CodeResponse,
        },
    )
    try:
        return response.parsed.dict()
    except Exception as e:
        return {"code": "", "dependencies": ""}

def generate_code(improved_prompt: str, files: dict) -> dict:
    ensure_client()
    file_info = "\n".join([f"Archivo: {name}" for name in files.keys()])
    contents = (
        "Ejemplo:\n"
        "Si el prompt dice 'Generar un gráfico a partir de datos CSV', el código debe importar 'pandas' y 'matplotlib' y contener un bloque principal que realice la lectura y el gráfico.\n\n"
        f"Tarea: {improved_prompt}\nArchivos disponibles: {file_info}"
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=f"Genera código Python y una lista de dependencias en formato requirements.txt (una dependencia por línea, sin texto adicional) para resolver la siguiente tarea:\n{contents}",
        config={
            "response_mime_type": "application/json",
            "response_schema": CodeResponse,
        },
    )
    return response.parsed.dict()

def generate_code_modification(current_code: str, current_dependencies: str, new_prompt: str, files: dict) -> dict:
    ensure_client()
    file_info = "\n".join([f"Archivo: {name}" for name in files.keys()])
    contents = (
        f"Código actual:\n```python\n{current_code}\n```\n"
        f"Dependencias actuales:\n{current_dependencies}\n"
        f"Nuevo requerimiento: {new_prompt}\n"
        f"Archivos disponibles: {file_info}\n\n"
        "Genera una versión modificada del código Python que cumpla con el nuevo requerimiento. "
        "Además, proporciona una lista actualizada de dependencias en formato requirements.txt "
        "(una dependencia por línea, como 'pandas', 'matplotlib', sin explicaciones ni texto adicional). "
        "Asegúrate de incluir todas las dependencias necesarias para el código modificado, "
        "manteniendo las dependencias actuales que aún sean requeridas y agregando nuevas si es necesario."
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config={
            "response_mime_type": "application/json",
            "response_schema": CodeResponse,
        },
    )
    print("Respuesta cruda de la API:", response.text)  # Depuración
    try:
        parsed_response = response.parsed.dict()
        code = parsed_response.get("code", current_code)
        dependencies = parsed_response.get("dependencies", "")
        print("Código generado:", code)  # Depuración
        print("Dependencias parseadas:", dependencies)  # Depuración
        if not code.strip():
            print("Error: El código generado está vacío.")
            return {"code": current_code, "dependencies": current_dependencies}
        if not dependencies.strip():
            print("Advertencia: Las dependencias están vacías. Usando dependencias actuales.")
            parsed_response["dependencies"] = current_dependencies
        return parsed_response
    except Exception as e:
        print(f"Error al parsear la respuesta: {e}")
        return {"code": current_code, "dependencies": current_dependencies}

def analyze_execution_result(execution_result: dict) -> dict:
    ensure_client()
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
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=("Analiza el siguiente resultado de ejecución y devuelve 'OK' si fue exitoso o 'ERROR' si hubo problemas, "
                  "junto con una breve descripción del error:\n" + contents),
        config={
            "response_mime_type": "application/json",
            "response_schema": AnalysisResponse,
        },
    )
    return response.parsed.dict()

def generate_fix(error_type: str, error_message: str, code: str, dependencies: str, history: list) -> dict:
    ensure_client()
    history_text = "\n".join([f"Intento {i+1}: Error: {item.get('error_type', '')} - {item.get('error_message', '')}\nCódigo:\n{item.get('code', '')}\n" for i, item in enumerate(history)])
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
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt_fix,
        config={
            "response_mime_type": "application/json",
            "response_schema": FixResponse,
        },
    )
    return response.parsed.dict()

def generate_report(problem_description: str, code: str, stdout: str, files: dict) -> str:
    ensure_client()
    file_list = "\n".join([f"- {name}" for name in files.keys()]) if files else "No hay archivos generados."
    contents = (
        "Genera un reporte en Markdown que incluya los siguientes puntos:\n"
        "1. Descripción del problema.\n"
        "2. Código generado (en un bloque de código Python).\n"
        "3. Salida estándar del programa.\n"
        "4. Listado de archivos generados (si los hubiera).\n\n"
        f"Problema: {problem_description}\n"
        f"Código:\n```python\n{code}\n```\n"
        f"Salida: {stdout}\n"
        f"Archivos generados:\n{file_list}"
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=contents,
        config={"response_mime_type": "text/plain"},
    )
    return response.text

def validate_requirements_format(requirements: str) -> str:
    """
    Valida y corrige el formato del archivo requirements.txt.
    Se asegura de que cada dependencia esté en una línea separada y correctamente formateada.
    Devuelve el contenido corregido en formato requirements.txt (una dependencia por línea, sin texto adicional).
    """
    ensure_client()
    prompt = (
        "Corrige y valida el siguiente contenido de un archivo requirements.txt. "
        "Asegúrate de que cada dependencia esté en una línea separada, sin texto adicional ni errores de formato. "
        f"Contenido original:\n{requirements}\n\n"
        "Devuelve un JSON con el campo 'dependencies' que contenga el contenido corregido y validado."
    )
    response = client.models.generate_content(
        model=MODEL_NAME,
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
        print(f"Error en validate_requirements_format: {e}")
        return requirements
