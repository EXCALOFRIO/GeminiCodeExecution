import subprocess
import sys
import platform
import os
import logging
import docker

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("docker-check")

def check_docker_cli():
    """Verifica si el Docker CLI está disponible"""
    try:
        version_result = subprocess.run(['docker', '--version'], 
                                      capture_output=True, text=True, check=True)
        logger.info(f"Docker CLI detectado: {version_result.stdout.strip()}")
        return True
    except Exception as e:
        logger.error(f"Docker CLI no disponible: {e}")
        return False

def check_docker_daemon():
    """Verifica si el daemon de Docker está en ejecución"""
    try:
        info_result = subprocess.run(['docker', 'info'], 
                                   capture_output=True, text=True, check=True)
        logger.info("Docker daemon está en ejecución")
        return True
    except Exception as e:
        logger.error(f"Docker daemon no está en ejecución: {e}")
        return False

def test_hello_world():
    """Prueba ejecutar el contenedor hello-world"""
    try:
        hello_result = subprocess.run(['docker', 'run', '--rm', 'hello-world'], 
                                    capture_output=True, text=True, check=True)
        logger.info("Test de Docker exitoso con contenedor 'hello-world'")
        logger.info(f"Salida del contenedor: {hello_result.stdout[:100]}...")
        return True
    except Exception as e:
        logger.error(f"No se pudo ejecutar el contenedor de prueba: {e}")
        return False

def test_docker_py():
    """Prueba la conexión utilizando la biblioteca docker-py"""
    try:
        logger.info("Intentando conexión con docker-py desde Docker.from_env()")
        client = docker.from_env()
        version = client.version()
        logger.info(f"Conexión exitosa a Docker con docker-py. Versión: {version.get('Version', 'Desconocida')}")
        return True
    except Exception as e:
        logger.error(f"Error al conectar con docker-py usando from_env(): {e}")
        
        # Intentar métodos alternativos
        if platform.system() == "Windows":
            logger.info("Detectado Windows, probando métodos alternativos...")
            
            # Probar diferentes URLs de conexión
            urls = [
                "npipe:////./pipe/docker_engine",
                "npipe://./pipe/docker_engine",
                "tcp://localhost:2375"
            ]
            
            for url in urls:
                try:
                    logger.info(f"Probando conexión con URL: {url}")
                    client = docker.DockerClient(base_url=url)
                    client.ping()
                    logger.info(f"Conexión exitosa a Docker con URL: {url}")
                    return True
                except Exception as e:
                    logger.error(f"Error al conectar con URL {url}: {e}")
        
        return False

if __name__ == "__main__":
    print("\n=== Diagnóstico de Docker ===\n")
    
    print(f"Sistema Operativo: {platform.system()} {platform.version()}")
    print(f"Python: {sys.version}")
    print(f"Docker-py: {docker.__version__}")
    
    print("\n--- Verificando componentes de Docker ---\n")
    
    cli_available = check_docker_cli()
    daemon_running = check_docker_daemon()
    hello_world_test = test_hello_world() if daemon_running else False
    docker_py_test = test_docker_py()
    
    print("\n--- Resumen ---\n")
    print(f"Docker CLI disponible: {'✅' if cli_available else '❌'}")
    print(f"Docker daemon en ejecución: {'✅' if daemon_running else '❌'}")
    print(f"Prueba hello-world exitosa: {'✅' if hello_world_test else '❌'}")
    print(f"Conexión con docker-py exitosa: {'✅' if docker_py_test else '❌'}")
    
    if docker_py_test:
        print("\n¡Todo OK! Docker está configurado correctamente.")
    else:
        print("\nSe detectaron problemas con Docker.")
        if cli_available and daemon_running and not docker_py_test:
            print("Docker está funcionando pero la biblioteca docker-py no puede conectarse.")
            print("Posibles soluciones:")
            print("1. Reiniciar Docker Desktop")
            print("2. Verificar los permisos de conexión")
            print("3. Exposición de API Docker en Docker Desktop (Settings > Docker Engine)")
            if platform.system() == "Windows":
                print("4. Verificar que la opción 'Expose daemon on tcp://localhost:2375 without TLS' esté activada en Docker Desktop") 