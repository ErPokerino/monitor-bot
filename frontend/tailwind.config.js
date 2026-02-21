/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './*.html',
    './src/**/*.{js,ts}',
  ],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'sans-serif'] },
      colors: {
        navy: {
          50: '#f0f1f8',
          100: '#d9dbed',
          400: '#5a5f9e',
          600: '#2d3268',
          700: '#222658',
          800: '#1a1a2e',
          900: '#12121f',
        },
        accent: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
        },
      },
    },
  },
  plugins: [],
}
