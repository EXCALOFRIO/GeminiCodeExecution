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
    error_type: str  # "OK", "DEPENDENCIAS", "CODE", "DATA"
    error_message: str

class FixResponse(BaseModel):
    code: str
    dependencies: str
    improved_prompt: str

# Configuración de Gemini
def configure_gemini():
    load_dotenv()
    keys = [os.environ.get(f"GEMINI_API_KEY{i}") for i in range(1, 7) if os.environ.get(f"GEMINI_API_KEY{i}")]
    if not keys:
        raise ValueError("No se encontraron claves API en .env")
    api_key = random.choice(keys)
    global client
    client = genai.Client(api_key=api_key)

client = None

def improve_prompt(prompt: str, files: dict) -> str:
    file_info = "\n".join([f"Archivo: {name}\nContenido: {content.decode('utf-8', errors='ignore')[:500]}" for name, content in files.items()])
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"Mejora este prompt incluyendo detalles de los archivos si es necesario:\nPrompt: {prompt}\nArchivos:\n{file_info}",
    )
    return response.text

def generate_code(improved_prompt: str, files: dict) -> dict:
    file_info = "\n".join([f"Archivo: {name}" for name in files.keys()])
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"Genera código Python y una lista de dependencias en formato requirements.txt (cada dependencia en una línea separada, sin texto adicional) para:\n{improved_prompt}\nArchivos disponibles: {file_info}",
        config={
            "response_mime_type": "application/json",
            "response_schema": CodeResponse,
        },
    )
    return response.parsed.dict()

def analyze_execution_result(execution_result: dict) -> dict:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"Analiza este resultado de ejecución y clasifica el resultado como OK o un error (DEPENDENCIAS, CODE, DATA) con un mensaje:\n{execution_result}",
        config={
            "response_mime_type": "application/json",
            "response_schema": AnalysisResponse,
        },
    )
    return response.parsed.dict()

def generate_fix(error_type: str, error_message: str, code: str, dependencies: str) -> dict:
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"Corrige este error:\nTipo: {error_type}\nMensaje: {error_message}\nCódigo:\n{code}\nDependencias:\n{dependencies}",
        config={
            "response_mime_type": "application/json",
            "response_schema": FixResponse,
        },
    )
    return response.parsed.dict()

def generate_report(problem_description: str, code: str, stdout: str, files: dict) -> str:
    file_list = "\n".join([f"- {name}" for name in files.keys()])
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"Genera un reporte en Markdown:\nProblema: {problem_description}\nCódigo:\n```python\n{code}\n```\nSalida: {stdout}\nArchivos generados:\n{file_list}",
        config={"response_mime_type": "text/plain"},
    )
    return response.text