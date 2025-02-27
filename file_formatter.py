import io
import os
import base64
import json
import pandas as pd
from html import escape
import chardet

def format_generated_file(filename: str, content: bytes) -> str:
    """
    Formatea la visualización de un archivo generado según su extensión para integrarse en Markdown/HTML.

    Permite previsualizar el contenido de archivos en diferentes formatos y ofrece enlaces clickeables
    para descarga o visualización en una nueva pestaña.

    Args:
        filename (str): Nombre del archivo, incluyendo la extensión.
        content (bytes): Contenido del archivo en formato binario.

    Returns:
        str: Representación HTML del archivo para su visualización o descarga.
    """
    ext = os.path.splitext(filename)[1].lower()

    # Función auxiliar para generar una URL de datos a partir del contenido binario
    def generate_data_url(mime: str, data: bytes) -> str:
        encoded = base64.b64encode(data).decode('utf-8')
        return f"data:{mime};base64,{encoded}"

    # --- Manejo de archivos CSV ---
    if ext == ".csv":
        try:
            df = None
            # Intentar leer el CSV con diferentes delimitadores
            for delimiter in [',', ';', '\t']:
                try:
                    df_candidate = pd.read_csv(io.BytesIO(content), delimiter=delimiter, encoding='utf-8')
                    if not df_candidate.empty:
                        df = df_candidate
                        break
                except Exception:
                    continue
            if df is None:
                raise ValueError("No se pudo leer el CSV con los delimitadores comunes.")
            html_table = df.to_html(classes="table table-striped", border=0, index=False, justify="center")
            return f'<div class="generated-file-preview">{html_table}</div>'
        except Exception as e:
            return f"<p>Error procesando el CSV '{escape(filename)}': {escape(str(e))}. Verifica el formato y la codificación.</p>"

    # --- Manejo de archivos Excel ---
    elif ext in [".xls", ".xlsx"]:
        try:
            df = pd.read_excel(io.BytesIO(content))
            html_table = df.to_html(classes="table table-bordered", border=0, index=False, justify="center")
            return f'<div class="generated-file-preview">{html_table}</div>'
        except Exception as e:
            return f"<p>Error procesando el archivo Excel '{escape(filename)}': {escape(str(e))}. Asegúrate de que el archivo sea válido.</p>"

    # --- Manejo de imágenes ---
    elif ext in [".png", ".jpg", ".jpeg", ".gif"]:
        try:
            mime_type = f"image/{ext[1:]}"  # Remover el punto de la extensión
            data_url = generate_data_url(mime_type, content)
            # La imagen es clickeable para ampliarla en una nueva pestaña
            return (
                f'<a href="{data_url}" target="_blank" title="Haz clic para ampliar la imagen">'
                f'<img src="{data_url}" alt="{escape(filename)}" style="max-width:100%; height:auto; '
                'border:1px solid #ddd; padding:5px; margin:5px 0;" /></a>'
            )
        except Exception as e:
            return f"<p>Error procesando la imagen '{escape(filename)}': {escape(str(e))}.</p>"

    # --- Manejo de archivos de texto y código ---
    elif ext in [".txt", ".md", ".py", ".log"]:
        try:
            # Detectar codificación usando chardet
            result = chardet.detect(content)
            encoding = result['encoding'] if result['encoding'] else 'utf-8'
            text_content = content.decode(encoding, errors="replace")
            # Mostrar el contenido en un contenedor con scroll horizontal
            return (
                f'<div style="overflow-x:auto; background:#f8f8f8; padding:10px; border:1px solid #ccc; '
                'border-radius:4px; margin:5px 0;">'
                f'<pre style="margin:0;">{escape(text_content)}</pre></div>'
            )
        except Exception as e:
            return f"<p>Error leyendo el archivo de texto '{escape(filename)}': {escape(str(e))}. Posible problema de codificación.</p>"

    # --- Manejo de archivos JSON ---
    elif ext == ".json":
        try:
            json_content = json.loads(content.decode('utf-8'))
            formatted_json = json.dumps(json_content, indent=4, ensure_ascii=False)
            return (
                f'<div style="overflow-x:auto; background:#f8f8f8; padding:10px; border:1px solid #ccc; '
                'border-radius:4px; margin:5px 0;">'
                f'<pre style="margin:0;">{escape(formatted_json)}</pre></div>'
            )
        except Exception as e:
            return f"<p>Error procesando el JSON '{escape(filename)}': {escape(str(e))}. Asegúrate de que el archivo sea válido.</p>"

    # --- Manejo de archivos PDF ---
    elif ext == ".pdf":
        try:
            data_url = generate_data_url("application/pdf", content)
            # Se muestra un enlace y un embed para previsualización
            html = (
                f'<p><a href="{data_url}" target="_blank" style="text-decoration:none; color:#337ab7;">'
                f'<strong>Ver PDF: {escape(filename)}</strong></a></p>'
                f'<embed src="{data_url}" type="application/pdf" width="100%" height="600px" '
                'style="border:1px solid #ccc; border-radius:4px;">'
            )
            return html
        except Exception as e:
            return f"<p>Error procesando el PDF '{escape(filename)}': {escape(str(e))}.</p>"

    # --- Manejo de archivos de audio ---
    elif ext in [".mp3", ".wav", ".ogg"]:
        try:
            mime_type = f"audio/{ext[1:]}"
            data_url = generate_data_url(mime_type, content)
            return (
                f'<div style="margin:5px 0;">'
                f'<audio controls style="width:100%; max-width:500px;">'
                f'<source src="{data_url}" type="{mime_type}">'
                'Tu navegador no soporta audio.'
                '</audio></div>'
            )
        except Exception as e:
            return f"<p>Error procesando el audio '{escape(filename)}': {escape(str(e))}.</p>"

    # --- Manejo de archivos de video ---
    elif ext in [".mp4", ".avi", ".webm"]:
        try:
            mime_type = f"video/{ext[1:]}"
            data_url = generate_data_url(mime_type, content)
            return (
                f'<div style="margin:5px 0;">'
                f'<video controls style="width:100%; max-width:600px;">'
                f'<source src="{data_url}" type="{mime_type}">'
                'Tu navegador no soporta video.'
                '</video></div>'
            )
        except Exception as e:
            return f"<p>Error procesando el video '{escape(filename)}': {escape(str(e))}.</p>"

    # --- Manejo de otros archivos binarios ---
    else:
        try:
            data_url = generate_data_url("application/octet-stream", content)
            return (
                f'<p><a href="{data_url}" download="{escape(filename)}" '
                'style="text-decoration:none; color:#337ab7;">'
                f'Descargar archivo: {escape(filename)}</a></p>'
            )
        except Exception as e:
            return f"<p>Error procesando el archivo '{escape(filename)}': {escape(str(e))}.</p>"