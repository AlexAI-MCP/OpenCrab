import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: "#00C896",
        ink: "#07100d",
        mist: "#8CA59B",
        line: "rgba(255,255,255,0.08)"
      },
      boxShadow: {
        shell: "0 24px 80px rgba(0, 0, 0, 0.38)",
        accent: "0 0 0 1px rgba(0, 200, 150, 0.22), 0 20px 60px rgba(0, 200, 150, 0.14)"
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(255,255,255,0.06) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.06) 1px, transparent 1px)"
      }
    }
  },
  plugins: []
};

export default config;
