import docker
import tempfile
import os
import hashlib
import sys

def initialize_docker_image():
    client = docker.from_env()
    base_image_name = "python_executor:latest"
    try:
        client.images.get(base_image_name)
        print("[INFO] Imagen Docker base ya existe.")
        return "Imagen Docker base ya existente."
    except docker.errors.ImageNotFound:
        print("[BUILD] Construyendo la imagen Docker base para ejecución de código...")
        try:
            image, logs = client.images.build(path="./executor", tag=base_image_name)
            for log in logs:
                if 'stream' in log:
                    print(log['stream'].strip())
            return "Imagen Docker base construida exitosamente."
        except Exception as build_err:
            return f"Error al construir la imagen Docker base: {build_err}"

def get_or_create_cached_image(dependencies: str) -> str:
    base_image_name = "python_executor:latest"
    if not dependencies.strip():
        return base_image_name

    dep_hash = hashlib.sha256(dependencies.encode("utf-8")).hexdigest()[:12]
    cached_image_name = f"python_executor_cache:{dep_hash}"

    client = docker.from_env()
    try:
        client.images.get(cached_image_name)
        print(f"[CACHE] Imagen {cached_image_name} ya existe, usando cache.")
        return cached_image_name
    except docker.errors.ImageNotFound:
        pass

    with tempfile.TemporaryDirectory() as tmpdir:
        dockerfile_content = f"""
FROM {base_image_name}
WORKDIR /app
COPY requirements.txt .
RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
""".strip()
        df_path = os.path.join(tmpdir, "Dockerfile")
        with open(df_path, "w") as f:
            f.write(dockerfile_content)
        
        req_path = os.path.join(tmpdir, "requirements.txt")
        with open(req_path, "w") as f:
            f.write(dependencies)
        
        print(f"[BUILD] Construyendo imagen derivada: {cached_image_name} (hash={dep_hash})")
        print(f"[BUILD] Contenido de requirements.txt:\n{dependencies}\n")
        try:
            image, logs = client.images.build(path=tmpdir, tag=cached_image_name)
            for log in logs:
                if 'stream' in log:
                    print(log['stream'].strip())
            return cached_image_name
        except docker.errors.BuildError as e:
            print(f"[ERROR] Error building image: {e}")
            for log in e.build_log:
                if 'stream' in log:
                    print(log['stream'].strip())
            return base_image_name
        except Exception as e:
            print(f"[ERROR] Error inesperado al construir la imagen: {e}")
            return base_image_name

def execute_code_in_docker(code: str, input_files: dict, dependencies: str = None) -> dict:
    client = docker.from_env()
    
    custom_image = get_or_create_cached_image(dependencies) if dependencies else "python_executor:latest"
    
    with tempfile.TemporaryDirectory() as temp_dir:
        print("[INFO] Guardando script.py en directorio temporal...")
        script_path = os.path.join(temp_dir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        print("[INFO] Guardando archivos de entrada en el directorio temporal...")
        for filename, content in input_files.items():
            file_path = os.path.join(temp_dir, filename)
            with open(file_path, "wb") as f:
                f.write(content)

        print(f"[INFO] Iniciando contenedor Docker con imagen: {custom_image}")
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
            error_msg = f"[ERROR] Error ejecutando contenedor Docker: {e}"
            print(error_msg)
            return {"stdout": "", "stderr": error_msg, "all_files": {}, "generated_files": {}}

        all_files = {}
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, temp_dir)
                try:
                    with open(file_path, "rb") as f:
                        all_files[rel_path] = f.read()
                except Exception as e:
                    print(f"[WARN] Error leyendo {file_path}: {e}")

        generated_files = {k: v for k, v in all_files.items() if k != "script.py" and k not in input_files}

        return {"stdout": stdout, "stderr": stderr, "all_files": all_files, "generated_files": generated_files}