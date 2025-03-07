import re
import streamlit as st
import io
import zipfile
import pandas as pd
import ast
import concurrent.futures
import time
import os
from typing import Dict, List

from gemini_client import (
    generate_code,
    analyze_execution_result,
    generate_report,
    configure_gemini,
    rank_solutions
)
from docker_executor import initialize_docker_image, execute_code_in_docker, clean_unused_images, clean_unused_containers
from code_formatter import clean_code  # Asumo que existe este módulo

# Limpieza inicial
clean_unused_images()
clean_unused_containers()

# Configuración de caché
@st.cache_resource
def init_docker() -> str:
    return initialize_docker_image()

@st.cache_resource
def init_gemini() -> str:
    return configure_gemini()

st.set_page_config(page_title="Generador de Código Python", layout="wide")

# Verificación inicial
docker_init_message = init_docker()
if "Error" in docker_init_message:
    st.error(docker_init_message, icon="❌")
    st.stop()

# Estilos CSS
st.markdown("""
<style>
.attempt-counter { color: #00BCD4; font-weight: bold; }
.success-message { color: #4CAF50; font-weight: bold; }
.error-message { color: #F44336; font-weight: bold; }
.report-container { padding: 20px; border-radius: 8px; margin-top: 20px; box-shadow: 0px 2px 8px rgba(0,0,0,0.3); }
.file-preview { padding: 15px; border-radius: 8px; margin-top: 10px; box-shadow: 0px 2px 8px rgba(0,0,0,0.3); }
.parallel-result { border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# Inicialización de estado
_ = init_gemini()
for key in ["attempts", "execution_history", "generated_files", "results_available", "formatted_report", 
            "execution_result", "preview_active", "preview_file", "preview_content", "all_files", "parallel_results"]:
    if key not in st.session_state:
        st.session_state[key] = [] if key in ["execution_history", "parallel_results"] else {} if key in ["generated_files", "execution_result", "all_files"] else False if key in ["results_available", "preview_active"] else None if key in ["preview_file", "preview_content", "formatted_report"] else 0

# Funciones auxiliares
def show_file_preview(file_name: str, file_content: bytes) -> None:
    st.session_state.preview_file = file_name
    st.session_state.preview_content = file_content
    st.session_state.preview_active = True

def close_file_preview() -> None:
    st.session_state.preview_file = None
    st.session_state.preview_content = None
    st.session_state.preview_active = False

def display_file_preview() -> None:
    if not st.session_state.preview_active or not st.session_state.preview_file:
        return
    file_name = st.session_state.preview_file
    file_content = st.session_state.preview_content
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
        st.code(file_content.decode('utf-8', errors='ignore'), language='python')
    else:
        st.text_area("Contenido", file_content.decode('utf-8', errors='ignore'), height=300)
    st.button("Cerrar Vista Previa", on_click=close_file_preview)

class FileBrowser:
    def __init__(self, files_dict: Dict[str, bytes]):
        self.files_dict = files_dict

    def render(self) -> None:
        if not self.files_dict:
            st.info("No se han generado archivos aún.", icon="ℹ️")
            return
        for file_name, content in self.files_dict.items():
            col1, col2 = st.columns([4, 1])
            col1.button(f"📄 {file_name}", key=f"preview_{file_name}", on_click=show_file_preview, args=(file_name, content))
            col2.download_button("⬇️", data=content, file_name=file_name, key=f"dl_{file_name}")

def process_report_content(report: str, files_dict: Dict[str, bytes]) -> List[Dict]:
    parts = []
    file_marker_regex = re.compile(r"\{\{(.+?)\}\}")
    last_end = 0
    for match in file_marker_regex.finditer(report):
        start, end = match.span()
        text_chunk = report[last_end:start].strip()
        if text_chunk:
            parts.append({"type": "text", "content": text_chunk})
        file_name = match.group(1)
        parts.append({"type": "file", "name": file_name, "content": files_dict.get(file_name, b"Archivo no encontrado")})
        last_end = end
    if last_end < len(report):
        parts.append({"type": "text", "content": report[last_end:].strip()})
    return parts

def display_processed_report(processed_report: List[Dict]) -> None:
    for item in processed_report:
        if item["type"] == "text":
            st.markdown(item["content"], unsafe_allow_html=True)
        else:
            file_name, file_content = item["name"], item["content"]
            st.subheader(f"Archivo: {file_name}")
            file_ext = file_name.split('.')[-1].lower()
            if file_ext in ['png', 'jpg', 'jpeg', 'gif']:
                st.image(file_content, caption=file_name)
            elif file_ext == 'csv':
                try:
                    df = pd.read_csv(io.BytesIO(file_content))
                    st.dataframe(df)
                except Exception as e:
                    st.error(f"Error al mostrar CSV: {e}")
            else:
                st.text_area("Contenido", file_content.decode('utf-8', errors='ignore'), height=300)

# Funciones principales
def generate_and_execute(task_id: int, input_files: Dict[str, bytes], prompt: str) -> Dict:
    enhanced_prompt = f"{prompt}\n\nManeja casos donde los archivos estén vacíos o no contengan datos esperados."
    max_attempts = 5
    for attempt in range(max_attempts):
        response = generate_code(enhanced_prompt, input_files)
        code = response.get("code", "")
        dependencies = response.get("dependencies", "")
        if not code.strip():
            continue
        cleaned_code = clean_code(code)
        try:
            ast.parse(cleaned_code)
            execution_result = execute_code_in_docker(cleaned_code, input_files, dependencies)
            analysis = analyze_execution_result(execution_result)
            if analysis.get("error_type") == "OK":
                generated_files = execution_result["files"]
                all_files = input_files.copy()
                all_files.update({"script.py": cleaned_code.encode('utf-8')})
                all_files.update(generated_files)
                return {
                    "task_id": task_id,
                    "code": cleaned_code,
                    "dependencies": dependencies,
                    "execution_result": execution_result,
                    "generated_files": generated_files,
                    "all_files": all_files,
                    "attempts": attempt + 1,
                    "is_successful": True
                }
        except SyntaxError:
            continue
    return {"task_id": task_id, "attempts": max_attempts, "execution_result": {}, "is_successful": False}

def parallel_execution() -> None:
    st.session_state.parallel_results = []
    num_executions = 5
    uploaded_files = st.session_state.get("user_files", [])
    input_files = {file.name: file.read() for file in uploaded_files}
    prompt = st.session_state["user_prompt"]
    
    temp_root = os.path.join(os.getcwd(), ".temp")
    os.makedirs(temp_root, exist_ok=True)
    
    with st.spinner("Ejecutando tareas en paralelo..."):
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_executions) as executor:
            futures = {executor.submit(generate_and_execute, i + 1, input_files, prompt): i + 1 for i in range(num_executions)}
            results = []
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result.get("is_successful", False):
                    timestamp = int(time.time() * 1000)
                    temp_dir = os.path.join(temp_root, f"tarea_{result['task_id']}_{timestamp}")
                    os.makedirs(temp_dir, exist_ok=True)
                    result["temp_dir"] = temp_dir
                    
                    with open(os.path.join(temp_dir, "script.py"), "w") as f:
                        f.write(result["code"])
                    with open(os.path.join(temp_dir, "requirements.txt"), "w") as f:
                        f.write(result["dependencies"])
                    for file_name, content in result["generated_files"].items():
                        file_path = os.path.join(temp_dir, file_name)
                        with open(file_path, "wb") as f:
                            f.write(content if isinstance(content, bytes) else content.encode('utf-8'))
                    
                    st.success(f"Tarea {result['task_id']}: Ejecutada exitosamente. Archivos en {temp_dir}", icon="✅")
                else:
                    st.error(f"Tarea {result['task_id']}: Falló tras {result['attempts']} intentos.", icon="❌")
                results.append(result)
    
    successful_results = [r for r in results if r.get("is_successful", False)]
    if not successful_results:
        st.error("No se obtuvieron resultados exitosos.", icon="❌")
        return
    
    rankings = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(rank_solutions, successful_results) for _ in range(5)]
        rankings = [future.result() for future in concurrent.futures.as_completed(futures)]
    
    sum_rankings = [sum(ranks[i] for ranks in rankings) for i in range(len(successful_results))]
    best_index = sum_rankings.index(min(sum_rankings))
    best_result = successful_results[best_index]
    
    st.session_state.results_available = True
    st.session_state.generated_files = best_result["generated_files"]
    st.session_state.cleaned_code = best_result["code"]
    st.session_state.execution_result = best_result["execution_result"]
    st.session_state.all_files = best_result["all_files"]
    st.session_state.formatted_report = generate_report(prompt, best_result["code"], best_result["execution_result"].get("stdout", ""), best_result["generated_files"])
    st.success(f"Tarea {best_result['task_id']} obtuvo la mejor suma de rankings ({sum_rankings[best_index]}).", icon="🏆")
    st.session_state.parallel_results = results

# Interfaz principal
if st.session_state.preview_active:
    display_file_preview()

st.subheader("📝 Describe tu Tarea")
st.text_area("Escribe qué quieres que haga el código:", key="user_prompt", height=150, placeholder="Ejemplo: 'Generar un gráfico de barras a partir de un CSV.'")

st.subheader("📂 Sube Archivos (Opcional)")
st.file_uploader("Archivos necesarios para el script:", accept_multiple_files=True, key="user_files")

if st.button("🚀 Generar y Ejecutar (Paralelo)"):
    parallel_execution()

# Resultados
if st.session_state.results_available:
    col_report, col_files = st.columns([5, 3])
    with col_report:
        st.subheader("📋 Reporte")
        processed_report = process_report_content(st.session_state.formatted_report, st.session_state.generated_files)
        display_processed_report(processed_report)
    with col_files:
        st.subheader("📁 Archivos Generados")
        FileBrowser(st.session_state.generated_files).render()
        if st.session_state.generated_files:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zipf:
                for name, content in st.session_state.generated_files.items():
                    zipf.writestr(name, content if isinstance(content, bytes) else content.encode('utf-8'))
            zip_buffer.seek(0)
            st.download_button("⬇️ Descargar Todo (ZIP)", zip_buffer, "generated_files.zip", "application/zip")

# Resultados paralelos
if st.session_state.parallel_results:
    st.subheader("📊 Resultados Paralelos")
    successful_results = [r for r in st.session_state.parallel_results if r.get("is_successful", False)]
    rankings = []
    if successful_results:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(rank_solutions, successful_results) for _ in range(5)]
            rankings = [f.result() for f in concurrent.futures.as_completed(futures)]
    
    data = []
    sum_rankings = [sum(r[i] for r in rankings) for i in range(len(successful_results))] if rankings else []
    for result in st.session_state.parallel_results:
        row = {"Tarea": result['task_id'], "Intentos": result['attempts']}
        if result.get("is_successful", False):
            idx = successful_results.index(result)
            row.update({"Suma de Rankings": sum_rankings[idx], "Rankings": ", ".join(map(str, [r[idx] for r in rankings]))})
        else:
            row.update({"Suma de Rankings": "N/A", "Rankings": "N/A"})
        data.append(row)
    st.dataframe(pd.DataFrame(data))
    
    for result in successful_results:
        with st.expander(f"Detalles de Tarea {result['task_id']}"):
            st.write(f"**Directorio Temporal:** {result['temp_dir']}")
            st.code(result["code"], language="python")
            st.text(result["dependencies"])
            st.text(result["execution_result"].get("stdout", ""))
            if result["execution_result"].get("stderr"):
                st.text(result["execution_result"]["stderr"])
            for file_name, content in result["generated_files"].items():
                st.download_button(f"⬇️ {file_name}", content, file_name, key=f"dl_{result['task_id']}_{file_name}")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zipf:
                zipf.writestr("script.py", result["code"])
                zipf.writestr("requirements.txt", result["dependencies"])
                for name, content in result["generated_files"].items():
                    zipf.writestr(name, content if isinstance(content, bytes) else content.encode('utf-8'))
            zip_buffer.seek(0)
            st.download_button(f"⬇️ Todo (ZIP) - Tarea {result['task_id']}", zip_buffer, f"tarea_{result['task_id']}_files.zip")