import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        base: '#0b0e14',
        panel: '#11161f',
        raised: '#161d29',
        edge: '#232b3b',
        accent: '#6c8cff',
        accentSoft: '#27345e',
        ink: '#e7eaf3',
        dim: '#8a93a8',
        ok: '#3fb950',
        warn: '#d29922',
        err: '#f85149',
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'JetBrains Mono', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config