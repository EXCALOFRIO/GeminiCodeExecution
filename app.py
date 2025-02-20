import streamlit as st
import pandas as pd
from gemini_client import (
    generate_code,
    refine_code,
    get_dependencies,
    refine_dependencies,
    improve_code
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
        index=MODEL_OPTIONS.index("gemini-2.0-flash-exp")
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
# Se elimina la generación de nombre descriptivo; se usará un nombre por defecto.
if "base_name" not in st.session_state:
    st.session_state["base_name"] = "Codigo"
if "version_counter" not in st.session_state:
    st.session_state["version_counter"] = 1
if "last_status" not in st.session_state:
    st.session_state["last_status"] = ""  # OK, CODE, DEPENDENCY, BOTH, etc.
if "log_history" not in st.session_state:
    st.session_state["log_history"] = ""
if "input_files" not in st.session_state:
    st.session_state["input_files"] = {}

def get_current_version_label():
    """
    Devuelve la etiqueta en formato 'Codigo vX'
    """
    return f"{st.session_state['base_name']} v{st.session_state['version_counter']}"

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
        st.session_state["version_counter"] = 1
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
            "\nGenerate **only the complete Python code** that solves the user's instruction, "
            "ready to be executed in an isolated environment (Docker). Do not include explanatory comments, "
            "additional text, or code delimiters. Ensure that the code is directly executable and functional. "
            "The code should generate images when appropriate; for each image, it must save the image file to the "
            "project's root directory."
        )

        # Generación de código inicial
        with st.spinner("Generando código con Gemini..."):
            try:
                code_generated = generate_code(prompt, model_name=selected_model)
                code_generated = clean_code(code_generated)
                st.success("Código generado exitosamente.")
            except Exception as e:
                st.error(f"Error al generar código: {e}")
                st.stop()

        # Guardar primera versión
        version_label = get_current_version_label()
        st.session_state["versions"].append({
            "label": version_label,
            "code": code_generated,
            "dependencies": "",
            "logs": "",
            "stdout": "",
            "stderr": "",
            "files": {}
        })
        log_placeholder.info(f"Guardada versión inicial: {version_label}")

        # Obtener dependencias
        with st.spinner("Obteniendo listado de dependencias necesarias..."):
            try:
                dependencies = get_dependencies(code_generated, model_name=selected_model)
                dependencies = clean_code(dependencies)
                st.success("Dependencias obtenidas.")
            except Exception as e:
                st.error(f"Error al obtener dependencias: {e}")
                st.stop()

        # Actualizar dependencias en la versión inicial
        st.session_state["versions"][-1]["dependencies"] = dependencies

        # Bucle de validación e iteración
        codigo_actual = code_generated
        deps_actuales = dependencies
        logs_accum = ""
        for intento in range(1, int(max_attempts) + 1):
            log_placeholder.info(f"Iniciando ejecución en contenedor Docker (intento {intento})...")
            with st.spinner(f"Ejecutando código en contenedor Docker (intento {intento})..."):
                outputs = execute_code_in_docker(codigo_actual, input_files, deps_actuales)
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
                        st.session_state["version_counter"] += 1
                        version_label = get_current_version_label()
                        st.session_state["versions"].append({
                            "label": version_label,
                            "code": new_code,
                            "dependencies": deps_actuales,
                            "logs": "",
                            "stdout": "",
                            "stderr": "",
                            "files": {}
                        })
                        codigo_actual = new_code
                        log_placeholder.info(f"Código refinado: {version_label}")
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
                        st.session_state["version_counter"] += 1
                        version_label = get_current_version_label()
                        st.session_state["versions"].append({
                            "label": version_label,
                            "code": new_code,
                            "dependencies": deps_actuales,
                            "logs": "",
                            "stdout": "",
                            "stderr": "",
                            "files": {}
                        })
                        codigo_actual = new_code
                        log_placeholder.info(f"Código refinado (BOTH): {version_label}")
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
# ============= MOSTRAR RESULTADOS =========
# =========================================

if st.session_state.get("generated", False):
    # Siempre se muestra la última versión generada
    latest_version_data = st.session_state["versions"][-1]

    col_left, col_right = st.columns([1, 2], gap="medium")

    # -- Columna Izquierda: Dependencias y Logs --
    with col_left:
        st.subheader("Dependencias")
        deps_text = latest_version_data["dependencies"].strip() if latest_version_data["dependencies"].strip() else "Sin dependencias"
        st.text_area("Listado de dependencias", deps_text, height=150)

        st.subheader("Logs de Ejecución")
        st.text_area("Logs", st.session_state["log_history"], height=300)

    # -- Columna Derecha: Código --
    with col_right:
        st.subheader("Código Generado")
        st.code(latest_version_data["code"], language="python")

    # Caja para mostrar la lista de archivos generados
    if latest_version_data["files"]:
        st.markdown("### Archivos Generados")
        with st.expander("Ver archivos generados"):
            for fname, fcontent in latest_version_data["files"].items():
                st.write(f"- {fname}")
                st.download_button(
                    label=f"Descargar {fname}",
                    data=fcontent,
                    file_name=fname
                )
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
                current_code = latest_version_data["code"]
                current_deps = latest_version_data["dependencies"]
                for i in range(improvement_iterations):
                    st.session_state["version_counter"] += 1
                    version_label = get_current_version_label()
                    with st.spinner(f"Generando mejora {version_label}..."):
                        try:
                            # Generar código mejorado
                            improved_code = improve_code(current_code, improvement_instructions, model_name=selected_model)
                            improved_code = clean_code(improved_code)
                            
                            if improved_code.strip() == current_code.strip():
                                st.info(f"No se detectaron cambios en la iteración {version_label}. El código se considera perfecto.")
                                st.session_state["versions"].append({
                                    "label": version_label,
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
                                # Obtener las nuevas dependencias para el código mejorado
                                improved_deps = get_dependencies(current_code, model_name=selected_model)
                                improved_deps = clean_code(improved_deps)
                                current_deps = improved_deps

                                # Ejecutar el código mejorado en Docker y actualizar resultados
                                outputs = execute_code_in_docker(current_code, st.session_state["input_files"], current_deps)
                                
                                st.session_state["versions"].append({
                                    "label": version_label,
                                    "code": current_code,
                                    "dependencies": current_deps,
                                    "logs": "",
                                    "stdout": outputs.get("stdout", ""),
                                    "stderr": outputs.get("stderr", ""),
                                    "files": outputs.get("files", {})
                                })
                                st.success(f"Iteración {version_label} completada.")
                        except Exception as e:
                            st.error(f"Error en la iteración {version_label}: {e}")
                            break
                # Forzar la actualización de la UI tras las mejoras
                st.experimental_rerun()
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
