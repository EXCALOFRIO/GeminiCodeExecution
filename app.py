import streamlit as st
import io
import zipfile

from gemini_client import configure_gemini, improve_prompt, generate_code, analyze_execution_result, generate_fix, generate_report
from docker_executor import initialize_docker_image, execute_code_in_docker
from code_formatter import clean_code

# Configuración de la página Streamlit
st.set_page_config(page_title="Generador de Código Python", layout="wide")

# Título y descripción
st.title("✨ Generador de Código Python con IA")
st.markdown("Describe tu problema o tarea y sube archivos si es necesario. ¡La IA generará y ejecutará el código por ti!")

# --- Inicialización ---
if "docker_initialized" not in st.session_state:
    with st.spinner("Inicializando Docker..."):
        init_message = initialize_docker_image()
        st.session_state.docker_initialized = True
        st.success(f"Docker listo: {init_message}")

if "gemini_configured" not in st.session_state:
    with st.spinner("Configurando Gemini..."):
        configure_gemini()
        st.session_state.gemini_configured = True
        st.success("Gemini configurado.")

# --- Interfaz de usuario ---
st.subheader("📝 Describe tu Tarea")
prompt = st.text_area("Escribe qué quieres que haga el código Python:", height=150)

st.subheader("📂 Sube Archivos (Opcional)")
uploaded_files = st.file_uploader("Archivos que el script pueda necesitar:", accept_multiple_files=True)

# Estado de sesión
if "attempts" not in st.session_state:
    st.session_state.attempts = 0
if "execution_history" not in st.session_state:
    st.session_state.execution_history = []

error_container = st.empty()

# --- Lógica principal ---
if st.button("🚀 Generar y Ejecutar"):
    if not prompt:
        st.error("Por favor, escribe una descripción antes de generar.")
    else:
        st.session_state.attempts = 0
        st.session_state.execution_history = []
        error_container.empty()

        input_files = {file.name: file.read() for file in uploaded_files} if uploaded_files else {}

        # Mejorar el prompt
        with st.spinner("🧠 Mejorando el prompt..."):
            improved_prompt = improve_prompt(prompt, input_files)

        while st.session_state.attempts < 10:
            st.info(f"🔄 Intento {st.session_state.attempts + 1}/10")

            # Generar código y dependencias
            with st.spinner("📜 Generando código..."):
                response = generate_code(improved_prompt, input_files)
                generated_code = response["code"]
                dependencies = response["dependencies"]
                cleaned_code = clean_code(generated_code)

            # Ejecutar en Docker
            with st.spinner("🏃 Ejecutando en Docker..."):
                execution_result = execute_code_in_docker(cleaned_code, input_files, dependencies)

            # Analizar resultado
            with st.spinner("🧐 Analizando resultado..."):
                analysis = analyze_execution_result(execution_result)
                st.session_state.execution_history.append({
                    "code": cleaned_code,
                    "dependencies": dependencies,
                    "result": execution_result,
                    "error_type": analysis["error_type"],
                    "error_message": analysis["error_message"]
                })

            if analysis["error_type"] == "OK":
                st.success("✅ ¡Éxito!")
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("📜 Código")
                    st.code(cleaned_code, language="python")
                    st.subheader("📦 Dependencias")
                    st.write(dependencies or "Ninguna")
                    st.subheader("📤 Salida")
                    st.text(execution_result.get("stdout", "Sin salida"))
                with col2:
                    st.subheader("📂 Archivos Generados")
                    if execution_result.get("files"):
                        for name, content in execution_result["files"].items():
                            st.write(f"**{name}**")
                            if name.endswith((".png", ".jpg")):
                                st.image(content)
                            else:
                                st.text(content.decode("utf-8", errors="ignore"))
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w") as zipf:
                            for name, content in execution_result["files"].items():
                                zipf.writestr(name, content)
                        zip_buffer.seek(0)
                        st.download_button("⬇️ Descargar Archivos", zip_buffer, "files.zip", "application/zip")
                    else:
                        st.write("Ningún archivo generado.")

                # Generar reporte
                with st.spinner("📑 Generando reporte..."):
                    report = generate_report(prompt, cleaned_code, execution_result.get("stdout", ""), execution_result.get("files", {}))
                st.markdown("### 📋 Reporte")
                st.markdown(report, unsafe_allow_html=True)
                break

            else:
                error_container.error(f"🚨 Error en intento {st.session_state.attempts + 1}: {analysis['error_type']} - {analysis['error_message']}")
                st.session_state.attempts += 1
                if st.session_state.attempts >= 10:
                    error_container.error("❌ Límite de 10 intentos alcanzado.")
                    break
                with st.spinner("🔧 Generando corrección..."):
                    fix = generate_fix(analysis["error_type"], analysis["error_message"], cleaned_code, dependencies)
                    generated_code = fix["code"]
                    dependencies = fix["dependencies"]
                    improved_prompt = fix.get("improved_prompt", improved_prompt)