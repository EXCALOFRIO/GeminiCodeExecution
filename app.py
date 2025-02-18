# app.py
import streamlit as st
import pandas as pd
from gemini_client import (
    generate_code,
    refine_code,
    get_dependencies,
    refine_dependencies,
    improve_code,
    generate_code_name
)
from code_formatter import clean_code, format_output
from docker_executor import execute_code_in_docker, initialize_docker_image
from file_formatter import format_generated_file  # Para formatear CSV, imágenes, etc.
import os
import time

# =========================================
# ========== CONFIGURACIÓN Y UI ===========
# =========================================

st.set_page_config(page_title="AI Code Docker Executor", layout="wide")

# Inicializamos el entorno Docker una sola vez
if "docker_initialized" not in st.session_state:
    with st.spinner("Inicializando entorno Docker..."):
        docker_init_msg = initialize_docker_image()
        st.write(docker_init_msg)  # Mostrar mensaje de inicialización
    st.session_state["docker_initialized"] = True

# Panel lateral de configuraciones
with st.sidebar:
    st.header("Configuración Gemini")
    MODEL_OPTIONS = [
        "gemini-2.0-flash-lite-preview-02-05",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash-thinking-exp-01-21"
    ]
    selected_model = st.selectbox(
        "Modelo de Gemini:",
        MODEL_OPTIONS,
        index=MODEL_OPTIONS.index("gemini-2.0-flash-thinking-exp-01-21")
    )

    st.header("Parámetros de Ejecución")
    max_attempts = st.number_input(
        "Máx. intentos de refinamiento (errores)",
        min_value=1,
        max_value=10,
        value=5
    )
    improvement_iterations = st.number_input(
        "Iteraciones de mejora",
        min_value=1,
        max_value=10,
        value=1,
        help="Número de veces que Gemini revisará y mejorará el código tras ejecución exitosa."
    )

# Variables de sesión para almacenar el flujo
if "generated" not in st.session_state:
    st.session_state["generated"] = False  # Indica si ya se generó código
if "versions" not in st.session_state:
    # Cada elemento es un dict con información de cada versión generada
    st.session_state["versions"] = []
if "base_name" not in st.session_state:
    st.session_state["base_name"] = ""  # Nombre descriptivo base del código
if "major_version" not in st.session_state:
    st.session_state["major_version"] = 1
if "minor_version" not in st.session_state:
    st.session_state["minor_version"] = 0
if "last_status" not in st.session_state:
    st.session_state["last_status"] = ""  # OK, CODE, DEPENDENCY, BOTH, etc.
if "log_history" not in st.session_state:
    st.session_state["log_history"] = ""
if "input_files" not in st.session_state:
    st.session_state["input_files"] = {}
if "selected_version" not in st.session_state:
    st.session_state["selected_version"] = ""

def get_current_version_label():
    """
    Devuelve la etiqueta en formato 'base_name X.Y'
    """
    return f"{st.session_state['base_name']} {st.session_state['major_version']}.{st.session_state['minor_version']}"

def validate_execution(outputs):
    combined_output = outputs.get("stdout", "") + outputs.get("stderr", "")
    
    # Si se detecta "ModuleNotFoundError", se considera que falta una dependencia
    if "ModuleNotFoundError" in combined_output:
        return "DEPENDENCY", "Error en la generación de dependencias: módulo no encontrado."
    
    dependency_error = False
    code_error = False

    # Detectar errores de dependencias comunes
    if ("Could not find a version that satisfies" in combined_output or
        "No matching distribution found" in combined_output):
        dependency_error = True

    # Detectar errores de sintaxis o de ejecución en el código
    if ("SyntaxError" in combined_output or
        "invalid syntax" in combined_output or
        "Traceback" in combined_output):
        code_error = True

    if not dependency_error and not code_error:
        return "OK", "El código se ejecutó correctamente."
    if dependency_error and code_error:
        return "BOTH", "Se detectaron errores en dependencias y en el código."
    if dependency_error:
        return "DEPENDENCY", "Error en la generación de dependencias."
    if code_error:
        return "CODE", "Error en el código."


# =========================================
# =========== LÓGICA PRINCIPAL ============
# =========================================

st.title("AI Code Docker Executor")
st.markdown(
    "Genera y refina código Python usando la API de Gemini y ejecútalo en un "
    "entorno aislado (Docker) con validación y retroalimentación automática."
)

# Sección de entrada de datos (prompt + archivos)
with st.expander("Instrucciones y Archivos Adjuntos", expanded=True):
    user_instruction = st.text_area(
        "Instrucción (prompt) para generar código Python:",
        placeholder="Ejemplo: Analiza las ventas de un archivo Excel y crea un gráfico de barras comparando las ventas por producto."
    )

    uploaded_files = st.file_uploader(
        "Sube uno o varios archivos (opcional)",
        accept_multiple_files=True,
        help="Los archivos adjuntos se ubicarán en el mismo directorio que el script y serán analizados por Gemini."
    )

# Placeholder para mensajes y logs en tiempo real
log_placeholder = st.empty()

# Botón para generar y ejecutar el código
if st.button("Generar y Ejecutar Código"):
    if not user_instruction.strip():
        st.error("Por favor, ingresa una instrucción antes de generar el código.")
    else:
        # Reiniciar estado para un nuevo prompt
        st.session_state["generated"] = True
        st.session_state["versions"] = []
        st.session_state["base_name"] = ""
        st.session_state["major_version"] = 1
        st.session_state["minor_version"] = 0
        st.session_state["last_status"] = ""
        st.session_state["log_history"] = ""
        st.session_state["input_files"] = {}

        log_placeholder.info("Procesando archivos adjuntos...")
        # Procesar archivos
        input_files = {}
        resumen_archivos = ""
        for file in uploaded_files:
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
                    resumen_archivos += f"\nArchivo {file.name}: Se adjunta para uso en el código.\n"
            except Exception as e:
                resumen_archivos += f"\nNo se pudo procesar {file.name}: {e}\n"
        st.session_state["input_files"] = input_files
        log_placeholder.success("Archivos procesados correctamente.")

        # Construir prompt para generar código
        prompt = f"Instrucción del usuario:\n{user_instruction}\n"
        if resumen_archivos:
            prompt += f"\nInformación de archivos adjuntos:\n{resumen_archivos}\n"
        prompt += (
            "\nGenera **únicamente el código Python completo** que soluciona la instrucción del usuario, "
            "listo para ser ejecutado en un entorno aislado (Docker). "
            "No incluyas comentarios explicativos, texto adicional, ni delimitadores de código.\n"
            "Asegúrate de que el código sea directamente ejecutable y funcional."
        )

        # Generación de código inicial
        with st.spinner("Generando código con Gemini..."):
            try:
                code_generated = generate_code(prompt, model_name=selected_model)
                code_generated = clean_code(code_generated)
                st.success("Código generado exitosamente.")
                # Mostrar el código generado inmediatamente
                st.subheader("Código Generado")
                st.code(code_generated, language="python")
            except Exception as e:
                st.error(f"Error al generar código: {e}")
                st.stop()

        # Generación de nombre descriptivo
        with st.spinner("Generando nombre descriptivo para el código..."):
            try:
                descriptive_name = generate_code_name(code_generated, model_name=selected_model)
                descriptive_name = descriptive_name.strip()
                if not descriptive_name:
                    descriptive_name = "MiCodigo"
                st.session_state["base_name"] = descriptive_name
                st.success(f"Nombre descriptivo generado: {descriptive_name}")
            except Exception as e:
                st.error(f"Error al generar nombre descriptivo: {e}")
                st.session_state["base_name"] = "MiCodigo"

        # Obtener dependencias
        with st.spinner("Obteniendo listado de dependencias necesarias..."):
            try:
                dependencies = get_dependencies(code_generated, model_name=selected_model)
                dependencies = clean_code(dependencies)
                st.success("Dependencias obtenidas.")
            except Exception as e:
                st.error(f"Error al obtener dependencias: {e}")
                st.stop()

        # Guardar primera versión (1.0)
        version_label = get_current_version_label()
        st.session_state["versions"].append({
            "label": version_label,
            "code": code_generated,
            "dependencies": dependencies,
            "logs": "",
            "stdout": "",
            "stderr": "",
            "files": {}
        })
        log_placeholder.info(f"Guardada versión inicial: {version_label}")

        # Bucle de validación e iteración
        codigo_actual = code_generated
        deps_actuales = dependencies
        logs_accum = ""
        for intento in range(1, int(max_attempts) + 1):
            log_placeholder.info(f"Iniciando ejecución en contenedor Docker (intento {intento})...")
            with st.spinner(f"Ejecutando código en contenedor Docker (intento {intento})..."):
                outputs = execute_code_in_docker(codigo_actual, input_files, deps_actuales)
            logs_accum += f"\n--- Intento {intento} ---\n"
            logs_accum += f"stdout:\n{outputs.get('stdout','')}\n"
            logs_accum += f"stderr:\n{outputs.get('stderr','')}\n"
            status, msg = validate_execution(outputs)
            logs_accum += f"Validación: {status} - {msg}\n"
            # Actualizar logs en la versión actual
            st.session_state["versions"][-1]["logs"] = logs_accum
            st.session_state["versions"][-1]["stdout"] = outputs.get("stdout", "")
            st.session_state["versions"][-1]["stderr"] = outputs.get("stderr", "")
            st.session_state["versions"][-1]["files"] = outputs.get("files", {})

            log_placeholder.info(f"Intento {intento}: {msg}")
            # Actualización en tiempo real del log
            log_placeholder.text(logs_accum)
            time.sleep(0.5)  # Pausa breve para actualizar la UI

            if status == "OK":
                st.session_state["last_status"] = "OK"
                break
            elif status == "DEPENDENCY":
                st.session_state["last_status"] = "DEPENDENCY"
                with st.spinner("Refinando dependencias..."):
                    try:
                        new_deps = refine_dependencies(deps_actuales, codigo_actual, outputs, model_name=selected_model)
                        new_deps = clean_code(new_deps)
                        deps_actuales = new_deps
                        st.session_state["versions"][-1]["dependencies"] = deps_actuales
                        log_placeholder.info("Dependencias refinadas.")
                    except Exception as e:
                        logs_accum += f"Error al refinar dependencias: {e}\n"
                        log_placeholder.error(f"Error al refinar dependencias: {e}")
                        break
            elif status == "CODE":
                st.session_state["last_status"] = "CODE"
                with st.spinner("Refinando código..."):
                    try:
                        new_code = refine_code(codigo_actual, outputs, model_name=selected_model)
                        new_code = clean_code(new_code)
                        st.session_state["minor_version"] += 1
                        new_label = get_current_version_label()
                        st.session_state["versions"].append({
                            "label": new_label,
                            "code": new_code,
                            "dependencies": deps_actuales,
                            "logs": "",
                            "stdout": "",
                            "stderr": "",
                            "files": {}
                        })
                        codigo_actual = new_code
                        log_placeholder.info(f"Código refinado: {new_label}")
                    except Exception as e:
                        logs_accum += f"Error al refinar código: {e}\n"
                        log_placeholder.error(f"Error al refinar código: {e}")
                        break
            elif status == "BOTH":
                st.session_state["last_status"] = "BOTH"
                with st.spinner("Refinando dependencias y código..."):
                    try:
                        new_deps = refine_dependencies(deps_actuales, codigo_actual, outputs, model_name=selected_model)
                        new_deps = clean_code(new_deps)
                        deps_actuales = new_deps
                        st.session_state["versions"][-1]["dependencies"] = deps_actuales
                        log_placeholder.info("Dependencias refinadas (BOTH).")
                    except Exception as e:
                        logs_accum += f"Error al refinar dependencias: {e}\n"
                        log_placeholder.error(f"Error al refinar dependencias: {e}")
                        break
                    try:
                        new_code = refine_code(codigo_actual, outputs, model_name=selected_model)
                        new_code = clean_code(new_code)
                        st.session_state["minor_version"] += 1
                        new_label = get_current_version_label()
                        st.session_state["versions"].append({
                            "label": new_label,
                            "code": new_code,
                            "dependencies": deps_actuales,
                            "logs": "",
                            "stdout": "",
                            "stderr": "",
                            "files": {}
                        })
                        codigo_actual = new_code
                        log_placeholder.info(f"Código refinado (BOTH): {new_label}")
                    except Exception as e:
                        logs_accum += f"Error al refinar código: {e}\n"
                        log_placeholder.error(f"Error al refinar código: {e}")
                        break
            else:
                logs_accum += "Estado de validación desconocido.\n"
                log_placeholder.error("Estado de validación desconocido.")
                break

            if intento == max_attempts:
                logs_accum += "Alcanzado el número máximo de intentos.\n"
                log_placeholder.warning("Alcanzado el número máximo de intentos.")

        st.session_state["log_history"] = logs_accum

# =========================================
# ============= MOSTRAR RESULTADOS ========
# =========================================

if st.session_state.get("generated", False):

    # Layout principal en dos columnas
    col_left, col_right = st.columns([1, 2], gap="medium")

    # -- Columna Izquierda: Dependencias y Logs --
    with col_left:
        st.subheader("Dependencias")
        version_labels = [v["label"] for v in st.session_state["versions"]]
        if st.session_state["selected_version"] not in version_labels:
            st.session_state["selected_version"] = version_labels[-1] if version_labels else ""
        selected_label = st.selectbox(
            "Selecciona la versión para ver dependencias y logs:",
            version_labels,
            index=version_labels.index(st.session_state["selected_version"]) if st.session_state["selected_version"] in version_labels else 0
        )
        st.session_state["selected_version"] = selected_label
        selected_version_data = next((v for v in st.session_state["versions"] if v["label"] == selected_label), None)
        if selected_version_data:
            deps_text = selected_version_data["dependencies"] if selected_version_data["dependencies"].strip() else "Sin dependencias"
            st.text_area("Listado de dependencias", deps_text, height=150)
            st.subheader("Logs Generales")
            st.text_area("Logs", selected_version_data["logs"], height=200)

    # -- Columna Derecha: Código --
    with col_right:
        st.subheader("Código")
        selected_version_code_label = st.selectbox(
            "Selecciona la versión para ver el código:",
            version_labels,
            index=version_labels.index(st.session_state["selected_version"]) if st.session_state["selected_version"] in version_labels else 0
        )
        st.session_state["selected_version"] = selected_version_code_label
        version_data_for_code = next((v for v in st.session_state["versions"] if v["label"] == selected_version_code_label), None)
        if version_data_for_code:
            st.code(version_data_for_code["code"], language="python")

    # -- Sección de Output --
    st.subheader("Output")
    if selected_version_data:
        st.markdown("**stdout:**")
        st.text_area("stdout", format_output(selected_version_data["stdout"]), height=150)
        st.markdown("**stderr:**")
        st.text_area("stderr", format_output(selected_version_data["stderr"]), height=150)

        # Mostrar archivos generados con formato adecuado
        if selected_version_data["files"]:
            st.markdown("**Archivos generados:**")
            for fname, fcontent in selected_version_data["files"].items():
                st.markdown(f"**{fname}**")
                st.download_button(
                    label=f"Descargar {fname}",
                    data=fcontent,
                    file_name=fname
                )
                # Vista previa formateada (CSV, imagen, etc.)
                preview = format_generated_file(fname, fcontent)
                st.markdown(preview, unsafe_allow_html=True)

    # ======================================
    # ============ MEJORAS ADICIONALES =====
    # ======================================
    if st.session_state["last_status"] == "OK":
        st.markdown("---")
        st.markdown("### Mejoras Adicionales")
        improvement_instructions = st.text_area(
            "Instrucciones de mejora:",
            placeholder="Ejemplo: Optimiza la eficiencia, agrega manejo de excepciones, etc."
        )
        if st.button("Aplicar Iteraciones de Mejora"):
            if improvement_instructions.strip():
                st.session_state["major_version"] += 1
                st.session_state["minor_version"] = 0
                current_code = selected_version_data["code"]
                current_deps = selected_version_data["dependencies"]
                for i in range(improvement_iterations):
                    if i > 0:
                        st.session_state["minor_version"] += 1
                    new_label = get_current_version_label()
                    with st.spinner(f"Generando mejora {new_label}..."):
                        try:
                            improved_code = improve_code(current_code, improvement_instructions, model_name=selected_model)
                            improved_code = clean_code(improved_code)
                            if improved_code.strip() == current_code.strip():
                                st.info(f"No se detectaron cambios en la iteración {new_label}. El código se considera perfecto.")
                                st.session_state["versions"].append({
                                    "label": new_label,
                                    "code": current_code,
                                    "dependencies": current_deps,
                                    "logs": "Sin cambios en la iteración de mejora.",
                                    "stdout": "",
                                    "stderr": "",
                                    "files": {}
                                })
                                break
                            else:
                                current_code = improved_code
                                st.session_state["versions"].append({
                                    "label": new_label,
                                    "code": current_code,
                                    "dependencies": current_deps,
                                    "logs": "",
                                    "stdout": "",
                                    "stderr": "",
                                    "files": {}
                                })
                                outputs = execute_code_in_docker(current_code, st.session_state["input_files"], current_deps)
                                st.session_state["versions"][-1]["stdout"] = outputs.get("stdout", "")
                                st.session_state["versions"][-1]["stderr"] = outputs.get("stderr", "")
                                st.session_state["versions"][-1]["files"] = outputs.get("files", {})
                                st.success(f"Iteración {new_label} completada.")
                        except Exception as e:
                            st.error(f"Error en la iteración {new_label}: {e}")
                            break
                st.session_state["selected_version"] = get_current_version_label()
                st.success("Mejoras iterativas completadas.")
            else:
                st.info("Por favor, ingresa instrucciones de mejora antes de aplicar las iteraciones.")
    else:
        st.info("No se permiten mejoras adicionales porque la ejecución todavía no es OK o se alcanzó el número máximo de intentos.")

    # Botón para reiniciar y comenzar un nuevo prompt
    if st.button("Nuevo Prompt"):
        keys_to_keep = ["docker_initialized"]
        for key in list(st.session_state.keys()):
            if key not in keys_to_keep:
                del st.session_state[key]
        st.experimental_rerun()
