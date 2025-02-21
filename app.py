import streamlit as st 
import pandas as pd
import base64
import re
from difflib import get_close_matches
from io import BytesIO
from fpdf import FPDF
from gemini_client import (
    generate_code,
    refine_code,
    get_dependencies,
    refine_dependencies,
    improve_code,
    generate_markdown_report
)
from code_formatter import clean_code
from docker_executor import execute_code_in_docker

# =============================================================================
# ====================== CONFIGURACIÓN DE BLOQUEO ============================
# =============================================================================
HARM_BLOCK_THRESHOLD = "OFF"  # Opciones: HARM_BLOCK_THRESHOLD_UNSPECIFIED, BLOCK_LOW_AND_ABOVE, BLOCK_MEDIUM_AND_ABOVE, BLOCK_ONLY_HIGH, BLOCK_NONE, OFF

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

def display_generated_files(generated_files, container):
    """Muestra los archivos generados con íconos y botones de descarga."""
    with container:
        if generated_files:
            st.markdown("### Archivos Generados")
            for fname, fcontent in generated_files.items():
                icon = get_file_icon(fname)
                st.write(f"{icon} **{fname}**")
                st.download_button(
                    label="Descargar",
                    data=fcontent,
                    file_name=fname
                )
        else:
            st.info("No se generaron archivos.")

def convert_markdown_to_pdf(md_text):
    """Convierte el contenido Markdown en un PDF simple."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in md_text.splitlines():
        pdf.multi_cell(0, 10, line)
    pdf_bytes = pdf.output(dest='S').encode('latin1')
    return pdf_bytes

def validate_execution(outputs):
    """Valida los resultados de la ejecución del código."""
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

def update_status(container, message, progress_bar, progress):
    """Actualiza el mensaje de estado y la barra de progreso con estilo."""
    container.markdown(f"🔄 **{message}**")
    progress_bar.progress(progress)

def handle_new_improvement(current_code, prompt_text, attached_file=None, selected_model="gemini-2.0-flash-001"):
    """Genera una nueva versión del código con mejoras basadas en el prompt y un archivo opcional."""
    file_info = ""
    if attached_file is not None:
        attached_file.seek(0)
        file_content = attached_file.read().decode("utf-8", errors="ignore")
        file_info = f"\nContenido del archivo adjunto:\n{file_content}\n"
    full_prompt = (
        "A partir del siguiente código Python:\n"
        f"{current_code}\n"
        "\nRealiza las siguientes mejoras solicitadas:\n"
        f"{prompt_text}\n"
        f"{file_info}\n"
        "Devuelve el código completo y funcional con las mejoras integradas."
    )
    new_code = improve_code(current_code, full_prompt, model_name=selected_model)
    new_code = clean_code(new_code)
    return new_code

def find_best_match(filename, files, cutoff=0.6):
    """Encuentra la mejor coincidencia de archivo usando difflib.get_close_matches."""
    matches = get_close_matches(filename, files.keys(), n=1, cutoff=cutoff)
    return matches[0] if matches else None

def render_markdown_with_visualizations(md_report, files):
    """Renderiza el reporte Markdown procesando los marcadores {{visualize_nombre_archivo}} para visualizar archivos."""
    pattern = r'(\{\{visualize_(.+?)\}\})'
    parts = re.split(pattern, md_report)
    for part in parts:
        if part.startswith('{{visualize_') and part.endswith('}}'):
            filename = part[13:-2]  # Extraer el nombre del archivo
            if filename in files:
                file_content = files[filename]
            else:
                # Buscar la mejor coincidencia
                best_match = find_best_match(filename, files)
                if best_match:
                    file_content = files[best_match]
                else:
                    st.error(f"Archivo no encontrado y sin coincidencias cercanas: {filename}")
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
# ====================== CONFIGURACIÓN Y ESTADO INICIAL =======================
# =============================================================================

st.set_page_config(page_title="AI Code Docker Executor", layout="wide")

st.title("AI Code Docker Executor")

# Selector horizontal de nivel de profundidad con st.radio para estilo de botones
nivel_profundidad = st.radio(
    "Nivel de Profundidad",
    options=["Poca", "Normal", "Extremo"],
    index=1,  # Por defecto "Normal"
    horizontal=True,
    help="Selecciona el nivel de profundidad para los prompts."
)

# Asignar modelo según nivel de profundidad
if nivel_profundidad == "Poca":
    selected_model = "gemini-2.0-flash-lite-preview-02-05"
elif nivel_profundidad == "Normal":
    selected_model = "gemini-2.0-flash-001"
else:  # Extremo
    selected_model = "gemini-2.0-flash-thinking-exp-01-21"

# Inicializar variables de sesión
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
    "Genera y refina código Python usando la API de Gemini y ejecútalo en un entorno aislado (Docker) con validación automática. "
    "La salida se presenta en Markdown (en pestañas) y se muestran únicamente los archivos generados para su descarga."
)

# =============================================================================
# ====================== BLOQUE DE ENTRADA INICIAL ============================
# =============================================================================

if not st.session_state["generated"]:
    with st.container():
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
# ====================== BLOQUE DE PROCESO DE GENERACIÓN =======================
# =============================================================================

if st.session_state["generated"] and not st.session_state["process_completed"]:
    status_container = st.empty()
    progress_bar = st.progress(0)
    try:
        update_status(status_container, "Procesando archivos adjuntos...", progress_bar, 10)
        resumen_archivos = st.session_state.get("resumen_archivos", "")

        update_status(status_container, "Generando código con Gemini...", progress_bar, 20)
        prompt_initial = st.session_state["prompt_initial"]
        prompt = (
            "Instrucción del usuario:\n"
            f"{prompt_initial}\n"
            "\nInformación de archivos adjuntos (si hay):\n"
            f"{resumen_archivos if resumen_archivos else 'No hay archivos adjuntos.'}\n"
            "\nGenera código Python completo y funcional para cumplir la instrucción, listo para ejecutarse en un entorno Docker."
        )
        code_generated = generate_code(prompt, model_name=selected_model)
        code_generated = clean_code(code_generated)
        current_code = code_generated

        update_status(status_container, "Mejorando código...", progress_bar, 30)
        improvement_prompt = (
            "Dado el siguiente código Python:\n"
            f"{current_code}\n"
            "\nMejóralo para asegurar que genere imágenes o archivos de datos correctamente."
        )
        new_code = improve_code(current_code, improvement_prompt, model_name=selected_model)
        new_code = clean_code(new_code)
        if new_code.strip() != current_code.strip():
            current_code = new_code

        st.session_state["current_code"] = current_code

        update_status(status_container, "Obteniendo dependencias requeridas...", progress_bar, 40)
        dependencies = get_dependencies(current_code, model_name=selected_model)
        dependencies = clean_code(dependencies)

        max_attempts = 5
        attempt = 1
        success = False
        while attempt <= max_attempts:
            update_status(status_container, f"Ejecutando código en Docker (intento {attempt}/{max_attempts})...", progress_bar, 40 + (attempt - 1) * 10)
            outputs = execute_code_in_docker(current_code, st.session_state["input_files"], dependencies)
            status, msg = validate_execution(outputs)
            if status == "OK":
                success = True
                break
            elif status == "DEPENDENCY":
                update_status(status_container, "Error de dependencias detectado. Refinando dependencias...", progress_bar, 40 + (attempt - 1) * 10 + 5)
                new_dependencies = refine_dependencies(dependencies, current_code, outputs, model_name=selected_model)
                new_dependencies = clean_code(new_dependencies)
                if new_dependencies.strip() != dependencies.strip():
                    dependencies = new_dependencies
                else:
                    st.error("No se pudieron resolver las dependencias después de la refinación.")
                    break
            elif status == "CODE":
                update_status(status_container, "Error en el código detectado. Refinando código...", progress_bar, 40 + (attempt - 1) * 10 + 5)
                new_code = refine_code(current_code, outputs, model_name=selected_model)
                new_code = clean_code(new_code)
                if new_code.strip() != current_code.strip():
                    current_code = new_code
                    st.session_state["current_code"] = new_code
                else:
                    st.error("No se pudo corregir el código después de la refinación.")
                    break
            attempt += 1

        if not success:
            update_status(status_container, f"El código no se ejecutó correctamente después de {max_attempts} intentos.", progress_bar, 100)

        files = outputs.get("files", {})
        st.session_state["files"] = files

        update_status(status_container, "Generando reporte Markdown...", progress_bar, 90)
        image_files = [fname for fname in files.keys() if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
        data_files = [fname for fname in files.keys() if fname.lower().endswith((".csv", ".xlsx", ".xls"))]
        md_report = generate_markdown_report(outputs.get("stdout", ""), outputs.get("stderr", ""), image_files, data_files, model_name=selected_model)
        report_label = f"Reporte v{len(st.session_state['reports'])+1}"
        st.session_state["reports"].append({"label": report_label, "md_report": md_report, "files": files})

        update_status(status_container, "Proceso completado exitosamente.", progress_bar, 100)
        st.session_state["process_completed"] = True
        st.session_state["running"] = False
    except Exception as e:
        update_status(status_container, f"Error durante el proceso: {str(e)}", progress_bar, 100)

# =============================================================================
# ====================== BLOQUE DE MEJORAS Y RESULTADOS ========================
# =============================================================================

if st.session_state.get("generated", False) and st.session_state.get("process_completed", False):
    files_container = st.container()
    display_generated_files(st.session_state["files"], files_container)
    
    if st.session_state["reports"]:
        st.markdown("### Reportes en Markdown")
        ordered_reports = st.session_state["reports"][::-1]
        report_tabs = st.tabs([report["label"] for report in ordered_reports])
        for idx, tab in enumerate(report_tabs):
            with tab:
                report = ordered_reports[idx]
                render_markdown_with_visualizations(report["md_report"], report["files"])
                pdf_bytes = convert_markdown_to_pdf(report["md_report"])
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
    improvement_file = st.file_uploader("Adjunta un archivo (opcional) para la mejora", key="improve_file")
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
                    current_code, prompt_improve, attached_file=improvement_file, selected_model=selected_model
                )
                st.session_state["current_code"] = new_code

                update_status(status_container, "Obteniendo dependencias para la nueva versión...", progress_bar, 20)
                dependencies = get_dependencies(new_code, model_name=selected_model)
                dependencies = clean_code(dependencies)

                max_attempts = 5
                attempt = 1
                success = False
                while attempt <= max_attempts:
                    update_status(status_container, f"Ejecutando nueva versión en Docker (intento {attempt}/{max_attempts})...", progress_bar, 20 + (attempt - 1) * 10)
                    outputs = execute_code_in_docker(new_code, st.session_state["input_files"], dependencies)
                    status, msg = validate_execution(outputs)
                    if status == "OK":
                        success = True
                        break
                    elif status == "DEPENDENCY":
                        update_status(status_container, "Error de dependencias detectado. Refinando dependencias...", progress_bar, 20 + (attempt - 1) * 10 + 5)
                        new_dependencies = refine_dependencies(dependencies, new_code, outputs, model_name=selected_model)
                        new_dependencies = clean_code(new_dependencies)
                        if new_dependencies.strip() != dependencies.strip():
                            dependencies = new_dependencies
                        else:
                            st.error("No se pudieron resolver las dependencias después de la refinación.")
                            break
                    elif status == "CODE":
                        update_status(status_container, "Error en el código detectado. Refinando código...", progress_bar, 20 + (attempt - 1) * 10 + 5)
                        new_code = refine_code(new_code, outputs, model_name=selected_model)
                        new_code = clean_code(new_code)
                        if new_code.strip() != st.session_state["current_code"].strip():
                            st.session_state["current_code"] = new_code
                        else:
                            st.error("No se pudo corregir el código después de la refinación.")
                            break
                    attempt += 1

                if not success:
                    update_status(status_container, f"El código no se ejecutó correctamente después de {max_attempts} intentos.", progress_bar, 100)
                else:
                    update_status(status_container, "Código ejecutado correctamente.", progress_bar, 70)

                files = outputs.get("files", {})
                st.session_state["files"] = files

                update_status(status_container, "Generando nuevo reporte Markdown...", progress_bar, 80)
                image_files = [fname for fname in files.keys() if fname.lower().endswith((".png", ".jpg", ".jpeg", ".gif"))]
                data_files = [fname for fname in files.keys() if fname.lower().endswith((".csv", ".xlsx", ".xls"))]
                md_report = generate_markdown_report(outputs.get("stdout", ""), outputs.get("stderr", ""), image_files, data_files, model_name=selected_model)
                new_report_label = f"Reporte v{len(st.session_state['reports'])+1}"
                st.session_state["reports"].append({"label": new_report_label, "md_report": md_report, "files": files})

                update_status(status_container, "Mejora aplicada y nuevo reporte generado.", progress_bar, 100)
            except Exception as e:
                update_status(status_container, f"Error durante la mejora: {str(e)}", progress_bar, 100)

# Botón para reiniciar el proceso
if st.button("Nuevo Prompt (Reiniciar)"):
    keys_to_keep = ["docker_initialized"]
    for key in list(st.session_state.keys()):
        if key not in keys_to_keep:
            del st.session_state[key]