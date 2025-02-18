# gemini_client.py
import os
import google.generativeai as genai

def configure_gemini():
    # Configura la clave API de Gemini a partir de una variable de entorno.
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Clave API de Gemini no encontrada. Configura la variable GEMINI_API_KEY.")
    genai.configure(api_key=api_key)

def clean_generated_code(text: str) -> str:
    """
    Limpia el texto generado eliminando delimitadores de Markdown (por ejemplo, ```).
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()

def generate_code(prompt: str, model_name="gemini-2.0-flash-lite-preview-02-05") -> str:
    """
    Envía el prompt a la API de Gemini para generar código Python.
    """
    configure_gemini()
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        code = response.text.strip()
        return clean_generated_code(code)
    except Exception as e:
        raise RuntimeError(f"Error al generar código con Gemini (modelo: {model_name}): {e}")

def get_dependencies(code: str, model_name="gemini-2.0-flash-lite-preview-02-05") -> str:
    """
    Solicita a Gemini la lista de dependencias necesarias para ejecutar el código.
    """
    prompt = (
        "Dado el siguiente código Python:\n"
        f"{code}\n\n"
        "Genera la lista de dependencias Python necesarias para ejecutar este código en un entorno aislado. "
        "Recuerda que los archivos adjuntos se encuentran en el mismo directorio que el script y deben ser analizados si es necesario.\n"
        "Devuelve **únicamente** la lista de dependencias en formato `requirements.txt` (una dependencia por línea, "
        "formato 'package==version' si es posible).\n"
        "**No incluyas explicaciones, comentarios, ni delimitadores de código.**\n"
        "Si no se requieren dependencias, devuelve una cadena vacía."
    )
    result = generate_code(prompt, model_name=model_name)
    result = result.strip("` \n")
    return result

def refine_code(previous_code: str, outputs: dict, model_name="gemini-2.0-flash-lite-preview-02-05") -> str:
    """
    Envía el código previo y los outputs para que Gemini genere una versión mejorada.
    """
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        "El código Python anterior es:\n"
        f"{previous_code}\n\n"
        "Los resultados de la ejecución de este código fueron:\n"
        f"{outputs_str}\n\n"
        "Analiza los resultados de la ejecución. Si hay errores o posibles mejoras, genera una **versión mejorada y corregida del código Python**.\n"
        "**Devuelve únicamente el código Python corregido y completo.**\n"
        "**No incluyas comentarios explicativos, delimitadores de código, ni texto adicional.**\n"
        "Asegúrate de que el código resultante sea directamente ejecutable."
    )
    refined = generate_code(prompt, model_name=model_name)
    return clean_generated_code(refined)

def refine_dependencies(previous_deps: str, code: str, outputs: dict, model_name="gemini-2.0-flash-lite-preview-02-05") -> str:
    """
    Envía la lista de dependencias previa, el código y los outputs para que Gemini genere una versión corregida.
    """
    prompt = (
        "El código Python es:\n"
        f"{code}\n\n"
        "La lista de dependencias anterior fue:\n"
        f"{previous_deps}\n\n"
        "La ejecución del código con estas dependencias produjo el siguiente resultado (stdout/stderr):\n"
        f"{outputs.get('stdout','')}\n{outputs.get('stderr','')}\n\n"
        "Corrige **únicamente la lista de dependencias** para que el código se ejecute correctamente en un entorno aislado.\n"
        "Devuelve solo la lista de dependencias corregida en formato `requirements.txt` (una dependencia por línea, "
        "formato 'package==version' si es posible).\n"
        "**No incluyas explicaciones, comentarios, delimitadores de código, ni ningún otro texto.**\n"
        "Si no se requieren dependencias adicionales, devuelve una cadena vacía."
    )
    refined = generate_code(prompt, model_name=model_name)
    refined = refined.strip("` \n")
    return refined

def improve_code(previous_code: str, additional_instructions: str, model_name="gemini-2.0-flash-lite-preview-02-05") -> str:
    """
    Toma el código actual y las instrucciones adicionales para generar una versión mejorada.
    """
    prompt = (
        "El código Python actual es:\n"
        f"{previous_code}\n\n"
        "Instrucciones adicionales del usuario para mejorar o modificar el código:\n"
        f"{additional_instructions}\n\n"
        "Recuerda que los archivos adjuntos se encuentran en el mismo directorio que el script que se ejecuta.\n"
        "Genera una versión mejorada y/o modificada del código Python basándote en las instrucciones anteriores.\n"
        "**Devuelve únicamente el código Python mejorado y completo sin comentarios, delimitadores o texto adicional.**"
    )
    improved = generate_code(prompt, model_name=model_name)
    return improved.strip()

def generate_code_name(code: str, model_name="gemini-2.0-flash-lite-preview-02-05") -> str:
    """
    Genera un nombre descriptivo para el código (corto y que refleje su propósito).
    """
    prompt = (
        "Basado en el siguiente código:\n"
        f"{code}\n\n"
        "Genera un nombre breve y descriptivo que refleje la funcionalidad o propósito principal del código. "
        "Devuelve solo el nombre, sin texto adicional, ni comillas, ni delimitadores."
    )
    name = generate_code(prompt, model_name=model_name)
    return name.strip()