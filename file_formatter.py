# file_formatter.py
import io
import pandas as pd
from PIL import Image
import base64
import os

def format_generated_file(filename: str, content: bytes) -> str:
    """
    Formatea la visualización de un archivo generado según su extensión.
    Por ejemplo, para CSV se genera una tabla HTML, para imágenes se muestra una vista previa, etc.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        try:
            df = pd.read_csv(io.BytesIO(content))
            return df.to_html(classes="table table-striped", border=0)
        except Exception as e:
            return f"<pre>Error al procesar CSV: {e}</pre>"
    elif ext in [".png", ".jpg", ".jpeg", ".gif"]:
        try:
            b64 = base64.b64encode(content).decode("utf-8")
            image_type = ext[1:]
            return f'<img src="data:image/{image_type};base64,{b64}" alt="{filename}" style="max-width:100%;">'
        except Exception as e:
            return f"<pre>Error al mostrar imagen: {e}</pre>"
    else:
        try:
            return f"<pre>{content.decode('utf-8')}</pre>"
        except Exception:
            return f"<pre>No se puede mostrar el contenido de {filename}</pre>"