import type { Config } from "tailwindcss";

const v = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        fg: v("fg"),
        card: v("card"),
        muted: v("muted"),
        border: v("border"),
        accent: v("accent"),
        "accent-fg": v("accent-fg"),
      },
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"] },
    },
  },
  plugins: [],
};

export default config;
