import pandas as pd
import base64
import re
from difflib import get_close_matches
from io import BytesIO
from fpdf import FPDF, HTMLMixin
from unidecode import unidecode  # Para manejar Unicode
import markdown  # Para convertir Markdown a HTML

from gemini_client import (
    generate_code,
    refine_code,
    get_dependencies,
    refine_dependencies,
    improve_code,
    generate_markdown_report,
    generate_thought_chain,
    review_code,
    improve_code_based_on_review,
    review_report,
    improve_report_based_on_review,
    classify_execution_error  # Para clasificación de errores
)
from code_formatter import clean_code
from docker_executor import execute_code_in_docker

import streamlit as st
# FIRST STREAMLIT COMMAND - Must come before any other st.* calls
st.set_page_config(page_title="AI Code Docker Executor", layout="wide")

# =============================================================================
# ===================== CONFIGURACIÓN Y ESTILOS PERSONALIZADOS =================
# =============================================================================

# Inyección de CSS para personalizar la apariencia
custom_css = """
<style>
/* Fondo y fuente general */
body {
    background-color: #f5f5f5;
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}
/* Encabezado principal */
h1 {
    color: #333333;
    text-align: center;
}
/* Barra lateral */
.sidebar .sidebar-content {
    background: #ffffff;
    padding: 20px;
    border-radius: 8px;
    box-shadow: 0px 0px 10px rgba(0,0,0,0.1);
}
/* Contenedores principales */
div[data-testid="stHorizontalBlock"] {
    margin-bottom: 20px;
}
/* Estilo para botones de descarga */
.stDownloadButton {
    margin-top: 5px;
}
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

st.title("🚀 AI Code Docker Executor")

# =============================================================================
# ===================== CONFIGURACIÓN DESDE LA BARRA LATERAL ====================
# =============================================================================

st.sidebar.header("Configuración")
nivel_profundidad = st.sidebar.radio(
    "Nivel de Profundidad",
    options=["Poca", "Normal", "Extremo"],
    index=1,
    help="Selecciona el nivel de profundidad para los prompts."
)

if nivel_profundidad == "Poca":
    selected_model = "gemini-2.0-flash-lite-001"
    cot_iterations = 2
    revision_iterations = 2
elif nivel_profundidad == "Normal":
    selected_model = "gemini-2.0-flash-exp"
    cot_iterations = 3
    revision_iterations = 3
else:  # Extremo
    selected_model = "gemini-2.0-flash-thinking-exp-01-21"
    cot_iterations = 3
    revision_iterations = 3

st.sidebar.markdown("---")
st.sidebar.info("Esta app genera y refina código Python usando la API de Gemini y lo ejecuta en Docker.")

# =============================================================================
# ===================== FUNCIONES AUXILIARES ====================================
# =============================================================================

def get_file_icon(filename):
    ext = filename.lower().split('.')[-1]
    icons = {
        'csv': "📄", 'xlsx': "📊", 'xls': "📊", 'png': "🖼️", 'jpg': "🖼️",
        'jpeg': "🖼️", 'gif': "🖼️", 'md': "📝", 'html': "📝", 'txt': "📄",
        'mp4': "🎞️", 'mov': "🎞️", 'avi': "🎞️", 'webm': "🎞️", 'pdf': "📕",
        'mp3': "🎵", 'wav': "🎵", 'ogg': "🎵"
    }
    return icons.get(ext, "📁")

def display_generated_files(generated_files, container):
    with container:
        if generated_files:
            st.markdown("### Archivos Generados")
            for fname, fcontent in generated_files.items():
                icon = get_file_icon(fname)
                st.write(f"{icon} **{fname}**")
                st.download_button(
                    label="Descargar",
                    data=fcontent,
                    file_name=fname,
                    key=f"btn_{fname}"
                )
        else:
            st.info("No se generaron archivos.")

def convert_markdown_to_pdf(md_text, files):
    """
    Convierte un texto en Markdown a PDF.
    - Interpreta estilos de encabezados, negritas, cursivas, etc.
    - Busca marcadores del tipo {{visualize_nombre.ext}} y, si se trata de una imagen,
      la inserta inline en el PDF usando HTML <img> con datos en base64.
    """
    # Reemplaza los marcadores de imágenes con etiquetas <img>
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
    
    # Convierte el Markdown (con imágenes ya insertadas) a HTML
    html_body = markdown.markdown(md_text_with_images, extensions=['extra'])
    
    # Agrega estilos CSS para mejorar la tipografía y el formato
    html = f"""
    <html>
    <head>
    <style>
    body {{
        font-family: Helvetica, Arial, sans-serif;
        font-size: 12pt;
        line-height: 1.4;
    }}
    h1 {{
        font-size: 24pt;
        font-weight: bold;
        margin-bottom: 10pt;
    }}
    h2 {{
        font-size: 18pt;
        font-weight: bold;
        margin-bottom: 8pt;
    }}
    h3 {{
        font-size: 14pt;
        font-weight: bold;
        margin-bottom: 6pt;
    }}
    p {{
        margin: 5pt 0;
    }}
    em {{
        font-style: italic;
    }}
    strong {{
        font-weight: bold;
    }}
    img {{
        margin: 10pt 0;
    }}
    </style>
    </head>
    <body>
    {html_body}
    </body>
    </html>
    """
    
    # Clase personalizada para PDF con soporte HTML
    class PDF(FPDF, HTMLMixin):
        pass

    pdf = PDF()
    pdf.add_page()
    pdf.write_html(html)
    pdf_bytes = pdf.output(dest='S').encode('latin1')
    return pdf_bytes

def validate_execution(outputs, model_name):
    combined_output = outputs.get("stdout", "") + outputs.get("stderr", "")
    classification = classify_execution_error(combined_output, model_name=model_name)
    if classification == "OK":
        return "OK", "Código ejecutado exitosamente."
    elif classification == "DEPENDENCY":
        return "DEPENDENCY", "Error en dependencias."
    elif classification == "CODE":
        return "CODE", "Error en el código."
    elif classification == "BOTH":
        return "BOTH", "Errores en el código y dependencias."
    else:
        return "UNKNOWN", "Error desconocido."

def update_status(container, message, progress_bar, progress):
    container.markdown(f"<div style='color:#0077cc; font-weight:bold;'>{message}</div>", unsafe_allow_html=True)
    progress_bar.progress(progress)

def handle_new_improvement(current_code, prompt_text, attached_file=None, selected_model="gemini-2.0-flash-001", cot_iterations=0):
    file_info = ""
    if attached_file is not None:
        attached_file.seek(0)
        file_content = attached_file.read().decode("utf-8", errors="ignore")
        file_info = f"\nContenido del archivo adjunto:\n{file_content}\n"
    thought_chain_improve = generate_thought_chain(
        f"Instrucción de mejora: {prompt_text}\nCódigo actual:\n{current_code}\n{file_info}",
        cot_iterations,
        model_name=selected_model
    )
    full_prompt = (
        f"{thought_chain_improve}\n\n"
        "Con base en el análisis anterior, realiza las siguientes mejoras solicitadas en el código Python:\n"
        f"{prompt_text}\n"
        f"{file_info}\n"
        "**IMPORTANTE**: El código debe estar en un solo archivo Python y generar archivos (imágenes, CSV, etc.) en la raíz del proyecto.\n"
        "Devuelve el código completo y funcional con las mejoras integradas."
    )
    new_code = improve_code(current_code, full_prompt, thought_chain_improve, model_name=selected_model)
    new_code = clean_code(new_code)
    return new_code

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
                else:
                    st.error(f"Archivo no encontrado: {filename}")
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

# =============================================================================
# ===================== INICIALIZACIÓN DEL ESTADO DE SESSION ==================
# =============================================================================

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

st.markdown(
    "Utiliza esta app para generar y refinar código Python que se ejecuta en un entorno Docker. "
    "La salida se presenta en formato Markdown y podrás descargar los archivos generados."
)

# =============================================================================
# ===================== BLOQUE DE ENTRADA INICIAL =============================
# =============================================================================

if not st.session_state["generated"]:
    with st.expander("Instrucciones y Archivos Adjuntos", expanded=True):
        prompt_initial = st.text_area(
            "Instrucción (prompt)",
            key="prompt_initial",
            placeholder="Ejemplo: Analiza ventas desde un archivo Excel y crea un gráfico de barras comparando ventas por producto."
        )
        uploaded_files = st.file_uploader(
            "Sube uno o varios archivos (opcional)",
            accept_multiple_files=True,
            key="uploaded_files",
            help="Los archivos adjuntos se usarán durante la generación del código."
        )
    if st.button("Generar y Ejecutar Código"):
        if not prompt_initial.strip():
            st.error("Por favor, ingresa una instrucción antes de generar el código.")
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
                        resumen_archivos += f"\nArchivo {file.name}: Adjunto para uso en el código.\n"
                except Exception as e:
                    resumen_archivos += f"\nNo se pudo procesar {file.name}: {e}\n"
            st.session_state["input_files"] = input_files
            st.session_state["resumen_archivos"] = resumen_archivos

# =============================================================================
# ===================== BLOQUE DE PROCESO DE GENERACIÓN ========================
# =============================================================================

if st.session_state["generated"] and not st.session_state["process_completed"]:
    status_container = st.empty()
    progress_bar = st.progress(0)
    error_history = []
    try:
        update_status(status_container, "Procesando archivos adjuntos...", progress_bar, 10)
        resumen_archivos = st.session_state.get("resumen_archivos", "")

        update_status(status_container, "Generando cadena de pensamiento para el código...", progress_bar, 15)
        prompt_initial = st.session_state["prompt_initial"]
        thought_chain_code = generate_thought_chain(
            f"Instrucción del usuario: {prompt_initial}\nInformación de archivos adjuntos: {resumen_archivos if resumen_archivos else 'No hay archivos adjuntos.'}",
            cot_iterations,
            model_name=selected_model
        )

        update_status(status_container, "Generando código con Gemini...", progress_bar, 20)
        prompt_code = (
            f"{thought_chain_code}\n\n"
            "Con base en el análisis anterior, genera código Python completo y funcional para cumplir la instrucción del usuario.\n"
            "**IMPORTANTE**: El código debe estar en un solo archivo Python y generar archivos (imágenes, animaciones, CSV, Excel, etc.) en la raíz del proyecto.\n"
            "- El código debe ser ejecutable en un entorno Docker.\n"
            "- Incluye manejo de errores y lógica adaptable según el modo ('Poca', 'Normal', 'Extremo').\n"
            "Ejemplo:\n"
            "```python\n"
            "modo = 'Normal'  # Puede ser 'Poca', 'Normal' o 'Extremo'\n"
            "if modo == 'Normal':\n"
            "    num_iteraciones = 1\n"
            "elif modo == 'Extremo':\n"
            "    num_iteraciones = 2\n"
            "else:\n"
            "    num_iteraciones = 0\n"
            "```\n"
            "**REITERACIÓN**: Genera archivos de salida en la raíz del proyecto."
        )
        code_generated = generate_code(prompt_code, model_name=selected_model)
        code_generated = clean_code(code_generated)
        current_code = code_generated

        for i in range(revision_iterations):
            update_status(status_container, f"Revisando código (iteración {i+1}/{revision_iterations})...", progress_bar, 25 + i * 5)
            review = review_code(current_code, model_name=selected_model)
            update_status(status_container, f"Mejorando código (iteración {i+1}/{revision_iterations})...", progress_bar, 30 + i * 5)
            current_code = improve_code_based_on_review(current_code, review, model_name=selected_model)
            current_code = clean_code(current_code)
        st.session_state["current_code"] = current_code

        update_status(status_container, "Obteniendo dependencias requeridas...", progress_bar, 40)
        dependencies = get_dependencies(current_code, model_name=selected_model)
        dependencies = clean_code(dependencies)

        max_attempts = 10
        attempt = 1
        success = False
        while attempt <= max_attempts:
            update_status(status_container, f"Ejecutando código en Docker (intento {attempt}/{max_attempts})...", progress_bar, 40 + (attempt - 1) * 10)
            outputs = execute_code_in_docker(current_code, st.session_state["input_files"], dependencies)
            status, msg = validate_execution(outputs, model_name=selected_model)
            print(f"Status: {status}, Message: {msg}")
            if status == "OK":
                success = True
                break
            else:
                error_history.append(f"Intento {attempt}: {msg}")
                error_type = "DEPENDENCY" if status == "DEPENDENCY" else "CODE"
                thought_chain_error = generate_thought_chain(
                    f"Error de tipo '{error_type}' en la ejecución:\nCódigo:\n{current_code}\nSalida:\n{outputs.get('stdout', '')}\n{outputs.get('stderr', '')}\nAnaliza y sugiere solución.",
                    cot_iterations,
                    model_name=selected_model
                )
                if status == "DEPENDENCY":
                    update_status(status_container, "Error en dependencias. Refinando dependencias...", progress_bar, 40 + (attempt - 1) * 10 + 5)
                    new_dependencies = refine_dependencies(dependencies, current_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                    new_dependencies = clean_code(new_dependencies)
                    if new_dependencies.strip() != dependencies.strip():
                        dependencies = new_dependencies
                    else:
                        st.error("No se pudieron resolver las dependencias tras la refinación.")
                        break
                elif status == "CODE":
                    update_status(status_container, "Error en el código. Refinando código...", progress_bar, 40 + (attempt - 1) * 10 + 5)
                    new_code = refine_code(current_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                    new_code = clean_code(new_code)
                    if new_code.strip() != current_code.strip():
                        current_code = new_code
                        st.session_state["current_code"] = new_code
                    else:
                        st.error("No se pudo corregir el código tras la refinación.")
                        break
            attempt += 1

        if success:
            files = outputs.get("files", {})
            st.session_state["files"] = files

            update_status(status_container, "Generando cadena de pensamiento para el reporte...", progress_bar, 85)
            thought_chain_report = generate_thought_chain(
                f"Resultados:\nSTDOUT: {outputs.get('stdout', '')}\nSTDERR: {outputs.get('stderr', '')}\nArchivos: {list(files.keys())}",
                cot_iterations,
                model_name=selected_model
            )

            update_status(status_container, "Generando reporte Markdown...", progress_bar, 90)
            image_files = [fname for fname in files.keys() if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
            data_files = [fname for fname in files.keys() if fname.lower().endswith((".csv", ".xlsx", ".xls"))]
            md_report = generate_markdown_report(
                outputs.get("stdout", ""), outputs.get("stderr", ""), image_files, data_files, thought_chain_report, model_name=selected_model
            )

            for i in range(revision_iterations):
                update_status(status_container, f"Revisando reporte (iteración {i+1}/{revision_iterations})...", progress_bar, 95 + i * 2)
                review = review_report(md_report, model_name=selected_model)
                update_status(status_container, f"Mejorando reporte (iteración {i+1}/{revision_iterations})...", progress_bar, 97 + i * 2)
                md_report = improve_report_based_on_review(md_report, review, model_name=selected_model)

            report_label = f"Reporte v{len(st.session_state['reports']) + 1}"
            st.session_state["reports"].append({"label": report_label, "md_report": md_report, "files": files})

            update_status(status_container, "Proceso completado exitosamente.", progress_bar, 100)
            st.session_state["process_completed"] = True
            st.session_state["running"] = False
        else:
            st.error(f"No se pudo ejecutar el código tras {max_attempts} intentos. Último error: {msg}")
            st.session_state["process_completed"] = False
            st.session_state["running"] = False

    except Exception as e:
        st.error(f"Error durante el proceso: {str(e)}")
        st.session_state["process_completed"] = False
        st.session_state["running"] = False

# =============================================================================
# ===================== BLOQUE DE MEJORAS Y RESULTADOS =========================
# =============================================================================

if st.session_state.get("generated", False) and st.session_state.get("process_completed", False):
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("Archivos Generados")
        display_generated_files(st.session_state["files"], st.container())
    with col2:
        st.subheader("Reportes en Markdown")
        ordered_reports = st.session_state["reports"][::-1]
        report_tabs = st.tabs([report["label"] for report in ordered_reports])
        for idx, tab in enumerate(report_tabs):
            with tab:
                report = ordered_reports[idx]
                render_markdown_with_visualizations(report["md_report"], report["files"])
                # Ahora se pasa también el diccionario de archivos a la función para incrustar imágenes en el PDF
                pdf_bytes = convert_markdown_to_pdf(report["md_report"], report["files"])
                st.download_button("Descargar Reporte como PDF",
                                   data=pdf_bytes,
                                   file_name=f"{report['label']}.pdf",
                                   mime="application/pdf")

    st.markdown("### Ingresa nuevas instrucciones o mejoras")
    prompt_improve = st.text_area(
        "Instrucción / Mejora",
        key="prompt_improve",
        placeholder="Agrega aquí tus comentarios o instrucciones para mejorar la implementación actual."
    )
    improvement_file = st.file_uploader("Adjunta un archivo (opcional)", key="improve_file")
    if st.button("Aplicar Mejora"):
        if not prompt_improve.strip():
            st.error("Por favor, ingresa instrucciones para la mejora.")
        else:
            status_container = st.empty()
            progress_bar = st.progress(0)
            try:
                update_status(status_container, "Aplicando mejora...", progress_bar, 10)
                current_code = st.session_state["current_code"]
                new_code = handle_new_improvement(
                    current_code, prompt_improve, attached_file=improvement_file,
                    selected_model=selected_model, cot_iterations=cot_iterations
                )
                st.session_state["current_code"] = new_code

                update_status(status_container, "Obteniendo dependencias para la nueva versión...", progress_bar, 20)
                dependencies = get_dependencies(new_code, model_name=selected_model)
                dependencies = clean_code(dependencies)

                max_attempts = 5
                attempt = 1
                success = False
                error_history = []
                while attempt <= max_attempts:
                    update_status(status_container, f"Ejecutando nueva versión en Docker (intento {attempt}/{max_attempts})...", progress_bar, 20 + (attempt - 1) * 10)
                    outputs = execute_code_in_docker(new_code, st.session_state["input_files"], dependencies)
                    status, msg = validate_execution(outputs, model_name=selected_model)
                    print(f"Status: {status}, Message: {msg}")
                    if status == "OK":
                        success = True
                        break
                    else:
                        error_history.append(f"Intento {attempt}: {msg}")
                        error_type = "DEPENDENCY" if status == "DEPENDENCY" else "CODE"
                        thought_chain_error = generate_thought_chain(
                            f"Error de tipo '{error_type}' en la ejecución de la mejora:\nCódigo:\n{new_code}\nSalida:\nSTDOUT: {outputs.get('stdout', '')}\nSTDERR: {outputs.get('stderr', '')}\nAnaliza y sugiere solución.",
                            cot_iterations,
                            model_name=selected_model
                        )
                        if status == "DEPENDENCY":
                            update_status(status_container, "Error en dependencias en la mejora. Refinando dependencias...", progress_bar, 20 + (attempt - 1) * 10 + 5)
                            new_dependencies = refine_dependencies(dependencies, new_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                            new_dependencies = clean_code(new_dependencies)
                            if new_dependencies.strip() != dependencies.strip():
                                dependencies = new_dependencies
                            else:
                                st.error("No se pudieron resolver las dependencias tras la refinación.")
                                break
                        elif status == "CODE":
                            update_status(status_container, "Error en el código de la mejora. Refinando código...", progress_bar, 20 + (attempt - 1) * 10 + 5)
                            new_code = refine_code(new_code, outputs, thought_chain_error, error_history, model_name=selected_model)
                            new_code = clean_code(new_code)
                            if new_code.strip() != st.session_state["current_code"].strip():
                                st.session_state["current_code"] = new_code
                            else:
                                st.error("No se pudo corregir el código tras la refinación.")
                                break
                    attempt += 1

                if success:
                    update_status(status_container, "Código mejorado ejecutado correctamente.", progress_bar, 70)
                    files = outputs.get("files", {})
                    st.session_state["files"] = files

                    update_status(status_container, "Generando cadena de pensamiento para el nuevo reporte...", progress_bar, 75)
                    thought_chain_report = generate_thought_chain(
                        f"Resultados de la mejora:\nSTDOUT: {outputs.get('stdout', '')}\nSTDERR: {outputs.get('stderr', '')}\nArchivos: {list(files.keys())}",
                        cot_iterations,
                        model_name=selected_model
                    )

                    update_status(status_container, "Generando nuevo reporte Markdown...", progress_bar, 80)
                    image_files = [fname for fname in files.keys() if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
                    data_files = [fname for fname in files.keys() if fname.lower().endswith((".csv", ".xlsx", ".xls"))]
                    md_report = generate_markdown_report(
                        outputs.get("stdout", ""), outputs.get("stderr", ""), image_files, data_files, thought_chain_report, model_name=selected_model
                    )

                    for i in range(revision_iterations):
                        update_status(status_container, f"Revisando nuevo reporte (iteración {i+1}/{revision_iterations})...", progress_bar, 85 + i * 2)
                        review = review_report(md_report, model_name=selected_model)
                        update_status(status_container, f"Mejorando nuevo reporte (iteración {i+1}/{revision_iterations})...", progress_bar, 87 + i * 2)
                        md_report = improve_report_based_on_review(md_report, review, model_name=selected_model)

                    new_report_label = f"Reporte v{len(st.session_state['reports']) + 1}"
                    st.session_state["reports"].append({"label": new_report_label, "md_report": md_report, "files": files})

                    update_status(status_container, "Mejora aplicada y nuevo reporte generado.", progress_bar, 100)
                else:
                    st.error(f"No se pudo ejecutar la mejora tras {max_attempts} intentos. Último error: {msg}")

            except Exception as e:
                st.error(f"Error durante la mejora: {str(e)}")

# =============================================================================
# ===================== BOTÓN DE REINICIO =======================================
# =============================================================================

if st.button("Nuevo Prompt (Reiniciar)"):

    keys_to_keep = ["docker_initialized"]
    for key in list(st.session_state.keys()):
        if key not in keys_to_keep:
            del st.session_state[key]
    st.experimental_rerun()
