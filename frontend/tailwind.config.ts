import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        base: '#0B0C0E',
        panel: '#121417',
        raised: '#1A1D21',
        edge: '#2A2E34',
        ink: '#EDE8DE',
        dim: '#9A958C',
        faint: '#6B675F',
        accent: '#8FE388',
        accentSoft: '#20351F',
        ok: '#8FE388',
        warn: '#E0B45C',
        err: '#E06C62',
        diffAdd: '#16351F',
        diffDel: '#3A1D1B',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', '14px'],
        xs: ['11px', '16px'],
        sm: ['12px', '17px'],
        base: ['13px', '20px'],
        md: ['14px', '21px'],
        lg: ['16px', '24px'],
        xl: ['18px', '26px'],
        '2xl': ['22px', '30px'],
        '3xl': ['28px', '36px'],
      },
      transitionTimingFunction: { DEFAULT: 'ease-out' },
      borderRadius: { sm: '4px', md: '6px', lg: '10px', xl: '14px' },
      boxShadow: {
        pop: '0 16px 48px rgba(0,0,0,0.55)',
        inset: 'inset 0 1px 0 rgba(255,255,255,0.03)',
      },
    },
  },
  plugins: [],
} satisfies Config
