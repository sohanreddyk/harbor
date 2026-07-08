/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        harbor: {
          ink: "var(--harbor-ink)",
          surface: "var(--harbor-surface)",
          surface2: "var(--harbor-surface2)",
          line: "var(--harbor-line)",
          fg: "var(--harbor-fg)",
          muted: "var(--harbor-muted)",
          beacon: "var(--harbor-beacon)",
          patina: "var(--harbor-patina)",
          coral: "var(--harbor-coral)",
        },
      },
      fontFamily: {
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        display: ['"Space Grotesk"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
