/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: '#EF3124', dark: '#C9241A', soft: '#FDECEA' },
        fact: { DEFAULT: '#4B5563', soft: '#F3F4F6' },
        bank: { DEFAULT: '#C9241A', soft: '#FDECEA' },
        ai: { DEFAULT: '#1D4ED8', soft: '#EFF4FF' },
      },
      fontFamily: { sans: ['Inter', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'] },
    },
  },
  plugins: [],
}
