'use client';

import React, { useState, useEffect, useRef } from 'react';
import { io, Socket } from 'socket.io-client';
import axios from 'axios';

// --- Tipos ---
interface ChecklistStatus {
  taskId: string;
  execIndex: number;
  step: string;
  status: string;
  isError: boolean;
}

interface GeneratedFile {
  [filename: string]: string; // nombre: contenido en base64
}

interface FinalResult {
  taskId: string;
  bestExecIndex: number;
  report: string;
  generatedFiles: GeneratedFile;
  code: string;
  logs: { stdout: string; stderr: string };
}

// --- Constantes ---
const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8080';

export default function Home() {
  const [prompt, setPrompt] = useState('');
  const [files, setFiles] = useState<FileList | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checklist, setChecklist] = useState<Record<number, Record<string, { status: string; isError: boolean }>>>({});
  const [finalResult, setFinalResult] = useState<FinalResult | null>(null);
  const socketRef = useRef<Socket | null>(null);
  const [isDarkMode, setIsDarkMode] = useState(false);
  const [socketStatus, setSocketStatus] = useState<'disconnected' | 'connecting' | 'connected'>('disconnected');
  const socketReconnectAttempts = useRef(0);
  const maxReconnectAttempts = 5;
  const [dockerStatus, setDockerStatus] = useState<{ available: boolean; message: string }>({ 
    available: false, 
    message: 'Verificando disponibilidad de Docker...' 
  });

  // Detectar si estamos en modo oscuro
  useEffect(() => {
    const checkDarkMode = () => {
      const isDark = document.documentElement.classList.contains('dark');
      setIsDarkMode(isDark);
    };

    // Verificar al inicio
    checkDarkMode();

    // Crear un MutationObserver para detectar cambios en las clases del documento
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === 'class') {
          checkDarkMode();
        }
      });
    });

    observer.observe(document.documentElement, { attributes: true });
    
    return () => observer.disconnect();
  }, []);

  // --- Función para establecer conexión WebSocket ---
  const setupSocketConnection = () => {
    if (socketRef.current && socketRef.current.connected) return;
    
    setSocketStatus('connecting');
    
    // Limpiar cualquier socket existente
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current.removeAllListeners();
    }
    
    socketRef.current = io(BACKEND_URL, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: maxReconnectAttempts,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 20000,
      forceNew: true
    });

    socketRef.current.on('connect', () => {
      console.log('WebSocket conectado:', socketRef.current?.id);
      setSocketStatus('connected');
      socketReconnectAttempts.current = 0;
      
      // Si hay una tarea activa, unirse a su sala
      if (taskId) {
        socketRef.current?.emit('join_task_room', taskId);
      }
    });

    socketRef.current.on('connection_established', (data) => {
      console.log('Conexión establecida:', data);
    });

    socketRef.current.on('disconnect', () => {
      console.log('WebSocket desconectado');
      setSocketStatus('disconnected');
    });

    socketRef.current.on('connect_error', (err) => {
      console.error('Error de conexión WebSocket:', err);
      setSocketStatus('disconnected');
      
      socketReconnectAttempts.current += 1;
      if (socketReconnectAttempts.current >= maxReconnectAttempts) {
        setError(`Error de conexión con el backend: ${err.message}. Por favor, recarga la página.`);
        socketRef.current?.disconnect();
      }
    });

    // --- Listeners de Eventos ---
    socketRef.current.on('checklist_update', (data: ChecklistStatus) => {
      console.log('Actualización de checklist:', data);
      setChecklist((prev) => {
        const updatedChecklist = { ...prev };
        if (!updatedChecklist[data.execIndex]) {
          updatedChecklist[data.execIndex] = {};
        }
        updatedChecklist[data.execIndex][data.step] = { status: data.status, isError: data.isError };
        return updatedChecklist;
      });
    });

    socketRef.current.on('task_completed', (data: FinalResult) => {
      console.log('Tarea completada:', data);
      
      // Garantizar que se actualice el estado correctamente
      setFinalResult(data);
      setIsLoading(false); 
      setTaskId(null);
      
      // Notificar al usuario que la tarea se ha completado
      try {
        // Usar notificación nativa del navegador si está disponible
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('Tarea completada', {
            body: 'El procesamiento de tu tarea ha finalizado con éxito',
            icon: '/favicon.ico'
          });
        }
      } catch (e) {
        console.error('Error al mostrar notificación:', e);
      }
    });

    socketRef.current.on('task_failed', (data: { taskId: string; error: string }) => {
      console.error('Tarea fallida:', data);
      setError(`La tarea falló: ${data.error}`);
      setIsLoading(false);
      setTaskId(null);
      
      // Notificar al usuario sobre el error
      try {
        if ('Notification' in window && Notification.permission === 'granted') {
          new Notification('Tarea fallida', {
            body: `Error: ${data.error}`,
            icon: '/favicon.ico'
          });
        }
      } catch (e) {
        console.error('Error al mostrar notificación:', e);
      }
    });

    socketRef.current.on('execution_summary', (data) => {
      console.log('Resumen de ejecución:', data);
      // Puedes usar esto para mostrar el estado final de cada ejecución paralela
    });
  };

  // Inicializar conexión WebSocket al cargar la página
  useEffect(() => {
    setupSocketConnection();
    
    // Función para verificar la salud del servidor de backend
    const checkBackendHealth = async () => {
      try {
        const response = await axios.get(`${BACKEND_URL}/health`, { timeout: 5000 });
        console.log('Backend está en línea', response.data);
        
        // Actualizar estado de Docker
        setDockerStatus({
          available: response.data.docker_available,
          message: response.data.docker_status
        });
        
        if (socketStatus !== 'connected') {
          setupSocketConnection();
        }
      } catch (err) {
        console.error('Backend no disponible:', err);
        setSocketStatus('disconnected');
        setDockerStatus({
          available: false,
          message: 'No se pudo conectar con el servidor para verificar Docker.'
        });
      }
    };
    
    // Verificar al inicio
    checkBackendHealth();
    
    // Verificar periódicamente
    const healthInterval = setInterval(checkBackendHealth, 30000);
    
    // Solicitar permisos de notificación
    if ('Notification' in window) {
      if (Notification.permission !== 'granted' && Notification.permission !== 'denied') {
        Notification.requestPermission();
      }
    }
    
    return () => {
      clearInterval(healthInterval);
      if (socketRef.current) {
        socketRef.current.disconnect();
        socketRef.current = null;
      }
    };
  }, []);

  // Unirse a la sala de la tarea cuando cambia el taskId
  useEffect(() => {
    if (!taskId || !socketRef.current) return;
    
    // Asegurarse de que el socket está conectado antes de unirse a la sala
    if (socketRef.current.connected) {
      socketRef.current.emit('join_task_room', taskId);
    } else {
      setupSocketConnection();
    }
  }, [taskId]);

  // --- Manejadores ---
  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setFiles(event.target.files);
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!prompt || !files || files.length === 0) {
      setError('Por favor, ingresa un prompt y selecciona archivos.');
      return;
    }

    // Verificar si Docker está disponible
    if (!dockerStatus.available) {
      setError(`Docker no está disponible: ${dockerStatus.message}. No se puede ejecutar código.`);
      return;
    }

    setIsLoading(true);
    setError(null);
    setChecklist({}); // Reset checklist
    setFinalResult(null); // Reset results

    // Asegurarse de que el socket está conectado
    if (!socketRef.current?.connected) {
      setupSocketConnection();
    }

    const formData = new FormData();
    formData.append('prompt', prompt);
    for (let i = 0; i < files.length; i++) {
      formData.append('files', files[i]);
    }

    try {
      const response = await axios.post(`${BACKEND_URL}/execute`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
        timeout: 10000
      });
      console.log('Tarea enviada:', response.data);
      setTaskId(response.data.taskId); // Inicia la conexión WebSocket
    } catch (err: any) {
      console.error('Error al enviar la tarea:', err);
      setError(err.response?.data?.detail || err.message || 'Error al enviar la tarea.');
      setIsLoading(false);
    }
  };

  // --- Renderizado ---

  // Helper para renderizar checklist
  const renderChecklist = () => {
    if (Object.keys(checklist).length === 0) return null;
    return (
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6 mb-8">
        {Object.entries(checklist)
          .sort(([idxA], [idxB]) => parseInt(idxA) - parseInt(idxB)) // Ordenar por índice
          .map(([execIndex, steps]) => (
            <div key={execIndex} className={`card p-4 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <h4 className={`text-lg font-bold mb-3 ${isDarkMode ? 'text-indigo-400' : 'text-indigo-700'} flex items-center`}>
                <span className={`${isDarkMode ? 'bg-indigo-900 text-indigo-300' : 'bg-indigo-100 text-indigo-800'} text-xs font-semibold rounded-full w-6 h-6 flex items-center justify-center mr-2`}>
                  {parseInt(execIndex) + 1}
                </span>
                Tarea {parseInt(execIndex) + 1}
              </h4>
              <ul className="space-y-2">
                {Object.entries(steps).map(([stepName, { status, isError }]) => (
                  <li 
                    key={stepName} 
                    className={`py-1 px-2 rounded flex items-start ${
                      isError 
                        ? isDarkMode ? 'bg-red-900/30 text-red-400' : 'bg-red-50 text-red-700'
                        : status.includes('✅') 
                          ? isDarkMode ? 'bg-green-900/30 text-green-400' : 'bg-green-50 text-green-700'  
                          : isDarkMode ? 'bg-blue-900/30 text-blue-400' : 'bg-blue-50 text-blue-700'
                    }`}
                  >
                    <span className="mr-2 mt-0.5">
                      {isError 
                        ? '❌' 
                        : (status.includes('✅') || status.includes('Completo')) 
                          ? '✅' 
                          : '🔄'}
                    </span>
                    <div>
                      <p className="font-medium">{stepName}</p>
                      <p className="text-xs">{status}</p>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
      </div>
    );
  };

  // Helper para renderizar archivos
  const renderGeneratedFiles = (files: GeneratedFile) => {
    // Lógica para mostrar/descargar archivos decodificando base64
    const handleDownload = (filename: string, base64Content: string) => {
      try {
        const byteCharacters = atob(base64Content);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
          byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray]);
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (error) {
        console.error('Error al descargar archivo:', error);
        setError('Error al descargar el archivo. Verifica la consola para más detalles.');
      }
    };

    const getFileIcon = (filename: string) => {
      const extension = filename.split('.').pop()?.toLowerCase();
      switch (extension) {
        case 'csv':
        case 'xlsx':
        case 'xls':
          return '📊';
        case 'txt':
          return '📝';
        case 'py':
          return '🐍';
        case 'json':
          return '📋';
        case 'png':
        case 'jpg':
        case 'jpeg':
        case 'gif':
          return '🖼️';
        case 'pdf':
          return '📑';
        default:
          return '📄';
      }
    };

    return (
      <div className="card p-6">
        <h4 className={`text-xl font-bold mb-4 ${isDarkMode ? 'text-gray-200' : 'text-gray-800'}`}>Archivos Generados</h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {Object.entries(files).map(([name, content]) => (
            <div key={name} className={`border ${isDarkMode ? 'border-gray-700 hover:bg-gray-700' : 'border-gray-200 hover:bg-gray-50'} rounded-md p-3 transition-colors`}>
              <div className="flex items-center mb-2">
                <span className="text-2xl mr-2">{getFileIcon(name)}</span>
                <span className="text-sm font-medium truncate flex-1">{name}</span>
              </div>
              <button
                onClick={() => handleDownload(name, content)}
                className="btn-primary text-xs py-1 w-full flex items-center justify-center"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                </svg>
                Descargar
              </button>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // Contenido principal
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
      {/* Barra superior */}
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-2xl font-bold">GeminiCodeExecution</h1>
        
        {/* Indicadores de estado */}
        <div className="flex items-center gap-4">
          <div className="flex items-center">
            <div className={`status-indicator mr-2 ${
              socketStatus === 'connected' 
                ? 'status-connected' 
                : socketStatus === 'connecting' 
                  ? 'status-connecting' 
                  : 'status-disconnected'
            }`}></div>
            <span className={`text-xs ${
              socketStatus === 'connected' 
                ? isDarkMode ? 'text-green-400' : 'text-green-600' 
                : socketStatus === 'connecting' 
                  ? isDarkMode ? 'text-yellow-400' : 'text-yellow-600' 
                  : isDarkMode ? 'text-red-400' : 'text-red-600'
            }`}>
              {socketStatus === 'connected' 
                ? 'Conectado al servidor' 
                : socketStatus === 'connecting' 
                  ? 'Conectando...' 
                  : 'Desconectado'}
            </span>
          </div>
          
          <div className="flex items-center">
            <div className={`status-indicator mr-2 ${
              dockerStatus.available 
                ? 'status-connected' 
                : 'status-disconnected'
            }`}></div>
            <span className={`text-xs ${
              dockerStatus.available 
                ? isDarkMode ? 'text-green-400' : 'text-green-600' 
                : isDarkMode ? 'text-red-400' : 'text-red-600'
            }`}>
              Docker: {dockerStatus.available ? 'Disponible' : 'No disponible'}
            </span>
          </div>
        </div>
      </div>

      {/* Formulario */}
      {!finalResult && (
        <div className="card p-6 mb-8 animate-fade-in">
          <form onSubmit={handleSubmit}>
            <div className="mb-6">
              <label htmlFor="prompt" className="block font-medium mb-1">Describe tu Tarea</label>
              <textarea
                id="prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Ej: Analizar los datos en el CSV y generar un gráfico de correlación entre las variables"
                className="textarea-field h-32"
                disabled={isLoading}
              />
            </div>

            <div className="mb-6">
              <label htmlFor="files" className="block font-medium mb-1">Sube tus Archivos</label>
              <div className={`border-2 border-dashed p-6 rounded-lg text-center ${isDarkMode ? 'border-gray-600' : 'border-gray-300'}`}>
                <input
                  id="files"
                  type="file"
                  onChange={handleFileChange}
                  multiple
                  className="hidden"
                  disabled={isLoading}
                />
                <label htmlFor="files" className="cursor-pointer">
                  <div className="text-7xl mb-3">
                    {files && files.length > 0 ? (
                      <span role="img" aria-label="Archivos subidos">📂</span>
                    ) : (
                      <span role="img" aria-label="Subir archivos">📁</span>
                    )}
                  </div>
                  <div className="font-medium mb-1">
                    {files && files.length > 0
                      ? `${files.length} archivo${files.length === 1 ? '' : 's'} seleccionado${files.length === 1 ? '' : 's'}`
                      : 'Ningún archivo seleccionado'}
                  </div>
                  <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                    Haz clic para seleccionar archivos
                  </div>
                </label>
              </div>
            </div>

            {/* Error message */}
            {error && (
              <div className={`mb-6 p-3 rounded-md ${isDarkMode ? 'bg-red-900/30 text-red-400' : 'bg-red-50 text-red-700'}`}>
                {error}
              </div>
            )}

            <button
              type="submit"
              className={`btn-primary w-full py-3 flex items-center justify-center ${isLoading ? 'opacity-70 cursor-not-allowed' : ''}`}
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Procesando...
                </>
              ) : (
                <>
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 mr-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                  Generar y Ejecutar
                </>
              )}
            </button>
          </form>
        </div>
      )}

      {/* Checklist durante la ejecución */}
      {isLoading && renderChecklist()}

      {/* Resultado final */}
      {finalResult && (
        <div className="animate-fade-in">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div className="lg:col-span-2">
              <div className="card p-6 mb-6">
                <h3 className={`text-xl font-bold mb-4 ${isDarkMode ? 'text-gray-200' : 'text-gray-800'}`}>Reporte Científico</h3>
                <div className="prose" dangerouslySetInnerHTML={{ __html: finalResult.report }} />
              </div>
              
              <div className="card p-6">
                <h3 className={`text-xl font-bold mb-4 ${isDarkMode ? 'text-gray-200' : 'text-gray-800'}`}>Código Generado</h3>
                <pre className={`p-4 rounded-lg overflow-auto text-sm ${isDarkMode ? 'bg-gray-900 text-gray-300' : 'bg-gray-50 text-gray-800'}`}>
                  <code>{finalResult.code}</code>
                </pre>
              </div>
            </div>
            
            <div className="lg:col-span-1">
              {renderGeneratedFiles(finalResult.generatedFiles)}
              
              <div className="card p-6 mt-6">
                <h3 className={`text-xl font-bold mb-4 ${isDarkMode ? 'text-gray-200' : 'text-gray-800'}`}>Logs de Ejecución</h3>
                
                {finalResult.logs.stdout && (
                  <div className="mb-4">
                    <h4 className={`text-sm font-medium mb-2 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>Salida Estándar</h4>
                    <pre className={`p-3 rounded-lg text-xs overflow-auto h-32 ${isDarkMode ? 'bg-gray-900 text-gray-300' : 'bg-gray-50 text-gray-800'}`}>
                      {finalResult.logs.stdout}
                    </pre>
                  </div>
                )}
                
                {finalResult.logs.stderr && (
                  <div>
                    <h4 className={`text-sm font-medium mb-2 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>Errores</h4>
                    <pre className={`p-3 rounded-lg text-xs overflow-auto h-32 ${isDarkMode ? 'bg-red-900/20 text-red-400' : 'bg-red-50 text-red-600'}`}>
                      {finalResult.logs.stderr}
                    </pre>
                  </div>
                )}
              </div>
              
              <button
                onClick={() => setFinalResult(null)}
                className="btn-secondary w-full mt-6"
              >
                ↩ Generar Otra Solución
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
} 