import os
import re
import ast
import sys
import time
import zipfile
import subprocess
import tempfile
import hashlib
import base64
from io import BytesIO
from xhtml2pdf import pisa
from difflib import get_close_matches  # Added for fuzzy matching
import markdown
import pandas as pd
import streamlit as st
from gemini_client import (
    generate_code, refine_code, get_dependencies, refine_dependencies,
    improve_code, generate_markdown_report, generate_thought_chain,
    review_code, improve_code_based_on_review, review_report,
    improve_report_based_on_review, classify_execution_error,
    refine_requirements_with_gemini
)
from code_formatter import clean_code
from docker_executor import initialize_docker_image, execute_code_in_docker
from file_formatter import format_generated_file  # Kept but not used in rendering

# Configuración de la página
st.set_page_config(page_title="AI Code Docker Executor", layout="wide")

# Estilos personalizados (unchanged)
custom_css = """
<style>
body { background-color: #f5f5f5; color: #333333; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
h1 { color: #333333; text-align: center; }
.sidebar .sidebar-content { background: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0px 0px 10px rgba(0,0,0,0.1); }
div[data-testid="stHorizontalBlock"] { margin-bottom: 20px; }
.stDownloadButton { margin-top: 5px; }
.status-container { background-color: #e6f7ff; color: #333333; border-left: 5px solid #1890ff; padding: 10px; margin-bottom: 10px; border-radius: 4px; }
.error-container { background-color: #fff1f0; color: #333333; border-left: 5px solid #ff4d4f; padding: 10px; margin-bottom: 10px; border-radius: 4px; }
@media (prefers-color-scheme: dark) {
    body { background-color: #1e1e1e; color: #f5f5f5; }
    h1 { color: #f5f5f5; }
    .sidebar .sidebar-content { background: #2e2e2e; box-shadow: 0px 0px 10px rgba(255,255,255,0.1); }
    .status-container { background-color: #2e2e2e; color: #f5f5f5; border-left: 5px solid #1890ff; }
    .error-container { background-color: #3b2e2e; color: #f5f5f5; border-left: 5px solid #ff4d4f; }
}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

st.title("🚀 AI Code Docker Executor")

# Configuración desde la barra lateral (unchanged)
st.sidebar.header("Configuración")
nivel_profundidad = st.sidebar.radio(
    "Nivel de Profundidad", options=["Poca", "Normal", "Extremo"], index=1,
    help="Selecciona el nivel de profundidad para los prompts."
)

if nivel_profundidad == "Poca":
    selected_model = "gemini-2.0-flash-lite-001"
    cot_iterations = 0
    revision_iterations = 0
elif nivel_profundidad == "Normal":
    selected_model = "gemini-2.0-flash-exp"
    cot_iterations = 1
    revision_iterations = 0
else:
    selected_model = "gemini-2.0-flash-thinking-exp-01-21"
    cot_iterations = 1
    revision_iterations = 1

st.sidebar.info("Genera, refina y ejecuta código Python en Docker con dependencias automáticas y reportes detallados.")

# Funciones auxiliares
def get_file_icon(filename):
    ext = filename.lower().split('.')[-1]
    icons = {
        'csv': "📄", 'xlsx': "📊", 'xls': "📊", 'png': "🖼️", 'jpg': "🖼️",
        'jpeg': "🖼️", 'gif': "🖼️", 'md': "📝", 'html': "📝", 'txt': "📄",
        'mp4': "🎞️", 'mov': "🎞️", 'avi': "🎞️", 'webm': "🎞️", 'pdf': "📕",
        'mp3': "🎵", 'wav': "🎵", 'ogg': "🎵", 'py': "🐍"
    }
    return icons.get(ext, "📁")

def display_generated_files(generated_files, container):
    with container:
        if generated_files:
            st.markdown("#### Archivos")
            for fname, fcontent in generated_files.items():
                icon = get_file_icon(fname)
                st.write(f"{icon} **{fname}**")
                st.download_button(label="Descargar", data=fcontent, file_name=fname, key=f"btn_{fname}")
        else:
            st.info("No se encontraron archivos.")

def convert_markdown_to_pdf(md_text, files):
    pattern = r'\{\{visualize_(.+?)\}\}'
    def replace_marker(match):
        filename = match.group(1).strip()
        if filename in files:
            file_content = files[filename]
            ext = filename.split('.')[-1].lower()
            if ext in ['png', 'jpg', 'jpeg', 'gif']:
                b64 = base64.b64encode(file_content).decode('utf-8')
                return f'<img src="data:image/{ext};base64,{b64}" style="max-width:100%;"/><br/>'
        return f'<p>[Imagen {filename} no encontrada]</p>'
    md_text_with_images = re.sub(pattern, replace_marker, md_text)
    html_body = markdown.markdown(md_text_with_images, extensions=['extra'])
    html = f"""
    <html>
    <head><style>
    body {{ font-family: Helvetica; font-size: 12pt; line-height: 1.4; }}
    h1 {{ font-size: 24pt; font-weight: bold; margin-bottom: 10pt; }}
    h2 {{ font-size: 18pt; font-weight: bold; margin-bottom: 8pt; }}
    h3 {{ font-size: 14pt; font-weight: bold; margin-bottom: 6pt; }}
    p {{ margin: 5pt 0; }} em {{ font-style: italic; }} strong {{ font-weight: bold; }}
    img {{ margin: 10pt 0; }}
    </style></head><body>{html_body}</body></html>
    """
    result_file = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result_file)
    if pisa_status.err:
        raise Exception("Error al generar el PDF con xhtml2pdf")
    result_file.seek(0)
    return result_file.read()

def extract_imports(code):
    tree = ast.parse(code)
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imports.add(name.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split('.')[0])
    return imports

def generate_requirements_file(code, temp_dir):
    with open(os.path.join(temp_dir, "script.py"), "w", encoding="utf-8") as f:
        f.write(code)
    try:
        subprocess.run(["pipreqs", temp_dir, "--force", "--mode", "no-pin"], check=True, capture_output=True, text=True)
        with open(os.path.join(temp_dir, "requirements.txt"), "r", encoding="utf-8") as f:
            reqs = f.read().strip().splitlines()
    except subprocess.CalledProcessError as e:
        st.warning(f"pipreqs falló: {e.stderr}. Usando análisis estático.")
        reqs = []
    detected_imports = extract_imports(code)
    existing_packages = {line.strip() for line in reqs}
    for pkg in detected_imports:
        if pkg not in existing_packages and pkg not in sys.builtin_module_names:
            reqs.append(pkg)
    requirements = "\n".join(sorted(reqs))
    return clean_code(requirements)

def validate_execution(outputs, model_name):
    combined_output = outputs.get("stdout", "") + outputs.get("stderr", "")
    classification = classify_execution_error(combined_output, model_name=model_name)
    messages = {
        "OK": "Código ejecutado exitosamente.",
        "DEPENDENCY": "Error en dependencias detectado.",
        "CODE": "Error en el código detectado.",
        "BOTH": "Errores en código y dependencias.",
        "UNKNOWN": "Error desconocido."
    }
    return classification, messages.get(classification, "Error desconocido.")

def update_status(status_container, message, progress_bar, progress):
    status_container.markdown(f"<div class='status-container'><strong>Estado:</strong> {message}</div>", unsafe_allow_html=True)
    progress_bar.progress(min(progress, 100))

def display_error(error_container, message, details=None):
    content = f"<div class='error-container'><strong>Error:</strong> {message}"
    if details:
        content += f"<br><strong>Detalles:</strong> <pre>{details}</pre>"
    content += "</div>"
    error_container.markdown(content, unsafe_allow_html=True)

def handle_new_improvement(current_code, prompt_text, attached_file=None, selected_model="gemini-2.0-flash-001", cot_iterations=0):
    file_info = ""
    if attached_file is not None:
        attached_file.seek(0)
        file_content = attached_file.read().decode("utf-8", errors="ignore")
        file_info = f"\nContenido del archivo adjunto ({attached_file.name}):\n```python\n{file_content}\n```"
    thought_chain_improve = generate_thought_chain(
        f"Instrucción de mejora: {prompt_text}\nCódigo actual:\n```python\n{current_code}\n```{file_info}",
        cot_iterations,
        model_name=selected_model
    )
    full_prompt = (
        f"{thought_chain_improve}\n\n"
        "Mejora el código Python existente siguiendo estas instrucciones:\n"
        f"- Instrucción: {prompt_text}\n"
        f"{file_info}\n"
        "**Requisitos:**\n"
        "- Código completo en un solo archivo Python.\n"
        "- Generar archivos en la raíz del proyecto (/app), sin subdirectorios.\n"
        "- Incluir manejo robusto de errores y comentarios en español.\n"
        "- Adaptar la complejidad al modo seleccionado.\n"
        "- Optimizar rendimiento y seguridad.\n"
        "- Asegurar que se generen resultados visibles (imágenes, CSV, audios, etc.) según la instrucción."
    )
    new_code = improve_code(current_code, full_prompt, thought_chain_improve, model_name=selected_model)
    return clean_code(new_code)

def check_syntax(code):
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)

def find_best_match(filename, files, cutoff=0.6):
    matches = get_close_matches(filename, files.keys(), n=1, cutoff=cutoff)
    return matches[0] if matches else None

def render_markdown_with_visualizations(md_report, files):
    pattern = r'(\{\{visualize_(.+?)\}\})'
    parts = re.split(pattern, md_report)
    for part in parts:
        if part.startswith('{{visualize_') and part.endswith('}}'):
            filename = part[13:-2]
            if filename in files:
                file_content = files[filename]
            else:
                best_match = find_best_match(filename, files)
                if best_match:
                    file_content = files[best_match]
                    st.warning(f"Archivo '{filename}' no encontrado, usando '{best_match}' en su lugar.")
                else:
                    st.error(f"Archivo no encontrado: {filename}. Archivos disponibles: {list(files.keys())}")
                    continue
            ext = filename.lower().split('.')[-1]
            if ext in ['png', 'jpg', 'jpeg', 'gif']:
                st.image(file_content, caption=filename)
            elif ext == 'csv':
                df = pd.read_csv(BytesIO(file_content))
                st.dataframe(df)
            elif ext in ['xlsx', 'xls']:
                df = pd.read_excel(BytesIO(file_content))
                st.dataframe(df)
            elif ext in ['mp3', 'wav', 'ogg']:
                st.audio(file_content, format=f'audio/{ext}')
            elif ext in ['mp4', 'mov', 'avi', 'webm']:
                st.video(file_content, format=f'video/{ext}')
            else:
                st.download_button(
                    label=f"Descargar {filename}",
                    data=file_content,
                    file_name=filename
                )
        else:
            st.markdown(part, unsafe_allow_html=True)

# Inicialización del estado de sesión (unchanged)
if "generated" not in st.session_state:
    st.session_state["generated"] = False
if "process_completed" not in st.session_state:
    st.session_state["process_completed"] = False
if "running" not in st.session_state:
    st.session_state["running"] = False
if "reports" not in st.session_state:
    st.session_state["reports"] = []
if "current_code" not in st.session_state:
    st.session_state["current_code"] = ""
if "input_files" not in st.session_state:
    st.session_state["input_files"] = {}
if "docker_initialized" not in st.session_state:
    st.session_state["docker_initialized"] = False
if "all_files" not in st.session_state:
    st.session_state["all_files"] = {}
if "generated_files" not in st.session_state:
    st.session_state["generated_files"] = {}

st.markdown("Genera y refina código Python ejecutado en Docker. Visualiza resultados en Markdown, accede al directorio completo y descarga todo.")

# Bloque de entrada inicial (unchanged)
if not st.session_state["generated"]:
    with st.expander("Instrucciones y Archivos Adjuntos", expanded=True):
        prompt_initial = st.text_area("Instrucción (prompt)", key="prompt_initial", placeholder="Ejemplo: Analiza ventas desde un Excel y crea un gráfico de barras.")
        uploaded_files = st.file_uploader("Sube archivos (opcional)", accept_multiple_files=True, key="uploaded_files")
    if st.button("Generar y Ejecutar Código"):
        if not prompt_initial.strip():
            st.error("Ingresa una instrucción antes de generar.")
        else:
            st.session_state["generated"] = True
            st.session_state["running"] = True
            input_files = {}
            resumen_archivos = ""
            for file in uploaded_files or []:
                file.seek(0)
                try:
                    if file.name.lower().endswith(".csv"):
                        df = pd.read_csv(file)
                        resumen = df.head().to_string()
                        resumen_archivos += f"\nArchivo {file.name} (CSV):\n```\n{resumen}\n```"
                        file.seek(0)
                        input_files[file.name] = file.read()
                    elif file.name.lower().endswith((".xlsx", ".xls")):
                        df = pd.read_excel(file)
                        resumen = df.head().to_string()
                        resumen_archivos += f"\nArchivo {file.name} (Excel):\n```\n{resumen}\n```"
                        file.seek(0)
                        input_files[file.name] = file.read()
                    else:
                        content = file.read()
                        input_files[file.name] = content
                        resumen_archivos += f"\nArchivo {file.name}: Adjunto.\n"
                except Exception as e:
                    resumen_archivos += f"\nError procesando {file.name}: {e}\n"
            st.session_state["input_files"] = input_files
            st.session_state["resumen_archivos"] = resumen_archivos

# Bloque de proceso de generación (unchanged except for prompt adjustment)
if st.session_state["generated"] and not st.session_state["process_completed"]:
    status_container = st.empty()
    error_container = st.empty()
    progress_bar = st.progress(0)
    error_history = []

    try:
        update_status(status_container, "Inicializando imagen Docker...", progress_bar, 5)
        if not st.session_state["docker_initialized"]:
            init_message = initialize_docker_image()
            st.session_state["docker_initialized"] = True
            update_status(status_container, init_message, progress_bar, 10)
        else:
            update_status(status_container, "Imagen Docker ya inicializada.", progress_bar, 10)

        update_status(status_container, "Procesando archivos adjuntos...", progress_bar, 15)
        resumen_archivos = st.session_state.get("resumen_archivos", "")

        update_status(status_container, "Generando cadena de pensamiento...", progress_bar, 20)
        prompt_initial = st.session_state["prompt_initial"]
        thought_chain_code = generate_thought_chain(
            f"Instrucción: {prompt_initial}\nArchivos adjuntos:\n{resumen_archivos or 'Ninguno.'}",
            cot_iterations,
            model_name=selected_model
        )

        update_status(status_container, "Generando código con Gemini...", progress_bar, 25)
        prompt_code = (
            f"{thought_chain_code}\n\n"
            "Genera código Python completo para cumplir la instrucción:\n"
            f"- Instrucción: {prompt_initial}\n"
            f"- Archivos: {resumen_archivos or 'Ninguno.'}\n"
            "**Requisitos:**\n"
            "- Código en un solo archivo Python, ejecutable en Docker.\n"
            "- Generar archivos (visualizaciones PNG/JPG/GIF, datos CSV/Excel, audios MP3/WAV, etc.) en la raíz del directorio de trabajo (/app), sin subdirectorios.\n"
            "- Incluir manejo robusto de errores y comentarios en español.\n"
            "- Adaptar la complejidad al modo seleccionado.\n"
            "- Optimizar rendimiento y seguridad.\n"
            "- Asegurar que se generen resultados visibles según la instrucción."
        )
        code_generated = generate_code(prompt_code, model_name=selected_model)
        current_code = clean_code(code_generated)

        syntax_ok, syntax_error = check_syntax(current_code)
        if not syntax_ok:
            update_status(status_container, "Corrigiendo sintaxis del código...", progress_bar, 30)
            thought_chain_error = generate_thought_chain(
                f"Error de sintaxis detectado:\n```python\n{current_code}\n```\nError: {syntax_error}",
                cot_iterations,
                model_name=selected_model
            )
            current_code = refine_code(current_code, {"stderr": syntax_error}, thought_chain_error, error_history, model_name=selected_model)
            current_code = clean_code(current_code)

        for i in range(revision_iterations):
            update_status(status_container, f"Revisando código (iteración {i+1})...", progress_bar, 35 + i * 5)
            review = review_code(current_code, model_name=selected_model)
            update_status(status_container, f"Mejorando código (iteración {i+1})...", progress_bar, 40 + i * 5)
            current_code = improve_code_based_on_review(current_code, review, model_name=selected_model)
            current_code = clean_code(current_code)
        st.session_state["current_code"] = current_code

        update_status(status_container, "Generando dependencias con pipreqs y análisis estático...", progress_bar, 45)
        temp_dir = tempfile.gettempdir()
        initial_requirements = generate_requirements_file(current_code, temp_dir)
        initial_requirements = clean_code(initial_requirements)

        update_status(status_container, "Refinando dependencias con Gemini...", progress_bar, 47)
        dependencies = refine_requirements_with_gemini(initial_requirements, current_code, model_name=selected_model)
        dependencies = clean_code(dependencies)

        if not dependencies:
            update_status(status_container, "No se requieren dependencias adicionales.", progress_bar, 50)
        else:
            update_status(status_container, f"Dependencias refinadas:\n```\n{dependencies}\n```", progress_bar, 50)

        max_attempts = 10
        max_code_corrections = 3
        code_correction_attempts = 0

        for attempt in range(max_attempts):
            update_status(status_container, f"Ejecutando en Docker (intento {attempt + 1}/{max_attempts})...", progress_bar, 55 + attempt * 5)
            outputs = execute_code_in_docker(current_code, st.session_state["input_files"], dependencies)
            status, msg = validate_execution(outputs, model_name=selected_model)

            if status == "OK":
                break

            error_history.append(f"Intento {attempt + 1}: {msg}\nSalida: {outputs.get('stdout', '')}\nError: {outputs.get('stderr', '')}")
            display_error(error_container, msg, f"STDOUT:\n{outputs.get('stdout', '')}\nSTDERR:\n{outputs.get('stderr', '')}")

            stderr = outputs.get("stderr", "")
            missing_modules = re.findall(r"ModuleNotFoundError: No module named '(.+?)'", stderr)

            if missing_modules and attempt < max_attempts - 1:
                update_status(status_container, "Detectando y agregando dependencias faltantes...", progress_bar, 60 + attempt * 5)
                existing_deps = set(dependencies.splitlines())
                for module in missing_modules:
                    if module not in existing_deps:
                        existing_deps.add(module)
                        st.info(f"Dependencia faltante detectada: '{module}'. Agregada a requirements.txt.")
                dependencies = "\n".join(sorted(existing_deps))
                dependencies = clean_code(dependencies)
                thought_chain_deps = generate_thought_chain(
                    f"Error de ejecución:\n{stderr}\nDependencias actuales:\n{dependencies}",
                    cot_iterations,
                    model_name=selected_model
                )
                dependencies = refine_requirements_with_gemini(dependencies, current_code, model_name=selected_model, error_info=stderr)
                update_status(status_container, f"Dependencias actualizadas:\n```\n{dependencies}\n```", progress_bar, 65 + attempt * 5)
            elif status in ["CODE", "BOTH"] and code_correction_attempts < max_code_corrections:
                update_status(status_container, "Intentando corregir el código...", progress_bar, 70 + attempt * 5)
                thought_chain_error = generate_thought_chain(
                    f"Error en la ejecución:\n```python\n{current_code}\n```\nSalida: {outputs.get('stdout', '')}\nError: {outputs.get('stderr', '')}",
                    cot_iterations,
                    model_name=selected_model
                )
                current_code = refine_code(current_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                current_code = clean_code(current_code)
                code_correction_attempts += 1
                st.session_state["current_code"] = current_code
                attempt = -1
            elif status == "UNKNOWN" and code_correction_attempts < max_code_corrections:
                update_status(status_container, "Intentando corrección genérica por error desconocido...", progress_bar, 70 + attempt * 5)
                thought_chain_error = generate_thought_chain(
                    f"Error desconocido en la ejecución:\n```python\n{current_code}\n```\nSalida: {outputs.get('stdout', '')}\nError: {outputs.get('stderr', '')}",
                    cot_iterations,
                    model_name=selected_model
                )
                current_code = refine_code(current_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                current_code = clean_code(current_code)
                code_correction_attempts += 1
                st.session_state["current_code"] = current_code
                attempt = -1
            else:
                break

        if status == "OK":
            st.session_state["all_files"] = outputs.get("all_files", {})
            st.session_state["generated_files"] = outputs.get("generated_files", {})

            update_status(status_container, "Generando reporte Markdown...", progress_bar, 85)
            thought_chain_report = generate_thought_chain(
                f"Resultados de ejecución:\nSTDOUT:\n```\n{outputs.get('stdout', '')}\n```\nSTDERR:\n```\n{outputs.get('stderr', '')}\n```\nArchivos generados:\n{list(st.session_state['generated_files'].keys())}",
                cot_iterations,
                model_name=selected_model
            )
            image_files = [f for f in st.session_state["generated_files"].keys() if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
            data_files = [f for f in st.session_state["generated_files"].keys() if f.lower().endswith((".csv", ".xlsx", ".xls"))]
            audio_files = [f for f in st.session_state["generated_files"].keys() if f.lower().endswith((".mp3", ".wav", ".ogg"))]
            md_report = generate_markdown_report(
                outputs.get("stdout", ""), outputs.get("stderr", ""),
                image_files, data_files + audio_files, thought_chain_report, model_name=selected_model
            )

            for i in range(revision_iterations):
                update_status(status_container, f"Revisando reporte (iteración {i+1})...", progress_bar, 90 + i * 2)
                review = review_report(md_report, model_name=selected_model)
                md_report = improve_report_based_on_review(md_report, review, model_name=selected_model)

            report_label = f"Reporte v{len(st.session_state['reports']) + 1}"
            st.session_state["reports"].append({"label": report_label, "md_report": md_report, "files": st.session_state["generated_files"]})
            update_status(status_container, "Proceso completado exitosamente.", progress_bar, 100)
            st.session_state["process_completed"] = True
        else:
            display_error(error_container, "No se pudo ejecutar el código tras intentos de corrección.", "\n".join(error_history))

    except Exception as e:
        display_error(error_container, "Error crítico en el proceso.", str(e))
        st.session_state["process_completed"] = False
    finally:
        st.session_state["running"] = False

# Bloque de resultados (updated with debugging section)
if st.session_state.get("generated", False) and st.session_state.get("process_completed", False):
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("Entorno Virtual")
        if st.session_state["all_files"]:
            st.write("#### Directorio `/app` ejecutado en Docker:")
            display_generated_files(st.session_state["all_files"], st.container())
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for filename, content in st.session_state["all_files"].items():
                    zip_file.writestr(filename, content)
            zip_buffer.seek(0)
            st.download_button(
                label="Descargar Directorio Completo como ZIP",
                data=zip_buffer,
                file_name="directorio_app.zip",
                mime="application/zip"
            )

    with col2:
        st.subheader("Reportes en Markdown")
        ordered_reports = st.session_state["reports"][::-1]
        report_tabs = st.tabs([report["label"] for report in ordered_reports])
        for idx, tab in enumerate(report_tabs):
            with tab:
                report = ordered_reports[idx]
                render_markdown_with_visualizations(report["md_report"], report["files"])
                with st.expander("Detalles técnicos"):
                    st.write("### Markdown crudo")
                    st.code(report["md_report"], language="markdown")
                    st.write("### Archivos generados")
                    for fname in report["files"].keys():
                        st.write(f"- {fname}")
                pdf_bytes = convert_markdown_to_pdf(report["md_report"], report["files"])
                st.download_button(
                    "Descargar Reporte como PDF",
                    data=pdf_bytes,
                    file_name=f"{report['label']}.pdf",
                    mime="application/pdf"
                )

    st.markdown("### Ingresa mejoras")
    prompt_improve = st.text_area("Instrucción / Mejora", key="prompt_improve", placeholder="Ejemplo: Añade un gráfico de líneas al análisis.")
    improvement_file = st.file_uploader("Adjunta archivo (opcional)", key="improve_file")
    if st.button("Aplicar Mejora"):
        if not prompt_improve.strip():
            st.error("Ingresa instrucciones para la mejora.")
        else:
            status_container = st.empty()
            error_container = st.empty()
            progress_bar = st.progress(0)
            error_history = []
            try:
                update_status(status_container, "Aplicando mejora al código...", progress_bar, 10)
                current_code = st.session_state["current_code"]
                new_code = handle_new_improvement(
                    current_code, prompt_improve, improvement_file,
                    selected_model=selected_model, cot_iterations=cot_iterations
                )
                new_code = clean_code(new_code)
                st.session_state["current_code"] = new_code

                update_status(status_container, "Generando dependencias con pipreqs y análisis estático...", progress_bar, 20)
                initial_requirements = generate_requirements_file(new_code, tempfile.gettempdir())
                initial_requirements = clean_code(initial_requirements)

                update_status(status_container, "Refinando dependencias con Gemini...", progress_bar, 22)
                dependencies = refine_requirements_with_gemini(initial_requirements, new_code, model_name=selected_model)
                dependencies = clean_code(dependencies)

                if not dependencies:
                    update_status(status_container, "No se requieren dependencias adicionales.", progress_bar, 25)
                else:
                    update_status(status_container, f"Dependencias refinadas:\n```\n{dependencies}\n```", progress_bar, 25)

                max_attempts = 10
                max_code_corrections = 3
                code_correction_attempts = 0

                for attempt in range(max_attempts):
                    update_status(status_container, f"Ejecutando mejora en Docker (intento {attempt + 1}/{max_attempts})...", progress_bar, 30 + attempt * 10)
                    outputs = execute_code_in_docker(new_code, st.session_state["input_files"], dependencies)
                    status, msg = validate_execution(outputs, model_name=selected_model)

                    if status == "OK":
                        break

                    error_history.append(f"Intento {attempt + 1}: {msg}\nSalida: {outputs.get('stdout', '')}\nError: {outputs.get('stderr', '')}")
                    display_error(error_container, msg, f"STDOUT:\n{outputs.get('stdout', '')}\nSTDERR:\n{outputs.get('stderr', '')}")

                    stderr = outputs.get("stderr", "")
                    missing_modules = re.findall(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if missing_modules and attempt < max_attempts - 1:
                        update_status(status_container, "Detectando y agregando dependencias faltantes...", progress_bar, 35 + attempt * 10)
                        existing_deps = set(dependencies.splitlines())
                        for module in missing_modules:
                            if module not in existing_deps:
                                existing_deps.add(module)
                                st.info(f"Dependencia faltante detectada: '{module}'. Agregada a requirements.txt.")
                        dependencies = "\n".join(sorted(existing_deps))
                        dependencies = clean_code(dependencies)
                        thought_chain_deps = generate_thought_chain(
                            f"Error de ejecución:\n{stderr}\nDependencias actuales:\n{dependencies}",
                            cot_iterations,
                            model_name=selected_model
                        )
                        dependencies = refine_requirements_with_gemini(dependencies, new_code, model_name=selected_model, error_info=stderr)
                        update_status(status_container, f"Dependencias actualizadas:\n```\n{dependencies}\n```", progress_bar, 40 + attempt * 10)
                    elif status in ["CODE", "BOTH"] and code_correction_attempts < max_code_corrections:
                        update_status(status_container, "Intentando corregir el código...", progress_bar, 45 + attempt * 10)
                        thought_chain_error = generate_thought_chain(
                            f"Error en la ejecución:\n```python\n{new_code}\n```\nSalida: {outputs.get('stdout', '')}\nError: {outputs.get('stderr', '')}",
                            cot_iterations,
                            model_name=selected_model
                        )
                        new_code = refine_code(new_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                        new_code = clean_code(new_code)
                        code_correction_attempts += 1
                        st.session_state["current_code"] = new_code
                        attempt = -1
                    elif status == "UNKNOWN" and code_correction_attempts < max_code_corrections:
                        update_status(status_container, "Intentando corrección genérica por error desconocido...", progress_bar, 45 + attempt * 10)
                        thought_chain_error = generate_thought_chain(
                            f"Error desconocido en la ejecución:\n```python\n{new_code}\n```\nSalida: {outputs.get('stdout', '')}\nError: {outputs.get('stderr', '')}",
                            cot_iterations,
                            model_name=selected_model
                        )
                        new_code = refine_code(new_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                        new_code = clean_code(new_code)
                        code_correction_attempts += 1
                        st.session_state["current_code"] = new_code
                        attempt = -1
                    else:
                        break

                if status == "OK":
                    st.session_state["all_files"] = outputs.get("all_files", {})
                    st.session_state["generated_files"] = outputs.get("generated_files", {})
                    update_status(status_container, "Generando reporte de mejora...", progress_bar, 70)
                    thought_chain_report = generate_thought_chain(
                        f"Resultados de la mejora:\nSTDOUT:\n```\n{outputs.get('stdout', '')}\n```\nSTDERR:\n```\n{outputs.get('stderr', '')}\n```\nArchivos generados:\n{list(st.session_state['generated_files'].keys())}",
                        cot_iterations,
                        model_name=selected_model
                    )
                    image_files = [f for f in st.session_state["generated_files"].keys() if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
                    data_files = [f for f in st.session_state["generated_files"].keys() if f.lower().endswith((".csv", ".xlsx", ".xls"))]
                    audio_files = [f for f in st.session_state["generated_files"].keys() if f.lower().endswith((".mp3", ".wav", ".ogg"))]
                    md_report = generate_markdown_report(
                        outputs.get("stdout", ""), outputs.get("stderr", ""),
                        image_files, data_files + audio_files, thought_chain_report, model_name=selected_model
                    )
                    for i in range(revision_iterations):
                        update_status(status_container, f"Revisando reporte (iteración {i+1})...", progress_bar, 85 + i * 2)
                        review = review_report(md_report, model_name=selected_model)
                        md_report = improve_report_based_on_review(md_report, review, model_name=selected_model)
                    new_report_label = f"Reporte v{len(st.session_state['reports']) + 1}"
                    st.session_state["reports"].append({"label": new_report_label, "md_report": md_report, "files": st.session_state["generated_files"]})
                    update_status(status_container, "Mejora aplicada exitosamente.", progress_bar, 100)
                else:
                    display_error(error_container, "No se ejecutó la mejora tras intentos de corrección.", "\n".join(error_history))

            except Exception as e:
                display_error(error_container, "Error al aplicar la mejora.", str(e))

# Botón de reinicio (unchanged)
if st.button("Nuevo Prompt (Reiniciar)"):
    keys_to_keep = ["docker_initialized"]
    for key in list(st.session_state.keys()):
        if key not in keys_to_keep:
            del st.session_state[key]
    st.experimental_rerun()