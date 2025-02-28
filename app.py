import streamlit as st
import io
import zipfile
import base64
import os

from gemini_client import (
    configure_gemini,
    improve_prompt,
    generate_code,
    analyze_execution_result,
    generate_fix,
    generate_report
)
from docker_executor import initialize_docker_image, execute_code_in_docker
from code_formatter import clean_code

# ----------------------------------------------------------------
# 1. CACHE Y CONFIGURACIÓN DE PÁGINA
# ----------------------------------------------------------------

@st.cache_resource
def init_docker():
    """Inicializa Docker solo 1 vez por sesión."""
    return initialize_docker_image()

@st.cache_resource
def init_gemini():
    """Configura Gemini solo 1 vez por sesión."""
    configure_gemini()
    return "OK"

st.set_page_config(page_title="Generador de Código Python", layout="wide")

# ----------------------------------------------------------------
# 2. ESTILOS CSS
# ----------------------------------------------------------------
st.markdown("""
<style>
/* Estilos generales */
.input-container {
    padding: 15px;
    border-radius: 8px;
    margin-bottom: 20px;
    box-shadow: 0px 2px 4px rgba(0,0,0,0.1);
}
.report-container {
    padding: 20px;
    border-radius: 8px;
    margin-top: 20px;
    margin-left: auto;
    margin-right: auto;
    box-shadow: 0px 2px 4px rgba(0,0,0,0.1);
}
.attempt-message {
    font-size: 18px;
    font-weight: bold;
    color: #007bff;
    margin-bottom: 0.5rem;
}
.error-message-box {
    background-color: #ffe8e8;
    border: 1px solid #ff4d4f;
    padding: 10px;
    border-radius: 8px;
    color: #ff4d4f;
    margin-top: 10px;
    margin-bottom: 10px;
}
.success-message-box {
    background-color: #e9f7ef;
    border: 1px solid #28a745;
    padding: 10px;
    border-radius: 8px;
    color: #28a745;
    margin-top: 10px;
    margin-bottom: 10px;
}
.file-preview {
    padding: 15px;
    border-radius: 8px;
    margin-top: 10px;
    box-shadow: 0px 2px 4px rgba(0,0,0,0.1);
}
.preview-header {
    font-size: 16px;
    font-weight: bold;
    margin-bottom: 10px;
}
.preview-image {
    max-width: 100%;
    border-radius: 4px;
}
/* Modo oscuro */
@media (prefers-color-scheme: dark) {
    .input-container, .report-container, .file-preview {
        background-color: #262730;
        border: 1px solid #444;
    }
    .error-message-box {
        background-color: #4d0000;
        border: 1px solid #ff4d4f;
        color: #ffb3b3;
    }
    .success-message-box {
        background-color: #1f3d2e;
        border: 1px solid #28a745;
        color: #9ae6b4;
    }
}
</style>
""", unsafe_allow_html=True)

# ----------------------------------------------------------------
# 3. INICIALIZACIÓN DE SESIÓN
# ----------------------------------------------------------------
_ = init_docker()  # Inicializa Docker (cacheado)
_ = init_gemini()  # Configura Gemini (cacheado)

# Variables de estado
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

# ----------------------------------------------------------------
# 4. FUNCIONES AUXILIARES (PREVIEW, FILEBROWSER, ETC.)
# ----------------------------------------------------------------
def show_file_preview(file_name, file_content):
    """Activa la vista previa en la sesión (con callback)."""
    st.session_state.preview_file = file_name
    st.session_state.preview_content = file_content
    st.session_state.preview_active = True

def close_file_preview():
    """Cierra la vista previa (con callback)."""
    st.session_state.preview_file = None
    st.session_state.preview_content = None
    st.session_state.preview_active = False

def display_file_preview():
    """Muestra la vista previa de un archivo (imagen, texto, código, etc.) y detiene la ejecución."""
    file_name = st.session_state.preview_file
    file_content = st.session_state.preview_content
    
    st.markdown(f"<div class='file-preview'><div class='preview-header'>📄 {file_name}</div>", unsafe_allow_html=True)
    
    file_ext = file_name.split('.')[-1].lower()
    if file_ext in ['png', 'jpg', 'jpeg', 'gif']:
        b64 = base64.b64encode(file_content).decode()
        st.markdown(f"<img src='data:image/{file_ext};base64,{b64}' class='preview-image'>", unsafe_allow_html=True)
    elif file_ext in ['txt', 'md', 'csv']:
        try:
            text_content = file_content.decode('utf-8')
            st.text_area("Contenido", text_content, height=300)
        except:
            st.warning("No se puede mostrar el contenido de este archivo como texto.")
    elif file_ext in ['py', 'js', 'html', 'css']:
        try:
            code_content = file_content.decode('utf-8')
            st.code(code_content, language=file_ext)
        except:
            st.warning("No se puede mostrar el código de este archivo.")
    else:
        st.info(f"Vista previa no disponible para archivos .{file_ext}")
        
    st.download_button(
        "⬇️ Descargar Archivo", 
        file_content, 
        file_name, 
        key=f"download_{file_name}"
    )

    # Botón para cerrar la vista previa
    st.button("Cerrar Vista Previa", on_click=close_file_preview)
    st.markdown("</div>", unsafe_allow_html=True)

    # Importante: detenemos la ejecución para que no se muestre nada más
    st.stop()

class FileBrowser:
    """Explorador de archivos generados."""
    def __init__(self, files_dict):
        self.files_dict = files_dict
    
    def render(self):
        if not self.files_dict:
            st.info("No se han generado archivos aún.")
            return
        
        for file_name, content in self.files_dict.items():
            file_ext = file_name.split('.')[-1].lower()
            if file_ext in ['png', 'jpg', 'jpeg', 'gif']:
                icon = "🖼️"
            elif file_ext == 'py':
                icon = "🐍"
            elif file_ext in ['txt', 'md']:
                icon = "📄"
            elif file_ext in ['csv', 'xlsx', 'json']:
                icon = "📊"
            else:
                icon = "📁"
                
            file_size = len(content) / 1024  # KB
            
            col1, col2 = st.columns([4, 1])
            with col1:
                # Botón de vista previa con callback
                st.button(
                    f"{icon} {file_name} ({file_size:.2f} KB)",
                    key=f"preview_{file_name}",
                    on_click=show_file_preview,
                    args=(file_name, content)
                )
            with col2:
                st.download_button(
                    "⬇️", 
                    data=content, 
                    file_name=file_name, 
                    key=f"dl_{file_name}",
                    help=f"Descargar {file_name}"
                )

def procesar_reporte(report, files_dict):
    """Transforma el reporte en un markdown con íconos y tamaños de archivos."""
    lines = report.split('\n')
    in_files_section = False
    formatted_lines = []
    for line in lines:
        if line.startswith("Archivos Generados:"):
            in_files_section = True
            formatted_lines.append("### Archivos Generados")
        elif in_files_section and line.startswith("- "):
            file_name = line[2:].strip()
            extension = file_name.split('.')[-1].lower()
            if extension in ['png', 'jpg', 'jpeg']:
                icon = '🖼️'
            elif extension == 'txt':
                icon = '📄'
            else:
                icon = '📁'
            file_size = len(files_dict.get(file_name, b'')) / 1024
            formatted_lines.append(f"{icon} **{file_name}** ({file_size:.2f} KB)")
        else:
            in_files_section = False
            formatted_lines.append(line)
    return '\n'.join(formatted_lines)

# ----------------------------------------------------------------
# 5. FUNCIÓN PRINCIPAL PARA GENERAR Y EJECUTAR
# ----------------------------------------------------------------
def generate_and_execute():
    """Callback que se dispara al pulsar el botón 'Generar y Ejecutar'."""
    prompt = st.session_state["user_prompt"]
    uploaded_files = st.session_state["user_files"]

    if not prompt.strip():
        st.error("Por favor, escribe una descripción antes de generar.")
        return

    # Reseteo de estados previos
    st.session_state.attempts = 0
    st.session_state.execution_history = []
    st.session_state.generated_files = {}
    st.session_state.results_available = False
    st.session_state.cleaned_code = ""
    st.session_state.execution_result = {}

    # Tomamos los archivos subidos (si los hay)
    input_files = {}
    if uploaded_files:
        for f in uploaded_files:
            input_files[f.name] = f.read()

    with st.spinner("Generando y ejecutando el código, por favor espera..."):
        # 1) Mejorar prompt
        improved_prompt = improve_prompt(prompt, input_files)

        # 2) Hasta 5 intentos
        while st.session_state.attempts < 5:
            attempt_number = st.session_state.attempts + 1
            st.markdown(f"<div class='attempt-message'>🔄 Intento {attempt_number}/5</div>", unsafe_allow_html=True)

            # Generar código
            response = generate_code(improved_prompt, input_files)
            generated_code = response.get("code", "")
            dependencies = response.get("dependencies", "")
            cleaned_code = clean_code(generated_code)

            # Ejecutar en Docker
            execution_result = execute_code_in_docker(cleaned_code, input_files, dependencies)

            # Analizar resultado
            analysis = analyze_execution_result(execution_result)
            st.session_state.execution_history.append({
                "code": cleaned_code,
                "dependencies": dependencies,
                "result": execution_result,
                "error_type": analysis.get("error_type", ""),
                "error_message": analysis.get("error_message", "")
            })

            if analysis.get("error_type", "") == "OK":
                # Éxito
                st.markdown(
                    "<div class='success-message-box'>✅ ¡Código ejecutado con éxito!</div>", 
                    unsafe_allow_html=True
                )
                st.session_state.results_available = True
                st.session_state.generated_files = execution_result["files"]
                st.session_state.cleaned_code = cleaned_code
                st.session_state.execution_result = execution_result
                break
            else:
                # Error en este intento
                error_html = f"""
                    <div class='error-message-box'>
                        🚨 <b>Error en intento {attempt_number}:</b><br>
                        <b>Mensaje:</b> {analysis.get('error_message', '')}
                    </div>
                """
                st.markdown(error_html, unsafe_allow_html=True)

                st.session_state.attempts += 1
                if st.session_state.attempts >= 5:
                    st.markdown(
                        "<div class='error-message-box'>❌ Límite de 5 intentos alcanzado.</div>",
                        unsafe_allow_html=True
                    )
                    break

                # Generar corrección
                fix = generate_fix(
                    error_type=analysis.get("error_type", ""),
                    error_message=analysis.get("error_message", ""),
                    code=cleaned_code,
                    dependencies=dependencies,
                    history=st.session_state.execution_history
                )
                cleaned_code = fix.get("code", cleaned_code)
                dependencies = fix.get("dependencies", dependencies)

# ----------------------------------------------------------------
# 6. INTERFAZ PRINCIPAL
# ----------------------------------------------------------------
st.title("✨ Generador de Código Python con IA")

# 6.1 - Si hay una vista previa activa, se muestra y se detiene la ejecución.
if st.session_state.preview_active and st.session_state.preview_file:
    display_file_preview()

# 6.2 - Si NO hay vista previa, mostramos el formulario y resultados (si hay).
st.subheader("📝 Describe tu Tarea")
st.text_area(
    "Escribe qué quieres que haga el código Python:",
    key="user_prompt",
    height=150
)

st.subheader("📂 Sube Archivos (Opcional)")
st.file_uploader(
    "Archivos que el script pueda necesitar:",
    accept_multiple_files=True,
    key="user_files"
)

# Botón que llama a la función de generación
st.button("🚀 Generar y Ejecutar", on_click=generate_and_execute)
st.markdown("</div>", unsafe_allow_html=True)

# ----------------------------------------------------------------
# 7. MOSTRAR RESULTADOS SI DISPONIBLES
# ----------------------------------------------------------------
if st.session_state.results_available:
    # (Opcional) Ver Código Generado:
    # with st.expander("Ver Código Generado"):
    #     st.code(st.session_state.cleaned_code, language="python")

    # Layout en columnas: 70% (Reporte) y 30% (Archivos)
    col_report, col_files = st.columns([7, 3])

    with col_report:
        st.subheader("📋 Reporte")
        report = generate_report(
            st.session_state["user_prompt"],
            st.session_state.cleaned_code,
            st.session_state.execution_result.get("stdout", ""),
            st.session_state.generated_files
        )
        formatted_report = procesar_reporte(report, st.session_state.generated_files)
        st.markdown(f"<div class='report-container'>{formatted_report}</div>", unsafe_allow_html=True)

    with col_files:
        st.subheader("📁 Archivos Generados")
        browser = FileBrowser(st.session_state.generated_files)
        browser.render()

        # Botón para descargar todo en ZIP
        if st.session_state.generated_files:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zipf:
                for name, content in st.session_state.generated_files.items():
                    zipf.writestr(name, content)
            zip_buffer.seek(0)
            st.download_button(
                "⬇️ Descargar Todo (ZIP)", 
                zip_buffer, 
                "generated_files.zip", 
                "application/zip"
            )
