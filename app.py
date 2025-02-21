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

def partition_markdown_with_images(md_report, image_files, generated_files):
    """
    Particiona el Markdown, detecta referencias a imágenes y archivos CSV/Excel,
    e inserta la imagen correspondiente en base64 o un placeholder para visualización.
    """
    image_ref_pattern = r'!\[.*?\]\((.*?)\)'
    parts = []
    last_pos = 0

    for match in re.finditer(image_ref_pattern, md_report):
        start, end = match.span()
        ref_name = match.group(1)

        parts.append(md_report[last_pos:start])
        best_match = find_best_image_match(ref_name, image_files)
        if best_match:
            b64 = encode_image_to_base64(image_files[best_match])
            parts.append(f"![{best_match}](data:image/png;base64,{b64})")
        else:
            parts.append(md_report[start:end])

        last_pos = end

    parts.append(md_report[last_pos:])

    csv_excel_pattern = r'\[.*?\]\((.*?)\)'
    final_parts = []
    for part in parts:
        for match in re.finditer(csv_excel_pattern, part):
            ref_name = match.group(1)
            if ref_name.lower().endswith(('.csv', '.xlsx', '.xls')) and ref_name in generated_files:
                part = part.replace(match.group(0), f"{{{{visualize_{ref_name}}}}}")
        final_parts.append(part)

    return ''.join(final_parts)

def display_generated_files(generated_files):
    """Muestra los archivos generados con íconos y botones de descarga."""
    if generated_files:
        for fname, fcontent in generated_files.items():
            icon = get_file_icon(fname)
            st.write(f"{icon} {fname}")
            st.download_button(
                label="Descargar",
                data=fcontent,
                file_name=fname
            )
    else:
        st.info("No se generaron archivos.")

def display_markdown_with_visualizations(md_report, generated_files):
    """Renderiza el Markdown y muestra visualizaciones para archivos CSV/Excel."""
    st.markdown(md_report, unsafe_allow_html=True)
    for fname, fcontent in generated_files.items():
        if f"{{{{visualize_{fname}}}}}" in md_report:
            if fname.lower().endswith('.csv'):
                df = pd.read_csv(BytesIO(fcontent))
                st.write(f"**Visualización de {fname}:**")
                st.dataframe(df)
            elif fname.lower().endswith(('.xlsx', '.xls')):
                df = pd.read_excel(BytesIO(fcontent))
                st.write(f"**Visualización de {fname}:**")
                st.dataframe(df)

# =============================================================================
# ====================== CONFIGURACIÓN Y UI ===================================
# =============================================================================

st.set_page_config(page_title="AI Code Docker Executor", layout="wide")

if "docker_initialized" not in st.session_state:
    with st.spinner("Inicializando entorno Docker..."):
        docker_init_msg = initialize_docker_image()
    st.write(docker_init_msg)
    st.session_state["docker_initialized"] = True

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

# Variables de estado inicial
if "generated" not in st.session_state:
    st.session_state["generated"] = False
    st.session_state["versions"] = [{"label": "Code v1", "code": "", "dependencies": "", "logs": "", "stdout": "", "stderr": "", "files": {}}]
    st.session_state["base_name"] = "Code"
    st.session_state["version_counter"] = 1
    st.session_state["last_status"] = ""
    st.session_state["log_history"] = ""
    st.session_state["input_files"] = {}
    st.session_state["md_report"] = ""
    st.session_state["status_messages"] = []

def get_current_version_label():
    return f"{st.session_state['base_name']} v{st.session_state['version_counter']}"

def validate_execution(outputs):
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
# ====================== INTERFAZ PRINCIPAL ===================================
# =============================================================================

st.title("AI Code Docker Executor")
st.markdown(
    "Genera y refina código Python usando la API de Gemini y ejecútalo en un entorno aislado (Docker) con validación automática y retroalimentación."
)

# Función para actualizar mensajes de estado
def update_status(message):
    st.session_state["status_messages"].append(f"[{time.strftime('%H:%M:%S')}] {message}")

# Sección de entrada con expander
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
    if st.button("Generar y Ejecutar Código"):
        if not user_instruction.strip():
            st.error("Por favor, ingresa una instrucción antes de generar el código.")
        else:
            st.session_state["generated"] = True
            st.session_state["versions"] = [{"label": "Code v1", "code": "", "dependencies": "", "logs": "", "stdout": "", "stderr": "", "files": {}}]
            st.session_state["version_counter"] = 1
            st.session_state["last_status"] = ""
            st.session_state["log_history"] = ""
            st.session_state["input_files"] = {}
            st.session_state["md_report"] = ""
            st.session_state["status_messages"] = []

            update_status("Procesando archivos adjuntos...")
            input_files = {}
            resumen_archivos = ""
            for file in uploaded_files or []:
                file.seek(0)
                try:
                    if file.name.lower().endswith(".csv"):
                        df = pd.read_csv(file)
                        resumen = df.head().to_string()
                        resumen_archivos += f"\nFile {file.name} (CSV):\n{resumen}\n"
                        file.seek(0)
                        input_files[file.name] = file.read()
                    elif file.name.lower().endswith((".xlsx", ".xls")):
                        df = pd.read_excel(file)
                        resumen = df.head().to_string()
                        resumen_archivos += f"\nFile {file.name} (Excel):\n{resumen}\n"
                        file.seek(0)
                        input_files[file.name] = file.read()
                    else:
                        content = file.read()
                        input_files[file.name] = content
                        resumen_archivos += f"\nFile {file.name}: Attached for use in the code.\n"
                except Exception as e:
                    resumen_archivos += f"\nUnable to process {file.name}: {e}\n"

            st.session_state["input_files"] = input_files
            update_status("Archivos procesados exitosamente.")

            prompt = (
                "User instruction:\n"
                f"{user_instruction}\n"
                "\nAttached files information (if any):\n"
                f"{resumen_archivos if resumen_archivos else 'No files attached.'}\n"
                "\nGenerate complete and functional Python code to fulfill the user's instruction, ready to run in an isolated Docker environment. "
                "Ensure the code is executable and handles attached files appropriately. If relevant, generate images and save them as PNG files in the root directory. "
                "If data analysis is involved, consider generating CSV or Excel files as output. "
                "Example: If the instruction is 'Analyze sales from an Excel file and create a bar chart,' generate code that reads the Excel file, processes the data, "
                "creates a bar chart with matplotlib, and saves it as 'bar_chart.png'. Provide only the complete Python code, without explanations or delimiters."
            )

            with st.spinner("Generating code with Gemini..."):
                code_generated = generate_code(prompt, model_name=selected_model)
                code_generated = clean_code(code_generated)
                st.session_state["versions"][-1]["code"] = code_generated
                update_status("Código generado exitosamente.")

            current_code = code_generated
            if improvement_iterations > 0:
                improvement_prompt = (
                    "Given the following Python code:\n"
                    f"{current_code}\n"
                    "\nImprove this code to ensure it correctly generates images (e.g., PNG files) or data files (e.g., CSV/Excel) as appropriate, "
                    "and optimizes its functionality based on the user's instruction. Provide only the improved Python code, without explanations or delimiters."
                )
                for i in range(int(improvement_iterations)):
                    with st.spinner(f"Improving code (iteration {i+1}/{int(improvement_iterations)})..."):
                        new_code = improve_code(current_code, improvement_prompt, model_name=selected_model)
                        new_code = clean_code(new_code)
                        if new_code.strip() == current_code.strip():
                            update_status("No improvements detected in this iteration.")
                            break
                        current_code = new_code
                        st.session_state["versions"][-1]["code"] = current_code

            update_status(f"Guardada versión inicial: {get_current_version_label()}")

            with st.spinner("Obtaining required dependencies..."):
                dependencies_prompt = (
                    "Given the following Python code:\n"
                    f"{current_code}\n"
                    "\nGenerate a list of Python dependencies required to run this code in an isolated environment. "
                    "Return only the list in requirements.txt format (one dependency per line, e.g., 'matplotlib==3.8.0'), without explanations or delimiters. "
                    "If no dependencies are needed beyond the standard library, return an empty string."
                )
                dependencies = get_dependencies(current_code, model_name=selected_model)
                dependencies = clean_code(dependencies)
                st.session_state["versions"][-1]["dependencies"] = dependencies
                update_status("Dependencias obtenidas.")

            codigo_actual = current_code
            deps_actuales = dependencies
            logs_accum = ""
            for intento in range(1, int(max_attempts) + 1):
                update_status(f"Ejecutando código en Docker (intento {intento})...")
                with st.spinner(f"Executing code in Docker (attempt {intento})..."):
                    outputs = execute_code_in_docker(codigo_actual, input_files, deps_actuales)
                status, msg = validate_execution(outputs)
                logs_accum += f"Attempt {intento}: {status} - {msg}\n"
                st.session_state["versions"][-1]["logs"] = logs_accum
                st.session_state["versions"][-1]["stdout"] = outputs.get("stdout", "")
                st.session_state["versions"][-1]["stderr"] = outputs.get("stderr", "")
                st.session_state["versions"][-1]["files"] = outputs.get("files", {})
                st.session_state["log_history"] = logs_accum

                update_status(f"Validación: {status} - {msg}")

                if status == "OK":
                    st.session_state["last_status"] = "OK"
                    with st.spinner("Generating Markdown report..."):
                        image_files = {fname: fcontent for fname, fcontent in outputs.get("files", {}).items()
                                       if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))}
                        data_files = {fname: fcontent for fname, fcontent in outputs.get("files", {}).items()
                                      if fname.lower().endswith((".csv", ".xlsx", ".xls"))}
                        report_prompt = (
                            "Based on the following execution results, generate a comprehensive Markdown report that clearly and scientifically explains the outcomes. "
                            "Structure the report with sections like Introduction, Methodology, Results, and Conclusion. "
                            "Include references to generated images using Markdown syntax, e.g., ![Description](image_name.png). "
                            "If CSV or Excel files were generated, include references to them, e.g., [Data](data_file.csv), for later visualization. "
                            "Example: If the code generated 'sales_chart.png' and 'sales_summary.csv', include '![Sales Chart](sales_chart.png)' and '[Sales Data](sales_summary.csv)' in the Results section. "
                            "Return only the complete Markdown content, without additional comments or delimiters.\n\n"
                            "Execution results:\n"
                            f"STDOUT: {outputs.get('stdout', '')}\n"
                            f"STDERR: {outputs.get('stderr', '')}\n"
                            f"Logs: {logs_accum}\n"
                            f"Generated Code:\n{codigo_actual}\n"
                            f"Generated images (use these names in the report): {', '.join(image_files.keys())}\n"
                            f"Generated data files (use these names in the report): {', '.join(data_files.keys())}\n"
                        )
                        md_report = generate_code(report_prompt, model_name=selected_model)
                        md_report = clean_code(md_report)
                        md_report = partition_markdown_with_images(md_report, image_files, outputs.get("files", {}))
                        st.session_state["md_report"] = md_report
                        update_status("Reporte Markdown generado.")
                    break
                elif status == "DEPENDENCY":
                    st.session_state["last_status"] = "DEPENDENCY"
                    with st.spinner("Refining dependencies..."):
                        refine_deps_prompt = (
                            "Given the following Python code:\n"
                            f"{codigo_actual}\n"
                            "Previous dependencies list:\n"
                            f"{deps_actuales}\n"
                            "Execution results:\n"
                            f"STDOUT: {outputs.get('stdout', '')}\nSTDERR: {outputs.get('stderr', '')}\n"
                            "\nRefine the dependencies list to resolve execution errors. Return only the updated list in requirements.txt format (one dependency per line), "
                            "without explanations or delimiters."
                        )
                        new_deps = refine_dependencies(deps_actuales, codigo_actual, outputs, model_name=selected_model)
                        new_deps = clean_code(new_deps)
                        deps_actuales = new_deps
                        st.session_state["versions"][-1]["dependencies"] = deps_actuales
                        update_status("Dependencias refinadas.")
                elif status == "CODE":
                    st.session_state["last_status"] = "CODE"
                    with st.spinner("Refining code..."):
                        refine_code_prompt = (
                            "Given the following Python code:\n"
                            f"{codigo_actual}\n"
                            "Execution results:\n"
                            f"STDOUT: {outputs.get('stdout', '')}\nSTDERR: {outputs.get('stderr', '')}\n"
                            "\nAnalyze the results and fix any errors in the code. Return only the corrected Python code, without explanations or delimiters."
                        )
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
                if intento == max_attempts:
                    logs_accum += "Maximum number of attempts reached.\n"
                    st.session_state["log_history"] = logs_accum
                    update_status("Máximo de intentos alcanzado.")

            st.rerun()

# Secciones de resultados (siempre visibles)
col_left, col_right = st.columns([1, 2], gap="medium")

with col_left:
    st.subheader("Dependencias")
    deps_area = st.text_area("Lista de dependencias", st.session_state["versions"][-1]["dependencies"], height=150, key="deps_area")

    st.subheader("Logs de Ejecución")
    logs_area = st.text_area("Logs", st.session_state["log_history"], height=300, key="logs_area")

    st.subheader("Archivos Generados")
    files_container = st.container()
    with files_container:
        display_generated_files(st.session_state["versions"][-1]["files"])

with col_right:
    st.subheader("Código Generado")
    code_area = st.code(st.session_state["versions"][-1]["code"], language="python")

md_container = st.container()
with md_container:
    if st.session_state["md_report"]:
        st.markdown("---")
        st.markdown("### Reporte de Resultados (Markdown)")
        display_markdown_with_visualizations(st.session_state["md_report"], st.session_state["versions"][-1]["files"])

# Contenedor para mensajes de estado (debajo de todo)
status_container = st.container()
with status_container:
    st.markdown("---")
    st.subheader("Estado del Proceso")
    if st.session_state["status_messages"]:
        st.markdown("\n".join(st.session_state["status_messages"]), unsafe_allow_html=True)
    else:
        st.info("No hay mensajes de estado aún.")

# Mejoras adicionales
if st.session_state["last_status"] == "OK":
    with st.expander("Mejoras Adicionales", expanded=False):
        improvement_instructions = st.text_area(
            "Instrucciones de mejora:",
            placeholder="Ejemplo: Optimize efficiency and ensure image generation."
        )
        if st.button("Aplicar Mejora Adicional"):
            if improvement_instructions.strip():
                current_code = st.session_state["versions"][-1]["code"]
                with st.spinner("Applying additional improvement..."):
                    improve_prompt = (
                        "Current Python code:\n"
                        f"{current_code}\n"
                        "Additional improvement instructions:\n"
                        f"{improvement_instructions}\n"
                        "\nGenerate an improved version of the code based on the instructions. Return only the complete Python code, without explanations or delimiters."
                    )
                    improved_code = improve_code(current_code, improve_prompt, model_name=selected_model)
                    improved_code = clean_code(improved_code)
                    if improved_code.strip() == current_code.strip():
                        update_status("No changes detected in additional improvement.")
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
                        st.session_state["log_history"] = ""
                        st.session_state["md_report"] = ""
                        update_status("Mejora adicional aplicada exitosamente.")
                        st.rerun()
            else:
                st.error("Ingresa instrucciones de mejora antes de aplicar.")

if st.button("Nuevo Prompt"):
    keys_to_keep = ["docker_initialized"]
    for key in list(st.session_state.keys()):
        if key not in keys_to_keep:
            del st.session_state[key]
    st.rerun()