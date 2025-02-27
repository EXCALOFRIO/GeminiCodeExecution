import os
import random
import google.generativeai as genai

_API_KEYS = []
_API_KEY_INDEX = 0

def load_api_keys():
    global _API_KEYS, _API_KEY_INDEX
    keys = [value for key, value in os.environ.items() if key.startswith("GEMINI_API_KEY") and value]
    if not keys:
        raise ValueError("No se encontraron claves API de Gemini en variables de entorno con prefijo GEMINI_API_KEY.")
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
    
    num_keys = len(_API_KEYS)
    errors = []
    
    for _ in range(num_keys):
        configure_gemini()
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            code = response.text.strip()
            return clean_generated_code(code)
        except Exception as e:
            errors.append(str(e))
            continue
    raise RuntimeError(f"Error generando contenido con Gemini (modelo: {model_name}) tras {num_keys} intentos. Errores: {errors}")

def generate_thought_chain(initial_prompt: str, iterations: int, model_name: str = "gemini-2.0-flash-001") -> str:
    if iterations <= 0:
        return ""
    thought = initial_prompt
    for i in range(iterations):
        prompt = (
            f"# INSTRUCCIÓN\n"
            f"Analiza profundamente la siguiente información, explorando todos los aspectos técnicos:\n\n"
            f"```\n{thought}\n```\n\n"
            f"# FORMATO DE RESPUESTA\n"
            f"Proporciona un razonamiento técnico detallado en español con estos pasos:\n"
            f"1. **Contexto del problema**: Identifica elementos clave, restricciones y variables.\n"
            f"2. **Objetivos**: Define claramente qué se busca lograr y qué preguntas responder.\n"
            f"3. **Análisis técnico**: Realiza un análisis exhaustivo de los datos, código o instrucciones.\n"
            f"4. **Enfoques de solución**: Propón estrategias y algoritmos concretos, evaluando pros y contras.\n"
            f"5. **Obstáculos potenciales**: Identifica limitaciones, casos extremos o problemas posibles.\n"
            f"6. **Plan de implementación**: Detalla los pasos específicos para implementar la solución óptima.\n"
            f"7. **Criterios de éxito**: Define métricas y métodos para evaluar la efectividad.\n"
            f"8. **Perspectivas críticas**: Destaca los descubrimientos o insights más importantes.\n\n"
            f"# RESTRICCIONES\n"
            f"- NO uses frases como 'Basado en la información proporcionada'.\n"
            f"- NO reproduzcas el enunciado original o delimitadores.\n"
            f"- MANTÉN un enfoque técnico y detallado.\n"
            f"- PRIORIZA claridad, precisión y exhaustividad.\n"
            f"- ESCRIBE todo en español técnico fluido.\n"
            f"- EVITA declaraciones genéricas; cada oración debe aportar insights específicos."
        )
        thought = generate_code(prompt, model_name=model_name)
    return thought

def review_code(code: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# INSTRUCCIÓN\n"
        "Realiza un análisis exhaustivo a nivel experto del siguiente código Python:\n\n"
        f"```python\n{code}\n```\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Estructura tu análisis en español con estas secciones:\n"
        "1. **Resumen ejecutivo**: Descripción general del código y su propósito (2-3 oraciones).\n"
        "2. **Errores críticos**: Identifica bugs, errores de sintaxis o lógicos que impidan la ejecución.\n"
        "3. **Problemas de rendimiento**: Detecta cuellos de botella o patrones ineficientes.\n"
        "4. **Vulnerabilidades de seguridad**: Señala riesgos como inyecciones o manejo inseguro de datos.\n"
        "5. **Calidad y mantenibilidad**: Evalúa organización, legibilidad, modularidad y adherencia a PEP 8.\n"
        "6. **Dependencias y compatibilidad**: Analiza bibliotecas usadas y posibles problemas de compatibilidad.\n"
        "7. **Recomendaciones priorizadas**: Lista mejoras específicas ordenadas por importancia con ejemplos.\n"
        "8. **Estrategia de pruebas**: Sugiere casos de prueba específicos para validar la funcionalidad.\n\n"
        "# RESTRICCIONES\n"
        "- NO incluyas el código original en la respuesta.\n"
        "- NO uses marcadores genéricos como 'Error 1' o 'Problema 2'.\n"
        "- SÉ específico al señalar problemas, indicando líneas y contexto.\n"
        "- MANTÉN un tono técnico y objetivo.\n"
        "- ESCRIBE todo en español técnico fluido.\n"
        "- PROPORCIONA fragmentos de código para cada recomendación."
    )
    return generate_code(prompt, model_name=model_name)

def improve_code_based_on_review(code: str, review: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# INSTRUCCIÓN\n"
        "Mejora el siguiente código Python implementando todas las recomendaciones del análisis técnico:\n\n"
        f"## CÓDIGO ORIGINAL\n```python\n{code}\n```\n\n"
        f"## ANÁLISIS TÉCNICO\n```\n{review}\n```\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el código Python completo y mejorado.\n\n"
        "# REQUISITOS\n"
        "1. Código completo y funcional en un solo archivo.\n"
        "2. Genera visualizaciones (PNG, JPG) o gráficos animados (GIF, MP4).\n"
        "3. Exporta datos para análisis (CSV, Excel, JSON) cuando corresponda.\n"
        "4. Todos los archivos generados deben guardarse en la raíz del proyecto.\n"
        "5. Incluye manejo robusto de errores y documentación clara.\n"
        "6. Optimiza rendimiento y seguridad.\n"
        "7. Agrega docstrings y comentarios útiles en español.\n\n"
        "# RESTRICCIONES\n"
        "- NO incluyas explicaciones ni notas.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- NO omitas secciones con comentarios como '# resto del código...'.\n"
        "- INCLUYE comentarios explicativos en español dentro del código.\n"
        "- ASEGURA que el código esté listo para producción."
    )
    return generate_code(prompt, model_name=model_name)

def review_report(report: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# INSTRUCCIÓN\n"
        "Evalúa el siguiente reporte técnico en Markdown como experto en ciencia de datos:\n\n"
        f"```markdown\n{report}\n```\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Estructura tu evaluación en español con estas secciones:\n"
        "1. **Evaluación general**: Calidad, coherencia y efectividad del reporte.\n"
        "2. **Fortalezas**: Aspectos positivos y elementos bien ejecutados.\n"
        "3. **Debilidades críticas**: Problemas que comprometan validez o utilidad.\n"
        "4. **Análisis por sección**: Evaluación detallada de cada sección principal.\n"
        "5. **Rigor metodológico**: Evaluación de metodología, análisis estadístico y validez.\n"
        "6. **Visualización de datos**: Crítica de gráficos, tablas y elementos visuales.\n"
        "7. **Recomendaciones específicas**: Sugerencias concretas y priorizadas con ejemplos.\n"
        "8. **Precisión científica**: Adherencia a estándares científicos.\n\n"
        "# RESTRICCIONES\n"
        "- NO reproduzcas el contenido original del reporte.\n"
        "- NO uses lenguaje ambiguo o genérico.\n"
        "- SÉ específico al señalar problemas, citando texto exacto si es relevante.\n"
        "- MANTÉN un tono técnico, constructivo y objetivo.\n"
        "- ENFÓCATE en contenido y estructura, no en problemas de formato Markdown.\n"
        "- ESCRIBE todo en español técnico fluido.\n"
        "- INCLUYE ejemplos de cómo mejorar secciones específicas."
    )
    return generate_code(prompt, model_name=model_name)

def improve_report_based_on_review(report: str, review: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# INSTRUCCIÓN\n"
        "Mejora el siguiente reporte científico en Markdown implementando todas las recomendaciones del análisis:\n\n"
        f"## REPORTE ORIGINAL\n```markdown\n{report}\n```\n\n"
        f"## REVISIÓN TÉCNICA\n```\n{review}\n```\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el reporte mejorado en Markdown.\n\n"
        "# REQUISITOS\n"
        "1. Mantén la estructura general pero mejora cada sección según el análisis.\n"
        "2. Fortalece el rigor científico, claridad y presentación de datos.\n"
        "3. Conserva referencias a visualizaciones con el formato `{{visualize_filename}}`.\n"
        "4. Asegura análisis profundo, conclusiones sólidas y lenguaje preciso.\n"
        "5. Agrega secciones faltantes que mejoren la calidad científica.\n"
        "6. Reorganiza el contenido si es necesario para mejorar el flujo lógico.\n"
        "7. Usa términos técnicos precisos y explícalos adecuadamente.\n\n"
        "# RESTRICCIONES\n"
        "- NO incluyas explicaciones sobre los cambios.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- NO omitas secciones importantes del reporte original.\n"
        "- MANTÉN formato puro Markdown (sin HTML).\n"
        "- ESCRIBE todo en español técnico fluido.\n"
        "- ASEGURA coherencia en terminología y notación."
    )
    return generate_code(prompt, model_name=model_name)

def get_dependencies(code: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# INSTRUCCIÓN\n"
        "Analiza el siguiente código Python y genera un archivo requirements.txt preciso, teniendo en cuenta que se usa python:3.9-slim en un Docker:\n\n"
        f"```python\n{code}\n```\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el contenido del requirements.txt, con cada dependencia en una línea.\n\n"
        "# REQUISITOS\n"
        "1. Incluye TODAS las bibliotecas importadas explícita e implícitamente.\n"
        "2. Especifica versiones exactas en formato `package==version`.\n"
        "3. Incluye dependencias secundarias críticas si son necesarias.\n"
        "4. Ordena alfabéticamente las dependencias.\n"
        "5. Asegura compatibilidad para visualizaciones (matplotlib, plotly, etc.).\n"
        "6. Incluye bibliotecas de procesamiento de datos (pandas, numpy) si se usan.\n"
        "7. Usa las versiones estables más recientes de febrero 2025.\n"
        "8. Garantiza compatibilidad entre versiones.\n\n"
        "# RESTRICCIONES\n"
        "- LAS VERSIONES deben ser compatibles con python:3.9-slim en un Docker.\n"
        "- NO incluyas explicaciones ni comentarios.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- NO incluyas paquetes del sistema (solo paquetes pip).\n"
        "- SI no hay dependencias, retorna una cadena vacía.\n"
        "- ASEGURA que las versiones estén disponibles en PyPI."
    )
    result = generate_code(prompt, model_name=model_name)
    return result.strip()

def refine_code(previous_code: str, outputs: dict, thought_chain: str, error_history: list = None, model_name: str = "gemini-2.0-flash-001") -> str:
    if error_history is None:
        error_history = []
    error_history_str = "\n".join(error_history)
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        "# CONTEXTO\n"
        f"## ANÁLISIS PREVIO\n```\n{thought_chain}\n```\n\n"
        f"## HISTORIAL DE ERRORES\n```\n{error_history_str or 'Ninguno.'}\n```\n\n"
        f"## CÓDIGO ACTUAL\n```python\n{previous_code}\n```\n\n"
        f"## RESULTADOS DE EJECUCIÓN\n```\n{outputs_str}\n```\n\n"
        "# INSTRUCCIÓN\n"
        "Corrige el código Python para resolver todos los errores identificados. Usa un enfoque diferente si es necesario.\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el código Python completo y corregido.\n\n"
        "# REQUISITOS\n"
        "1. Código completo en un solo archivo.\n"
        "2. Resuelve TODOS los errores de los resultados de ejecución.\n"
        "3. Genera visualizaciones (PNG, JPG) o gráficos animados (GIF, MP4).\n"
        "4. Exporta datos (CSV, Excel, JSON) cuando corresponda.\n"
        "5. Guarda todos los archivos generados en la raíz del proyecto.\n"
        "6. Usa un enfoque distinto al anterior si falló previamente.\n"
        "7. Incluye manejo de errores robusto con tipos de excepciones específicos.\n"
        "8. Agrega logging completo para depuración.\n\n"
        "# RESTRICCIONES\n"
        "- NO incluyas explicaciones ni notas.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- NO omitas secciones con comentarios como '# resto del código...'.\n"
        "- INCLUYE comentarios explicativos en español dentro del código.\n"
        "- ESCRIBE docstrings y comentarios en español.\n"
        "- ASEGURA una solución significativamente distinta si los enfoques previos fallaron."
    )
    return generate_code(prompt, model_name=model_name)

def refine_dependencies(previous_deps: str, code: str, outputs: dict, thought_chain: str, error_history: list = None, model_name: str = "gemini-2.0-flash-001") -> str:
    if error_history is None:
        error_history = []
    error_history_str = "\n".join(error_history)
    outputs_str = "\n".join(f"{k}: {v}" for k, v in outputs.items())
    prompt = (
        "# CONTEXTO\n"
        f"## ANÁLISIS PREVIO\n```\n{thought_chain}\n```\n\n"
        f"## HISTORIAL DE ERRORES\n```\n{error_history_str or 'Ninguno.'}\n```\n\n"
        f"## CÓDIGO ACTUAL\n```python\n{code}\n```\n\n"
        f"## DEPENDENCIAS ACTUALES\n```\n{previous_deps}\n```\n\n"
        f"## RESULTADOS DE EJECUCIÓN\n```\n{outputs_str}\n```\n\n"
        "# INSTRUCCIÓN\n"
        "Corrige el archivo requirements.txt para resolver todos los errores de dependencias identificados.\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el contenido corregido del requirements.txt, con cada dependencia en una línea.\n\n"
        "# REQUISITOS\n"
        "1. Incluye TODAS las bibliotecas necesarias para ejecutar el código sin errores.\n"
        "2. Especifica versiones exactas en formato `package==version`.\n"
        "3. Resuelve errores de importación o ModuleNotFoundError en los resultados.\n"
        "4. Asegura dependencias para manejo de datos y visualizaciones.\n"
        "5. Corrige conflictos de versiones si están presentes.\n"
        "6. Agrega dependencias faltantes que causen errores.\n"
        "7. Elimina dependencias que generen conflictos.\n"
        "8. Garantiza compatibilidad con Python 3.9+.\n\n"
        "# RESTRICCIONES\n"
        "- NO incluyas explicaciones ni comentarios.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- NO incluyas paquetes del sistema (solo paquetes pip).\n"
        "- ASEGURA compatibilidad entre versiones.\n"
        "- ENFÓCATE en dependencias que resuelvan los errores de ejecución."
    )
    return generate_code(prompt, model_name=model_name).strip()

def improve_code(previous_code: str, additional_instructions: str, thought_chain: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# CONTEXTO\n"
        f"## ANÁLISIS PREVIO\n```\n{thought_chain}\n```\n\n"
        f"## CÓDIGO ACTUAL\n```python\n{previous_code}\n```\n\n"
        f"## INSTRUCCIONES ADICIONALES\n```\n{additional_instructions}\n```\n\n"
        "# INSTRUCCIÓN\n"
        "Mejora el código Python según las instrucciones adicionales y el análisis previo. Aplica mejoras sustanciales más allá de lo solicitado.\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el código Python completo y mejorado.\n\n"
        "# REQUISITOS\n"
        "1. Código completo en un solo archivo.\n"
        "2. Implementa TODAS las mejoras solicitadas en las instrucciones adicionales.\n"
        "3. Genera visualizaciones (PNG, JPG) o gráficos animados (GIF, MP4).\n"
        "4. Exporta datos (CSV, Excel, JSON) cuando corresponda.\n"
        "5. Guarda todos los archivos generados en la raíz del proyecto.\n"
        "6. Ejecutable en Docker sin configuración adicional.\n"
        "7. Incluye manejo de errores y logging completo.\n"
        "8. Mejora organización, modularidad y documentación.\n\n"
        "# RESTRICCIONES\n"
        "- NO incluyas explicaciones ni notas.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- NO omitas secciones con comentarios como '# resto del código...'.\n"
        "- INCLUYE comentarios explicativos en español dentro del código.\n"
        "- ESCRIBE docstrings y comentarios en español.\n"
        "- ASEGURA mejoras significativas más allá de lo solicitado."
    )
    return generate_code(prompt, model_name=model_name)

def generate_markdown_report(stdout: str, stderr: str, image_files: list, data_files: list, thought_chain: str, model_name: str = "gemini-2.0-flash-001") -> str:
    images = ", ".join(image_files) if image_files else "Ninguna"
    data = ", ".join(data_files) if data_files else "Ninguna"
    prompt = (
        "# CONTEXTO\n"
        f"## ANÁLISIS PREVIO\n```\n{thought_chain}\n```\n\n"
        f"## ARCHIVOS GENERADOS\n"
        f"- Imágenes: {images}\n"
        f"- Datos: {data}\n\n"
        f"## SALIDA ESTÁNDAR\n```\n{stdout}\n```\n\n"
        f"## ERRORES\n```\n{stderr}\n```\n\n"
        "# INSTRUCCIÓN\n"
        "Genera un reporte científico completo en Markdown que analice los resultados con profundidad y precisión técnica.\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el reporte científico en Markdown.\n\n"
        "# REQUISITOS\n"
        "1. Estructura del reporte:\n"
        "   - Título descriptivo\n"
        "   - Resumen ejecutivo (abstract)\n"
        "   - Introducción y contexto\n"
        "   - Metodología con detalles técnicos\n"
        "   - Resultados con análisis detallado\n"
        "   - Discusión de implicaciones y limitaciones\n"
        "   - Conclusiones con insights clave\n"
        "   - Recomendaciones para trabajo futuro\n"
        "   - Referencias (si aplica)\n\n"
        "2. Por cada imagen:\n"
        "   - Descripción técnica detallada\n"
        "   - Análisis de patrones observados\n"
        "   - Interpretación científica con teoría de soporte\n"
        "   - Limitaciones y consideraciones\n"
        "   - Comparación con resultados esperados\n\n"
        "3. Por cada archivo de datos:\n"
        "   - Descripción de estructura y contenido\n"
        "   - Análisis estadístico relevante\n"
        "   - Interpretación de tendencias o hallazgos\n"
        "   - Evaluación de calidad de datos\n"
        "   - Recomendaciones basadas en insights\n\n"
        "4. Referencia archivos con el marcador `{{visualize_filename}}` donde corresponda.\n\n"
        "# RESTRICCIONES\n"
        "- NO analices ni menciones el código fuente.\n"
        "- NO uses HTML dentro del Markdown.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- NO pongas comillas alrededor de {{visualize_filename}}.\n"
        "- MANTÉN un tono científico, objetivo y técnico.\n"
        "- ESCRIBE todo en español técnico fluido.\n"
        "- ASEGURA que cada sección aporte insights específicos."
    )
    return generate_code(prompt, model_name=model_name)

def classify_execution_error(combined_output: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# INSTRUCCIÓN\n"
        "Analiza la siguiente salida de ejecución de un script Python en Docker y clasifica el tipo de error principal:\n\n"
        f"```\n{combined_output}\n```\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Responde con SOLO UNA PALABRA de estas opciones:\n"
        "- 'DEPENDENCY': Error por dependencias faltantes o incompatibles.\n"
        "- 'CODE': Error en la lógica o sintaxis del código.\n"
        "- 'BOTH': Errores tanto de dependencias como de código.\n"
        "- 'OK': Sin errores, ejecución exitosa.\n\n"
        "# RESTRICCIONES\n"
        "- RESponde solo con una de las cuatro opciones en mayúsculas.\n"
        "- NO incluyas explicaciones ni justificaciones.\n"
        "- NO uses delimitadores, comillas ni puntuación adicional.\n"
        "- ANALIZA cuidadosamente 'ImportError', 'ModuleNotFoundError' (DEPENDENCY) vs 'SyntaxError', 'TypeError', etc. (CODE).\n"
        "- PRIORIZA el error más crítico si hay varios presentes."
    )
    response = generate_code(prompt, model_name=model_name)
    classification = response.strip().upper()
    if classification in ["DEPENDENCY", "CODE", "BOTH", "OK"]:
        return classification
    else:
        return "UNKNOWN"

def refine_requirements_with_gemini(initial_requirements: str, code: str, model_name: str = "gemini-2.0-flash-001") -> str:
    prompt = (
        "# INSTRUCCIÓN\n"
        "Analiza el siguiente código Python y el archivo requirements.txt inicial. Corrige y optimiza las dependencias para que sean precisas y compatibles con Python 3.9 en un contenedor Docker basado en python:3.9-slim.\n\n"
        f"## CÓDIGO PYTHON\n```python\n{code}\n```\n\n"
        f"## REQUIREMENTS.TXT INICIAL\n```\n{initial_requirements}\n```\n\n"
        "# FORMATO DE RESPUESTA\n"
        "Proporciona solo el contenido corregido del requirements.txt, con cada dependencia en una línea y versiones exactas en formato `package==version`.\n\n"
        "# REQUISITOS\n"
        "1. Excluye módulos estándar de Python (como hashlib, logging, re, warnings).\n"
        "2. Corrige nombres de paquetes incorrectos.\n"
        "3. Incluye todas las bibliotecas necesarias para ejecutar el código sin errores.\n"
        "4. Especifica versiones exactas compatibles con Python 3.9.\n"
        "5. Asegura compatibilidad entre versiones de las dependencias.\n"
        "6. Ordena alfabéticamente las dependencias.\n"
        "7. Elimina cualquier dependencia que no sea necesaria.\n"
        "8. Asegura que las dependencias van sin version para que se encuentre la compatible, asi que no pongas la version\n\n"
        "# RESTRICCIONES\n"
        "- NO incluyas explicaciones ni comentarios.\n"
        "- NO uses delimitadores de markdown (```).\n"
        "- ASEGURA que todas las dependencias sean instalables con pip en python:3.9-slim.\n"
        "- SI no hay dependencias necesarias, retorna una cadena vacía."
    )
    refined_requirements = generate_code(prompt, model_name=model_name)
    return refined_requirements.strip()