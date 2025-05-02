import os
import random
import time
import logging
import pandas as pd
import io
import tempfile
import re
import json
import base64
from typing import Any, Dict, List, Set, Tuple, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator
from google import genai
from google.genai import types
from PIL import Image
from io import BytesIO

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==============================
# Modelos Pydantic para respuestas
# ==============================

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
        return {key: str(value) for key, value in v.items()} if isinstance(v, dict) else v

class FileManifestEntry(BaseModel):
    name: str
    description: str

class FileManifestResponse(BaseModel):
    files: List[FileManifestEntry]

# ==============================
# Manejo de claves API y cliente
# ==============================

failed_api_keys: Set[str] = set()

def load_api_keys() -> List[str]:
    """Carga las claves API de Gemini desde el archivo .env."""
    load_dotenv()
    keys = [os.environ.get(f"GEMINI_API_KEY{i}") for i in range(1, 7) if os.environ.get(f"GEMINI_API_KEY{i}")]
    if not keys:
        raise ValueError("No se encontraron claves API en .env")
    return keys

def get_client(exclude_keys: Optional[Set[str]] = None) -> Tuple['genai.Client', str]:
    """Obtiene un cliente Gemini, manejando claves API fallidas y reintentos."""
    global failed_api_keys
    exclude_keys = exclude_keys or set()
    keys = load_api_keys()
    available_keys = [k for k in keys if k not in failed_api_keys and k not in exclude_keys]
    if not available_keys:
        raise ValueError("No hay claves API disponibles")
    api_key = random.choice(available_keys)
    client = genai.Client(api_key=api_key)
    return client, api_key

def safe_generate_content(model: str, contents: str, config: Dict, retries: int = 3) -> 'genai.Response':
    """Genera contenido de forma segura, reintentando en caso de errores de límite de tasa."""
    global failed_api_keys
    from google.genai.errors import ClientError
    used_keys: Set[str] = set()
    for attempt in range(retries):
        client, current_key = get_client(exclude_keys=used_keys)
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            return response
        except ClientError as e:
            if "rate limit" in str(e).lower():
                used_keys.add(current_key)
                failed_api_keys.add(current_key)
                logging.warning(f"Clave API {current_key} falló por límite de tasa")
                time.sleep(2 ** attempt)
                continue
            logging.error(f"Error de servicio: {e}")
            raise
        except Exception as e:
            logging.exception(f"Error inesperado: {e}")
            raise
    raise Exception(f"Todos los intentos fallaron tras {retries} reintentos")

def configure_gemini() -> str:
    """Configura y verifica la conexión al cliente Gemini."""
    try:
        client, _ = get_client()
        logging.info("Gemini configurado exitosamente")
        return "OK"
    except ValueError as e:
        logging.error(f"Error al configurar Gemini: {e}")
        return f"Error: {e}"
    except Exception as e:
        logging.exception(f"Error inesperado: {e}")
        return f"Error: {e}"

# ==============================
# Funciones para manejo y análisis de archivos
# ==============================

def upload_media_files(files: Dict[str, bytes]) -> Dict[str, Any]:
    """Sube archivos multimedia a Gemini."""
    client, _ = get_client()
    uploaded_files = {}
    for name, content in files.items():
        ext = os.path.splitext(name)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.svg',
                   '.mp4', '.mov', '.avi', '.mkv', '.webm', '.mp3', '.wav', '.ogg']:
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(content)
                tmp_filename = tmp.name
            try:
                file_ref = client.files.upload(file=tmp_filename)
                uploaded_files[name] = file_ref
                logging.info(f"Archivo {name} subido: {file_ref.uri}")
            except Exception as e:
                logging.error(f"Error subiendo {name}: {e}")
            finally:
                os.remove(tmp_filename)
    return uploaded_files

def analyze_files_context(files: Dict[str, bytes]) -> Dict[str, str]:
    """Analiza el contexto de los archivos proporcionados."""
    file_details = {}
    for name, content in files.items():
        ext = os.path.splitext(name)[1].lower()
        if ext == '.csv':
            try:
                df = pd.read_csv(io.BytesIO(content))
                file_details[name] = f"CSV con columnas: {', '.join(df.columns)}. Tipos: {', '.join([f'{col}: {dtype}' for col, dtype in df.dtypes.items()])}"
            except Exception:
                file_details[name] = "CSV - No se pudo analizar"
        elif ext in ['.xls', '.xlsx']:
            try:
                df = pd.read_excel(io.BytesIO(content))
                file_details[name] = f"Excel con columnas: {', '.join(df.columns)}. Tipos: {', '.join([f'{col}: {dtype}' for col, dtype in df.dtypes.items()])}"
            except Exception:
                file_details[name] = "Excel - No se pudo analizar"
        elif ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.svg']:
            try:
                img = Image.open(io.BytesIO(content))
                file_details[name] = f"Imagen {img.format}, {img.size[0]}x{img.size[1]}"
            except Exception:
                file_details[name] = "Imagen - No se pudo analizar"
        else:
            try:
                preview = content[:500].decode('utf-8', errors='ignore')
                file_details[name] = f"Vista previa: {preview[:100]}..."
            except Exception:
                file_details[name] = "No se pudo extraer vista previa"
    return file_details

def get_detailed_file_explanations(files: Dict[str, bytes], files_context: Dict[str, str]) -> Dict[str, str]:
    """Obtiene explicaciones detalladas de los archivos para mejorar el prompt."""
    if not files:
        return {}
    file_info = []
    for name, content in files.items():
        ext = os.path.splitext(name)[1].lower()
        if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.tiff']:
            decoded_content = content[:1000].decode('utf-8', errors='ignore')
            escaped_content = decoded_content.replace('\\', '\\\\')
            file_info.append(f"- {name}: {escaped_content}")
        else:
            file_info.append(f"- {name}: Archivo de imagen")
    joined_file_info = "\n".join(file_info)
    prompt = f"""
Tengo los siguientes archivos para un experimento:
{joined_file_info}
Contexto:
{json.dumps(files_context, ensure_ascii=False, indent=2)}
Por favor, proporciona una explicación detallada (8-10 líneas) para cada archivo.
Para cada archivo, incluye:
- Contenido y vista previa
- Formato y características técnicas
- Función y utilidad en el experimento
- Modo de creación (cómo se generó)
Utiliza el marcador `{{nombre_archivo}}` para identificar cada archivo.
Devuelve la respuesta en JSON con la siguiente estructura:
{{"explanations": {{"nombre_archivo": "explicación detallada"}}}}
"""
    try:
        response = safe_generate_content(
            model="gemini-2.0-flash-lite-001",
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.2}
        )
        return response.candidates[0].content.parts[0].function_response.response['explanations']
    except Exception as e:
        logging.error(f"Error en explicaciones: {e}")
        return {}

def improve_prompt(prompt: str, files: Dict[str, bytes]) -> str:
    """Mejora el prompt del usuario con contexto de los archivos."""
    if not files:
        return prompt
    files_context = analyze_files_context(files)
    detailed_explanations = get_detailed_file_explanations(files, files_context)
    explanations_text = ("\nInformación detallada:\n" +
                         "\n".join(f"- {k}: {v}" for k, v in detailed_explanations.items())
                         if detailed_explanations else "")
    return f"""
Tarea: {prompt}
Archivos: {', '.join(files.keys())}
Contexto de archivos:
{json.dumps(files_context, ensure_ascii=False, indent=2)}
{explanations_text}
Crea una solución científica utilizando solo los archivos proporcionados.
"""

def generate_file_manifest(files: Dict[str, bytes]) -> Dict[str, Any]:
    """Genera un manifiesto de archivos a crear."""
    prompt = f"""
Archivos disponibles: {', '.join(files.keys())}
Genera un JSON con los archivos a crear en la raíz. Cada entrada debe incluir:
- "name": nombre del archivo.
- "description": explicación (4-10 líneas) de su contenido, función, modo de creación y debe incluir el marcador `{{nombre_archivo}}`.
La respuesta debe tener la siguiente estructura:
{{"files": [{{"name": "archivo.ext", "description": "explicación"}}]}}
"""
    try:
        response = safe_generate_content(
            model="gemini-2.0-flash-lite-001",
            contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": FileManifestResponse, "temperature": 1.0}
        )
        return response.parsed.dict()
    except Exception as e:
        logging.error(f"Error en manifiesto: {e}")
        return {}

def generate_plan(improved_prompt: str, files: Dict[str, bytes]) -> str:
    """Genera un plan paso a paso para la tarea."""
    contents = f"""
Genera un plan paso a paso para la siguiente tarea:
Tarea: {improved_prompt}
Archivos disponibles: {', '.join(files.keys())}
Asegúrate de describir cada paso de forma clara y concisa.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "text/plain", "temperature": 1.0}
    )
    return response.text

def generate_code(plan: str, files: Dict[str, bytes], save_prompt_to_file: bool = True) -> Dict[str, str]:
    """Genera código Python basado en el plan y el manifiesto de archivos."""
    file_manifest = generate_file_manifest(files)
    contents = f"""
Genera código Python que implemente el siguiente plan:
Plan: {plan}
Manifiesto de archivos:
{json.dumps(file_manifest, ensure_ascii=False, indent=2)}
Archivos disponibles: {', '.join(files.keys())}
Requisitos:
- Crear archivos en la raíz.
- Utilizar el marcador `{{nombre_archivo}}` para indicar dónde se insertará la explicación detallada.
- Incluir comentarios que expliquen la funcionalidad.
Solo usa los archivos proporcionados.
"""
    if save_prompt_to_file:
        with open("generate_code_prompt.txt", "w", encoding="utf-8") as f:
            f.write(contents)
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "application/json", "response_schema": CodeResponse, "temperature": 0.7}
    )
    return response.parsed.dict()

def analyze_execution_result(execution_result: Dict) -> Dict[str, str]:
    """Analiza el resultado de la ejecución del código en Docker."""
    stdout = execution_result.get("stdout", "")[:300000]
    stderr = execution_result.get("stderr", "")[:300000]
    files_list = list(execution_result.get("files", {}).keys())
    contents = f"Resultado: stdout: {stdout}\nstderr: {stderr}\nArchivos generados: {files_list}"
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=f"Analiza lo siguiente y devuelve 'OK' o 'ERROR' con descripción:\n{contents}",
        config={"response_mime_type": "application/json", "response_schema": AnalysisResponse, "temperature": 1.0}
    )
    return response.parsed.dict()

def generate_fix(error_type: str, error_message: str, code: str, dependencies: str, history: List[Dict]) -> Dict[str, str]:
    """Genera una corrección para el código basado en el error y el historial."""
    history_text = "\n".join([f"Intento {i+1}: {item.get('analysis', {})}" for i, item in enumerate(history)])
    prompt = f"""
Corrige el siguiente código considerando el historial de intentos:
Historial: {history_text}
Error: {error_type} - {error_message}
Código actual: {code}
Dependencias: {dependencies}
Genera una versión corregida que solucione los errores.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": FixResponse, "temperature": 1.0}
    )
    return response.parsed.dict()

# ==============================
# Funciones para generación y edición de imágenes
# ==============================

def generate_imagen_report_images(prompt: str, number_of_images: int = 1, aspect_ratio: str = "1:1") -> List[str]:
    """a
    Genera imágenes usando el modelo Imagen.
    Devuelve una lista de imágenes codificadas en base64 (formato PNG) para incluir en Markdown.
    """
    client, _ = get_client()
    response = client.models.generate_images(
        model='imagen-3.0-generate-002',
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=number_of_images,
            aspect_ratio=aspect_ratio,
        )
    )
    images_base64 = []
    for generated_image in response.generated_images:
        img = Image.open(BytesIO(generated_image.image.image_bytes))
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        images_base64.append(img_str)
    return images_base64

def edit_report_image(image_path: str, prompt: str) -> Optional[Image.Image]:
    """
    Edita una imagen existente utilizando Gemini.
    Recibe la ruta de la imagen y un prompt de edición.
    Devuelve la imagen editada o None en caso de error.
    """
    try:
        image = Image.open(image_path)
        client, _ = get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash-exp-image-generation",
            contents=[prompt, image],
            config=types.GenerateContentConfig(
                response_modalities=['Text', 'Image']
            )
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                edited_image = Image.open(BytesIO(part.inline_data.data))
                return edited_image
    except Exception as e:
        logging.error(f"Error editando imagen: {e}")
    return None

# ==============================
# Nuevas funciones para mejorar y corregir el Markdown
# ==============================

def improve_markdown(report: str) -> str:
    """
    Revisa y corrige el formato Markdown, asegurando:
    - Bloques de código correctamente cerrados.
    - Que los marcadores de archivos ({{nombre_archivo}}) estén en líneas separadas.
    """
    # Verifica si hay bloques de código sin cerrar (comprobando las comillas triples)
    count_backticks = report.count("```")
    if count_backticks % 2 != 0:
        report += "\n```"
    # Asegura que los marcadores de archivo estén en líneas separadas
    report = re.sub(r"([^\n])({{[^}]+}})", r"\1\n\2", report)
    report = re.sub(r"({{[^}]+}})([^\n])", r"\1\n\2", report)
    return report

def verify_file_markers(report: str, files: List[str]) -> str:
    """
    Verifica que cada archivo relevante tenga su marcador en el reporte.
    Si falta alguno, lo añade en una sección "Marcadores Faltantes".
    """
    missing = []
    for f in files:
        marker = f"{{{{{f}}}}}"
        if marker not in report:
            missing.append(marker)
    if missing:
        report += "\n\n## Marcadores Faltantes\n"
        for marker in missing:
            report += f"\n{marker}\nExplicación pendiente para {marker[2:-2]}.\n"
    return report

def finalize_markdown_report(report: str, relevant_files: List[str]) -> str:
    """
    Orquesta la mejora del reporte Markdown, corrigiendo el formato y verificando la existencia de marcadores.
    """
    report = improve_markdown(report)
    report = verify_file_markers(report, relevant_files)
    return report

# ==============================
# Función actualizada para generación de reporte extenso
# ==============================

def generate_extensive_report(plan: str, files: Dict[str, bytes], image_prompts: Optional[Dict[str, str]] = None) -> str:
    """
    Genera un reporte científico extenso y formal en Markdown.
    Incluye secciones numeradas, explicaciones detalladas de archivos y manejo de imágenes.
    Se integra la mejora del Markdown para asegurar formato impecable.
    """
    important_files = ", ".join(filter_relevant_files(files, max_files=5))
    prompt = f"""
Como autor del experimento, redacta un reporte científico extenso y formal en Markdown con al menos 1000 palabras.
NO AÑADAS FRAGMENTO DE CODIGO NUNCA QUE NO AYUDA A NADA ES UN RESUMEN INFORMATIVO, NO QUIERO FRAGMENTOS DE CODIGO.
El reporte debe estar escrito en primera persona y contener las siguientes secciones, numeradas de forma lógica:

# 1. Introducción
   - 1.0 Propósito del Experimento
   - 1.1 Contexto y Antecedentes Relevantes
   - 1.2 Hipótesis o Preguntas de Investigación

# 2. Metodología
   - 2.0 Descripción Detallada del Plan
   - 2.1 Técnicas y Métodos Utilizados

# 3. Resultados
   - 3.0 Presentación de Resultados (incluye figuras y tablas si es pertinente)
   - 3.1 Análisis de Resultados

# 4. Conclusiones
   - 4.0 Resumen de Hallazgos
   - 4.1 Implicaciones y Discusión

Archivos relevantes: {important_files}

Para cada archivo relevante, **separe la inserción del marcador `{{nombre_archivo}}` del texto Markdown circundante en líneas separadas**.
Inmediatamente después del marcador `{{nombre_archivo}}` en una nueva línea, proporcione una explicación detallada de 8-10 líneas que incluya:
  - Contenido y vista previa.
  - Formato y características técnicas.
  - Función y utilidad en el experimento.
  - Modo de creación (cómo se generó).

**Ejemplo de inserción de archivo en el reporte (formato correcto):**

```markdown
## Sección de Resultados

Aquí presentamos algunos resultados importantes.

{{mi_archivo.csv}}
Explicación detallada de mi_archivo.csv:
Este archivo contiene datos de experimentos... (8-10 líneas de explicación)

Y aquí continúa el texto Markdown después de la inserción del archivo.
```

Asegúrate de que el reporte tenga formato Markdown correcto desde el inicio para que se visualice de manera impecable en visualizadores como Streamlit.
Solo utiliza los archivos proporcionados y, si se especifican prompts para imágenes, reemplaza el marcador correspondiente por la imagen generada en formato base64.
Genera el reporte en un solo paso, sin fragmentaciones, que sea claro, conciso y perfecto.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "temperature": 0.8}
    )
    report = response.text.strip()

    # Reemplazo de marcadores por imágenes generadas, si se han especificado
    if image_prompts:
        for marker, img_prompt in image_prompts.items():
            imgs = generate_imagen_report_images(img_prompt, number_of_images=1)
            if imgs:
                img_markdown = f"![{marker}](data:image/png;base64,{imgs[0]})"
                report = report.replace(f"{{{{{marker}}}}}", img_markdown)
    # Finaliza el reporte aplicando mejoras en el Markdown y verificando marcadores
    relevant_files = list(filter_relevant_files(files, max_files=5))
    report = finalize_markdown_report(report, relevant_files)
    return report

def enhance_problem_description(description: str) -> str:
    """Mejora la descripción del problema para un tono científico."""
    prompt = f"Redacta de manera científica y formal el siguiente problema:\n{description}"
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "temperature": 1.0}
    )
    return response.text.strip()

def rank_solutions(solutions: List[Dict]) -> List[int]:
    """Rankea las soluciones generadas."""
    contents = "\n".join([f"Solución {i}: Archivos: {', '.join(sol['generated_files'].keys())}" for i, sol in enumerate(solutions)])
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=f"Rankea las soluciones de mejor a peor basándote en la calidad de los archivos generados:\n{contents}\nDevuelve los índices en el campo 'order'.",
        config={"response_mime_type": "application/json", "response_schema": RankResponse, "temperature": 1.0}
    )
    order = response.parsed.dict().get('order', [])
    rankings = [0] * len(solutions)
    for rank, idx in enumerate(order, 1):
        rankings[idx] = rank
    return rankings

def filter_relevant_files(files: Dict[str, bytes], max_files: int = 5) -> List[str]:
    """Filtra los archivos más relevantes para el reporte."""
    file_names = list(files.keys())
    if len(file_names) <= max_files:
        return file_names
    prompt = f"""
    Archivos disponibles: {', '.join(file_names)}
    Selecciona los {max_files} archivos más relevantes para el reporte científico.
    Devuelve un JSON con la lista en el campo 'relevant_files', por ejemplo:
    {{"relevant_files": ["archivo1.ext", "archivo2.ext", ...]}}
    """
    try:
        response = safe_generate_content(
            model="gemini-2.0-flash-lite-001",
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.3}
        )
        return response.parsed.dict().get("relevant_files", [])[:max_files]
    except Exception as e:
        logging.error(f"Error filtrando archivos: {e}")
        return file_names[:max_files]