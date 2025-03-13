import os
import random
import time
import logging
import pandas as pd
import io
import tempfile
import re
import json
from typing import Any, Dict, List, Set, Tuple, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator
from google import genai
from PIL import Image

# Configuración mejorada de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Modelos Pydantic para estructurar respuestas JSON
class PlanResponse(BaseModel):
    steps: List[str]

class CodeResponse(BaseModel):
    code: str
    dependencies: str

class AnalysisResponse(BaseModel):
    error_type: str
    error_message: str

class FixResponse(BaseModel):
    code: str
    dependencies: str

class MarkdownResponse(BaseModel):
    content: str

class RankResponse(BaseModel):
    order: List[int]

class FilesExplanationResponse(BaseModel):
    explanations: Dict[str, str]

    @field_validator("explanations", mode="before")
    def convert_values_to_str(cls, v):
        if isinstance(v, dict):
            return {key: str(value) for key, value in v.items()}
        return v

# Nuevos modelos para el manifiesto de archivos
class FileManifestEntry(BaseModel):
    name: str
    description: str

class FileManifestResponse(BaseModel):
    files: List[FileManifestEntry]

# Modelo para selección de archivos (opcional)
class SelectedFilesResponse(BaseModel):
    selected_files: List[str]

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
    """Obtiene un cliente Gemini con una clave API disponible."""
    global failed_api_keys
    exclude_keys = exclude_keys or set()
    keys = load_api_keys()
    available_keys = [k for k in keys if k not in failed_api_keys and k not in exclude_keys]
    if not available_keys:
        raise ValueError("No hay claves API disponibles (todas descartadas por errores).")
    api_key = random.choice(available_keys)
    client = genai.Client(api_key=api_key)
    return client, api_key

def safe_generate_content(model: str, contents: str, config: Dict, retries: int = 3) -> 'genai.Response':
    """Genera contenido con manejo robusto de errores y reintentos."""
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
                time.sleep(2 ** attempt)
                continue
            logging.error(f"Error de servicio: {e}")
            raise
        except Exception as e:
            logging.exception(f"Error inesperado: {e}")
            raise
    raise Exception(f"Todos los intentos fallaron tras {retries} reintentos.")

def configure_gemini() -> str:
    """Configura el cliente Gemini y verifica su estado."""
    try:
        client, api_key = get_client()
        logging.info("Gemini configurado exitosamente.")
        return "OK"
    except ValueError as e:
        logging.error(f"Error al configurar Gemini: {e}")
        return f"Error: {e}"
    except Exception as e:
        logging.exception(f"Error inesperado al configurar Gemini: {e}")
        return f"Error: {e}"

def upload_media_files(files: Dict[str, bytes]) -> Dict[str, Any]:
    """Sube archivos multimedia a Gemini."""
    client, _ = get_client()
    uploaded_files = {}
    for name, content in files.items():
        ext = os.path.splitext(name)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.svg', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.mp3', '.wav', '.ogg']:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(content)
                    tmp_filename = tmp.name
                file_ref = client.files.upload(file=tmp_filename)
                uploaded_files[name] = file_ref
                logging.info(f"Archivo {name} subido exitosamente: {file_ref.uri}")
            except Exception as e:
                logging.error(f"Error subiendo el archivo {name}: {e}")
            finally:
                try:
                    os.remove(tmp_filename)
                except Exception:
                    pass
    return uploaded_files

def analyze_image_content(image_bytes: bytes) -> str:
    """Analiza el contenido de una imagen (placeholder para visión por computadora)."""
    return "Descripción de la imagen pendiente de implementación."

def analyze_files_context(files: Dict[str, bytes]) -> Dict[str, str]:
    """Analiza el contexto de los archivos adjuntos."""
    file_details = {}
    for name, content in files.items():
        ext = os.path.splitext(name)[1].lower()
        if ext == '.csv':
            try:
                df = pd.read_csv(io.BytesIO(content))
                columns = ", ".join(df.columns)
                dtypes = ", ".join([f"{col}: {str(dtype)}" for col, dtype in df.dtypes.items()])
                file_details[name] = f"Archivo CSV con columnas: {columns}. Tipos de datos: {dtypes}. Datos estructurados para análisis."
            except Exception:
                file_details[name] = "Archivo CSV - No se pudo analizar el contenido."
        elif ext in ['.xls', '.xlsx']:
            try:
                df = pd.read_excel(io.BytesIO(content))
                columns = ", ".join(df.columns)
                dtypes = ", ".join([f"{col}: {str(dtype)}" for col, dtype in df.dtypes.items()])
                file_details[name] = f"Archivo Excel con columnas: {columns}. Tipos de datos: {dtypes}. Datos estructurados para procesamiento."
            except Exception:
                file_details[name] = "Archivo Excel - No se pudo analizar el contenido."
        elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.svg']:
            try:
                img = Image.open(io.BytesIO(content))
                width, height = img.size
                img_format = img.format
                description = analyze_image_content(content)
                file_details[name] = f"Imagen en formato {img_format}, dimensiones {width}x{height}. {description}"
            except Exception:
                file_details[name] = "Imagen - No se pudo analizar el contenido."
        else:
            try:
                preview = content[:500].decode('utf-8', errors='ignore')
                file_details[name] = f"Archivo con vista previa: {preview[:100]}... Propósito: datos o resultados específicos."
            except Exception:
                file_details[name] = "Archivo - No se pudo extraer una vista previa."
    return file_details

def get_detailed_file_explanations(files: Dict[str, bytes], files_context: Dict[str, str]) -> Dict[str, str]:
    """
    Obtiene explicaciones detalladas para cada archivo usando Gemini.
    
    Args:
        files (Dict[str, bytes]): Diccionario de nombre de archivo a contenido.
        files_context (Dict[str, str]): Información de contexto sobre los archivos.
        
    Returns:
        Dict[str, str]: Explicaciones detalladas para cada archivo (clave = nombre, valor = texto).
    """
    if not files:
        return {}
    
    file_info = []
    for file_name, content in files.items():
        file_ext = os.path.splitext(file_name)[1].lower()
        try:
            if file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.tiff']:
                file_info.append(f"- {file_name}: Archivo de imagen, contenido binario")
            else:
                try:
                    text_content = content.decode('utf-8', errors='ignore')
                    if len(text_content) > 1000:
                        text_content = text_content[:1000] + "... (truncado)"
                    file_info.append(f"- {file_name}: {text_content}")
                except:
                    file_info.append(f"- {file_name}: Contenido binario")
        except:
            file_info.append(f"- {file_name}: No se pudo analizar el contenido")
    
    file_info_str = "\n".join(file_info)
    
    response_schema = {
        "type": "object",
        "properties": {
            "explanations": {
                "type": "object",
                "properties": {}
            }
        }
    }
    
    for file_name in files.keys():
        response_schema["properties"]["explanations"]["properties"][file_name] = {
            "type": "string",
            "description": f"Explicación para {file_name}"
        }
    
    prompt = f"""
Tengo los siguientes archivos que se utilizarán para un experimento científico:
    
{file_info_str}
    
Información de contexto:
{json.dumps(files_context, ensure_ascii=False, indent=2)}

Por favor, proporciona una explicación detallada para cada archivo. Para cada archivo, la explicación debe extenderse entre 8 y 10 líneas, describiendo de forma completa:
- Su contenido.
- Formato y características técnicas.
- Función y utilidad en el estudio.
- Modo de creación o generación.
- Además, indica el marcador que se utilizará en el reporte, con el formato `{{nombre_archivo}}`.

**IMPORTANTE: Solo puedes referenciar archivos que te han sido proporcionados en la lista anterior. No debes inventar ni mencionar archivos que no existen.**

Responde en formato JSON con la estructura: 
{{ "explanations": {{ "nombre_archivo": "explicación detallada", ... }} }}
"""
    try:
        response = safe_generate_content(
            model="gemini-2.0-flash-lite-001",
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.2},
        )
        
        if response and hasattr(response, 'candidates') and response.candidates:
            result = response.candidates[0].content.parts[0].function_response.response['explanations']
            return result
        return {}
    except Exception as e:
        logging.error(f"Error al obtener explicaciones detalladas: {e}")
        return {}

def improve_prompt(prompt: str, files: Dict[str, bytes]) -> str:
    """
    Mejora el prompt del usuario agregando contexto de archivos.
    
    Args:
        prompt (str): Prompt original.
        files (Dict[str, bytes]): Diccionario de archivos.
        
    Returns:
        str: Prompt mejorado.
    """
    if not files:
        return prompt
    
    files_context = analyze_files_context(files)
    detailed_explanations = get_detailed_file_explanations(files, files_context)
    
    explanations_text = ""
    if detailed_explanations:
        explanations_text = "\nInformación detallada de archivos:\n"
        for filename, explanation in detailed_explanations.items():
            explanations_text += f"- {filename}: {explanation}\n"
    
    improved_prompt = f"""
Tarea original: {prompt}

Archivos disponibles:
{', '.join(files.keys())}

Contexto de archivos:
{json.dumps(files_context, ensure_ascii=False, indent=2)}
{explanations_text}

Crea una solución científica que aborde la tarea utilizando los archivos proporcionados. 
**Importante:** Debes incluir en la solución el proceso de generación de archivos de resultados que se guardarán en la raíz del proyecto. 
Cada archivo debe generarse con un marcador en el reporte usando el formato `{{nombre_archivo}}` y debe ir acompañado de una explicación detallada (8-10 líneas) de su contenido, formato y modo de creación.
**SOLO puedes mencionar en el reporte los archivos que te he proporcionado en la lista 'Archivos disponibles'. No inventes archivos que no existen.**
"""
    return improved_prompt

def generate_file_manifest(files: Dict[str, bytes]) -> Dict[str, Any]:
    """
    Genera un manifiesto de archivos que se deben crear en la raíz del proyecto.
    Cada entrada debe incluir:
      - "name": el nombre del archivo (ruta en la raíz del proyecto).
      - "description": una explicación detallada (4-10 líneas) de qué es el archivo, su contenido, función, 
        cómo debe crearse y el marcador correspondiente en el reporte (usar formato `{{nombre_archivo}}`).
    """
    file_list = list(files.keys())
    prompt = f"""
Tengo los siguientes archivos disponibles para documentar el experimento:
{', '.join(file_list)}
Por favor, genera un listado en formato JSON de todos los archivos que se deben crear en la raíz del proyecto, 
donde cada entrada incluya:
- "name": el nombre del archivo.
- "description": una explicación detallada (4-10 líneas) que describa:
    • Contenido y características técnicas.
    • Función y utilidad en el estudio.
    • Modo de creación.
    • El marcador a usar en el reporte, en el formato `{{nombre_archivo}}`.
**SOLO puedes mencionar en el reporte los archivos que te he proporcionado en la lista de archivos disponibles. No inventes archivos que no existen.**
Responde en el siguiente formato:
{{
  "files": [
    {{"name": "archivo1.ext", "description": "explicación detallada"}} ,
    {{"name": "archivo2.ext", "description": "explicación detallada"}} ,
    ...
  ]
}}
"""
    try:
        response = safe_generate_content(
            model="gemini-2.0-flash-lite-001",
            contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": FileManifestResponse, "top_p": 0.95, "temperature": 1.0}
        )
        return response.parsed.dict()
    except Exception as e:
        logging.error(f"Error generando el manifiesto de archivos: {e}")
        return {}

def generate_plan(improved_prompt: str, files: Dict[str, bytes]) -> str:
    """Genera un plan paso a paso para resolver la tarea científica."""
    contents = f"""
Genera un plan paso a paso para resolver esta tarea científica:
Tarea: {improved_prompt}
Archivos disponibles: {', '.join(files.keys())}
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "text/plain", "top_p": 0.95, "temperature": 1.0}
    )
    return response.text

def generate_code(plan: str, files: Dict[str, bytes], save_prompt_to_file: bool = True) -> Dict[str, str]:
    """
    Genera código Python y dependencias basado en el plan, incluyendo el manifiesto de archivos.
    **Importante:** El código generado debe crear y guardar en el directorio raíz del proyecto todos los archivos de resultados.
    Debe incluir, para cada archivo, un marcador en el reporte (formato `{{nombre_archivo}}`) y una explicación detallada (8-10 líneas)
    que describa su contenido, formato, función y modo de creación. Estos archivos se generarán obligatoriamente, aunque no se lo indique explícitamente.
    """
    file_manifest = generate_file_manifest(files)
    manifest_str = json.dumps(file_manifest, ensure_ascii=False, indent=2)
    # Quitar "Archivo:" para no repetirlo en la lista de archivos
    file_info = "\n".join([name for name in files.keys()])
    contents = f"""
Genera el código Python y las dependencias necesarias basados en el siguiente plan científico:
Plan: {plan}

Manifiesto de archivos (a crear en la raíz del proyecto):
{manifest_str}

Archivos disponibles:
{file_info}

**Requisitos adicionales:**
- El código debe obligatoriamente crear y guardar los archivos de resultados en la raíz del proyecto.
- Cada archivo generado debe tener un marcador en el reporte en el formato `{{nombre_archivo}}`.
- Para cada archivo, incluye en el reporte una explicación detallada (8-10 líneas) de su contenido, formato, función y modo de creación.
**SOLO puedes mencionar en el reporte los archivos que te he proporcionado en la lista de archivos disponibles. No inventes archivos que no existen.**
"""
    if save_prompt_to_file:
        with open("generate_code_prompt.txt", "w", encoding="utf-8") as f:
            f.write(contents)
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "application/json", "response_schema": CodeResponse, "top_p": 0.95, "temperature": 0.7}
    )
    return response.parsed.dict()

def analyze_execution_result(execution_result: Dict) -> Dict[str, str]:
    """Analiza el resultado de la ejecución del código."""
    stdout = execution_result.get("stdout", "")
    stderr = execution_result.get("stderr", "")
    files = execution_result.get("files", {})
    summary = f"stdout: {stdout[:300000]}\nstderr: {stderr[:300000]}\narchivos: {list(files.keys())}"
    contents = f"Resultado: {summary}"
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=("Analiza el resultado y devuelve 'OK' si fue exitoso o 'ERROR' con una descripción:\n" + contents),
        config={"response_mime_type": "application/json", "response_schema": AnalysisResponse, "top_p": 0.95, "temperature": 1.0}
    )
    return response.parsed.dict()

def generate_fix(error_type: str, error_message: str, code: str, dependencies: str, history: List[Dict]) -> Dict[str, str]:
    """Corrige el código basado en el error encontrado."""
    history_text = "\n".join([f"Intento {i+1}: {item.get('analysis', {})}" for i, item in enumerate(history)])
    prompt_fix = f"""
Corrige el código para resolver el error:
Historial: {history_text}
Error: {error_type} - {error_message}
Código: {code}
Dependencias: {dependencies}
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt_fix,
        config={"response_mime_type": "application/json", "response_schema": FixResponse, "top_p": 0.95, "temperature": 1.0}
    )
    return response.parsed.dict()

def improve_markdown(content: str) -> str:
    """Mejora el formato Markdown para mayor legibilidad y evita repeticiones en títulos."""
    content = re.sub(r'(#+)(\w)', r'\1 \2', content)
    content = re.sub(r'^-\s*([^\s])', r'- \1', content, flags=re.MULTILINE)
    content = re.sub(r'(#+.+)\n([^#\n])', r'\1\n\n\2', content)
    content = re.sub(r'\n{3,}', r'\n\n', content)

    # Agregar numeración manual para secciones principales
    lines = content.splitlines()
    new_lines = []
    section_counter = 0
    for line in lines:
        if line.strip().startswith('#'):
            if line.count('#') == 1:
                section_counter += 1
                line = re.sub(r'^#\s*', f'# {section_counter}. ', line)
            else:
                line = re.sub(r'^#+\s*', '# ', line)
        new_lines.append(line)
    return "\n".join(new_lines).strip()

def select_relevant_files(files: Dict[str, bytes]) -> List[str]:
    """
    Selecciona archivos relevantes para incluir en el reporte, 
    considerando solo los generados y evitando duplicados.
    """
    excluded_files = {"script.py", "requirements.txt", "generate_code_prompt.txt"}
    candidates = {name: content for name, content in files.items() if name not in excluded_files}
    if not candidates:
        return []
    video_ext = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    gif_ext = {'.gif'}
    image_ext = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.svg'}
    csv_ext = {'.csv'}
    
    videos, gifs, csvs, images, others = [], [], [], [], []
    for name in candidates:
        ext = os.path.splitext(name)[1].lower()
        if ext in video_ext:
            videos.append(name)
        elif ext in gif_ext:
            gifs.append(name)
        elif ext in csv_ext:
            csvs.append(name)
        elif ext in image_ext:
            images.append(name)
        else:
            others.append(name)
            
    selected = []
    if videos or gifs:
        selected.extend(videos + gifs + csvs + others)
    else:
        selected.extend(csvs + images[:1] + others)
    seen = set()
    final_selected = []
    for file in selected:
        if file not in seen and file in candidates:
            final_selected.append(file)
            seen.add(file)
    return final_selected

def filter_relevant_files(files: Dict[str, bytes], max_files: int = 5) -> List[str]:
    """
    Selecciona los archivos más relevantes para incluir en el reporte cuando hay muchos disponibles.
    Se utiliza un prompt a Gemini para evaluar la relevancia y devolver solo hasta 'max_files' archivos.
    """
    file_names = list(files.keys())
    if len(file_names) <= max_files:
        return file_names

    prompt = f"""
Tengo la siguiente lista de archivos disponibles:
{', '.join(file_names)}
Debido a que incluir todos los archivos en el reporte puede resultar muy extenso,
por favor, selecciona únicamente los {max_files} archivos más relevantes, considerando que
deben aportar la información esencial para la interpretación científica del experimento.
Devuélveme la respuesta en formato JSON con la siguiente estructura:
{{
  "relevant_files": ["nombre_archivo1", "nombre_archivo2", ...]
}}
Recuerda que solo debes elegir aquellos archivos que sean cruciales para el análisis.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.3}
    )
    try:
        parsed = response.parsed.dict()
        relevant_files = parsed.get("relevant_files", [])
        return relevant_files[:max_files]
    except Exception as e:
        logging.error(f"Error al filtrar archivos relevantes: {e}")
        return file_names[:max_files]

def extend_report_section(section_title: str, base_content: str, files: Dict[str, bytes]) -> str:
    """
    Extiende y enriquece una sección del reporte científico haciendo una petición a Gemini.
    
    Args:
        section_title (str): Título de la sección (ej., "Introducción").
        base_content (str): Contenido base de la sección.
        files (Dict[str, bytes]): Lista de archivos disponibles.
        
    Returns:
        str: Texto extendido y enriquecido para la sección.
    """
    file_list = list(files.keys())
    prompt = f"""
Por favor, extiende y enriquece la siguiente sección del reporte científico titulada "{section_title}".
Contenido base:
{base_content}
Archivos disponibles: {', '.join(file_list)}
Incluye detalles adicionales, análisis profundo, ejemplos y cualquier información relevante que amplíe la comprensión del tema.

Si la sección hace referencia a archivos de resultados, solo puedes mencionar archivos que te he proporcionado en la lista de archivos disponibles.

Indica el marcador correspondiente en el formato `{{nombre_archivo}}` y proporciona una explicación detallada (8-10 líneas) de cada archivo, su contenido, formato, función y utilidad en el estudio.
Respuesta completa en español.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "top_p": 0.95, "temperature": 1.0}
    )
    return response.text.strip()

def enhance_problem_description(description: str) -> str:
    """Redacta de manera científica y formal la descripción del problema."""
    prompt = (
        "Redacta de manera científica y formal la siguiente descripción del problema:\n\n"
        f"{description}"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "top_p": 0.95, "temperature": 1.0}
    )
    return response.text.strip()

def rank_solutions(solutions: List[Dict]) -> List[int]:
    """Rankea las soluciones científicas generadas."""
    contents = "\n".join([f"Solución {i}: Archivos: {', '.join(sol['generated_files'].keys())}" for i, sol in enumerate(solutions)])
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=(f"Rankea estas soluciones científicas:\n{contents}\nDevuelve una lista de índices en orden (mejor a peor) en 'order'."),
        config={"response_mime_type": "application/json", "response_schema": RankResponse, "top_p": 0.95, "temperature": 1.0}
    )
    order = response.parsed.dict().get('order', [])
    rankings = [0] * len(solutions)
    for rank, idx in enumerate(order, 1):
        rankings[idx] = rank
    return rankings

def generate_extensive_report(plan: str, files: Dict[str, bytes]) -> str:
    """
    Genera un reporte extenso y detallado en un único prompt.
    
    El reporte debe:
    - Explicar únicamente los archivos más importantes de los generados.
    - Incluir para cada archivo un marcador en el formato `{{nombre_archivo}}` y una explicación detallada (8-10 líneas) que describa su contenido, formato, función y modo de creación.
    - Estar redactado en primera persona, afirmando categóricamente la creación y utilidad de cada archivo sin expresiones dubitativas (no usar frases como "creo que" o "puede ser").
    - Incluir toda la información relevante en un solo mensaje.
    
    Args:
        plan (str): El plan científico utilizado para la generación de código.
        files (Dict[str, bytes]): Diccionario con los archivos generados.
    
    Returns:
        str: El reporte extenso en formato texto.
    """
    # Seleccionar solo los archivos más importantes (máximo 5)
    important_files = filter_relevant_files(files, max_files=5)
    files_list = ", ".join(important_files)
    
    prompt = f"""
Como autor del experimento, he generado un código que cumple con el plan científico establecido. A continuación, presento un reporte extenso y detallado en el que describo de manera categórica y en primera persona los archivos más importantes que se han generado en la raíz del proyecto. Cada archivo se identifica con un marcador en el formato `{{nombre_archivo}}` y se acompaña de una explicación completa de 8 a 10 líneas, en la que afirmo su contenido, formato, función y el proceso de creación, sin utilizar expresiones dudosas.

Plan científico utilizado:
{plan}

Archivos más importantes generados: {files_list}

Por favor, redacta un reporte extenso y unificado que incluya todos estos detalles en un solo prompt, asegurándote de que cada archivo relevante se describa detalladamente siguiendo el formato indicado.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "top_p": 0.95, "temperature": 1.0}
    )
    return response.text.strip()
