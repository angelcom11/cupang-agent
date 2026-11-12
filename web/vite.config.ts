import path from "node:path";
import react from "@vitejs/plugin-react";
import styleX from "@stylexjs/rollup-plugin";
import {defineConfig} from "vite";

const SRC = path.resolve(import.meta.dirname, "src");

// Flask 가 이 번들을 서빙한다 (templates 대신 static/dist).
// StyleX 컴파일러는 **내 소스만** 본다 — node_modules/@astryxdesign 는 이미 빌드된
// 스타일시트(astryx.css)를 쓰므로 가리키면 안 된다. 일부 페이지 템플릿이 StyleX 를 쓴다.
export default defineConfig({
  base: "/static/dist/",
  plugins: [
    react(),
    {
      ...styleX({include: [path.join(SRC, "**/*.{ts,tsx}")], useCSSLayers: true}),
      enforce: "pre",
      // apply 를 "build" 로 묶으면 dev 서버에서 StyleX 가 컴파일되지 않아
      // "Unexpected 'stylex.create' call at runtime" 으로 화면이 빈다 (직접 겪음).
    },
  ],
  build: {
    outDir: path.resolve(import.meta.dirname, "..", "static", "dist"),
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    // 개발 중에는 Flask(26118/26119)로 API 를 넘긴다
    proxy: {
      "/api": {target: "http://127.0.0.1:26119", changeOrigin: true},
    },
  },
});
