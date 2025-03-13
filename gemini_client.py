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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

failed_api_keys: Set[str] = set()

def load_api_keys() -> List[str]:
    load_dotenv()
    keys = [os.environ.get(f"GEMINI_API_KEY{i}") for i in range(1, 7) if os.environ.get(f"GEMINI_API_KEY{i}")]
    if not keys:
        raise ValueError("No se encontraron claves API en .env")
    return keys

def get_client(exclude_keys: Optional[Set[str]] = None) -> Tuple['genai.Client', str]:
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

def upload_media_files(files: Dict[str, bytes]) -> Dict[str, Any]:
    client, _ = get_client()
    uploaded_files = {}
    for name, content in files.items():
        ext = os.path.splitext(name)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.svg', '.mp4', '.mov', '.avi', '.mkv', '.webm', '.mp3', '.wav', '.ogg']:
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
    if not files:
        return {}
    file_info = [f"- {name}: {content[:1000].decode('utf-8', errors='ignore') if ext not in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.tiff'] else 'Archivo de imagen'}" 
                 for name, content in files.items() for ext in [os.path.splitext(name)[1].lower()]]
    prompt = f"""
Tengo estos archivos para un experimento:
{'\n'.join(file_info)}
Contexto:
{json.dumps(files_context, ensure_ascii=False, indent=2)}
Proporciona una explicación detallada (8-10 líneas) para cada archivo:
- Contenido
- Formato y características
- Función y utilidad
- Modo de creación
- Marcador: `{{nombre_archivo}}`
Solo usa archivos proporcionados. Responde en JSON: {{"explanations": {{"nombre": "explicación"}}}}
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
    if not files:
        return prompt
    files_context = analyze_files_context(files)
    detailed_explanations = get_detailed_file_explanations(files, files_context)
    explanations_text = "\nInformación detallada:\n" + "\n".join(f"- {k}: {v}" for k, v in detailed_explanations.items()) if detailed_explanations else ""
    return f"""
Tarea: {prompt}
Archivos: {', '.join(files.keys())}
Contexto:
{json.dumps(files_context, ensure_ascii=False, indent=2)}
{explanations_text}
Crea una solución científica usando los archivos. Genera archivos de resultados en la raíz con marcador `{{nombre_archivo}}` y explicación detallada (8-10 líneas).
Solo usa archivos proporcionados.
"""

def generate_file_manifest(files: Dict[str, bytes]) -> Dict[str, Any]:
    prompt = f"""
Archivos disponibles: {', '.join(files.keys())}
Genera un JSON con archivos a crear en la raíz:
- "name": nombre
- "description": explicación (4-10 líneas) de contenido, función, creación y marcador `{{nombre_archivo}}`
Solo usa archivos proporcionados:
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
    contents = f"""
Genera un plan paso a paso:
Tarea: {improved_prompt}
Archivos: {', '.join(files.keys())}
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "text/plain", "temperature": 1.0}
    )
    return response.text

def generate_code(plan: str, files: Dict[str, bytes], save_prompt_to_file: bool = True) -> Dict[str, str]:
    file_manifest = generate_file_manifest(files)
    contents = f"""
Genera código Python y dependencias:
Plan: {plan}
Manifiesto:
{json.dumps(file_manifest, ensure_ascii=False, indent=2)}
Archivos: {', '.join(files.keys())}
- Crea archivos en la raíz
- Usa marcador `{{nombre_archivo}}` con explicación (8-10 líneas)
Solo usa archivos proporcionados
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
    stdout = execution_result.get("stdout", "")[:300000]
    stderr = execution_result.get("stderr", "")[:300000]
    files = list(execution_result.get("files", {}).keys())
    contents = f"Resultado: stdout: {stdout}\nstderr: {stderr}\narchivos: {files}"
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=f"Analiza y devuelve 'OK' o 'ERROR' con descripción:\n{contents}",
        config={"response_mime_type": "application/json", "response_schema": AnalysisResponse, "temperature": 1.0}
    )
    return response.parsed.dict()

def generate_fix(error_type: str, error_message: str, code: str, dependencies: str, history: List[Dict]) -> Dict[str, str]:
    history_text = "\n".join([f"Intento {i+1}: {item.get('analysis', {})}" for i, item in enumerate(history)])
    prompt = f"""
Corrige el código:
Historial: {history_text}
Error: {error_type} - {error_message}
Código: {code}
Dependencias: {dependencies}
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "application/json", "response_schema": FixResponse, "temperature": 1.0}
    )
    return response.parsed.dict()

def improve_markdown(content: str) -> str:
    content = re.sub(r'(#+)(\w)', r'\1 \2', content)
    content = re.sub(r'^-\s*([^\s])', r'- \1', content, flags=re.MULTILINE)
    content = re.sub(r'(#+.+)\n([^#\n])', r'\1\n\n\2', content)
    content = re.sub(r'\n{3,}', r'\n\n', content)
    lines = content.splitlines()
    new_lines = []
    section_counter = 0
    subsection_counter = 0
    for line in lines:
        if line.strip().startswith('#'):
            if line.count('#') == 1:
                section_counter += 1
                subsection_counter = 0
                line = re.sub(r'^#\s*', f'# {section_counter}. ', line)
            elif line.count('#') == 2:
                subsection_counter += 1
                line = re.sub(r'^##\s*', f'## {section_counter}.{subsection_counter} ', line)
            else:
                line = re.sub(r'^#+\s*', '# ', line)
        new_lines.append(line)
    return "\n".join(new_lines).strip()

def filter_relevant_files(files: Dict[str, bytes], max_files: int = 5) -> List[str]:
    file_names = list(files.keys())
    if len(file_names) <= max_files:
        return file_names
    prompt = f"""
Archivos: {', '.join(file_names)}
Selecciona los {max_files} más relevantes para el reporte científico:
{{"relevant_files": ["nombre1", "nombre2", ...]}}
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.3}
    )
    try:
        return response.parsed.dict().get("relevant_files", [])[:max_files]
    except Exception as e:
        logging.error(f"Error filtrando archivos: {e}")
        return file_names[:max_files]

def generate_extensive_report(plan: str, files: Dict[str, bytes]) -> str:
    important_files = filter_relevant_files(files, max_files=5)
    prompt = f"""
Como autor del experimento, he generado un código basado en este plan:
{plan}
Archivos generados más importantes: {', '.join(important_files)}
Redacta un reporte extenso en Markdown, en primera persona, con:
1. Introducción: propósito y contexto
2. Metodología: pasos del plan
3. Resultados: análisis de archivos
4. Conclusiones: hallazgos
Cada archivo usa marcador `{{nombre_archivo}}` con explicación (8-10 líneas) de contenido, formato, función y creación.
Numeración: # 1., ## 1.1, etc. Solo usa archivos proporcionados.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "temperature": 1.0}
    )
    return improve_markdown(response.text.strip())

def enhance_problem_description(description: str) -> str:
    prompt = f"Redacta de manera científica y formal:\n{description}"
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "temperature": 1.0}
    )
    return response.text.strip()

def rank_solutions(solutions: List[Dict]) -> List[int]:
    contents = "\n".join([f"Solución {i}: Archivos: {', '.join(sol['generated_files'].keys())}" for i, sol in enumerate(solutions)])
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=f"Rankea soluciones:\n{contents}\nDevuelve índices en 'order' (mejor a peor)",
        config={"response_mime_type": "application/json", "response_schema": RankResponse, "temperature": 1.0}
    )
    order = response.parsed.dict().get('order', [])
    rankings = [0] * len(solutions)
    for rank, idx in enumerate(order, 1):
        rankings[idx] = rank
    return rankings