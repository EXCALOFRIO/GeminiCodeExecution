import threading
import time
import docker
import tempfile
import os
import hashlib
import logging
import requests

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE_IMAGE_NAME = "python_executor:latest"

def initialize_docker_image():
    """Inicializa la imagen base de Docker si no existe."""
    client = docker.from_env()
    try:
        client.images.get(BASE_IMAGE_NAME)
        logging.info("Imagen Docker base ya existente.")
        return "Imagen Docker base ya existente."
    except docker.errors.ImageNotFound:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dockerfile_path = os.path.join(script_dir, "executor")
            if not os.path.exists(dockerfile_path):
                error_msg = f"Error: El directorio {dockerfile_path} no existe o no contiene un Dockerfile."
                logging.error(error_msg)
                return error_msg
            logging.info(f"Construyendo imagen Docker base desde {dockerfile_path}...")
            image, logs = client.images.build(path=dockerfile_path, tag=BASE_IMAGE_NAME)
            for item in logs:
                logging.info(item.get('stream', ''))
            return "Imagen Docker base construida exitosamente."
        except Exception as e:
            error_msg = f"Error al construir la imagen Docker: {e}"
            logging.error(error_msg)
            return error_msg
    except Exception as e:
        error_msg = f"Error al conectar con el daemon de Docker: {e}. Asegúrate de que Docker esté corriendo."
        logging.error(error_msg)
        return error_msg

def get_or_create_cached_image(dependencies: str) -> str:
    """Obtiene o crea una imagen Docker con las dependencias especificadas."""
    if not dependencies.strip():
        logging.info("No se especificaron dependencias, usando imagen base.")
        return BASE_IMAGE_NAME

    dep_lines = []
    for line in dependencies.split('\n'):
        line = line.strip()
        if line:
            deps = [dep.strip() for dep in line.split(',') if dep.strip()]
            dep_lines.extend(deps)
    if not dep_lines:
        logging.warning("Advertencia: dependencies está vacío después de limpiar, usando imagen base.")
        return BASE_IMAGE_NAME
    cleaned_dependencies = '\n'.join(dep_lines)
    
    dep_hash = hashlib.sha256(cleaned_dependencies.encode("utf-8")).hexdigest()[:12]
    cached_image_name = f"python_executor_cache:{dep_hash}"
    client = docker.from_env()

    try:
        client.images.get(cached_image_name)
        logging.info(f"Imagen encontrada: {cached_image_name}")
        return cached_image_name
    except docker.errors.ImageNotFound:
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile_content = f"""
            FROM {BASE_IMAGE_NAME}
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install --no-cache-dir -r requirements.txt
            """
            dockerfile_path = os.path.join(tmpdir, "Dockerfile")
            with open(dockerfile_path, "w") as f:
                f.write(dockerfile_content.strip())
            req_path = os.path.join(tmpdir, "requirements.txt")
            with open(req_path, "w") as f:
                f.write(cleaned_dependencies)
            logging.info(f"Contenido de requirements.txt:\n{cleaned_dependencies}")
            try:
                logging.info(f"Construyendo imagen para dependencias: {cached_image_name}")
                image, logs = client.images.build(path=tmpdir, tag=cached_image_name)
                for item in logs:
                    logging.info(item.get('stream', ''))
                return cached_image_name
            except Exception as e:
                logging.error(f"Error al construir imagen con dependencias: {e}")
                return BASE_IMAGE_NAME

client = docker.from_env(timeout=120)

def background_clean_images():
    """Ejecuta la limpieza de imágenes no utilizadas en segundo plano."""
    threading.Thread(target=clean_unused_images).start()

def background_clean_containers():
    """Ejecuta la limpieza de contenedores no utilizados en segundo plano."""
    threading.Thread(target=clean_unused_containers).start()

def clean_unused_images():
    """Limpia imágenes Docker no utilizadas."""
    try:
        pruned = client.images.prune(filters={"dangling": True})
        logging.info(f"Imágenes cacheadas eliminadas: {pruned}")
    except docker.errors.APIError as e:
        if e.status_code == 409:
            logging.warning("Operación de limpieza ya en curso. Esperando 5 segundos...")
            time.sleep(5)
            clean_unused_images()
        else:
            logging.error(f"Error al limpiar imágenes: {e}")

def clean_unused_containers():
    """Limpia contenedores Docker no utilizados."""
    try:
        client.containers.prune()
        logging.info("Contenedores no utilizados eliminados.")
    except docker.errors.APIError as e:
        if e.status_code == 409:
            logging.warning("Operación de limpieza ya en curso. Esperando 5 segundos...")
            time.sleep(5)
            clean_unused_containers()
        else:
            logging.error(f"Error al limpiar contenedores: {e}")

def execute_code_in_docker(code: str, input_files: dict, dependencies: str = None) -> dict:
    """Ejecuta código Python en un contenedor Docker."""
    client = docker.from_env()
    image = get_or_create_cached_image(dependencies) if dependencies else BASE_IMAGE_NAME

    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        for filename, content in input_files.items():
            file_path = os.path.join(temp_dir, filename)
            try:
                if isinstance(content, str):
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(content)
                else:
                    with open(file_path, "wb") as f:
                        f.write(content)
            except Exception as e:
                logging.error(f"Error al escribir archivo {filename}: {e}")
                return {"stdout": "", "stderr": f"Error al escribir archivo {filename}: {e}", "files": {}}

        container = None
        try:
            container = client.containers.run(
                image=image,
                command=["/bin/bash", "-c", "python script.py 2> error.log"],
                volumes={temp_dir: {"bind": "/app", "mode": "rw"}},
                working_dir="/app",
                detach=True
            )
            try:
                container.wait(timeout=60)
            except requests.exceptions.ReadTimeout:
                container.stop()
                return {"stdout": "", "stderr": "Tiempo excedido (60s)", "files": {}}

            stdout = container.logs().decode("utf-8", errors="replace")
            stderr = ""
            error_log_path = os.path.join(temp_dir, "error.log")
            if os.path.exists(error_log_path):
                with open(error_log_path, "r", encoding="utf-8", errors="ignore") as f:
                    stderr = f.read()

        except Exception as e:
            logging.error(f"Error al ejecutar código en Docker: {e}")
            return {"stdout": "", "stderr": str(e), "files": {}}
        finally:
            if container:
                try:
                    container.stop()
                    container.remove(force=True)
                except Exception as e:
                    logging.error(f"Error al eliminar contenedor: {e}")

        generated_files = {}
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file in ["error.log", "script.py"]:
                    continue
                file_path = os.path.join(root, file)
                with open(file_path, "rb") as f:
                    generated_files[file] = f.read()

        return {"stdout": stdout, "stderr": stderr, "files": generated_files}