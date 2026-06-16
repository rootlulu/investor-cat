import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiTarget = process.env.VITE_API_TARGET || "http://127.0.0.1:5173";

export default defineConfig({
  root: "frontend",
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5174,
    proxy: {
      "/api": apiTarget
    }
  },
  build: {
    outDir: "../public",
    emptyOutDir: true
  }
});
