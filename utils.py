import os
import re
import ast
import sys
import subprocess
import tempfile
import autopep8
from code_formatter import clean_code

def lint_code(code, temp_dir, log_file="linting.log"):
    """Verifica el código con flake8 y registra problemas en un archivo de log."""
    script_path = os.path.join(temp_dir, "script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        result = subprocess.run(["flake8", script_path], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            with open(log_file, "a") as log:
                log.write(f"Problemas de linting detectados:\n{result.stdout}\n")
            return False, result.stdout
        return True, ""
    except FileNotFoundError:
        with open(log_file, "a") as log:
            log.write("flake8 no está instalado. Instálalo con 'pip install flake8'.\n")
        return True, ""  # Continúa sin linting si no está instalado

def check_syntax(code):
    """Verifica la sintaxis del código Python."""
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)

def generate_requirements_file(code, temp_dir):
    """Genera un archivo requirements.txt combinando pipreqs y análisis estático."""
    script_path = os.path.join(temp_dir, "script.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(code)
    reqs = []
    try:
        subprocess.run(["pipreqs", temp_dir, "--force", "--mode", "no-pin"], check=True, capture_output=True, text=True)
        with open(os.path.join(temp_dir, "requirements.txt"), "r", encoding="utf-8") as f:
            reqs = f.read().strip().splitlines()
    except subprocess.CalledProcessError:
        pass  # Si pipreqs falla, usa análisis estático
    detected_imports = extract_imports(code)
    existing_packages = {line.strip() for line in reqs}
    for pkg in detected_imports:
        if pkg not in existing_packages and pkg not in sys.builtin_module_names:
            reqs.append(pkg)
    requirements = "\n".join(sorted(reqs))
    return clean_code(requirements)

def extract_imports(code):
    """Extrae todos los imports del código, incluyendo los anidados."""
    try:
        tree = ast.parse(code)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.add(name.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
        return imports
    except SyntaxError:
        return set()

def auto_correct_code(code):
    """Intenta corregir automáticamente errores de sintaxis y estilo con autopep8."""
    try:
        corrected_code = autopep8.fix_code(code, options={'aggressive': 1})
        return corrected_code
    except Exception as e:
        return code  # Si falla, devuelve el código original