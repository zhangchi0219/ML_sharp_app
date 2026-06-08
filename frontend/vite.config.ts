import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 本机个人工具：dev 时前端 :5173，把 /api 与 /files 代理到后端 :8000。
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/files": "http://localhost:8000",
    },
  },
  build: {
    // 大型依赖单独分包，避免初始包过大。
    rollupOptions: {
      output: {
        manualChunks: {
          three: ["three"],
          splat: ["@mkkellogg/gaussian-splats-3d"],
        },
      },
    },
  },
});
