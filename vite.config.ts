import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 8742,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8741",
    },
  },
  preview: {
    host: "127.0.0.1",
    port: 8742,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    target: "es2022",
    emptyOutDir: true,
    sourcemap: false,
  },
});
