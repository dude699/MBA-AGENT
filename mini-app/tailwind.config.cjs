/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#1a1a1a',
          100: '#1e1e1e',
          200: '#2a2a2a',
          300: '#3a3a3a',
          400: '#666666',
          500: '#888888',
          600: '#aaaaaa',
          700: '#cccccc',
          800: '#e0e0e0',
          900: '#ffffff',
          950: '#ffffff',
        },
        accent: {
          DEFAULT: '#ffffff',
          light: '#f0f0f0',
          dark: '#e0e0e0',
          blue: '#2a2a2a',
        },
        surface: {
          white: '#0a0a0a',
          light: '#000000',
          muted: '#0f0f0f',
          border: '#1a1a1a',
        },
        status: {
          success: '#22c55e',
          warning: '#f59e0b',
          danger: '#ef4444',
          info: '#3b82f6',
        },
        stipend: {
          high: '#10b981',
          medium: '#f59e0b',
          low: '#666666',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      boxShadow: {
        'card': '0 1px 3px rgba(0,0,0,0.3)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.5)',
        'elevated': '0 8px 30px rgba(0,0,0,0.5)',
        'modal': '0 20px 60px rgba(0,0,0,0.7)',
        'inner-glow': 'inset 0 1px 0 rgba(255,255,255,0.05)',
      },
      borderRadius: {
        'xl': '0.875rem',
        '2xl': '1rem',
        '3xl': '1.25rem',
      },
      animation: {
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-down': 'slideDown 0.3s ease-out',
        'fade-in': 'fadeIn 0.2s ease-out',
        'pulse-soft': 'pulseSoft 2s infinite',
        'shimmer': 'shimmer 1.5s infinite',
      },
      keyframes: {
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        slideDown: {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.7' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
    },
  },
  plugins: [],
};
