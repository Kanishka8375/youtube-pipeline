import type { Config } from "tailwindcss";

/**
 * Dark cinematic glassmorphism. Two things this palette is deliberately
 * careful about:
 *
 * - Status colours are not hue-only. `failed` and `completed` differ in
 *   lightness as well as hue, so red/green colour blindness -- around 8% of
 *   men -- does not make a job table unreadable. Every status also carries a
 *   word, never a bare dot.
 * - Glass panels sit on a dark ground with a real border. Pure translucency
 *   over a busy background is what makes glassmorphism illegible.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#04070d",
        panel: "rgba(12, 22, 38, 0.62)",
        hairline: "rgba(140, 190, 255, 0.14)",
        cyan: "#5dd6ff",
        violet: "#a78bfa",
        teal: "#2dd4bf",
        // Status: distinct in lightness, not only hue.
        ok: "#4ade80",
        warn: "#fbbf24",
        bad: "#fb7185",
        idle: "#94a3b8"
      },
      boxShadow: {
        glass: "0 18px 48px rgba(0, 0, 0, 0.42)",
        glow: "0 0 28px rgba(93, 214, 255, 0.18)"
      },
      keyframes: {
        drift: { "0%,100%": { transform: "translateY(0)" }, "50%": { transform: "translateY(-9px)" } },
        pulseNode: {
          "0%,100%": { opacity: "0.55", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.12)" }
        },
        conveyor: { "0%": { backgroundPosition: "0 0" }, "100%": { backgroundPosition: "48px 0" } },
        sweep: { "0%": { transform: "translateY(-120%)" }, "100%": { transform: "translateY(320%)" } },
        spinSlow: { to: { transform: "rotate(360deg)" } }
      },
      animation: {
        drift: "drift 7s ease-in-out infinite",
        pulseNode: "pulseNode 3s ease-in-out infinite",
        conveyor: "conveyor 2.4s linear infinite",
        sweep: "sweep 6s linear infinite",
        spinSlow: "spinSlow 26s linear infinite"
      }
    }
  },
  plugins: []
};

export default config;
