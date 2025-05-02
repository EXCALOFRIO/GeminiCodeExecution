import os
import sys
import subprocess
import threading
import time

# Asegurar que la ruta del proyecto esté en sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

def run_backend():
    """Ejecuta el servidor backend."""
    print("Iniciando servidor backend en http://0.0.0.0:8080")
    try:
        # Ejecutar uvicorn directamente como un proceso separado
        process = subprocess.Popen(
            ["uvicorn", "backend.main:socket_app", "--host", "0.0.0.0", "--port", "8080", "--reload"],
            cwd=current_dir
        )
        return process
    except Exception as e:
        print(f"Error al iniciar el backend: {e}")
        return None

def run_frontend():
    """Ejecuta el servidor frontend."""
    frontend_dir = os.path.join(current_dir, "frontend")
    if not os.path.exists(frontend_dir):
        print(f"Error: El directorio del frontend no existe en {frontend_dir}")
        return None
    
    print("Iniciando servidor frontend en http://localhost:3000")
    
    # Guardar el directorio actual para restaurarlo después
    original_dir = os.getcwd()
    os.chdir(frontend_dir)
    
    # Rutas posibles para npm en Windows
    npm_paths = [
        "npm",  # Si está en PATH
        "npm.cmd",  # Versión Windows de npm
        os.path.join(os.environ.get("APPDATA", ""), "npm", "npm.cmd"),
        os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", "npm.cmd"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "nodejs", "npm.cmd")
    ]
    
    process = None
    for npm_cmd in npm_paths:
        try:
            process = subprocess.Popen([npm_cmd, "run", "dev"], cwd=frontend_dir)
            break
        except (subprocess.SubprocessError, FileNotFoundError):
            continue
    
    # Restaurar el directorio original
    os.chdir(original_dir)
    
    if not process:
        print("Error: No se pudo iniciar npm. Verifica que Node.js esté instalado y en el PATH.")
        return None
        
    return process

if __name__ == "__main__":
    print("Iniciando GeminiCodeExecution...")
    
    # Iniciar procesos
    backend_process = run_backend()
    time.sleep(2)  # Esperar un poco para que el backend inicie
    frontend_process = run_frontend()
    
    if not backend_process and not frontend_process:
        print("Error: No se pudo iniciar ninguno de los servidores.")
        sys.exit(1)
    
    try:
        # Mantener el script en ejecución
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nDeteniendo servidores...")
        
        # Cerrar los procesos al recibir Ctrl+C
        if backend_process:
            backend_process.terminate()
        if frontend_process:
            frontend_process.terminate()
        
        print("Servidores detenidos.") 