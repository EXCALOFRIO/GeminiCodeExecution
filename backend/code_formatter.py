import re


def clean_code(code: str) -> str:
    """
    Limpia y formatea el código generado por LLM, removiendo comentarios innecesarios
    y normalizando el formato.
    """
    # Eliminar bloques de código markdown
    code = re.sub(r"```(?:python|py)?", "", code)
    code = re.sub(r"```\s*$", "", code)
    
    # Eliminar comentarios extensos al inicio
    lines = code.split('\n')
    content_started = False
    clean_lines = []
    
    for line in lines:
        stripped = line.strip()
        # Saltar líneas vacías al inicio
        if not content_started and not stripped:
            continue
        # Considerar que el contenido ha empezado cuando hay una línea no vacía
        if not content_started and stripped:
            content_started = True
        # Una vez que el contenido ha empezado, incluir todas las líneas
        if content_started:
            clean_lines.append(line)
    
    # Eliminar espacios en blanco excesivos al final
    while clean_lines and not clean_lines[-1].strip():
        clean_lines.pop()
    
    # Unir las líneas limpias
    clean_code = '\n'.join(clean_lines)
    
    # Normalizar saltos de línea
    clean_code = clean_code.replace('\r\n', '\n')
    
    return clean_code 