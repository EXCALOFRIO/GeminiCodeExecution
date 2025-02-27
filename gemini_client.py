import os
import random
import google.generativeai as genai

_API_KEYS = []
_API_KEY_INDEX = 0

def load_api_keys():
    global _API_KEYS, _API_KEY_INDEX
    keys = [value for key, value in os.environ.items() if key.startswith("GEMINI_API_KEY") and value]
    if not keys:
        raise ValueError("No se encontraron claves API de Gemini.")
    _API_KEYS = keys
    _API_KEY_INDEX = random.randrange(len(_API_KEYS))

def configure_gemini():
    global _API_KEYS, _API_KEY_INDEX
    if not _API_KEYS:
        load_api_keys()
    api_key = _API_KEYS[_API_KEY_INDEX]
    _API_KEY_INDEX = (_API_KEY_INDEX + 1) % len(_API_KEYS)
    genai.configure(api_key=api_key)

def clean_generated_code(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines and lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip().startswith("```") else lines
        text = "\n".join(lines)
    if text.startswith("python") or text.startswith("Python"):
        lines = text.splitlines()
        text = "\n".join(lines[1:])
    return text.strip()

def generate_code(prompt: str, model_name: str = "gemini-2.0-flash-001") -> str:
    if not _API_KEYS:
        load_api_keys()
    configure_gemini()
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        return clean_generated_code(response.text.strip())
    except Exception as e:
        raise RuntimeError(f"Error generando código: {e}")

def generate_thought_chain(initial_prompt: str, iterations: int, model_name: str) -> str:
    if iterations <= 0:
        return ""
    thought = initial_prompt
    for _ in range(iterations):
        prompt = (
            f"Analiza profundamente:\n{thought}\n"
            "Proporciona un razonamiento técnico detallado en español:\n"
            "1. Contexto del problema\n2. Objetivos\n3. Análisis técnico\n"
            "4. Enfoques de solución\n5. Obstáculos\n6. Plan de implementación\n"
            "7. Criterios de éxito\n8. Perspectivas críticas\n"
            "- Enfoque técnico y detallado\n- Todo en español"
        )
        thought = generate_code(prompt, model_name=model_name)
    return thought

def review_code(code: str, model_name: str) -> str:
    prompt = (
        f"Analiza este código Python:\n```python\n{code}\n```\n"
        "Proporciona un análisis en español:\n"
        "1. Resumen ejecutivo\n2. Errores críticos\n3. Problemas de rendimiento\n"
        "4. Vulnerabilidades\n5. Calidad y mantenibilidad\n6. Dependencias\n"
        "7. Recomendaciones\n8. Estrategia de pruebas\n"
        "- Específico y técnico\n- Sin repetir código"
    )
    return generate_code(prompt, model_name=model_name)

def improve_code_based_on_review(code: str, review: str, model_name: str) -> str:
    prompt = (
        f"Código:\n```python\n{code}\n```\n"
        f"Análisis:\n{review}\n"
        "Mejora el código según el análisis. Solo código completo.\n"
        "- Manejo de errores\n- Comentarios en español\n- Optimizado"
    )
    return generate_code(prompt, model_name=model_name)

def review_report(report: str, model_name: str) -> str:
    prompt = (
        f"Evalúa este reporte Markdown:\n```markdown\n{report}\n```\n"
        "Proporciona una evaluación en español:\n"
        "1. Evaluación general\n2. Fortalezas\n3. Debilidades\n"
        "4. Análisis por sección\n5. Rigor metodológico\n6. Visualización\n"
        "7. Recomendaciones\n8. Precisión científica\n"
        "- Técnico y específico"
    )
    return generate_code(prompt, model_name=model_name)

def improve_report_based_on_review(report: str, review: str, model_name: str) -> str:
    prompt = (
        f"Reporte:\n```markdown\n{report}\n```\n"
        f"Revisión:\n{review}\n"
        "Mejora el reporte en Markdown según la revisión. Solo el reporte."
    )
    return generate_code(prompt, model_name=model_name)

def get_dependencies(code: str, model_name: str) -> str:
    prompt = (
        f"Analiza este código Python:\n```python\n{code}\n```\n"
        "Genera un requirements.txt preciso para Python 3.9.\n"
        "Solo dependencias, sin versiones, alfabéticamente."
    )
    return generate_code(prompt, model_name=model_name).strip()

def refine_code(previous_code: str, outputs: dict, thought_chain: str, error_history: list = None, model_name: str = "gemini-2.0-flash-001") -> str:
    error_history_str = "\n".join(error_history or [])
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        f"Análisis:\n{thought_chain}\n"
        f"Errores:\n{error_history_str or 'Ninguno'}\n"
        f"Código:\n```python\n{previous_code}\n```\n"
        f"Resultados:\n{outputs_str}\n"
        "Corrige el código Python. Solo código completo.\n"
        "- Resuelve todos los errores\n- Manejo de errores\n- Comentarios en español"
    )
    return generate_code(prompt, model_name=model_name)

def refine_dependencies(previous_deps: str, code: str, outputs: dict, thought_chain: str, error_history: list = None, model_name: str = "gemini-2.0-flash-001") -> str:
    error_history_str = "\n".join(error_history or [])
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        f"Análisis:\n{thought_chain}\n"
        f"Errores:\n{error_history_str or 'Ninguno'}\n"
        f"Código:\n```python\n{code}\n```\n"
        f"Dependencias:\n{previous_deps}\n"
        f"Resultados:\n{outputs_str}\n"
        "Corrige el requirements.txt. Solo dependencias, sin versiones."
    )
    return generate_code(prompt, model_name=model_name).strip()

def improve_code(previous_code: str, additional_instructions: str, thought_chain: str, model_name: str) -> str:
    prompt = (
        f"Análisis:\n{thought_chain}\n"
        f"Código:\n```python\n{previous_code}\n```\n"
        f"Instrucciones:\n{additional_instructions}\n"
        "Mejora el código Python. Solo código completo.\n"
        "- Implementa instrucciones\n- Manejo de errores\n- Comentarios en español"
    )
    return generate_code(prompt, model_name=model_name)

def generate_markdown_report(stdout: str, stderr: str, image_files: list, data_files: list, thought_chain: str, model_name: str) -> str:
    images = ", ".join(image_files) if image_files else "Ninguna"
    data = ", ".join(data_files) if data_files else "Ninguna"
    prompt = (
        f"Análisis:\n{thought_chain}\n"
        f"Imágenes generadas: {images}\nArchivos de datos: {data}\n"
        f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}\n"
        "Genera un reporte Markdown científico con las siguientes secciones:\n"
        "- Tabla de Contenido (con enlaces a secciones)\n"
        "- Título\n- Resumen\n- Introducción\n- Metodología\n- Resultados\n"
        "- Discusión\n- Conclusiones\n- Recomendaciones\n- Referencias\n"
        "Inserta los marcadores {{visualize_filename}} con el nombre exacto del archivo donde corresponda "
        "(por ejemplo, {{visualize_graficos/poblacion.png}} para imágenes o {{visualize_analisis.txt}} para datos).\n"
        "Asegúrate de que el reporte sea claro, profesional y bien estructurado como un documento científico."
    )
    report = generate_code(prompt, model_name=model_name)
    all_files = image_files + data_files
    for file in all_files:
        report = report.replace("{{visualize_filename}}", f"{{visualize_{file}}}", 1)
    return report

def classify_execution_error(combined_output: str, model_name: str) -> str:
    error_keywords = ["error", "exception", "failed", "traceback", "cannot", "unable"]
    if any(keyword in combined_output.lower() for keyword in error_keywords):
        prompt = (
            f"Analiza esta salida:\n{combined_output}\n"
            "Clasifica el error (solo una palabra):\n"
            "DEPENDENCY, CODE, BOTH, OK"
        )
        response = generate_code(prompt, model_name=model_name).strip().upper()
        return response if response in ["DEPENDENCY", "CODE", "BOTH", "OK"] else "UNKNOWN"
    return "OK"  # Si no hay palabras clave de error, es exitoso

def refine_requirements_with_gemini(initial_requirements: str, code: str, model_name: str, error_info: str = "") -> str:
    prompt = (
        f"Código:\n```python\n{code}\n```\n"
        f"Dependencias iniciales:\n{initial_requirements}\n"
        f"Error (si aplica):\n{error_info}\n"
        "Corrige el requirements.txt para Python 3.9.\n"
        "Solo dependencias, sin versiones, alfabéticamente."
    )
    return generate_code(prompt, model_name=model_name).strip()

# Funciones para generar prompts
def get_code_generation_prompt(thought_chain: str, prompt_initial: str, resumen_archivos: str) -> str:
    return (
        f"{thought_chain}\n\n"
        "Genera código Python completo para:\n"
        f"{prompt_initial}\n"
        f"Archivos adjuntos: {resumen_archivos or 'Ninguno.'}\n"
        "Requisitos:\n"
        "- Un solo archivo Python ejecutable en Docker.\n"
        "- Archivos generados en /app.\n"
        "- Manejo de errores y comentarios en español.\n"
        "- Optimizar rendimiento y seguridad.\n"
        "- Resultados visibles."
    )

def get_code_refinement_prompt(current_code: str, outputs: dict, thought_chain: str, error_history: list) -> str:
    error_history_str = "\n".join(error_history or [])
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    return (
        f"Análisis:\n{thought_chain}\n"
        f"Errores:\n{error_history_str or 'Ninguno'}\n"
        f"Código:\n```python\n{current_code}\n```\n"
        f"Resultados:\n{outputs_str}\n"
        "Corrige el código Python. Solo código completo.\n"
        "- Resuelve todos los errores\n- Manejo de errores\n- Comentarios en español"
    )

def get_dependencies_refinement_prompt(previous_deps: str, code: str, outputs: dict, thought_chain: str, error_history: list) -> str:
    error_history_str = "\n".join(error_history or [])
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    return (
        f"Análisis:\n{thought_chain}\n"
        f"Errores:\n{error_history_str or 'Ninguno'}\n"
        f"Código:\n```python\n{code}\n```\n"
        f"Dependencias:\n{previous_deps}\n"
        f"Resultados:\n{outputs_str}\n"
        "Corrige el requirements.txt. Solo dependencias, sin versiones."
    )

def get_improvement_prompt(current_code: str, prompt_text: str, file_info: str, thought_chain: str) -> str:
    return (
        f"{thought_chain}\n\n"
        "Mejora el código Python existente según la instrucción:\n"
        f"- Instrucción: {prompt_text}\n"
        f"{file_info}\n"
        "**Requisitos:**\n"
        "- Código completo en un solo archivo Python.\n"
        "- Archivos generados en /app.\n"
        "- Manejo robusto de errores y comentarios en español.\n"
        "- Optimizar rendimiento y seguridad.\n"
        "- Resultados visibles según la instrucción."
    )