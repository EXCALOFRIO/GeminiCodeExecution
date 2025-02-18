# docker_executor.py
import docker
import tempfile
import os
import hashlib
import sys

def initialize_docker_image():
    """
    Initializes and builds the base Docker image (python_executor:latest) if it doesn't exist.
    """
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
    """
    Given a list of dependencies (requirements.txt), builds or reuses
    a derived image (FROM python_executor:latest) with those dependencies installed.
    Returns the image name to use.
    """
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
        try:
            image, logs = client.images.build(path=tmpdir, tag=cached_image_name)
            for log in logs:
                if 'stream' in log:
                    print(log['stream'].strip())
            return cached_image_name
        except Exception as e:
            print(f"Error building image: {e}")
            return base_image_name # Fallback to base image

def execute_code_in_docker(code: str, input_files: dict, dependencies: str = None, custom_image: str = "python_executor:latest") -> dict:
    """
    Executes the Python code in an isolated Docker container.
    Returns a dict with stdout, stderr, and generated files.
    """
    client = docker.from_env()
    
    if dependencies:
        custom_image = get_or_create_cached_image(dependencies)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        print("[INFO] Saving script.py in temporary directory...")
        sys.stdout.flush()
        script_path = os.path.join(temp_dir, "script.py")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        print("[INFO] Saving input files in the temporary directory...")
        sys.stdout.flush()
        for filename, content in input_files.items():
            file_path = os.path.join(temp_dir, filename)
            with open(file_path, "wb") as f:
                f.write(content)

        print(f"[INFO] Starting Docker container with image: {custom_image}")
        sys.stdout.flush()
        try:
            # When detach=False, client.containers.run() returns the logs directly
            logs = client.containers.run(
                image=custom_image,
                volumes={temp_dir: {'bind': '/app', 'mode': 'rw'}},
                working_dir="/app",
                detach=False,
                stdout=True,
                stderr=True,
                remove=True
            ).decode('utf-8', errors='replace')  # Decode the logs

            print(f"[INFO] Container finished. Capturing output...")
            sys.stdout.flush()
            
            stdout = ""
            stderr = ""
            if logs:
                # Basic separation of stdout/stderr - this might need more sophisticated parsing
                if "Traceback" in logs:
                    stderr = logs
                else:
                    stdout = logs

        except Exception as e:
            error_msg = f"[ERROR] Error executing Docker container: {e}"
            print(error_msg)
            sys.stdout.flush()
            return {"stdout": "", "stderr": error_msg, "files": {}}

        generated_files = {}
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file in ["script.py"] or file in input_files:
                    continue
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "rb") as f:
                        generated_files[file] = f.read()
                except Exception as e:
                    print(f"[WARN] Error reading {file_path}: {e}")
                    sys.stdout.flush()
        
        return {"stdout": stdout, "stderr": stderr, "files": generated_files}