import threading
import time
import docker
import tempfile
import os
import hashlib
import logging
import requests
import platform
import sys
import subprocess
import json

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BASE_IMAGE_NAME = "python_executor:latest"

def check_docker_availability():
    """
    Verifica si Docker está disponible en el sistema y muestra información detallada.
    """
    logging.info("=================== Verificación de Docker ===================")
    
    # Verificar si Docker CLI está disponible
    try:
        version_result = subprocess.run(['docker', '--version'], 
                                      capture_output=True, text=True, check=True)
        logging.info(f"Docker CLI detectado: {version_result.stdout.strip()}")
    except Exception as e:
        logging.error(f"Docker CLI no disponible: {e}")
        return False
    
    # Verificar si Docker daemon está corriendo
    try:
        info_result = subprocess.run(['docker', 'info'], 
                                   capture_output=True, text=True, check=True)
        logging.info("Docker daemon está en ejecución")
        
        # Intentar ejecutar un contenedor básico para probar la funcionalidad
        try:
            hello_result = subprocess.run(['docker', 'run', '--rm', 'hello-world'], 
                                       capture_output=True, text=True, check=True)
            logging.info("Test de Docker exitoso con contenedor 'hello-world'")
            logging.info(f"Salida del contenedor: {hello_result.stdout[:100]}...")
            return True
        except Exception as e:
            logging.error(f"No se pudo ejecutar el contenedor de prueba: {e}")
            return False
    except Exception as e:
        logging.error(f"Docker daemon no está en ejecución: {e}")
        return False

# Añadir verificación al inicio del módulo
print("Verificando disponibilidad de Docker...")
docker_is_available = check_docker_availability()
print(f"Docker está {'disponible' if docker_is_available else 'NO disponible'}")

def get_docker_client():
    """
    Crea un cliente Docker utilizando el método más confiable para cada sistema.
    En Windows, si el SDK falla, usa subprocesos de Docker CLI directamente.
    """
    # Primero verificamos si Docker CLI está disponible
    try:
        subprocess.run(['docker', '--version'], 
                     capture_output=True, text=True, check=True)
        docker_cli_available = True
        logging.info("Docker CLI está disponible")
    except Exception:
        docker_cli_available = False
        logging.error("Docker CLI no está disponible")
        return None
    
    # Si estamos en Windows y Docker CLI está disponible, podemos crear un cliente personalizado
    if platform.system() == "Windows" and docker_cli_available:
        # En Windows con Docker Desktop, usamos una clase especial que envolverá los comandos Docker
        return WindowsDockerClient()
    
    # Para otros sistemas, intentamos la conexión normal
    try:
        return docker.from_env(timeout=120)
    except Exception as e:
        logging.error(f"Error al conectar con Docker: {e}")
        if docker_cli_available:
            # Como último recurso, usamos el cliente CLI
            return WindowsDockerClient()
        return None

class WindowsDockerClient:
    """Cliente Docker personalizado para Windows que utiliza subprocesos del CLI"""
    
    def __init__(self):
        self.images = WindowsDockerImages()
        self.containers = WindowsDockerContainers()
    
    def ping(self):
        """Verifica si Docker está disponible"""
        try:
            subprocess.run(['docker', 'info'], 
                         capture_output=True, text=True, check=True)
            return True
        except Exception:
            return False
    
    def version(self):
        """Obtiene la versión de Docker"""
        try:
            result = subprocess.run(['docker', 'version', '--format', '{{json .}}'], 
                                  capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except Exception:
            return {"Version": "desconocida"}

class WindowsDockerImages:
    """Gestión de imágenes Docker a través de CLI para Windows"""
    
    def get(self, image_name):
        """Verifica si existe una imagen"""
        try:
            result = subprocess.run(['docker', 'image', 'inspect', image_name], 
                                  capture_output=True, text=True, check=True)
            return ImageWrapper(image_name)
        except Exception as e:
            if "No such image" in str(e):
                raise docker.errors.ImageNotFound(f"Imagen no encontrada: {image_name}")
            raise e
    
    def build(self, path, tag):
        """Construye una imagen Docker"""
        try:
            result = subprocess.run(['docker', 'build', '-t', tag, path], 
                                  capture_output=True, text=True, check=True)
            return ImageWrapper(tag), [{"stream": line} for line in result.stdout.splitlines()]
        except Exception as e:
            raise e

class WindowsDockerContainers:
    """Gestión de contenedores Docker a través de CLI para Windows"""
    
    def run(self, image, command, volumes, working_dir, detach=False):
        """Ejecuta un contenedor Docker"""
        try:
            cmd = ['docker', 'run']
            
            if detach:
                cmd.append('-d')
            
            # Convertir volúmenes al formato CLI
            for host_path, container_config in volumes.items():
                bind = container_config.get('bind')
                mode = container_config.get('mode', 'rw')
                cmd.extend(['-v', f"{host_path}:{bind}:{mode}"])
            
            # Directorio de trabajo
            if working_dir:
                cmd.extend(['-w', working_dir])
            
            # Imagen y comando
            cmd.append(image)
            cmd.extend(command)
            
            # Ejecutar el contenedor
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            container_id = result.stdout.strip()
            
            return ContainerWrapper(container_id)
        except Exception as e:
            raise e

class ImageWrapper:
    """Wrapper para imágenes Docker"""
    def __init__(self, image_id):
        self.id = image_id
        self.tags = [image_id]

class ContainerWrapper:
    """Wrapper para contenedores Docker"""
    def __init__(self, container_id):
        self.id = container_id
    
    def wait(self, timeout=None):
        """Espera a que el contenedor termine"""
        try:
            cmd = ['docker', 'wait', self.id]
            if timeout:
                # Si timeout es None, esto lanzará un error, por lo que lo verificamos
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
            else:
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return {"StatusCode": int(result.stdout.strip())}
        except subprocess.TimeoutExpired:
            raise docker.errors.APIError("Timeout waiting for container")
    
    def logs(self):
        """Obtiene los logs del contenedor"""
        try:
            result = subprocess.run(['docker', 'logs', self.id], 
                                  capture_output=True, check=True)
            return result.stdout
        except Exception as e:
            raise e
    
    def stop(self):
        """Detiene el contenedor"""
        try:
            subprocess.run(['docker', 'stop', self.id], 
                         capture_output=True, text=True, check=True)
        except Exception:
            pass
    
    def remove(self, force=False):
        """Elimina el contenedor"""
        try:
            cmd = ['docker', 'rm', self.id]
            if force:
                cmd.append('-f')
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except Exception:
            pass

def initialize_docker_image():
    """Inicializa la imagen base de Docker si no existe."""
    client = get_docker_client()
    if not client:
        return "Error: No se pudo conectar con Docker. Verifica que esté instalado y en ejecución."
    
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
    
    client = get_docker_client()
    if not client:
        logging.error("No se pudo obtener cliente Docker. Usando imagen base.")
        return BASE_IMAGE_NAME

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

# Inicialización del cliente global (si falla, se manejará en cada función)
try:
    client = get_docker_client()
    if not client:
        logging.warning("No se pudo inicializar el cliente Docker global. Se intentará en cada operación.")
except Exception as e:
    logging.error(f"Error al inicializar cliente Docker global: {e}")
    client = None

def background_clean_images():
    """Ejecuta la limpieza de imágenes no utilizadas en segundo plano."""
    threading.Thread(target=clean_unused_images).start()

def background_clean_containers():
    """Ejecuta la limpieza de contenedores no utilizados en segundo plano."""
    threading.Thread(target=clean_unused_containers).start()

def clean_unused_images():
    """Limpia imágenes Docker no utilizadas."""
    docker_client = client or get_docker_client()
    if not docker_client:
        logging.error("No se pudo obtener cliente Docker para limpiar imágenes.")
        return
    
    try:
        pruned = docker_client.images.prune(filters={"dangling": True})
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
    docker_client = client or get_docker_client()
    if not docker_client:
        logging.error("No se pudo obtener cliente Docker para limpiar contenedores.")
        return
    
    try:
        docker_client.containers.prune()
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
    docker_client = get_docker_client()
    if not docker_client:
        return {
            "stdout": "", 
            "stderr": "Error: No se pudo conectar con Docker. Verifica que esté instalado y en ejecución.", 
            "files": {}
        }
    
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
            container = docker_client.containers.run(
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