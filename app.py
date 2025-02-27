# app.py
import streamlit as st
from backend import (
    get_file_icon, display_generated_files, convert_markdown_to_pdf,
    render_markdown_with_visualizations, process_uploaded_files,
    generate_code_and_dependencies, execute_and_fix_code,
    generate_and_display_report, improve_existing_code,
    execute_improved_code, generate_and_display_improvement_report,
    initialize_docker_environment, update_status, display_error
)
from io import BytesIO
import zipfile

# Configuración de la página
st.set_page_config(page_title="AI Code Docker Executor", layout="wide")

# Estilos personalizados (moved from original code for clarity, can be kept in app.py)
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

# Configuración desde la barra lateral
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

# Inicialización del estado de sesión
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

st.markdown("Genera y refina código Python ejecutado en Docker. Visualiza resultados en Markdown y descarga todo.")

# Bloque de entrada inicial
if not st.session_state["generated"]:
    with st.expander("Instrucciones y Archivos Adjuntos", expanded=True):
        prompt_initial = st.text_area("Instrucción (prompt)", key="prompt_initial", placeholder="Ejemplo: Analiza ventas desde un Excel y crea un gráfico.")
        uploaded_files = st.file_uploader("Sube archivos (opcional)", accept_multiple_files=True, key="uploaded_files")
    if st.button("Generar y Ejecutar Código"):
        if not prompt_initial.strip():
            st.error("Ingresa una instrucción antes de generar.")
        else:
            st.session_state["generated"] = True
            st.session_state["running"] = True
            st.session_state["input_files"], st.session_state["resumen_archivos"] = process_uploaded_files(uploaded_files)

# Bloque de proceso de generación
if st.session_state["generated"] and not st.session_state["process_completed"]:
    status_container = st.empty()
    error_container = st.empty()
    progress_bar = st.progress(0)
    error_history = []

    try:
        # 1. Initialize Docker Environment
        update_status(status_container, "Inicializando imágenes Docker...", progress_bar, 5)
        init_message = initialize_docker_environment()
        update_status(status_container, init_message, progress_bar, 10)

        # 2. Generate Code and Dependencies
        update_status(status_container, "Generando código y dependencias...", progress_bar, 20)
        st.session_state["current_code"], dependencies = generate_code_and_dependencies(
            st.session_state["prompt_initial"], st.session_state["resumen_archivos"],
            cot_iterations, selected_model, error_history
        )
        if dependencies:
            update_status(status_container, f"Dependencias detectadas:\n```\n{dependencies}\n```", progress_bar, 50)
        else:
            update_status(status_container, "Sin dependencias adicionales detectadas.", progress_bar, 50)

        # 3. Execute and Fix Code (Iterative Loop)
        status, msg, outputs, st.session_state["current_code"], dependencies, error_history = execute_and_fix_code(
            st.session_state["current_code"], st.session_state["input_files"], dependencies,
            status_container, error_container, progress_bar, selected_model, cot_iterations, revision_iterations, error_history
        )

        if status == "OK":
            st.session_state["all_files"] = outputs.get("all_files", {})
            st.session_state["generated_files"] = outputs.get("generated_files", {})

            # 4. Generate and Display Report
            st.session_state["reports"] = generate_and_display_report(
                outputs, st.session_state["generated_files"], status_container, progress_bar,
                selected_model, cot_iterations, revision_iterations, st.session_state["reports"]
            )
            st.session_state["process_completed"] = True
        else:
            display_error(error_container, "Falló la ejecución tras varios intentos.", "\n".join(error_history[-3:]))

    except Exception as e:
        display_error(error_container, "Error crítico durante el proceso.", str(e))
    finally:
        st.session_state["running"] = False

# Bloque de resultados
if st.session_state.get("generated", False) and st.session_state.get("process_completed", False):
    col1, col2 = st.columns([1, 2])
    with col1:
        st.subheader("Entorno Virtual")
        if st.session_state["all_files"]:
            st.write("#### Directorio `/app` en Docker:")
            display_generated_files(st.session_state["all_files"], st.container())
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for filename, content in st.session_state["all_files"].items():
                    zip_file.writestr(filename, content)
            zip_buffer.seek(0)
            st.download_button(
                label="Descargar Directorio como ZIP",
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
    prompt_improve = st.text_area("Instrucción / Mejora", key="prompt_improve", placeholder="Ejemplo: Añade un gráfico de líneas.")
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
                update_status(status_container, "Aplicando mejora...", progress_bar, 10)
                new_code = improve_existing_code(
                    st.session_state["current_code"], prompt_improve, improvement_file,
                    selected_model=selected_model, cot_iterations=cot_iterations, error_history=error_history
                )
                st.session_state["current_code"] = new_code

                dependencies = st.session_state.get("dependencies", {}) # Using stored dependencies from the previous run if available

                status, msg, outputs, st.session_state["current_code"], dependencies, error_history = execute_improved_code(
                    new_code, st.session_state["input_files"], dependencies,
                    status_container, error_container, progress_bar, selected_model, cot_iterations, revision_iterations, error_history
                )

                if status == "OK":
                    st.session_state["all_files"] = outputs.get("all_files", {})
                    st.session_state["generated_files"] = outputs.get("generated_files", {})

                    st.session_state["reports"] = generate_and_display_improvement_report(
                        outputs, st.session_state["generated_files"], status_container, progress_bar,
                        selected_model, cot_iterations, revision_iterations, st.session_state["reports"]
                    )
                else:
                    display_error(error_container, "Falló la mejora tras varios intentos.", "\n".join(error_history[-3:]))

            except Exception as e:
                display_error(error_container, "Error al aplicar mejora.", str(e))

if st.button("Nuevo Prompt (Reiniciar)"):
    keys_to_keep = ["docker_initialized"]
    for key in list(st.session_state.keys()):
        if key not in keys_to_keep:
            del st.session_state[key]
    st.experimental_rerun()