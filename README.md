# GeminiCodeExecution

Aplicación para generar y ejecutar código Python utilizando Gemini AI.

## Requisitos previos

- Python 3.8+ 
- Node.js 16+ y npm
- Docker (opcional, para la ejecución de código)

## Configuración del entorno

### Backend

1. Navega al directorio del backend:
   ```bash
   cd backend
   ```

2. Crea un entorno virtual:
   ```bash
   python -m venv venv
   ```

3. Activa el entorno virtual:
   - Windows: `venv\Scripts\activate`
   - Linux/Mac: `source venv/bin/activate`

4. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

### Frontend

1. Navega al directorio del frontend:
   ```bash
   cd frontend
   ```

2. Instala las dependencias:
   ```bash
   npm install
   ```

## Ejecución de la aplicación

### Ejecutar la aplicación completa (recomendado)

Para iniciar tanto el backend como el frontend con un solo comando, desde la carpeta raíz del proyecto ejecuta:

```bash
python run_server.py
```

Esto iniciará:
- El backend en `http://localhost:8080`
- El frontend en `http://localhost:3000`

> **Nota**: La aplicación puede funcionar sin Docker, pero la funcionalidad de ejecución de código estará deshabilitada. Si Docker está instalado y en ejecución, la aplicación lo detectará automáticamente.

### Ejecutar los componentes por separado

Si prefieres iniciar los componentes por separado:

#### Iniciar solo el backend

```bash
python run_server.py
```

O alternativamente:

```bash
cd backend
python -m uvicorn main:socket_app --host 0.0.0.0 --port 8080 --reload
```

#### Iniciar solo el frontend

```bash
cd frontend
npm run dev
```

## Resolución de problemas

### Problemas de conexión WebSocket

Si experimentas problemas de conexión entre el frontend y el backend:

1. Verifica que tanto el frontend como el backend estén en ejecución
2. Asegúrate de que el puerto 8080 no esté bloqueado por un firewall
3. Comprueba la consola del navegador para ver mensajes de error

### Problemas con Docker

Si Docker no se detecta correctamente:

1. Asegúrate de que Docker esté instalado y en ejecución
2. En Windows, verifica que Docker Desktop esté configurado correctamente
3. La aplicación mostrará un indicador en el frontend cuando Docker esté disponible

## Estructura del proyecto

- `backend/` - Servidor FastAPI con WebSockets y soporte para Docker
- `frontend/` - Interfaz de usuario basada en Next.js
- `run_server.py` - Script de inicio para ejecutar tanto el backend como el frontend

## Estado de la aplicación

La aplicación muestra dos indicadores de estado en la barra superior:

- **Conexión al servidor**: Muestra si el frontend está conectado al backend
- **Estado de Docker**: Muestra si Docker está disponible para ejecutar código

## Licencia

[MIT](LICENSE)