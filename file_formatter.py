import io
import pandas as pd
import os

def format_generated_file(filename: str, content: bytes) -> str:
    """Formatea la visualización de un archivo generado según su extensión."""
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        try:
            df = pd.read_csv(io.BytesIO(content))
            return df.to_html(classes="table table-striped", border=0)
        except Exception as e:
            return f"<pre>Error procesando CSV: {e}</pre>"
    try:
        return f"<pre>{content.decode('utf-8')}</pre>"
    except Exception:
        return f"<pre>No se puede mostrar el contenido de {filename}</pre>"