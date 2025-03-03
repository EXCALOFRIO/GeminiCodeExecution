import re
import streamlit as st
import io
import zipfile
import pandas as pd
import ast
import concurrent.futures
import time

from gemini_client import (
    generate_code,
    analyze_execution_result,
    generate_report,
    configure_gemini,
    evaluate_execution,
    rank_solutions
)
from docker_executor import initialize_docker_image, execute_code_in_docker, clean_unused_images, clean_unused_containers
from code_formatter import clean_code

# Limpieza de recursos al inicio
clean_unused_images()
clean_unused_containers()

# Cache y configuración
@st.cache_resource
def init_docker():
    return initialize_docker_image()

@st.cache_resource
def init_gemini():
    configure_gemini()
    return "OK"

st.set_page_config(page_title="Generador de Código Python", layout="wide")

# Verificación de Docker
docker_init_message = init_docker()
if "Error" in docker_init_message:
    st.error(docker_init_message, icon="❌")
    st.stop()

# Estilos CSS
st.markdown("""
<style>
.attempt-counter { color: #00BCD4; font-weight: bold; }
.action { color: #90A4AE; margin-left: 10px; font-style: italic; }
.success-message { color: #4CAF50; font-weight: bold; }
.error-message { color: #F44336; font-weight: bold; }
.report-container { padding: 20px; border-radius: 8px; margin-top: 20px; box-shadow: 0px 2px 8px rgba(0,0,0,0.3); }
.file-preview { padding: 15px; border-radius: 8px; margin-top: 10px; box-shadow: 0px 2px 8px rgba(0,0,0,0.3); }
.file-container { width: 70%; margin: auto; }
.parallel-result { border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# Inicialización de sesión
_ = init_gemini()

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
if "parallel_results" not in st.session_state:
    st.session_state.parallel_results = []

# Funciones auxiliares
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
        st.markdown("<div class='file-container'>", unsafe_allow_html=True)
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
    parts = []
    file_marker_regex = re.compile(r"\{\{(.+?)\}\}")
    last_end = 0
    for match in file_marker_regex.finditer(report):
        file_name = match.group(1)
        start, end = match.span()
        text_chunk = report[last_end:start].strip()
        if text_chunk:
            parts.append({"type": "text", "content": text_chunk})
        if file_name in files_dict:
            parts.append({"type": "file", "name": file_name, "content": files_dict[file_name]})
        else:
            parts.append({"type": "text", "content": f"**Archivo no encontrado:** {file_name}"})
        last_end = end
    remaining_text = report[last_end:].strip()
    if remaining_text:
        parts.append({"type": "text", "content": remaining_text})
    return parts

def display_processed_report(processed_report):
    for item in processed_report:
        if item["type"] == "text":
            st.markdown(item["content"], unsafe_allow_html=True)
        elif item["type"] == "file":
            file_name = item["name"]
            file_content = item["content"]
            file_ext = file_name.split('.')[-1].lower()
            st.subheader(f"Archivo: {file_name}")
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
                    st.warning(f"No se puede mostrar el contenido de {file_name}.", icon="⚠️")

# Funciones principales
def generate_and_execute(task_id, input_files, prompt):
    prompt_with_error_handling = f"{prompt}\n\nAsegúrate de manejar casos donde los archivos estén vacíos o no contengan datos esperados."
    time.sleep(0.5)
    attempts = 0
    max_attempts = 3
    execution_result = None
    while attempts < max_attempts:
        attempts += 1
        response = generate_code(prompt_with_error_handling, input_files)
        generated_code = response.get("code", "")
        dependencies = response.get("dependencies", "")
        if not generated_code.strip():
            continue
        cleaned_code = clean_code(generated_code)
        try:
            ast.parse(cleaned_code)
        except SyntaxError:
            continue
        execution_result = execute_code_in_docker(cleaned_code, input_files, dependencies)
        analysis = analyze_execution_result(execution_result)
        if analysis.get("error_type", "") == "OK":
            generated_files = execution_result["files"]
            all_files = input_files.copy()
            all_files.update({"script.py": cleaned_code})
            all_files.update(generated_files)
            return {
                "task_id": task_id,
                "code": cleaned_code,
                "dependencies": dependencies,
                "execution_result": execution_result,
                "generated_files": generated_files,
                "all_files": all_files,
                "attempts": attempts,
                "is_successful": True
            }
    return {
        "task_id": task_id,
        "attempts": attempts,
        "execution_result": execution_result or {},
        "is_successful": False
    }

def parallel_execution():
    st.session_state.parallel_results = []
    num_executions = 5
    uploaded_files = st.session_state.get("user_files", [])
    input_files = {file.name: file.read() for file in uploaded_files}
    prompt = st.session_state["user_prompt"]
    with st.spinner("Ejecutando tareas en paralelo..."):
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_executions) as executor:
            futures = {
                executor.submit(generate_and_execute, i + 1, input_files, prompt): i + 1
                for i in range(num_executions)
            }
            results = []
            for future in concurrent.futures.as_completed(futures):
                task_id = futures[future]
                result = future.result()
                results.append(result)
                if result.get("is_successful", False):
                    st.success(f"Tarea {task_id}: Ejecutada exitosamente.", icon="✅")
                else:
                    st.error(f"Tarea {task_id}: Falló tras {result['attempts']} intentos.", icon="❌")
    
    # Filtrar resultados exitosos
    successful_results = [result for result in results if result.get("is_successful", False)]
    if not successful_results:
        st.error("No se obtuvieron resultados exitosos.", icon="❌")
        return
    
    # Realizar 5 rankings de las soluciones exitosas
    rankings = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(rank_solutions, successful_results) for _ in range(5)]
        for future in concurrent.futures.as_completed(futures):
            rankings.append(future.result())
    
    # Calcular la suma de rankings para cada solución
    sum_rankings = [sum(ranks[i] for ranks in rankings) for i in range(len(successful_results))]
    
    # Encontrar la solución con la suma más baja
    best_index = sum_rankings.index(min(sum_rankings))
    best_result = successful_results[best_index]
    
    # Actualizar estado con la mejor solución
    st.session_state.results_available = True
    st.session_state.generated_files = best_result["generated_files"]
    st.session_state.cleaned_code = best_result["code"]
    st.session_state.execution_result = best_result["execution_result"]
    st.session_state.all_files = best_result["all_files"]
    st.session_state.formatted_report = generate_report(
        prompt,
        st.session_state.cleaned_code,
        st.session_state.execution_result.get("stdout", ""),
        st.session_state.generated_files
    )
    st.success(f"La tarea {best_result['task_id']} obtuvo la mejor suma de rankings ({sum_rankings[best_index]}).", icon="🏆")
    st.session_state.parallel_results = results

# Interfaz principal
if st.session_state.preview_active:
    display_file_preview()

st.subheader("📝 Describe tu Tarea")
st.text_area(
    "Escribe qué quieres que haga el código Python:",
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

if st.button("🚀 Generar y Ejecutar (Paralelo)"):
    parallel_execution()

# Mostrar resultados
if st.session_state.results_available:
    col_report, col_files = st.columns([5, 3])
    with col_report:
        st.subheader("📋 Reporte")
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

# Mostrar resultados paralelos
if st.session_state.parallel_results:
    st.subheader("📊 Resultados de Todas las Tareas Paralelas")
    data = []
    successful_results = [r for r in st.session_state.parallel_results if r.get("is_successful", False)]
    rankings = []
    if successful_results:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(rank_solutions, successful_results) for _ in range(5)]
            for future in concurrent.futures.as_completed(futures):
                rankings.append(future.result())
    sum_rankings = [sum(ranks[i] for ranks in rankings) for i in range(len(successful_results))] if rankings else []
    
    for result in st.session_state.parallel_results:
        if result.get("is_successful", False):
            index = successful_results.index(result)
            data.append({
                "Tarea": result['task_id'],
                "Intentos": result['attempts'],
                "Suma de Rankings": sum_rankings[index],
                "Rankings": ", ".join(map(str, [ranks[index] for ranks in rankings]))
            })
        else:
            data.append({
                "Tarea": result['task_id'],
                "Intentos": result['attempts'],
                "Suma de Rankings": "N/A (Failed)",
                "Rankings": "N/A (Failed)"
            })
    df = pd.DataFrame(data)
    st.dataframe(df)