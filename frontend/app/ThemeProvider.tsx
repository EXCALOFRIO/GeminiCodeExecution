'use client';

import { useState, useEffect } from 'react';

export default function ThemeProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    // Verificar preferencia del usuario guardada o preferencia del sistema
    const savedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    if (savedTheme === 'dark' || (!savedTheme && prefersDark)) {
      setDarkMode(true);
      document.documentElement.classList.add('dark');
    }
  }, []);

  useEffect(() => {
    // Aplicar clases al body directamente
    if (darkMode) {
      document.body.className = 'min-h-screen bg-gradient-to-br from-gray-900 via-gray-800 to-indigo-900 text-white dark-mode';
    } else {
      document.body.className = 'min-h-screen bg-gradient-to-br from-indigo-50 via-white to-purple-50 light-mode';
    }
  }, [darkMode]);

  const toggleDarkMode = () => {
    if (darkMode) {
      document.documentElement.classList.remove('dark');
      localStorage.setItem('theme', 'light');
    } else {
      document.documentElement.classList.add('dark');
      localStorage.setItem('theme', 'dark');
    }
    setDarkMode(!darkMode);
  };

  return (
    <div className="min-h-screen flex flex-col">
      <header className={`border-b ${darkMode ? 
        'border-gray-700 bg-gray-800 bg-opacity-80' : 
        'border-gray-200 bg-white bg-opacity-80'
      } backdrop-blur-sm sticky top-0 z-10 shadow-sm`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center">
              <svg xmlns="http://www.w3.org/2000/svg" className={`h-8 w-8 ${darkMode ? 'text-indigo-400' : 'text-indigo-600'} mr-3`} viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M12.316 3.051a1 1 0 01.633 1.265l-4 12a1 1 0 11-1.898-.632l4-12a1 1 0 011.265-.633zM5.707 6.293a1 1 0 010 1.414L3.414 10l2.293 2.293a1 1 0 11-1.414 1.414l-3-3a1 1 0 010-1.414l3-3a1 1 0 011.414 0zm8.586 0a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 11-1.414-1.414L16.586 10l-2.293-2.293a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              <h1 className={`text-xl font-semibold ${darkMode ? 'text-white' : 'text-gray-900'}`}>Generador de Código Científico</h1>
            </div>
            <div className="flex space-x-4 items-center">
              {/* Botón de cambio de tema */}
              <button 
                onClick={toggleDarkMode}
                className={`p-2 rounded-full ${darkMode ? 
                  'bg-gray-700 hover:bg-gray-600' : 
                  'bg-gray-100 hover:bg-gray-200'
                } transition-colors duration-200`}
                aria-label={darkMode ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
              >
                {darkMode ? (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-yellow-300" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M10 2a1 1 0 011 1v1a1 1 0 11-2 0V3a1 1 0 011-1zm4 8a4 4 0 11-8 0 4 4 0 018 0zm-.464 4.95l.707.707a1 1 0 001.414-1.414l-.707-.707a1 1 0 00-1.414 1.414zm2.12-10.607a1 1 0 010 1.414l-.706.707a1 1 0 11-1.414-1.414l.707-.707a1 1 0 011.414 0zM17 11a1 1 0 100-2h-1a1 1 0 100 2h1zm-7 4a1 1 0 011 1v1a1 1 0 11-2 0v-1a1 1 0 011-1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zm1.414 8.486l-.707.707a1 1 0 01-1.414-1.414l.707-.707a1 1 0 011.414 1.414zM4 11a1 1 0 100-2H3a1 1 0 000 2h1z" clipRule="evenodd" />
                  </svg>
                ) : (
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 text-indigo-700" viewBox="0 0 20 20" fill="currentColor">
                    <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
                  </svg>
                )}
              </button>
              
            </div>
          </div>
        </div>
      </header>
      
      <main className={`flex-grow ${darkMode ? 'bg-gray-800 text-white' : 'bg-white text-gray-800'}`}>
        {children}
      </main>
      
      <footer className={`${darkMode ? 
        'bg-gray-900 text-gray-300 border-t border-gray-700' : 
        'bg-white text-gray-500 border-t border-gray-200'}`}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="text-center text-sm">
            <p>Creado con Next.js, FastAPI y Gemini AI</p>
            <p className="mt-1">© {new Date().getFullYear()} Generador de Código Científico</p>
          </div>
        </div>
      </footer>
    </div>
  );
} 