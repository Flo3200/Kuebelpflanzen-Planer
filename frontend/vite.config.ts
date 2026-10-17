import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development Vite proxies the API to the FastAPI server; in production FastAPI serves dist/.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/agent": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
    chunkSizeWarningLimit: 1500,
  },
});
