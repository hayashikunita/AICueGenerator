import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 開発時は Vite dev server (5173) から同一Originで /api・/ws を叩けるよう
// バックエンド (既定 127.0.0.1:8000) へプロキシする。
// 本番ビジュアルは backend/static へビルドし、バックエンドが同一Origin配信する。
const backend = process.env.VITE_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/ws": { target: backend, ws: true, changeOrigin: true },
    },
  },
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
  },
});
