/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'primary': '#4f46e5',
        'primary-dark': '#4338ca',
        'secondary': '#8b5cf6',
      },
      ringOpacity: {
        DEFAULT: '0.5',
      }
    },
  },
  plugins: [],
} 