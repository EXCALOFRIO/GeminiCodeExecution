import streamlit as st
import pandas as pd
import base64
import re
from difflib import get_close_matches
from gemini_client import (
    generate_code,
    refine_code,
    get_dependencies,
    refine_dependencies,
    improve_code,
    generate_code_name
)
from code_formatter import clean_code, format_output
from docker_executor import execute_code_in_docker, initialize_docker_image
from file_formatter import format_generated_file
import os
import time
from io import BytesIO

# =============================================================================
# ====================== FUNCIONES AUXILIARES ==================================
# =============================================================================

def get_file_icon(filename):
    """Devuelve un ícono basado en la extensión del archivo."""
    ext = filename.lower().split('.')[-1]
    icons = {
        'csv': "📄", 'xlsx': "📊", 'xls': "📊", 'png': "🖼️", 'jpg': "🖼️",
        'jpeg': "🖼️", 'gif': "🖼️", 'md': "📝", 'html': "📝", 'txt': "📄",
        'mp4': "🎞️", 'mov': "🎞️", 'avi': "🎞️", 'webm': "🎞️", 'pdf': "📕"
    }
    return icons.get(ext, "📁")

def encode_image_to_base64(image_content):
    """Codifica el contenido de la imagen en base64."""
    return base64.b64encode(image_content).decode('utf-8')

def find_best_image_match(ref_name, image_files):
    """
    Encuentra la mejor coincidencia de imagen basada en el nombre referenciado,
    usando coincidencias parciales e insensibles a mayúsculas/minúsculas.
    """
    image_names = list(image_files.keys())
    matches = get_close_matches(ref_name, image_names, n=1, cutoff=0.6)
    if matches:
        return matches[0]
    return None

def partition_markdown_with_images(md_report, image_files):
    """
    Particiona el Markdown, detecta referencias a imágenes, e inserta
    la imagen correspondiente en base64.
    """
    # Expresión regular para detectar referencias a imágenes en Markdown
    image_ref_pattern = r'!\[.*?\]\((.*?)\)'
    parts = []
    last_pos = 0

    # Buscar todas las referencias a imágenes
    for match in re.finditer(image_ref_pattern, md_report):
        start, end = match.span()
        ref_name = match.group(1)  # Nombre de la imagen referenciada

        # Agregar el texto antes de la referencia
        parts.append(md_report[last_pos:start])

        # Encontrar la mejor coincidencia de imagen
        best_match = find_best_image_match(ref_name, image_files)
        if best_match:
            b64 = encode_image_to_base64(image_files[best_match])
            # Insertar la imagen en base64
            parts.append(f"![{best_match}](data:image/png;base64,{b64})")
        else:
            # Si no hay coincidencia, mantener la referencia original
            parts.append(md_report[start:end])

        last_pos = end

    # Agregar el texto restante
    parts.append(md_report[last_pos:])
    return ''.join(parts)

# =============================================================================
# ====================== CONFIGURACIÓN Y UI ===================================
# =============================================================================

st.set_page_config(page_title="AI Code Docker Executor", layout="wide")

# Inicializar entorno Docker una sola vez
if "docker_initialized" not in st.session_state:
    with st.spinner("Inicializando entorno Docker..."):
        docker_init_msg = initialize_docker_image()
    st.write(docker_init_msg)
    st.session_state["docker_initialized"] = True

# Panel de configuración en la barra lateral
with st.sidebar:
    st.header("Configuración de Gemini")
    MODEL_OPTIONS = [
        "gemini-2.0-flash-lite-preview-02-05",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash-thinking-exp-01-21",
        "gemini-2.0-pro-exp-02-05"
    ]
    selected_model = st.selectbox(
        "Modelo de Gemini:",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index("gemini-2.0-flash-exp")
    )

    st.header("Parámetros de Ejecución")
    max_attempts = st.number_input(
        "Máximo de intentos de refinamiento (errores)",
        min_value=1,
        max_value=10,
        value=5
    )
    improvement_iterations = st.number_input(
        "Iteraciones iniciales de mejora",
        min_value=0,
        max_value=10,
        value=1,
        help="Número de veces que el código se refinará tras generarse para asegurar resultados correctos."
    )

# Variables de estado de la sesión
if "generated" not in st.session_state:
    st.session_state["generated"] = False
if "versions" not in st.session_state:
    st.session_state["versions"] = []
if "base_name" not in st.session_state:
    st.session_state["base_name"] = "Code"
if "version_counter" not in st.session_state:
    st.session_state["version_counter"] = 1
if "last_status" not in st.session_state:
    st.session_state["last_status"] = ""
if "log_history" not in st.session_state:
    st.session_state["log_history"] = ""
if "input_files" not in st.session_state:
    st.session_state["input_files"] = {}

def get_current_version_label():
    """Devuelve la etiqueta de versión en formato 'Code vX'."""
    return f"{st.session_state['base_name']} v{st.session_state['version_counter']}"

def validate_execution(outputs):
    """Valida la ejecución del código en Docker revisando errores comunes."""
    combined_output = outputs.get("stdout", "") + outputs.get("stderr", "")
    if "ModuleNotFoundError" in combined_output:
        return "DEPENDENCY", "Error en dependencias: módulo no encontrado."
    if "SyntaxError" in combined_output or "invalid syntax" in combined_output:
        return "CODE", "Error en el código: sintaxis inválida."
    if "Traceback" in combined_output:
        return "CODE", "Error en el código: excepción detectada."
    if "No matching distribution found" in combined_output:
        return "DEPENDENCY", "Error en dependencias: distribución no encontrada."
    return "OK", "Código ejecutado exitosamente."

# =============================================================================
# ====================== LÓGICA PRINCIPAL ======================================
# =============================================================================

st.title("AI Code Docker Executor")
st.markdown(
    "Genera y refina código Python usando la API de Gemini y ejecútalo en un entorno aislado (Docker) "
    "con validación automática y retroalimentación."
)

log_placeholder = st.empty()
status_placeholder = st.empty()

def update_status(message):
    """Actualiza el mensaje de estado en la interfaz."""
    status_placeholder.markdown(f"- {message}")

# Sección de entrada (prompt + archivos)
with st.expander("Instrucciones y Archivos Adjuntos", expanded=True):
    user_instruction = st.text_area(
        "Instrucción (prompt) para generar código Python:",
        placeholder="Ejemplo: Analiza ventas desde un archivo Excel y crea un gráfico de barras comparando ventas por producto."
    )
    uploaded_files = st.file_uploader(
        "Sube uno o varios archivos (opcional)",
        accept_multiple_files=True,
        help="Los archivos adjuntos se colocarán en el mismo directorio que el script."
    )

# Botón para generar y ejecutar código
if st.button("Generar y Ejecutar Código"):
    if not user_instruction.strip():
        st.error("Por favor, ingresa una instrucción antes de generar el código.")
    else:
        # Reiniciar estado para un nuevo prompt
        st.session_state["generated"] = True
        st.session_state["versions"] = []
        st.session_state["version_counter"] = 1
        st.session_state["last_status"] = ""
        st.session_state["log_history"] = ""
        st.session_state["input_files"] = {}

        update_status("Procesando archivos adjuntos...")
        input_files = {}
        resumen_archivos = ""
        for file in uploaded_files or []:
            file.seek(0)
            try:
                if file.name.lower().endswith(".csv"):
                    df = pd.read_csv(file)
                    resumen = df.head().to_string()
                    resumen_archivos += f"\nArchivo {file.name} (CSV):\n{resumen}\n"
                    file.seek(0)
                    input_files[file.name] = file.read()
                elif file.name.lower().endswith((".xlsx", ".xls")):
                    df = pd.read_excel(file)
                    resumen = df.head().to_string()
                    resumen_archivos += f"\nArchivo {file.name} (Excel):\n{resumen}\n"
                    file.seek(0)
                    input_files[file.name] = file.read()
                else:
                    content = file.read()
                    input_files[file.name] = content
                    resumen_archivos += f"\nArchivo {file.name}: Adjuntado para uso en el código.\n"
            except Exception as e:
                resumen_archivos += f"\nNo se pudo procesar {file.name}: {e}\n"

        st.session_state["input_files"] = input_files
        update_status("Archivos procesados exitosamente.")

        # Construir prompt para generación de código
        prompt = f"Instrucción del usuario:\n{user_instruction}\n"
        if resumen_archivos:
            prompt += f"\nInformación de archivos adjuntos:\n{resumen_archivos}\n"
        prompt += (
            "\nGenera el código Python completo que resuelva la instrucción del usuario, listo para ejecutarse en un entorno aislado (Docker). "
            "Asegúrate de que el código sea funcional y directamente ejecutable. Si es apropiado, genera imágenes y guárdalas como archivos PNG en el directorio raíz."
        )

        # Generación inicial del código
        with st.spinner("Generando código con Gemini..."):
            try:
                code_generated = generate_code(prompt, model_name=selected_model)
                code_generated = clean_code(code_generated)
                update_status("Código generado exitosamente.")
            except Exception as e:
                st.error(f"Error generando código: {e}")
                st.stop()

        # Mejora inicial del código
        current_code = code_generated
        if improvement_iterations > 0:
            improvement_prompt = (
                "Asegúrate de que el código genere correctamente imágenes o gráficos y los guarde como archivos PNG."
            )
            for i in range(int(improvement_iterations)):
                with st.spinner(f"Mejorando código (iteración {i+1}/{int(improvement_iterations)})..."):
                    try:
                        new_code = improve_code(current_code, improvement_prompt, model_name=selected_model)
                        new_code = clean_code(new_code)
                        if new_code.strip() == current_code.strip():
                            update_status("No se detectaron mejoras en esta iteración.")
                            break
                        current_code = new_code
                    except Exception as e:
                        st.error(f"Error en iteración de mejora inicial: {e}")
                        break

        # Guardar primera versión
        version_label = get_current_version_label()
        st.session_state["versions"].append({
            "label": version_label,
            "code": current_code,
            "dependencies": "",
            "logs": "",
            "stdout": "",
            "stderr": "",
            "files": {}
        })
        update_status(f"Guardada versión inicial: {version_label}")

        # Obtener dependencias
        with st.spinner("Obteniendo lista de dependencias requeridas..."):
            try:
                dependencies = get_dependencies(current_code, model_name=selected_model)
                dependencies = clean_code(dependencies)
                update_status("Dependencias obtenidas.")
            except Exception as e:
                st.error(f"Error obteniendo dependencias: {e}")
                st.stop()

        st.session_state["versions"][-1]["dependencies"] = dependencies

        # Ciclo de validación y refinamiento
        codigo_actual = current_code
        deps_actuales = dependencies
        logs_accum = ""
        for intento in range(1, int(max_attempts) + 1):
            update_status(f"Iniciando ejecución en contenedor Docker (intento {intento})...")
            with st.spinner(f"Ejecutando código en Docker (intento {intento})..."):
                outputs = execute_code_in_docker(codigo_actual, input_files, deps_actuales)
            status, msg = validate_execution(outputs)
            logs_accum += f"Validación: {status} - {msg}\n"
            st.session_state["versions"][-1]["logs"] = logs_accum
            st.session_state["versions"][-1]["stdout"] = outputs.get("stdout", "")
            st.session_state["versions"][-1]["stderr"] = outputs.get("stderr", "")
            st.session_state["versions"][-1]["files"] = outputs.get("files", {})

            update_status(f"Validación: {status} - {msg}")
            time.sleep(0.5)

            if status == "OK":
                st.session_state["last_status"] = "OK"
                # Generar reporte Markdown solo si la ejecución fue exitosa
                with st.spinner("Generando reporte Markdown de resultados con Gemini..."):
                    image_files = {fname: fcontent for fname, fcontent in outputs.get("files", {}).items()
                                   if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))}
                    report_prompt = (
                        "Basándote en los siguientes resultados de ejecución, genera un informe completo en Markdown que explique los resultados "
                        "de manera clara y científica, incluyendo secciones como Introducción, Metodología, Resultados y Conclusión. "
                        "Incluye referencias a las imágenes generadas usando la sintaxis de Markdown, por ejemplo: ![Descripción](nombre_imagen.png).\n\n"
                        "Resultados de ejecución:\n"
                        f"STDOUT: {outputs.get('stdout', '')}\n"
                        f"STDERR: {outputs.get('stderr', '')}\n"
                        f"Logs: {logs_accum}\n"
                        f"Código Generado:\n{codigo_actual}\n"
                        f"Imágenes generadas (usa estos nombres en el reporte): {', '.join(image_files.keys())}\n"
                    )
                    try:
                        md_report = generate_code(report_prompt, model_name=selected_model)
                        md_report = clean_code(md_report)
                        # Procesar el Markdown para incrustar imágenes
                        md_report = partition_markdown_with_images(md_report, image_files)
                        update_status("Reporte Markdown generado por Gemini.")
                    except Exception as e:
                        st.error(f"Error generando reporte Markdown: {e}")
                        md_report = "Error al generar el reporte Markdown."
                break
            elif status == "DEPENDENCY":
                st.session_state["last_status"] = "DEPENDENCY"
                with st.spinner("Refinando dependencias..."):
                    try:
                        new_deps = refine_dependencies(deps_actuales, codigo_actual, outputs, model_name=selected_model)
                        new_deps = clean_code(new_deps)
                        deps_actuales = new_deps
                        st.session_state["versions"][-1]["dependencies"] = deps_actuales
                        update_status("Dependencias refinadas.")
                    except Exception as e:
                        logs_accum += f"Error refinando dependencias: {e}\n"
                        break
            elif status == "CODE":
                st.session_state["last_status"] = "CODE"
                with st.spinner("Refinando código..."):
                    try:
                        new_code = refine_code(codigo_actual, outputs, model_name=selected_model)
                        new_code = clean_code(new_code)
                        st.session_state["version_counter"] += 1
                        version_label = get_current_version_label()
                        st.session_state["versions"].append({
                            "label": version_label,
                            "code": new_code,
                            "dependencies": deps_actuales,
                            "logs": "",
                            "stdout": "",
                            "stderr": "",
                            "files": {}
                        })
                        codigo_actual = new_code
                        update_status(f"Código refinado: {version_label}")
                    except Exception as e:
                        logs_accum += f"Error refinando código: {e}\n"
                        break
            if intento == max_attempts:
                logs_accum += "Se alcanzó el número máximo de intentos.\n"
                update_status("Máximo de intentos alcanzado.")

        st.session_state["log_history"] = logs_accum

# =============================================================================
# ====================== MOSTRAR RESULTADOS ===================================
# =============================================================================

if st.session_state.get("generated", False):
    latest_version_data = st.session_state["versions"][-1]

    col_left, col_right = st.columns([1, 2], gap="medium")

    with col_left:
        st.subheader("Dependencias")
        deps_text = latest_version_data["dependencies"].strip() or "Sin dependencias"
        st.text_area("Lista de dependencias", deps_text, height=150)

        st.subheader("Logs de Ejecución")
        st.text_area("Logs", st.session_state["log_history"], height=300)

        st.subheader("Archivos Generados")
        if latest_version_data["files"]:
            for fname, fcontent in latest_version_data["files"].items():
                icon = get_file_icon(fname)
                st.write(f"{icon} {fname}")
                st.download_button(
                    label="Descargar",
                    data=fcontent,
                    file_name=fname
                )
        else:
            st.info("No se generaron archivos.")

    with col_right:
        st.subheader("Código Generado")
        st.code(latest_version_data["code"], language="python")

    if st.session_state["last_status"] == "OK":
        st.markdown("---")
        st.markdown("### Reporte de Resultados (Markdown)")
        # Envolver el Markdown en un div con ancho máximo para que sea más bonito
        st.markdown(f'<div style="max-width: 800px; margin: auto;">{md_report}</div>', unsafe_allow_html=True)

    # Mejoras adicionales
    if st.session_state["last_status"] == "OK":
        st.markdown("---")
        st.markdown("### Mejoras Adicionales")
        improvement_instructions = st.text_area(
            "Instrucciones de mejora:",
            placeholder="Ejemplo: Optimizar eficiencia y asegurar generación de imágenes."
        )
        if st.button("Aplicar Mejora Adicional"):
            if improvement_instructions.strip():
                current_code = latest_version_data["code"]
                with st.spinner("Aplicando mejora adicional..."):
                    try:
                        improved_code = improve_code(current_code, improvement_instructions, model_name=selected_model)
                        improved_code = clean_code(improved_code)
                        if improved_code.strip() == current_code.strip():
                            update_status("No se detectaron cambios en la mejora adicional.")
                        else:
                            current_code = improved_code
                            improved_deps = get_dependencies(current_code, model_name=selected_model)
                            outputs = execute_code_in_docker(current_code, st.session_state["input_files"], improved_deps)
                            st.session_state["version_counter"] += 1
                            version_label = get_current_version_label()
                            st.session_state["versions"].append({
                                "label": version_label,
                                "code": current_code,
                                "dependencies": improved_deps,
                                "logs": "",
                                "stdout": outputs.get("stdout", ""),
                                "stderr": outputs.get("stderr", ""),
                                "files": outputs.get("files", {})
                            })
                            update_status("Mejora adicional aplicada exitosamente.")
                    except Exception as e:
                        st.error(f"Error en mejora adicional: {e}")
            else:
                st.error("Ingresa instrucciones de mejora antes de aplicar.")

    if st.button("Nuevo Prompt"):
        keys_to_keep = ["docker_initialized"]
        for key in list(st.session_state.keys()):
            if key not in keys_to_keep:
                del st.session_state[key]
        st.experimental_rerun()