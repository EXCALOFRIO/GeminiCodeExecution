# code_formatter.py
import re

def clean_code(code: str) -> str:
    """
    Limpia el código generado eliminando delimitadores de Markdown y caracteres innecesarios.
    """
    cleaned_code = re.sub(r'```(?:python)?', '', code)
    cleaned_code = cleaned_code.replace("```", "")
    cleaned_code = re.sub(r'~~~', '', cleaned_code)
    cleaned_code = "\n".join(line.rstrip() for line in cleaned_code.splitlines())
    return cleaned_code.strip()

def format_output(output_text: str) -> str:
    """
    Aplica un formato básico al texto de salida para mejorar su legibilidad.
    """
    if not output_text:
        return ""
    lines = [line.rstrip() for line in output_text.splitlines()]
    return "\n".join(lines)