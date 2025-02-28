import docker
import tempfile
import os
import hashlib
import requests

BASE_IMAGE_NAME = "python_executor:latest"
BASE_IMAGE_BUILT = False

def initialize_docker_image():
    """
    Construye la imagen base si no existe.
    Se asume que en la carpeta './executor' existe un Dockerfile base.
    """
    global BASE_IMAGE_BUILT
    client = docker.DockerClient()
    if BASE_IMAGE_BUILT:
        return "Imagen Docker base ya existente (cached)."
    try:
        client.images.get(BASE_IMAGE_NAME)
        BASE_IMAGE_BUILT = True
        return "Imagen Docker base ya existente."
    except docker.errors.ImageNotFound:
        try:
            print("Construyendo imagen Docker base...")
            image, logs = client.images.build(path="./executor", tag=BASE_IMAGE_NAME)
            for item in logs:
                print(item)
            BASE_IMAGE_BUILT = True
            return "Imagen Docker base construida."
        except Exception as e:
            return f"Error al construir imagen: {e}"

def get_or_create_cached_image(dependencies: str) -> str:
    """
    Reutiliza o crea una imagen con dependencias específicas.
    Se genera un archivo requirements.txt a partir de la lista de dependencias.
    """
    if not dependencies.strip():
        print("No se especificaron dependencias, usando imagen base.")
        return BASE_IMAGE_NAME

    # Limpiar y validar dependencias
    dep_lines = [line.strip() for line in dependencies.split('\n') if line.strip()]
    if not dep_lines:
        print("Advertencia: dependencies está vacío después de limpiar, usando imagen base.")
        return BASE_IMAGE_NAME
    cleaned_dependencies = '\n'.join(dep_lines)

    # Generar un hash basado en las dependencias para identificar la imagen cacheada
    dep_hash = hashlib.sha256(cleaned_dependencies.encode("utf-8")).hexdigest()[:12]
    cached_image_name = f"python_executor_cache:{dep_hash}"
    client = docker.DockerClient()

    try:
        client.images.get(cached_image_name)
        print(f"Imagen encontrada: {cached_image_name}")
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
            print(f"Contenido de requirements.txt:\n{cleaned_dependencies}")
            try:
                print(f"Construyendo imagen para dependencias: {cached_image_name}")
                image, logs = client.images.build(path=tmpdir, tag=cached_image_name)
                for item in logs:
                    print(item)
                return cached_image_name
            except Exception as e:
                print(f"Error al construir imagen: {e}")
                return BASE_IMAGE_NAME

def execute_code_in_docker(code: str, input_files: dict, dependencies: str = None) -> dict:
    """
    Ejecuta el código en un contenedor Docker utilizando la imagen base o una imagen cacheada con las dependencias.
    """
    client = docker.DockerClient()
    image = get_or_create_cached_image(dependencies) if dependencies else BASE_IMAGE_NAME

    with tempfile.TemporaryDirectory() as temp_dir:
        # Guardar el script principal
        script_path = os.path.join(temp_dir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        # Guardar archivos adicionales necesarios
        for filename, content in input_files.items():
            with open(os.path.join(temp_dir, filename), "wb") as f:
                f.write(content)

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
            return {"stdout": "", "stderr": str(e), "files": {}}
        finally:
            if container:
                container.remove()

        # Recopilar archivos generados que no sean el script, el log de errores ni los archivos de entrada
        generated_files = {}
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file in ["script.py", "error.log"] or file in input_files:
                    continue
                file_path = os.path.join(root, file)
                with open(file_path, "rb") as f:
                    generated_files[file] = f.read()

        return {"stdout": stdout, "stderr": stderr, "files": generated_files}
