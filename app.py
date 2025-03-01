import streamlit as st
import io
import zipfile
import base64
import time
import pandas as pd

from gemini_client import (
    configure_gemini,
    improve_prompt,
    generate_code,
    generate_code_modification,
    analyze_execution_result,
    generate_fix,
    generate_report
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
if "Error" not in docker_init_message:
    pass
else:
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
    width: 70%; /* Ancho del 70% */
    margin: auto; /* Centrado horizontal */
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
if "cleaned_code" not in st.session_state:
    st.session_state.cleaned_code = ""
if "execution_result" not in st.session_state:
    st.session_state.execution_result = {}
if "preview_active" not in st.session_state:
    st.session_state.preview_active = False
if "preview_file" not in st.session_state:
    st.session_state.preview_file = None
if "preview_content" not in st.session_state:
    st.session_state.preview_content = None
if "current_code" not in st.session_state:
    st.session_state.current_code = ""
if "current_dependencies" not in st.session_state:
    st.session_state.current_dependencies = ""
if "formatted_report" not in st.session_state:
    st.session_state.formatted_report = ""
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

def procesar_reporte(report, files_dict):
    lines = report.split('\n')
    formatted_lines = []
    for line in lines:
        if line.startswith("- ") and formatted_lines and "Archivos Generados" in formatted_lines[-1]:
            file_name = line[2:].strip()
            file_size = len(files_dict.get(file_name, b'')) / 1024
            formatted_lines.append(f"📄 **{file_name}** ({file_size:.2f} KB)")
        else:
            formatted_lines.append(line)
    return '\n'.join(formatted_lines)

# ----------------------------------------------------------------
# 6. FUNCIÓN PRINCIPAL PARA GENERAR Y EJECUTAR
# ----------------------------------------------------------------
def generate_and_execute():
    st.session_state.results_available = False
    st.session_state.generated_files = {}
    st.session_state.formatted_report = ""
    st.session_state.execution_result = {}
    st.session_state.attempts = 0
    st.session_state.execution_history = []

    prompt = st.session_state["user_prompt"]
    uploaded_files = st.session_state.get("user_files", [])

    all_files = {}
    if uploaded_files:
        for file in uploaded_files:
            all_files[file.name] = file.read()
    if st.session_state.generated_files:
        all_files.update(st.session_state.generated_files)
    if st.session_state.current_code:
        all_files["script.py"] = st.session_state.current_code

    st.session_state.all_files = all_files
    input_files = all_files

    status_area = st.empty()
    with st.spinner("Preparando el entorno..."):
        time.sleep(0.5)

    # Optimización del prompt
    status_area.info("Optimizando tu solicitud para obtener los mejores resultados...", icon="🪄")
    improved_response = improve_prompt(prompt, input_files)

    # Generación o modificación del código
    if not st.session_state.current_code:
        status_area.info("Generando el código Python y sus dependencias desde cero...", icon="🛠️")
        response = generate_code(improved_response["code"], input_files)
    else:
        status_area.info("Modificando el código existente según tu nueva solicitud...", icon="🔄")
        response = generate_code_modification(
            st.session_state.current_code,
            st.session_state.current_dependencies,
            improved_response["code"],
            input_files
        )

    # Validación del código y dependencias generados
    generated_code = response.get("code", "")
    dependencies = response.get("dependencies", "")
    if not generated_code.strip():
        status_area.error("No se generó código válido. Revisa tu solicitud.", icon="❌")
        return
    if not dependencies.strip():
        st.warning("No se generaron dependencias nuevas. Usando dependencias actuales.")
        dependencies = st.session_state.current_dependencies
    cleaned_code = clean_code(generated_code)

    # Bucle de ejecución con intentos
    while st.session_state.attempts < 5:
        attempt_number = st.session_state.attempts + 1
        status_area.info(f"Intento {attempt_number}/5: Ejecutando el código en un entorno Docker aislado...", icon="🚀")

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
            st.session_state.current_code = cleaned_code  # Actualizar el código actual
            st.session_state.current_dependencies = dependencies  # Actualizar las dependencias

            st.session_state.all_files.update({"script.py": cleaned_code})
            st.session_state.all_files.update(st.session_state.generated_files)

            report = generate_report(
                st.session_state["user_prompt"],
                st.session_state.cleaned_code,
                st.session_state.execution_result.get("stdout", ""),
                st.session_state.generated_files
            )
            st.session_state.formatted_report = procesar_reporte(report, st.session_state.generated_files)
            break
        else:
            error_msg = analysis.get("error_message", "Error inesperado.")
            status_area.error(f"Intento {attempt_number}/5 fallido: {error_msg}", icon="❌")
            st.session_state.attempts += 1
            if st.session_state.attempts >= 5:
                status_area.error("Límite de intentos alcanzado. No se pudo generar el código sin errores.", icon="🚫")
                break
            status_area.info("Analizando el error y aplicando correcciones...", icon="🔍")
            fix = generate_fix(
                error_type=analysis.get("error_type", ""),
                error_message=analysis.get("error_message", ""),
                code=cleaned_code,
                dependencies=dependencies,
                history=st.session_state.execution_history
            )
            cleaned_code = fix.get("code", cleaned_code)
            dependencies = fix.get("dependencies", dependencies)
            st.session_state.current_dependencies = dependencies  # Actualizar dependencias incluso en caso de error

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
        st.markdown(f"<div class='report-container'>{st.session_state.formatted_report}</div>", unsafe_allow_html=True)
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
