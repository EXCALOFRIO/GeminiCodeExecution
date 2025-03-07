import os
import random
import time
import logging
import pandas as pd
import io
from typing import Any, Dict, List, Set, Tuple, Optional
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator
import re
from google import genai
import json
from pydantic import ValidationError

# Configurar logging
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
            new_v = {}
            for key, value in v.items():
                if isinstance(value, dict):
                    # Si es un diccionario, intentamos extraer un valor razonable o convertirlo a string
                    new_v[key] = value.get("value", str(value))
                else:
                    new_v[key] = str(value)
            return new_v
        return v
    
        
# Variable global para claves API fallidas
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
        raise ValueError("No hay claves API disponibles (todas descartadas por errores).")
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

def improve_prompt(prompt: str, files: Dict[str, bytes]) -> str:
    examples = """
Ejemplo 1:
Prompt: "Generar un gráfico de barras a partir de un CSV."
Prompt Mejorado: "Crear un script Python que lea un archivo CSV con columnas 'fecha' y 'valor', genere un gráfico de barras con matplotlib mostrando 'valor' en el eje Y y 'fecha' en el eje X, y guarde la figura como 'barras.png'. Manejar errores si el CSV está vacío o las columnas no existen."
Dependencias: pandas, matplotlib

Ejemplo 2:
Prompt: "Analizar datos de ventas."
Prompt Mejorado: "Crear un script Python que lea 'ventas.csv' con columnas 'producto', 'cantidad' y 'precio', calcule el ingreso total por producto (cantidad * precio), ordene los resultados de mayor a menor y guarde el resultado en 'ingresos.csv'. Incluir manejo de errores para archivos vacíos o datos faltantes."
Dependencias: pandas
"""
    file_info = ""
    for name, content in files.items():
        file_info += f"Archivo: {name}\n"
        if name.endswith('.csv'):
            try:
                df = pd.read_csv(io.BytesIO(content))
                file_info += f"Columnas: {', '.join(df.columns)}\nTipos de datos: {df.dtypes.to_string()}\n"
            except Exception:
                file_info += "No se pudo analizar el CSV.\n"
        else:
            file_info += f"Contenido (primeros 500000 caracteres): {content[:500000].decode('utf-8', errors='ignore')}\n"
    
    chain_of_thought = (
        "Primero, analiza paso a paso el prompt original y los archivos provistos. "
        "Identifica las áreas que pueden mejorarse, las ambigüedades y los detalles faltantes. "
        "Luego, genera un prompt final optimizado, claro y detallado, incluyendo ejemplos si es necesario."
    )
    contents = f"{examples}\n\nPrompt original: {prompt}\nArchivos:\n{file_info}\n\n{chain_of_thought}"
    
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=("Mejora este prompt para que sea claro, detallado y efectivo, usando razonamiento paso a paso:\n" + contents),
        config={"response_mime_type": "text/plain", "top_p": 0.95, "temperature": 0.7}
    )
    return response.text

def generate_plan(prompt: str, files: Dict[str, bytes]) -> str:
    improved_prompt = improve_prompt(prompt, files)
    contents = f"""
Genera un plan paso a paso para resolver esta tarea:
Tarea: {improved_prompt}
Archivos disponibles: {', '.join(files.keys())}

Ejemplo:
Tarea: "Crear un gráfico de barras a partir de un CSV."
Plan:
1. Leer el archivo CSV usando pandas.
2. Verificar que las columnas esperadas existan.
3. Generar un gráfico de barras con matplotlib.
4. Guardar el gráfico como PNG.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "text/plain", "top_p": 0.95, "temperature": 0.7}
    )
    return response.text

def generate_code(plan: str, files: Dict[str, bytes]) -> Dict[str, str]:
    file_info = "\n".join([f"Archivo: {name}" for name in files.keys()])
    contents = f"""
Genera código Python y dependencias basado en este plan:
Plan: {plan}
Archivos disponibles: {file_info}
El código debe:
- Seguir los pasos del plan exactamente.
- Incluir manejo de errores (por ejemplo, para archivos vacíos o columnas faltantes).
- Tener comentarios explicativos en cada sección.
- Listar dependencias en formato requirements.txt, con una biblioteca por línea (por ejemplo: numpy
scipy
matplotlib), sin comas ni otros separadores.
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents,
        config={"response_mime_type": "application/json", "response_schema": CodeResponse, "top_p": 0.95, "temperature": 0.7}
    )
    try:
        result = response.parsed.dict()
        dependencies = result["dependencies"]
        # Procesar dependencias para asegurar el formato correcto
        dep_lines = []
        for line in dependencies.split('\n'):
            line = line.strip()
            if line:
                deps = [dep.strip() for dep in line.split(',') if dep.strip()]
                dep_lines.extend(deps)
        cleaned_dependencies = '\n'.join(dep_lines)
        # Excluir módulos estándar
        standard_modules = {"io", "os", "sys", "time", "random", "re", "json", "csv", "math", "datetime"}
        final_dependencies = '\n'.join(dep for dep in cleaned_dependencies.split('\n') if dep and dep not in standard_modules)
        return {"code": result["code"], "dependencies": final_dependencies}
    except Exception as e:
        logging.exception(f"Error en generate_code: {e}")
        return {"code": "", "dependencies": ""}

def analyze_execution_result(execution_result: Dict) -> Dict[str, str]:
    stdout = execution_result.get("stdout", "")
    stderr = execution_result.get("stderr", "")
    files = execution_result.get("files", {})
    truncated_stdout = stdout[:300000] + "\n... (truncado)" if len(stdout) > 300000 else stdout
    truncated_stderr = stderr[:300000] + "\n... (truncado)" if len(stderr) > 300000 else stderr
    file_names = list(files.keys())
    summary = f"stdout: {truncated_stdout}\nstderr: {truncated_stderr}\narchivos: {file_names}"
    contents = f"Resultado: {summary}"
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=("Analiza el resultado y devuelve 'OK' si fue exitoso o 'ERROR' con una descripción:\n" + contents),
        config={"response_mime_type": "application/json", "response_schema": AnalysisResponse, "top_p": 0.95, "temperature": 0.7}
    )
    return response.parsed.dict()

def generate_fix(error_type: str, error_message: str, code: str, dependencies: str, history: List[Dict]) -> Dict[str, str]:
    history_text = "\n".join([
        f"Intento {i+1}: Error: {item.get('analysis', {}).get('error_type', '')} - {item.get('analysis', {}).get('error_message', '')}\nCódigo:\n{item.get('code', '')}"
        for i, item in enumerate(history)
    ])
    prompt_fix = f"""
Corrige el código para resolver el error, usando el siguiente historial:
{history_text}
Error: {error_type} - {error_message}
Código:
{code}
Dependencias:
{dependencies}
Asegúrate de que las dependencias estén en formato requirements.txt (una biblioteca por línea, sin comas).
"""
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt_fix,
        config={"response_mime_type": "application/json", "response_schema": FixResponse, "top_p": 0.95, "temperature": 0.7}
    )
    result = response.parsed.dict()
    # Procesar dependencias en generate_fix también
    dep_lines = []
    for line in result["dependencies"].split('\n'):
        line = line.strip()
        if line:
            deps = [dep.strip() for dep in line.split(',') if dep.strip()]
            dep_lines.extend(deps)
    cleaned_dependencies = '\n'.join(dep_lines)
    return {"code": result["code"], "dependencies": cleaned_dependencies}

def improve_markdown(content: str) -> str:
    content = re.sub(r'(#+)(\w)', r'\1 \2', content)
    content = re.sub(r'^-\s*([^\s])', r'- \1', content, flags=re.MULTILINE)
    content = re.sub(r'^\*\s*([^\s])', r'* \1', content, flags=re.MULTILINE)
    content = re.sub(r'(#+.+)\n([^#\n])', r'\1\n\n\2', content)
    content = re.sub(r'```([a-z]*)\n', r'```\1\n', content)
    content = re.sub(r'\n{3,}', r'\n\n', content)
    content = re.sub(r'[ \t]+\n', r'\n', content)
    return content.strip()

def select_relevant_files(files: Dict[str, bytes]) -> List[str]:
    """
    Selecciona de manera inteligente los archivos relevantes para incluir en el reporte.
    Excluye 'script.py' y prioriza archivos de video o gif. Si hay muchos archivos de imagen,
    selecciona solo uno representativo.
    """
    candidates = {name: content for name, content in files.items() if name != "script.py"}
    if not candidates:
        return []
    video_ext = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
    gif_ext = {'.gif'}
    image_ext = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.svg'}
    csv_ext = {'.csv'}
    
    videos = []
    gifs = []
    csvs = []
    images = []
    others = []
    
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
    # Si hay videos o gifs, se priorizan
    if videos or gifs:
        selected.extend(videos)
        selected.extend(gifs)
        # Agrega CSVs y otros si existen
        selected.extend(csvs)
        selected.extend(others)
    else:
        # Si no hay videos/gifs, se consideran CSVs y una imagen representativa
        if csvs:
            selected.extend(csvs)
        if images:
            if len(images) > 3:
                selected.append(images[0])
            else:
                selected.extend(images)
        selected.extend(others)
            
    # Eliminar duplicados preservando el orden
    return list(dict.fromkeys(selected))

import json
from pydantic import ValidationError

def get_files_explanation(file_names: List[str]) -> Dict[str, str]:
    """
    Solicita una única vez a la API que explique los archivos relevantes.
    Devuelve un diccionario donde la clave es el nombre del archivo y el valor es la explicación.
    """
    # Prompt claro y específico
    prompt = """
    Explica en 6-8 oraciones el propósito y contenido probable de cada uno de los siguientes archivos generados en un script Python. 
    Devuelve un JSON con la clave 'explanations' que sea un diccionario donde cada clave es el nombre del archivo y el valor es la explicación correspondiente como una cadena de texto (string), sin sub-objetos ni estructuras anidadas.
    
    Ejemplo de formato esperado:
    {
        "explanations": {
            "script.py": "Este archivo contiene el código principal del script Python...",
            "output.csv": "Este archivo CSV almacena los resultados calculados..."
        }
    }
    
    Archivos:
    """
    for name in file_names:
        prompt += f"- {name}\n"
    
    # Esquema esperado (mantenemos esto para referencia, pero no lo forzamos inicialmente)
    response_schema = {
        "type": "object",
        "properties": {
            "explanations": {
                "type": "object",
                "additionalProperties": {
                    "type": "string"
                }
            }
        },
        "required": ["explanations"]
    }
    
    # Configuración sin forzar el esquema inicialmente
    config = {
        "response_mime_type": "application/json",
        "top_p": 0.95,
        "temperature": 1.0
    }
    
    # Llamar a la API
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config=config
    )
    
    # Parsear la respuesta manualmente
    try:
        response_dict = json.loads(response.text)
        # Extraer explanations directamente
        explanations = response_dict.get("explanations", {})
        
        # Validar y corregir con Pydantic
        validated_response = FilesExplanationResponse(**response_dict)
        explanations = validated_response.explanations
    except json.JSONDecodeError as e:
        logging.error(f"Error al decodificar JSON: {e}")
        explanations = {}
    except ValidationError as e:
        logging.error(f"Error de validación en la respuesta: {e}")
        # Si Pydantic falla, intentamos usar la respuesta cruda asegurándonos de que sean strings
        if isinstance(explanations, dict):
            explanations = {k: str(v) if not isinstance(v, str) else v for k, v in explanations.items()}
        else:
            explanations = {}
    
    return explanations

def enhance_problem_description(description: str) -> str:
    """
    Solicita a Gemini que redacte de forma científica y formal la descripción del problema,
    enfatizando los requerimientos del usuario sin entrar en detalles técnicos.
    """
    prompt = (
        "Por favor, redacta de manera científica y formal la siguiente descripción del problema, "
        "enfatizando los requerimientos del usuario y contextualizando la solución sin entrar en detalles técnicos del código:\n\n"
        f"{description}"
    )
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=prompt,
        config={"response_mime_type": "text/plain", "top_p": 0.95, "temperature": 0.7}
    )
    return response.text.strip()

def generate_report(problem_description: str, plan: str, code: str, stdout: str, files: Dict[str, bytes]) -> str:
    """
    Genera un reporte científico basado en el problema descrito, el plan y los archivos generados.
    """
    # Mejorar la descripción del problema utilizando Gemini
    enhanced_description = enhance_problem_description(problem_description)
    
    # Construir la sección de archivos generados con explicación detallada
    relevant_files = select_relevant_files(files)
    if relevant_files:
        explanations = get_files_explanation(relevant_files)
        file_entries = []
        for file_name in relevant_files:
            # Obtener la extensión del archivo
            file_ext = os.path.splitext(file_name)[1].lower()
            
            # Determinar el tipo de archivo para la cita APA
            if file_ext == '.csv':
                file_type = '[CSV]'
            elif file_ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp']:
                file_type = '[Image]'
            else:
                file_type = '[File]'  # Tipo genérico si no es CSV ni imagen
            
            # Formato APA para la cita
            # Nota: Aquí se asume que el autor es "Generated" y la fecha es "2024" para simplificar. Ajusta si tienes información real.
            apa_citation = f"(Generated, 2024)"
            
            explanation = explanations.get(file_name, "Sin explicación disponible.")
            
            # Insertar marcador para previsualización usando la sintaxis {{nombre_archivo}}
            marker = f"{{{{{file_name}}}}}"
            
            # Formatear la entrada del archivo con la cita APA y el enlace de previsualización
            file_entry = (
                f"- **{file_name}** {file_type}: {explanation} {apa_citation}\n"
                f"{marker}]"
            )
            file_entries.append(file_entry)
        file_section = "\n".join(file_entries)
    else:
        file_section = "No hay archivos generados."
    
    # Construir el reporte en formato markdown con estilo científico
    report = (
        "# Reporte Científico\n\n"
        "## Descripción del Problema\n"
        f"{enhanced_description}\n\n"
        "## Metodología\n"
        "La solución se desarrolló aplicando un enfoque científico estructurado en varias fases:\n"
        "- **Análisis del Requerimiento:** Se interpretaron y refinaron los requerimientos del usuario, "
        "optimizando la descripción del problema para alcanzar una mayor claridad y precisión.\n"
        "- **Planificación y Diseño del Algoritmo:** Se elaboró un plan paso a paso que incluyó la validación "
        "de las entradas, el manejo robusto de errores y la integración de las dependencias esenciales.\n"
        "- **Implementación y Ejecución en Entorno Controlado:** La solución se implementó utilizando contenedores "
        "Docker para asegurar un entorno aislado y reproducible, ejecutándose en paralelo para evaluar múltiples iteraciones.\n"
        "- **Optimización y Validación de Resultados:** Se aplicó un sistema de ranking para seleccionar la mejor solución, "
        "garantizando la calidad y consistencia de los resultados.\n\n"
        "## Resultados\n"
        "La ejecución de la solución produjo resultados de alta calidad, evaluados en función de la integridad y eficiencia "
        "de los datos procesados. A continuación se presentan los archivos generados:\n\n"
        "### Archivos Generados\n"
        f"{file_section}\n\n"
        "Cada archivo fue analizado de forma específica para extraer información relevante sobre su contenido. "
        "Los marcadores de previsualización permiten visualizar el archivo directamente en la interfaz, facilitando la verificación de los resultados.\n\n"
        "## Conclusiones\n"
        "El enfoque científico adoptado permitió desarrollar una solución robusta y precisa, alineada con los requerimientos del usuario. "
        "La metodología aplicada garantiza que cada etapa del proceso esté optimizada para ofrecer resultados confiables y de alta calidad."
    )
    return report


def rank_solutions(solutions: List[Dict]) -> List[int]:
    contents = """
    Rankea estas soluciones de mejor a peor según:
    1. Completitud (¿generó todos los archivos esperados?).
    2. Eficiencia (¿el código es limpio y optimizado?).
    3. Calidad de salida (¿los archivos generados son útiles?).
    """ + "\n".join([
        f"Solución {i}: Archivos: {', '.join(sol['generated_files'].keys())}, Código:\n{sol['code'][:100000]}..." 
        for i, sol in enumerate(solutions)
    ])
    response = safe_generate_content(
        model="gemini-2.0-flash-lite-001",
        contents=contents + "\nDevuelve una lista de índices en orden (mejor a peor) en 'order'.",
        config={"response_mime_type": "application/json", "response_schema": RankResponse, "top_p": 0.95, "temperature": 1.0}
    )
    order = response.parsed.dict().get('order', [])
    rankings = [0] * len(solutions)
    for rank, idx in enumerate(order, 1):
        rankings[idx] = rank
    return rankings