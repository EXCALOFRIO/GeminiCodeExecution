# backend.py
import os
import re
import streamlit as st
import zipfile
import subprocess
import tempfile
import hashlib
import base64
from io import BytesIO
from xhtml2pdf import pisa
from difflib import get_close_matches
import markdown
import pandas as pd
from gemini_client import (
    generate_code, refine_code, get_dependencies, refine_dependencies,
    improve_code, generate_markdown_report, generate_thought_chain,
    review_code, improve_code_based_on_review, review_report,
    improve_report_based_on_review, classify_execution_error,
    refine_requirements_with_gemini, get_code_generation_prompt,
    get_code_refinement_prompt, get_dependencies_refinement_prompt,
    get_improvement_prompt
)
from code_formatter import clean_code
from docker_executor import initialize_docker_image, prebuild_common_image, execute_code_in_docker
from file_formatter import format_generated_file
from utils import lint_code, check_syntax, generate_requirements_file, auto_correct_code

# --- Helper Functions ---
def get_file_icon(filename):
    """Returns an icon based on the file extension."""
    ext = filename.lower().split('.')[-1]
    icons = {
        'csv': "📄", 'xlsx': "📊", 'xls': "📊", 'png': "🖼️", 'jpg': "🖼️",
        'jpeg': "🖼️", 'gif': "🖼️", 'md': "📝", 'html': "📝", 'txt': "📄",
        'mp4': "🎞️", 'mov': "🎞️", 'avi': "🎞️", 'webm': "🎞️", 'pdf': "📕",
        'mp3': "🎵", 'wav': "🎵", 'ogg': "🎵", 'py': "🐍"
    }
    return icons.get(ext, "📁")

def display_generated_files(generated_files, container):
    """Displays generated files in a Streamlit container with download buttons."""
    with container:
        if generated_files:
            container.markdown("#### Archivos")
            for fname, fcontent in generated_files.items():
                icon = get_file_icon(fname)
                container.write(f"{icon} **{fname}**")
                st.download_button(label="Descargar", data=fcontent, file_name=fname, key=f"btn_{fname}")
        else:
            container.info("No se encontraron archivos.")

def convert_markdown_to_pdf(md_text, files):
    """Converts Markdown text with embedded images to PDF."""
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

def validate_execution(outputs, model_name):
    """Classifies execution output as OK, DEPENDENCY, CODE, BOTH, or UNKNOWN error."""
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
    """Updates the status message and progress bar in the Streamlit UI."""
    status_container.markdown(f"<div class='status-container'><strong>Estado:</strong> {message}</div>", unsafe_allow_html=True)
    progress_bar.progress(min(progress, 100))

def display_error(error_container, message, details=None):
    """Displays an error message in a styled container in the Streamlit UI."""
    content = f"<div class='error-container'><strong>Error:</strong> {message}"
    if details:
        content += f"<br><strong>Detalles:</strong> <pre>{details}</pre>"
    content += "</div>"
    error_container.markdown(content, unsafe_allow_html=True)

def handle_new_improvement(current_code, prompt_text, attached_file=None, selected_model="gemini-2.0-flash-001", cot_iterations=0):
    """Handles code improvement based on a new prompt and optional file."""
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
    prompt = get_improvement_prompt(current_code, prompt_text, file_info, thought_chain_improve)
    if len(prompt) > 50000:
        st.warning("Prompt de mejora demasiado largo. Resumiendo contenido.")
        file_info = file_info[:1000]
        prompt = get_improvement_prompt(current_code, prompt_text, file_info, thought_chain_improve[:2000])
    new_code = improve_code(current_code, prompt, thought_chain_improve, model_name=selected_model)
    return clean_code(new_code)

def find_best_match(filename, files, cutoff=0.6):
    """Finds the best matching filename in a list of files."""
    matches = get_close_matches(filename, files.keys(), n=1, cutoff=cutoff)
    return matches[0] if matches else None

def render_markdown_with_visualizations(md_report, files):
    """Renders a Markdown report with visualizations (images, dataframes, audio, video)."""
    pattern = r'\{\{visualize_(.+?)\}\}'
    parts = re.split(pattern, md_report)
    for i in range(0, len(parts), 2):
        if i < len(parts) and parts[i].strip():
            st.markdown(parts[i], unsafe_allow_html=True)
        if i + 1 < len(parts):
            filename = parts[i + 1].strip()
            if filename:
                if filename in files:
                    file_content = files[filename]
                else:
                    best_match = find_best_match(filename, files)
                    if best_match:
                        file_content = files[best_match]
                        st.warning(f"Archivo '{filename}' no encontrado, usando '{best_match}'.")
                    else:
                        st.error(f"Archivo no encontrado: {filename}. Disponibles: {list(files.keys())}")
                        continue
                ext = filename.lower().split('.')[-1]
                if ext in ['png', 'jpg', 'jpeg', 'gif']:
                    st.image(file_content, caption=f"Figura: {filename}", use_container_width=True)
                elif ext == 'csv':
                    df = pd.read_csv(BytesIO(file_content))
                    st.dataframe(df, use_container_width=True)
                elif ext in ['xlsx', 'xls']:
                    df = pd.read_excel(BytesIO(file_content))
                    st.dataframe(df, use_container_width=True)
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

# --- Core Execution Functions ---
def process_uploaded_files(uploaded_files):
    """Processes uploaded files, reads their content and generates a summary."""
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
    return input_files, resumen_archivos

def generate_code_and_dependencies(prompt_initial, resumen_archivos, cot_iterations, selected_model, error_history):
    """Generates initial code and infers dependencies."""
    thought_chain_code = generate_thought_chain(
        f"Instrucción: {prompt_initial}\nArchivos adjuntos:\n{resumen_archivos or 'Ninguno.'}",
        cot_iterations,
        model_name=selected_model
    )
    prompt_code = get_code_generation_prompt(thought_chain_code, prompt_initial, resumen_archivos)
    if len(prompt_code) > 50000:
        prompt_code = get_code_generation_prompt(thought_chain_code[:2000], prompt_initial, resumen_archivos[:1000])
    code_generated = generate_code(prompt_code, model_name=selected_model)
    current_code = clean_code(code_generated)
    current_code = auto_correct_code(current_code) # Auto-correct syntax errors

    temp_dir = tempfile.gettempdir()
    lint_ok, lint_output = lint_code(current_code, temp_dir)
    if not lint_ok:
        thought_chain_lint = generate_thought_chain(
            f"Problemas de linting:\n```python\n{current_code}\n```\nSalida: {lint_output}",
            cot_iterations,
            model_name=selected_model
        )
        prompt_refine = get_code_refinement_prompt(current_code, {"stderr": lint_output[:1000]}, thought_chain_lint, error_history)
        current_code = refine_code(current_code, {"stderr": lint_output[:1000]}, thought_chain_lint, error_history[-3:], model_name=selected_model)
        current_code = clean_code(current_code)

    initial_requirements = generate_requirements_file(current_code, temp_dir)
    dependencies = refine_requirements_with_gemini(initial_requirements, current_code, model_name=selected_model)
    return current_code, dependencies

def execute_and_fix_code(current_code, input_files, dependencies, status_container, error_container, progress_bar, selected_model, cot_iterations, revision_iterations, error_history):
    """Executes code in Docker, handles errors, and refines code/dependencies iteratively."""
    max_attempts = 10
    max_code_corrections = 5
    code_correction_attempts = 0
    dependency_correction_attempts = 0

    for attempt in range(max_attempts):
        update_status(status_container, f"Ejecutando en Docker (intento {attempt + 1}/{max_attempts})...", progress_bar, 55 + attempt * 4)
        outputs = execute_code_in_docker(current_code, input_files, dependencies)
        status, msg = validate_execution(outputs, model_name=selected_model)

        if status == "OK":
            update_status(status_container, "Ejecución exitosa.", progress_bar, 60 + attempt * 4)
            break

        stdout_truncated = outputs.get("stdout", "")[:1000]
        stderr_truncated = outputs.get("stderr", "")[:1000]
        error_history.append(f"Intento {attempt + 1}: {msg}\nSalida: {stdout_truncated}\nError: {stderr_truncated}")
        display_error(error_container, msg, f"STDOUT:\n{stdout_truncated}\nSTDERR:\n{stderr_truncated}")

        stderr = outputs.get("stderr", "")
        missing_modules = re.findall(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
        if missing_modules and dependency_correction_attempts < max_attempts:
            update_status(status_container, "Agregando dependencias faltantes...", progress_bar, 60 + attempt * 4)
            existing_deps = set(dependencies.splitlines())
            for module in missing_modules:
                if module not in existing_deps:
                    existing_deps.add(module)
            dependencies = "\n".join(sorted(existing_deps))
            dependencies = clean_code(dependencies)
            thought_chain_deps = generate_thought_chain(
                f"Error:\n{stderr[:1000]}\nDependencias actuales:\n{dependencies}",
                cot_iterations,
                model_name=selected_model
            )
            prompt_refine_deps = get_dependencies_refinement_prompt(dependencies, current_code, outputs, thought_chain_deps, error_history)
            dependencies = refine_dependencies(dependencies, current_code, outputs, thought_chain_deps, error_history[-3:], model_name=selected_model)
            dependency_correction_attempts += 1
        elif status in ["CODE", "BOTH"] and code_correction_attempts < max_code_corrections:
            update_status(status_container, "Corrigiendo código...", progress_bar, 65 + attempt * 4)
            thought_chain_error = generate_thought_chain(
                f"Error:\n```python\n{current_code}\n```\nSalida: {stdout_truncated}\nError: {stderr_truncated}",
                cot_iterations,
                model_name=selected_model
            )
            prompt_refine_code = get_code_refinement_prompt(current_code, outputs, thought_chain_error, error_history)
            current_code = refine_code(current_code, outputs, thought_chain_error, error_history[-3:], model_name=selected_model)
            current_code = clean_code(current_code)
            code_correction_attempts += 1
        else:
            update_status(status_container, f"Corrección fallida en intento {attempt + 1}. Continuando...", progress_bar, 60 + attempt * 4)
        if status == "OK":
            break # Exit loop if execution is successful

    return status, msg, outputs, current_code, dependencies, error_history

def generate_and_display_report(outputs, generated_files, status_container, progress_bar, selected_model, cot_iterations, revision_iterations, reports):
    """Generates a Markdown report and handles report revisions."""
    update_status(status_container, "Generando reporte...", progress_bar, 85)
    thought_chain_report = generate_thought_chain(
        f"Resultados:\nSTDOUT:\n```\n{outputs.get('stdout', '')[:1000]}\n```\nSTDERR:\n```\n{outputs.get('stderr', '')[:1000]}\n```\nArchivos:\n{list(generated_files.keys())}",
        cot_iterations,
        model_name=selected_model
    )
    image_files = [f for f in generated_files.keys() if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    data_files = [f for f in generated_files.keys() if f.lower().endswith((".csv", ".xlsx", ".xls"))]
    audio_files = [f for f in generated_files.keys() if f.lower().endswith((".mp3", ".wav", ".ogg"))]
    md_report = generate_markdown_report(
        outputs.get("stdout", ""), outputs.get("stderr", ""),
        image_files, data_files + audio_files, thought_chain_report, model_name=selected_model
    )
    for i in range(revision_iterations):
        update_status(status_container, f"Revisando reporte (iteración {i+1})...", progress_bar, 90 + i * 2)
        review = review_report(md_report, model_name=selected_model)
        md_report = improve_report_based_on_review(md_report, review, model_name=selected_model)
    report_label = f"Reporte v{len(reports) + 1}"
    reports.append({"label": report_label, "md_report": md_report, "files": generated_files})
    update_status(status_container, "Proceso completado.", progress_bar, 100)
    return reports

def improve_existing_code(current_code, prompt_improve, improvement_file, selected_model, cot_iterations, error_history):
    """Improves the existing code based on a new prompt and optional file."""
    new_code = handle_new_improvement(
        current_code, prompt_improve, improvement_file,
        selected_model=selected_model, cot_iterations=cot_iterations
    )
    new_code = auto_correct_code(new_code) # Auto-correct syntax errors

    temp_dir = tempfile.gettempdir()
    lint_ok, lint_output = lint_code(new_code, temp_dir)
    if not lint_ok:
        thought_chain_lint = generate_thought_chain(
            f"Problemas de linting:\n```python\n{new_code}\n```\nSalida: {lint_output}",
            cot_iterations,
            model_name=selected_model
        )
        prompt_refine = get_code_refinement_prompt(new_code, {"stderr": lint_output[:1000]}, thought_chain_lint, error_history)
        new_code = refine_code(new_code, {"stderr": lint_output[:1000]}, thought_chain_lint, error_history[-3:], model_name=selected_model)
        new_code = clean_code(new_code)
    return new_code

def execute_improved_code(new_code, input_files, dependencies, status_container, error_container, progress_bar, selected_model, cot_iterations, revision_iterations, error_history):
    """Executes improved code in Docker and handles errors, similar to initial execution."""
    max_attempts = 10
    max_code_corrections = 5
    code_correction_attempts = 0
    dependency_correction_attempts = 0

    for attempt in range(max_attempts):
        update_status(status_container, f"Ejecutando mejora (intento {attempt + 1}/{max_attempts})...", progress_bar, 30 + attempt * 7)
        outputs = execute_code_in_docker(new_code, input_files, dependencies)
        status, msg = validate_execution(outputs, model_name=selected_model)

        if status == "OK":
            update_status(status_container, "Mejora ejecutada exitosamente.", progress_bar, 35 + attempt * 7)
            break

        stdout_truncated = outputs.get("stdout", "")[:1000]
        stderr_truncated = outputs.get("stderr", "")[:1000]
        error_history.append(f"Intento {attempt + 1}: {msg}\nSalida: {stdout_truncated}\nError: {stderr_truncated}")
        display_error(error_container, msg, f"STDOUT:\n{stdout_truncated}\nSTDERR:\n{stderr_truncated}")

        stderr = outputs.get("stderr", "")
        missing_modules = re.findall(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
        if missing_modules and dependency_correction_attempts < max_attempts:
            update_status(status_container, "Agregando dependencias faltantes...", progress_bar, 35 + attempt * 7)
            existing_deps = set(dependencies.splitlines())
            for module in missing_modules:
                if module not in existing_deps:
                    existing_deps.add(module)
            dependencies = "\n".join(sorted(existing_deps))
            dependencies = clean_code(dependencies)
            thought_chain_deps = generate_thought_chain(
                f"Error:\n{stderr[:1000]}\nDependencias actuales:\n{dependencies}",
                cot_iterations,
                model_name=selected_model
            )
            prompt_refine_deps = get_dependencies_refinement_prompt(dependencies, new_code, outputs, thought_chain_deps, error_history)
            dependencies = refine_dependencies(dependencies, new_code, outputs, thought_chain_deps, error_history[-3:], model_name=selected_model)
            dependency_correction_attempts += 1
        elif status in ["CODE", "BOTH"] and code_correction_attempts < max_code_corrections:
            update_status(status_container, "Corrigiendo código...", progress_bar, 40 + attempt * 7)
            thought_chain_error = generate_thought_chain(
                f"Error:\n```python\n{new_code}\n```\nSalida: {stdout_truncated}\nError: {stderr_truncated}",
                cot_iterations,
                model_name=selected_model
            )
            prompt_refine_code = get_code_refinement_prompt(new_code, outputs, thought_chain_error, error_history)
            new_code = refine_code(new_code, outputs, thought_chain_error, error_history[-3:], model_name=selected_model)
            new_code = clean_code(new_code)
            code_correction_attempts += 1
        else:
            update_status(status_container, f"Corrección fallida en intento {attempt + 1}. Continuando...", progress_bar, 35 + attempt * 7)
        if status == "OK":
            break # Exit loop if execution is successful

    return status, msg, outputs, new_code, dependencies, error_history

def generate_and_display_improvement_report(outputs, generated_files, status_container, progress_bar, selected_model, cot_iterations, revision_iterations, reports):
    """Generates and displays a report for code improvements, similar to the initial report."""
    update_status(status_container, "Generando reporte de mejora...", progress_bar, 70)
    thought_chain_report = generate_thought_chain(
        f"Resultados:\nSTDOUT:\n```\n{outputs.get('stdout', '')[:1000]}\n```\nSTDERR:\n```\n{outputs.get('stderr', '')[:1000]}\n```\nArchivos:\n{list(generated_files.keys())}",
        cot_iterations,
        model_name=selected_model
    )
    image_files = [f for f in generated_files.keys() if f.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
    data_files = [f for f in generated_files.keys() if f.lower().endswith((".csv", ".xlsx", ".xls"))]
    audio_files = [f for f in generated_files.keys() if f.lower().endswith((".mp3", ".wav", ".ogg"))]
    md_report = generate_markdown_report(
        outputs.get("stdout", ""), outputs.get("stderr", ""),
        image_files, data_files + audio_files, thought_chain_report, model_name=selected_model
    )
    for i in range(revision_iterations):
        update_status(status_container, f"Revisando reporte (iteración {i+1})...", progress_bar, 85 + i * 2)
        review = review_report(md_report, model_name=selected_model)
        md_report = improve_report_based_on_review(md_report, review, model_name=selected_model)
    new_report_label = f"Reporte v{len(reports) + 1}"
    reports.append({"label": new_report_label, "md_report": md_report, "files": generated_files})
    update_status(status_container, "Mejora aplicada.", progress_bar, 100)
    return reports

# --- Docker Initialization ---
def initialize_docker_environment():
    """Initializes Docker environment and pre-builds common image if not already done."""
    init_message = "Inicializando imágenes Docker..."
    if not st.session_state.get("docker_initialized", False):
        init_message = initialize_docker_image()
        prebuild_common_image()
        st.session_state["docker_initialized"] = True
    else:
        init_message = "Imágenes Docker ya inicializadas."
    return init_message