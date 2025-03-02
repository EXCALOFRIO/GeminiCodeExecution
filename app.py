# app.py
import streamlit as st
import io
import zipfile
import base64
import time
import pandas as pd

from gemini_client import (
    generate_code,
    analyze_execution_result,
    generate_report,
    configure_gemini  # Asegúrate de importar configure_gemini
)
from docker_executor import initialize_docker_image, execute_code_in_docker, clean_unused_images, clean_unused_containers
from code_formatter import clean_code

# ----------------------------------------------------------------
# 1. LIMPIEZA DE RECURSOS AL INICIO
# ----------------------------------------------------------------
clean_unused_images()
clean_unused_containers()

# ----------------------------------------------------------------
# 2. CACHE Y CONFIGURACIÓN DE PÁGINA
# ----------------------------------------------------------------
@st.cache_resource
def init_docker():
    """Inicializa Docker solo si la imagen no existe."""
    return initialize_docker_image()

@st.cache_resource
def init_gemini():
    """Configura Gemini solo 1 vez por sesión."""
    configure_gemini()
    return "OK"

st.set_page_config(page_title="Generador de Código Python", layout="wide")

# Verificación inicial de Docker
docker_init_message = init_docker()
if "Error" in docker_init_message:
    st.error(docker_init_message, icon="❌")
    st.stop()

# ----------------------------------------------------------------
# 3. ESTILOS CSS (Adaptación automática al tema)
# ----------------------------------------------------------------
st.markdown("""
<style>
.attempt-counter {
    color: #00BCD4; /* Cian */
    font-weight: bold;
}
.action {
    color: #90A4AE;
    margin-left: 10px;
    font-style: italic;
}
.success-message {
    color: #4CAF50; /* Verde */
    font-weight: bold;
}
.error-message {
    color: #F44336; /* Rojo */
    font-weight: bold;
}
.report-container {
    padding: 20px;
    border-radius: 8px;
    margin-top: 20px;
    box-shadow: 0px 2px 8px rgba(0,0,0,0.3);
}
.file-preview {
    padding: 15px;
    border-radius: 8px;
    margin-top: 10px;
    box-shadow: 0px 2px 8px rgba(0,0,0,0.3);
}
.file-container {
    width: 70%;
    margin: auto;
}
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------
# 4. INICIALIZACIÓN DE SESIÓN
# ----------------------------------------------------------------
_ = init_gemini()  # Configura Gemini (cacheado)

if "attempts" not in st.session_state:
    st.session_state.attempts = 0
if "execution_history" not in st.session_state:
    st.session_state.execution_history = []
if "generated_files" not in st.session_state:
    st.session_state.generated_files = {}
if "results_available" not in st.session_state:
    st.session_state.results_available = False
if "formatted_report" not in st.session_state:
    st.session_state.formatted_report = ""
if "execution_result" not in st.session_state:
    st.session_state.execution_result = {}
if "preview_active" not in st.session_state:
    st.session_state.preview_active = False
if "preview_file" not in st.session_state:
    st.session_state.preview_file = None
if "preview_content" not in st.session_state:
    st.session_state.preview_content = None
if "all_files" not in st.session_state:
    st.session_state.all_files = {}

# ----------------------------------------------------------------
# 5. FUNCIONES AUXILIARES
# ----------------------------------------------------------------

def show_file_preview(file_name, file_content):
    st.session_state.preview_file = file_name
    st.session_state.preview_content = file_content
    st.session_state.preview_active = True

def close_file_preview():
    st.session_state.preview_file = None
    st.session_state.preview_content = None
    st.session_state.preview_active = False

def display_file_preview():
    if not st.session_state.preview_active or not st.session_state.preview_file:
        return

    file_name = st.session_state.preview_file
    file_content = st.session_state.preview_content

    with st.container():
        st.markdown(f"<div class='file-container'>", unsafe_allow_html=True)
        st.subheader(file_name)
        file_ext = file_name.split('.')[-1].lower()

        if file_ext in ['png', 'jpg', 'jpeg', 'gif']:
            st.image(file_content, caption=file_name)
        elif file_ext == 'csv':
            try:
                df = pd.read_csv(io.BytesIO(file_content))
                st.dataframe(df)
            except Exception as e:
                st.error(f"Error al mostrar CSV: {e}")
        elif file_ext == 'py':
            try:
                text_content = file_content.decode('utf-8')
                st.code(text_content, language='python')
            except Exception as e:
                st.error(f"Error al mostrar código Python: {e}")
        else:
            try:
                text_content = file_content.decode('utf-8')
                st.text_area("Contenido", text_content, height=300)
            except:
                st.warning("No se puede mostrar el contenido.", icon="⚠️")

        st.button("Cerrar Vista Previa", on_click=close_file_preview)
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()

class FileBrowser:
    def __init__(self, files_dict):
        self.files_dict = files_dict

    def render(self):
        if not self.files_dict:
            st.info("No se han generado archivos aún.", icon="ℹ️")
            return
        for file_name, content in self.files_dict.items():
            col1, col2 = st.columns([4, 1])
            with col1:
                st.button(f"📄 {file_name}", key=f"preview_{file_name}", on_click=show_file_preview, args=(file_name, content))
            with col2:
                st.download_button("⬇️", data=content, file_name=file_name, key=f"dl_{file_name}")

def process_report_content(report: str, files_dict: dict):
    """
    Processes the report, identifies file markers like {{filename}},
    and prepares the report for display, separating text from file content.
    """
    parts = []
    current_text = ""
    import re

    # Regex to find file markers like {{filename.ext}}
    file_marker_regex = re.compile(r"\{\{(.+?)\}\}")

    last_end = 0
    for match in file_marker_regex.finditer(report):
        file_name = match.group(1)
        start, end = match.span()

        # Add text before the marker
        text_chunk = report[last_end:start].strip()
        if text_chunk:
            parts.append({"type": "text", "content": text_chunk})

        # Add the file content
        if file_name in files_dict:
            parts.append({"type": "file", "name": file_name, "content": files_dict[file_name]})
        else:
            parts.append({"type": "text", "content": f"**Archivo no encontrado:** {file_name}"})

        last_end = end

    # Add any remaining text after the last marker
    remaining_text = report[last_end:].strip()
    if remaining_text:
        parts.append({"type": "text", "content": remaining_text})

    return parts

def display_processed_report(processed_report):
    """
    Displays the processed report, handling text and file components appropriately.
    """
    for item in processed_report:
        if item["type"] == "text":
            st.markdown(item["content"], unsafe_allow_html=True)  # Render markdown text
        elif item["type"] == "file":
            file_name = item["name"]
            file_content = item["content"]
            file_ext = file_name.split('.')[-1].lower()

            st.subheader(f"Archivo: {file_name}")  # Display file name as subheader
            if file_ext in ['png', 'jpg', 'jpeg', 'gif']:
                st.image(file_content, caption=file_name)
            elif file_ext == 'csv':
                try:
                    df = pd.read_csv(io.BytesIO(file_content))
                    st.dataframe(df)
                except Exception as e:
                    st.error(f"Error al mostrar CSV: {e}")
            elif file_ext == 'py':
                try:
                    text_content = file_content.decode('utf-8')
                    st.code(text_content, language='python')
                except Exception as e:
                    st.error(f"Error al mostrar código Python: {e}")
            else:
                try:
                    text_content = file_content.decode('utf-8')
                    st.text_area("Contenido", text_content, height=300)
                except:
                    st.warning(f"No se puede mostrar el contenido del archivo {file_name}.", icon="⚠️")


def clean_markdown(text: str) -> str:
    """
    Limpia el markdown eliminando caracteres innecesarios y formateando.
    """
    # Eliminar líneas en blanco adicionales
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]  # Eliminar líneas vacías
    return "\n".join(lines)

# ----------------------------------------------------------------
# 6. FUNCIÓN PRINCIPAL PARA GENERAR Y EJECUTAR
# ----------------------------------------------------------------
def generate_and_execute():
    # Reiniciamos el estado para que cada ejecución parta desde 0
    st.session_state.results_available = False
    st.session_state.generated_files = {}
    st.session_state.formatted_report = ""
    st.session_state.execution_result = {}
    st.session_state.attempts = 0
    st.session_state.execution_history = []
    st.session_state.all_files = {}

    prompt = st.session_state["user_prompt"]
    uploaded_files = st.session_state.get("user_files", [])

    all_files = {}
    if uploaded_files:
        for file in uploaded_files:
            all_files[file.name] = file.read()
    st.session_state.all_files = all_files
    input_files = all_files

    status_area = st.empty()
    with st.spinner("Preparando el entorno..."):
        time.sleep(0.5)

    # Generación inicial del código sin aplicar mejoras adicionales
    status_area.info("Generando el código Python y sus dependencias desde cero...", icon="🛠️")
    response = generate_code(prompt, input_files)

    generated_code = response.get("code", "")
    dependencies = response.get("dependencies", "")
    if not generated_code.strip():
        status_area.error("No se generó código válido. Revisa tu solicitud.", icon="❌")
        return
    if not dependencies.strip():
        st.warning("No se generaron dependencias nuevas. Usando dependencias actuales.")
        dependencies = ""
    cleaned_code = clean_code(generated_code)

    # Aumentamos el número de intentos a 8; en cada intento se vuelve a generar el código desde cero si ocurre error
    while st.session_state.attempts < 8:
        attempt_number = st.session_state.attempts + 1
        status_area.info(f"Intento {attempt_number}/8: Ejecutando el código en un entorno Docker aislado...", icon="🚀")

        execution_result = execute_code_in_docker(cleaned_code, input_files, dependencies)
        analysis = analyze_execution_result(execution_result)
        st.session_state.execution_history.append({
            "code": cleaned_code,
            "dependencies": dependencies,
            "result": execution_result,
            "error_type": analysis.get("error_type", ""),
            "error_message": analysis.get("error_message", "")
        })

        if analysis.get("error_type", "") == "OK":
            status_area.success("Código ejecutado exitosamente. Preparando resultados y reporte...", icon="✅")
            st.session_state.results_available = True
            st.session_state.generated_files = execution_result["files"]
            st.session_state.cleaned_code = cleaned_code
            st.session_state.execution_result = execution_result

            st.session_state.all_files.update({"script.py": cleaned_code})
            st.session_state.all_files.update(st.session_state.generated_files)

            report = generate_report(
                st.session_state["user_prompt"],
                st.session_state.cleaned_code,
                st.session_state.execution_result.get("stdout", ""),
                st.session_state.generated_files
            )
            # formatted_report = procesar_reporte(report, st.session_state.generated_files)
            st.session_state.formatted_report = report  # clean_markdown(formatted_report)  # Limpiar el markdown del reporte
            break
        else:
            error_msg = analysis.get("error_message", "Error inesperado.")
            status_area.error(f"Intento {attempt_number}/8 fallido: {error_msg}", icon="❌")
            st.session_state.attempts += 1
            if st.session_state.attempts >= 8:
                status_area.error("Límite de intentos alcanzado. No se pudo generar el código sin errores.", icon="🚫")
                break
            status_area.info("Reintentando la generación del código desde cero...", icon="🔄")
            response = generate_code(prompt, input_files)
            generated_code = response.get("code", "")
            dependencies = response.get("dependencies", "")
            if not generated_code.strip():
                status_area.error("No se generó código válido en el reintento. Revisa tu solicitud.", icon="❌")
                break
            if not dependencies.strip():
                st.warning("No se generaron dependencias nuevas en el reintento. Usando dependencias actuales.")
                dependencies = ""
            cleaned_code = clean_code(generated_code)

# ----------------------------------------------------------------
# 7. INTERFAZ PRINCIPAL
# ----------------------------------------------------------------

if st.session_state.preview_active:
    display_file_preview()

st.subheader("📝 Describe tu Tarea")
st.text_area(
    "Escribe qué quieres que haga el código Python (o cómo modificarlo):",
    key="user_prompt",
    height=150,
    placeholder="Ejemplo: 'Crea un script que genere un gráfico de barras a partir de un CSV.'"
)

st.subheader("📂 Sube Archivos (Opcional)")
st.file_uploader(
    "Archivos que el script pueda necesitar:",
    accept_multiple_files=True,
    key="user_files"
)

st.button("🚀 Generar y Ejecutar", on_click=generate_and_execute)

# ----------------------------------------------------------------
# 8. MOSTRAR RESULTADOS
# ----------------------------------------------------------------
if st.session_state.results_available:
    col_report, col_files = st.columns([7, 3])
    with col_report:
        st.subheader("📋 Reporte")
        #st.markdown(f"<div class='report-container'>{st.session_state.formatted_report}</div>", unsafe_allow_html=True)
        processed_report = process_report_content(st.session_state.formatted_report, st.session_state.generated_files)
        display_processed_report(processed_report)
    with col_files:
        st.subheader("📁 Archivos Generados")
        browser = FileBrowser(st.session_state.generated_files)
        browser.render()
        if st.session_state.generated_files:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zipf:
                for name, content in st.session_state.generated_files.items():
                    if isinstance(content, str):
                        zipf.writestr(name, content.encode('utf-8'))
                    else:
                        zipf.writestr(name, content)
            zip_buffer.seek(0)
            st.download_button(
                "⬇️ Descargar Todo (ZIP)",
                zip_buffer,
                "generated_files.zip",
                "application/zip"
            )