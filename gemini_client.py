import os
import google.generativeai as genai

def configure_gemini():
    """Configura la API de Gemini usando la clave de entorno."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No se encontró la clave de API de Gemini. Configura la variable de entorno GEMINI_API_KEY.")
    genai.configure(api_key=api_key)

def clean_generated_code(text: str) -> str:
    """Limpia el texto generado eliminando delimitadores Markdown."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].startswith("```") else lines
        text = "\n".join(lines)
    return text.strip()

def generate_code(prompt: str, model_name: str = "gemini-2.0-flash-lite-preview-02-05") -> str:
    """Genera código Python usando la API de Gemini."""
    configure_gemini()
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        code = response.text.strip()
        return clean_generated_code(code)
    except Exception as e:
        raise RuntimeError(f"Error generando código con Gemini (modelo: {model_name}): {e}")

def get_dependencies(code: str, model_name: str = "gemini-2.0-flash-lite-preview-02-05") -> str:
    """Genera una lista de dependencias requeridas en formato requirements.txt."""
    prompt = (
        "Dado el siguiente código Python:\n"
        f"{code}\n\n"
        "Genera la lista de dependencias Python necesarias para ejecutar este código en un entorno aislado. "
        "Devuelve **solo** la lista en formato `requirements.txt` (una dependencia por línea, 'paquete==versión' si es posible). "
        "No incluyas explicaciones ni delimitadores. Si no se requieren dependencias, devuelve una cadena vacía."
    )
    result = generate_code(prompt, model_name=model_name)
    return result.strip()

def refine_code(previous_code: str, outputs: dict, model_name: str = "gemini-2.0-flash-lite-preview-02-05") -> str:
    """Refina el código anterior basado en los resultados de ejecución."""
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        "El código Python anterior es:\n"
        f"{previous_code}\n\n"
        "Los resultados de ejecución fueron:\n"
        f"{outputs_str}\n\n"
        "Analiza los resultados. Si hay errores, genera una versión corregida del código Python. "
        "Devuelve **solo** el código completo y corregido, sin comentarios ni delimitadores."
    )
    return generate_code(prompt, model_name=model_name)

def refine_dependencies(previous_deps: str, code: str, outputs: dict, model_name: str = "gemini-2.0-flash-lite-preview-02-05") -> str:
    """Refina la lista de dependencias basada en el código y los resultados de ejecución."""
    prompt = (
        "El código Python es:\n"
        f"{code}\n\n"
        "La lista anterior de dependencias fue:\n"
        f"{previous_deps}\n\n"
        "La ejecución produjo:\n"
        f"STDOUT: {outputs.get('stdout', '')}\nSTDERR: {outputs.get('stderr', '')}\n\n"
        "Corrige **solo la lista de dependencias** para que el código se ejecute correctamente. "
        "Devuelve solo la lista en formato `requirements.txt` (una dependencia por línea, 'paquete==versión' si es posible), "
        "sin explicaciones ni delimitadores. Si no se requieren más dependencias, devuelve una cadena vacía."
    )
    return generate_code(prompt, model_name=model_name).strip()

def improve_code(previous_code: str, additional_instructions: str, model_name: str = "gemini-2.0-flash-lite-preview-02-05") -> str:
    """Mejora el código basado en instrucciones adicionales."""
    prompt = (
        "El código Python actual es:\n"
        f"{previous_code}\n\n"
        "Instrucciones adicionales para mejorar o modificar el código:\n"
        f"{additional_instructions}\n\n"
        "Genera una versión mejorada del código Python. Devuelve **solo** el código completo, sin comentarios ni delimitadores."
    )
    return generate_code(prompt, model_name=model_name)

def generate_code_name(code: str, model_name: str = "gemini-2.0-flash-lite-preview-02-05") -> str:
    """Genera un nombre descriptivo para el código basado en su funcionalidad."""
    prompt = (
        "Basado en el siguiente código:\n"
        f"{code}\n\n"
        "Genera un nombre краткий y descriptivo que refleje la funcionalidad principal del código. "
        "Devuelve solo el nombre, sin texto adicional."
    )
    return generate_code(prompt, model_name=model_name).strip()