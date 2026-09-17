/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: ['class'],
  theme: {
    extend: {
      colors: {
        void: 'var(--color-bg-void)',
        surface: 'var(--color-bg-surface)',
        card: 'var(--color-bg-card)',
        elevated: 'var(--color-bg-elevated)',
        border: {
          DEFAULT: 'var(--color-border)',
          lit: 'var(--color-border-lit)',
        },
        text: {
          DEFAULT: 'var(--color-text)',
          sec: 'var(--color-text-sec)',
          dim: 'var(--color-text-dim)',
        },
        primary: {
          DEFAULT: 'var(--color-primary)',
          hover: 'var(--color-primary-hover)',
          foreground: 'var(--color-on-primary)',
        },
      },
      fontFamily: {
        display: ["'Space Grotesk'", "'Noto Sans SC'", 'sans-serif'],
        body: ["'Noto Sans SC'", "'Space Grotesk'", 'sans-serif'],
        mono: ["'SF Mono'", "'Consolas'", 'monospace'],
      },
      borderRadius: {
        sm: '6px',
        md: '10px',
        lg: '16px',
        xl: '24px',
      },
      spacing: {
        header: '56px',
        sidebar: '260px',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'fade-in-scale': 'fadeInScale 0.6s cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-in-right': 'slideInRight 0.3s cubic-bezier(0.16, 1, 0.3, 1)',
        'glow-pulse': 'glowPulse 4s ease-in-out infinite',
        'typing-dot': 'typingDot 1.4s ease-in-out infinite',
        'logo-reveal': 'logoReveal 1s cubic-bezier(0.16, 1, 0.3, 1)',
        'orb-float': 'orbFloat 20s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        fadeInScale: {
          '0%': { opacity: '0', transform: 'scale(0.95)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        glowPulse: {
          '0%, 100%': { boxShadow: '0 0 20px color-mix(in srgb, var(--color-primary) 10%, transparent)' },
          '50%': { boxShadow: '0 0 40px color-mix(in srgb, var(--color-primary) 30%, transparent)' },
        },
        typingDot: {
          '0%, 60%, 100%': { opacity: '0.3', transform: 'translateY(0)' },
          '30%': { opacity: '1', transform: 'translateY(-4px)' },
        },
        logoReveal: {
          '0%': { opacity: '0', transform: 'scale(0.8) translateY(10px)' },
          '100%': { opacity: '1', transform: 'scale(1) translateY(0)' },
        },
        orbFloat: {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '25%': { transform: 'translate(100px, -50px) scale(1.1)' },
          '50%': { transform: 'translate(-50px, 100px) scale(0.9)' },
          '75%': { transform: 'translate(-100px, -50px) scale(1.05)' },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
};
