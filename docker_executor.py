import docker
import tempfile
import os
import hashlib
import sys

def initialize_docker_image():
    """Inicializa la imagen base de Docker."""
    client = docker.from_env()  # Corrección: usar from_env()
    base_image_name = "python_executor:latest"
    try:
        client.images.get(base_image_name)
        print("[INFO] Imagen Docker base ya existe.")
        return "Imagen Docker base ya existente."
    except docker.errors.ImageNotFound:
        print("[BUILD] Construyendo imagen base...")
        try:
            client.images.build(path="./executor", tag=base_image_name)
            return "Imagen base construida."
        except Exception as e:
            return f"Error al construir imagen base: {e}"

def prebuild_common_image():
    """Pre-construye una imagen con dependencias comunes para acelerar ejecuciones."""
    client = docker.from_env()  # Corrección: usar from_env()
    common_image_name = "python_executor_common:latest"
    try:
        client.images.get(common_image_name)
        print("[INFO] Imagen con dependencias comunes ya existe.")
    except docker.errors.ImageNotFound:
        common_deps = "pandas\nnumpy\nmatplotlib"
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile = f"""
            FROM python_executor:latest
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install -r requirements.txt
            """
            with open(os.path.join(tmpdir, "Dockerfile"), "w") as f:
                f.write(dockerfile.strip())
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write(common_deps)
            print("[BUILD] Construyendo imagen con dependencias comunes...")
            client.images.build(path=tmpdir, tag=common_image_name)

def get_or_create_cached_image(dependencies: str) -> str:
    """Crea o reutiliza una imagen Docker basada en las dependencias."""
    client = docker.from_env()  # Corrección: usar from_env()
    base_image_name = "python_executor_common:latest" if dependencies.strip() else "python_executor:latest"
    if not dependencies.strip():
        return base_image_name

    dep_hash = hashlib.sha256(dependencies.encode("utf-8")).hexdigest()[:12]
    cached_image_name = f"python_executor_cache:{dep_hash}"

    try:
        client.images.get(cached_image_name)
        print(f"[CACHE] Usando imagen cacheada: {cached_image_name}")
        return cached_image_name
    except docker.errors.ImageNotFound:
        with tempfile.TemporaryDirectory() as tmpdir:
            dockerfile = f"""
            FROM {base_image_name}
            WORKDIR /app
            COPY requirements.txt .
            RUN pip install -r requirements.txt
            """
            with open(os.path.join(tmpdir, "Dockerfile"), "w") as f:
                f.write(dockerfile.strip())
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write(dependencies)
            print(f"[BUILD] Construyendo imagen: {cached_image_name}")
            try:
                client.images.build(path=tmpdir, tag=cached_image_name)
                return cached_image_name
            except Exception as e:
                print(f"[ERROR] Falló construcción: {e}")
                return base_image_name

def execute_code_in_docker(code: str, input_files: dict, dependencies: str = None) -> dict:
    """Ejecuta el código en un contenedor Docker optimizado."""
    client = docker.from_env()  # Corrección: usar from_env()
    custom_image = get_or_create_cached_image(dependencies)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)
        for filename, content in input_files.items():
            with open(os.path.join(temp_dir, filename), "wb") as f:
                f.write(content)
        try:
            container = client.containers.run(
                image=custom_image,
                command="python /app/script.py",
                volumes={temp_dir: {'bind': '/app', 'mode': 'rw'}},
                working_dir="/app",
                detach=True,
                stdout=True,
                stderr=True
            )
            container.wait()
            stdout = container.logs(stdout=True, stderr=False).decode('utf-8', errors='replace')
            stderr = container.logs(stdout=False, stderr=True).decode('utf-8', errors='replace')
            container.remove()
        except Exception as e:
            return {"stdout": "", "stderr": f"Error ejecutando contenedor: {e}", "all_files": {}, "generated_files": {}}

        all_files = {}
        for root, _, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, temp_dir)
                with open(file_path, "rb") as f:
                    all_files[rel_path] = f.read()

        generated_files = {k: v for k, v in all_files.items() if k != "script.py" and k not in input_files}
        return {"stdout": stdout, "stderr": stderr, "all_files": all_files, "generated_files": generated_files}