def clean_code(code: str) -> str:
    lines = [line.rstrip() for line in code.splitlines() if line.strip()]
    return "\n".join(lines)