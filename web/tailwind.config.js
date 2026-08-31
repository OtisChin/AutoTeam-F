/** @type {import('tailwindcss').Config} */
const rgb = variable => `rgb(var(${variable}) / <alpha-value>)`
const neutral = Object.fromEntries(
  [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
    .map(shade => [shade, rgb(`--tw-neutral-${shade}`)]),
)
// The 950 token is intentionally part of the alpha-safe neutral palette.
// --tw-neutral-950 is defined per theme in style.css.

function tone(text, fill, strong) {
  return {
    50: rgb(text), 100: rgb(text), 200: rgb(text), 300: rgb(text), 400: rgb(text),
    500: rgb(fill), 600: rgb(strong), 700: rgb(strong), 800: rgb(strong), 900: rgb(strong), 950: rgb(strong),
  }
}

export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        white: rgb('--tw-white'), black: rgb('--tw-black'), gray: neutral, slate: neutral,
        blue: tone('--rgb-accent-text', '--rgb-accent-fill', '--rgb-accent-strong'),
        sky: tone('--rgb-accent-text', '--rgb-accent-fill', '--rgb-accent-strong'),
        emerald: tone('--rgb-success-text', '--rgb-success-fill', '--rgb-success-strong'),
        green: tone('--rgb-success-text', '--rgb-success-fill', '--rgb-success-strong'),
        rose: tone('--rgb-danger-text', '--rgb-danger-fill', '--rgb-danger-strong'),
        red: tone('--rgb-danger-text', '--rgb-danger-fill', '--rgb-danger-strong'),
        amber: tone('--rgb-warning-text', '--rgb-warning-fill', '--rgb-warning-strong'),
        yellow: tone('--rgb-warning-text', '--rgb-warning-fill', '--rgb-warning-strong'),
        cyan: tone('--rgb-info-text', '--rgb-info-fill', '--rgb-info-strong'),
        indigo: tone('--rgb-violet-text', '--rgb-violet-fill', '--rgb-violet-strong'),
        teal: tone('--rgb-info-text', '--rgb-info-fill', '--rgb-info-strong'),
        violet: tone('--rgb-violet-text', '--rgb-violet-fill', '--rgb-violet-strong'),
        purple: tone('--rgb-violet-text', '--rgb-violet-fill', '--rgb-violet-strong'),
      },
    },
  },
  plugins: [],
}
