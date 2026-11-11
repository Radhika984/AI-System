/** @type {import('tailwindcss').Config} */
// Editorial Intelligence Workspace palette - the only colours used by the console.
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        forest: '#183C32', // primary actions, key highlights
        ink: '#202B28', // headings
        sage: '#82968A', // secondary visual elements
        mist: '#E9EFE9', // soft sage background
        ivory: '#F7F6F1', // page background
        muted: '#747C75', // secondary text
        line: '#E5E6DE', // subtle borders
        ok: '#267653',
        okbg: '#EAF4ED',
        warn: '#A96B27',
        warnbg: '#FBF1E3',
        err: '#B34D49',
        errbg: '#F8ECEA',
        info: '#526D83',
        infobg: '#EDF2F5',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        serif: ['Lora', 'Georgia', 'Cambria', 'Times New Roman', 'serif'],
      },
    },
  },
  plugins: [],
}
