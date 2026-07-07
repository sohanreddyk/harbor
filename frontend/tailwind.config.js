/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        harbor: {
          bg: "#0b1120",
          panel: "#111c33",
          accent: "#38bdf8",
        },
      },
    },
  },
  plugins: [],
};
