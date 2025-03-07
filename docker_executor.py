import docker
import tempfile
import os
import hashlib
import requests

BASE_IMAGE_NAME = "python_executor:latest"
BASE_IMAGE_BUILT = False

def initialize_docker_image():
    global BASE_IMAGE_BUILT
    if BASE_IMAGE_BUILT:
        return "Imagen Docker base ya existente (cached)."

    try:
        client = docker.DockerClient()
    except Exception as e:
        return f"Error al conectar con el daemon de Docker: {e}. Asegúrate de que Docker esté corriendo."

    try:
        client.images.get(BASE_IMAGE_NAME)
        BASE_IMAGE_BUILT = True
        return "Imagen Docker base ya existente."
    except docker.errors.ImageNotFound:
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            dockerfile_path = os.path.join(script_dir, "executor")
            if not os.path.exists(dockerfile_path):
                return f"Error: El directorio {dockerfile_path} no existe o no contiene un Dockerfile."
            print(f"Construyendo imagen Docker base desde {dockerfile_path}...")
            image, logs = client.images.build(path=dockerfile_path, tag=BASE_IMAGE_NAME)
            for item in logs:
                print(item.get('stream', ''))
            BASE_IMAGE_BUILT = True
            return "Imagen Docker base construida exitosamente."
        except Exception as e:
            return f"Error al construir la imagen Docker: {e}"

def get_or_create_cached_image(dependencies: str) -> str:
    if not dependencies.strip():
        print("No se especificaron dependencias, usando imagen base.")
        return BASE_IMAGE_NAME

    # Procesar dependencias para asegurar el formato correcto
    dep_lines = []
    for line in dependencies.split('\n'):
        line = line.strip()
        if line:
            # Dividir por comas y limpiar cada entrada
            deps = [dep.strip() for dep in line.split(',') if dep.strip()]
            dep_lines.extend(deps)
    if not dep_lines:
        print("Advertencia: dependencies está vacío después de limpiar, usando imagen base.")
        return BASE_IMAGE_NAME
    cleaned_dependencies = '\n'.join(dep_lines)
    
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
                    print(item.get('stream', ''))
                return cached_image_name
            except Exception as e:
                print(f"Error al construir imagen con dependencias: {e}")
                return BASE_IMAGE_NAME

def clean_unused_images():
    client = docker.DockerClient()
    try:
        images = client.images.list(filters={"reference": "python_executor_cache:*"})
        for image in images:
            print(f"Eliminando imagen: {image.tags[0]}")
            client.images.remove(image.id, force=True)
        print("Imágenes cacheadas eliminadas.")
    except Exception as e:
        print(f"Error al limpiar imágenes: {e}")

def clean_unused_containers():
    client = docker.DockerClient()
    try:
        containers = client.containers.list(all=True, filters={"status": "exited"})
        for container in containers:
            if container.image.tags and any("python_executor" in tag for tag in container.image.tags):
                print(f"Eliminando contenedor: {container.id}")
                container.remove(force=True)
        print("Contenedores no utilizados eliminados.")
    except Exception as e:
        print(f"Error al limpiar contenedores: {e}")

def execute_code_in_docker(code: str, input_files: dict, dependencies: str = None) -> dict:
    client = docker.DockerClient()
    image = get_or_create_cached_image(dependencies) if dependencies else BASE_IMAGE_NAME

    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        for filename, content in input_files.items():
            file_path = os.path.join(temp_dir, filename)
            if isinstance(content, str):
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                with open(file_path, "wb") as f:
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
                container.stop()
                container.remove(force=True)

        generated_files = {}
        for root, _, files in os.walk(temp_dir):
            for file in files:
                if file == "error.log":
                    continue
                file_path = os.path.join(root, file)
                with open(file_path, "rb") as f:
                    generated_files[file] = f.read()

        return {"stdout": stdout, "stderr": stderr, "files": generated_files}