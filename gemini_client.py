import os
import google.generativeai as genai

def configure_gemini():
    """Configura la API de Gemini usando la clave de entorno GEMINI_API_KEY."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("No se encontró la clave de API de Gemini. Configura la variable de entorno GEMINI_API_KEY.")
    genai.configure(api_key=api_key)

def clean_generated_code(text: str) -> str:
    """Limpia el texto generado eliminando delimitadores Markdown y espacios innecesarios."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].startswith("```") else lines
        text = "\n".join(lines)
    return text.strip()

def generate_code(prompt: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """Genera contenido utilizando la API de Gemini basado en el prompt proporcionado."""
    configure_gemini()
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt)
        code = response.text.strip()
        return clean_generated_code(code)
    except Exception as e:
        raise RuntimeError(f"Error generando contenido con Gemini (modelo: {model_name}): {e}")

def get_dependencies(code: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """Genera una lista de dependencias necesarias en formato 'requirements.txt'."""
    prompt = (
        "Dado el siguiente código Python:\n"
        f"{code}\n\n"
        "Genera la lista de dependencias necesarias para ejecutar este código en un entorno aislado (Docker) en formato 'requirements.txt'.\n"
        "Cada dependencia debe aparecer en una línea, utilizando el formato 'paquete==versión' cuando sea posible.\n"
        "No incluyas explicaciones ni delimitadores adicionales. Si no se requieren dependencias, devuelve una cadena vacía."
    )
    result = generate_code(prompt, model_name=model_name)
    return result.strip()

def refine_code(previous_code: str, outputs: dict, model_name: str = "gemini-2.0-flash-001") -> str:
    """Corrige y mejora el código Python basado en los resultados de ejecución."""
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        "El código Python anterior es:\n"
        f"{previous_code}\n\n"
        "Los resultados de ejecución fueron los siguientes:\n"
        f"{outputs_str}\n\n"
        "Analiza los resultados. Si existen errores o problemas, genera una versión corregida del código Python.\n"
        "Asegúrate de que el nuevo código incluya la generación de imágenes de prueba (gráficas de análisis) y la integración correcta de archivos de datos.\n"
        "Todas las imágenes y archivos generados deben guardarse en la raíz del proyecto.\n"
        "Devuelve únicamente el código completo y funcional, sin comentarios ni delimitadores."
    )
    return generate_code(prompt, model_name=model_name)

def refine_dependencies(previous_deps: str, code: str, outputs: dict, model_name: str = "gemini-2.0-flash-001") -> str:
    """Corrige la lista de dependencias para que el código se ejecute sin errores."""
    prompt = (
        "El código Python es:\n"
        f"{code}\n\n"
        "La lista previa de dependencias es:\n"
        f"{previous_deps}\n\n"
        "La ejecución produjo los siguientes resultados:\n"
        f"STDOUT: {outputs.get('stdout', '')}\n"
        f"STDERR: {outputs.get('stderr', '')}\n\n"
        "Corrige únicamente la lista de dependencias para asegurar que el código se ejecute correctamente en un entorno Docker.\n"
        "Devuelve solo la lista en formato 'requirements.txt' (una dependencia por línea, utilizando 'paquete==versión' si es posible),\n"
        "sin explicaciones ni delimitadores. Si no se requieren dependencias adicionales, devuelve una cadena vacía."
    )
    return generate_code(prompt, model_name=model_name).strip()

def improve_code(previous_code: str, additional_instructions: str, model_name: str = "gemini-2.0-flash-001") -> str:
    """Genera una versión mejorada del código Python basada en instrucciones adicionales."""
    prompt = (
        "El código Python actual es:\n"
        f"{previous_code}\n\n"
        "Instrucciones adicionales para mejorar o modificar el código:\n"
        f"{additional_instructions}\n\n"
        "Genera una versión mejorada del código Python que cumpla las siguientes condiciones:\n"
        "- Debe ejecutarse correctamente en un entorno Docker aislado.\n"
        "- Debe generar imágenes de prueba (gráficas de análisis) en lugar de HTML, y guardarlas en la raíz del proyecto.\n"
        "- Debe generar y guardar cualquier archivo de datos (por ejemplo, CSV o Excel) en la raíz del proyecto.\n"
        "Devuelve únicamente el código completo y funcional, sin comentarios ni delimitadores."
    )
    return generate_code(prompt, model_name=model_name)

def generate_markdown_report(stdout: str, stderr: str, image_files: list, data_files: list, model_name: str = "gemini-2.0-flash-001") -> str:
    """Genera un reporte en Markdown basado únicamente en los resultados de ejecución."""
    imagenes = ", ".join(image_files) if image_files else "Ninguna"
    datos = ", ".join(data_files) if data_files else "Ninguno"
    prompt = (
        "Analiza los resultados proporcionados a continuación para generar un reporte científico completo en Markdown.\n"
        "**Importante:** No analices ni menciones ningún código fuente en este reporte. Céntrate exclusivamente en explicar y analizar los resultados (imágenes y archivos).\n"
        "El reporte debe ser un documento científico detallado, incluyendo análisis exhaustivo, observaciones relevantes y conclusiones significativas.\n"
        "Para mencionar archivos generados (imágenes, datos, etc.), utiliza el marcador `{{visualize_nombre_archivo}}` en el lugar apropiado del texto.\n"
        "Por ejemplo, 'La distribución se muestra en {{visualize_grafico.png}}' o 'Los datos están en {{visualize_datos.csv}}'.\n"
        "Asegúrate de que el reporte sea Markdown puro (sin HTML) y que los marcadores estén correctamente integrados para Streamlit.\n"
        "\n"
        "Resultados a analizar:\n"
        f"STDOUT: {stdout}\n"
        f"STDERR: {stderr}\n"
        f"Imágenes detectadas: {imagenes}\n"
        f"Archivos detectados: {datos}\n\n"
        "\n"
        "**Instrucciones específicas:**\n"
        "1. No analices ni comentes el código fuente.\n"
        "2. Explica y analiza detalladamente los resultados (imágenes y archivos).\n"
        "3. Adopta un tono y estructura de reporte científico.\n"
        "4. Utiliza correctamente los marcadores `{{visualize_nombre_archivo}}` para referenciar archivos.\n"
        "5. Entrega únicamente el reporte en Markdown, sin delimitadores ni explicaciones adicionales.\n"
        "\n"
        "Devuelve únicamente el reporte en Markdown."
    )
    return generate_code(prompt, model_name=model_name)