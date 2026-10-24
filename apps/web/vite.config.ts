import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
const forbiddenClientSecrets=Object.keys(process.env).filter(k=>/^VITE_.*(SECRET|TOKEN|PASSWORD|PRIVATE|INSTITUTIONAL)/i.test(k));
if(forbiddenClientSecrets.length) throw new Error("PRIVATE_CONFIGURATION_CANNOT_ENTER_CLIENT_BUILD: "+forbiddenClientSecrets.join(","));
export default defineConfig({
  server: {
    host: "127.0.0.1",
    fs: {
      allow: [
        fileURLToPath(new URL(".", import.meta.url)),
        fileURLToPath(new URL("../../shared", import.meta.url)),
      ],
    },
    proxy: { "/api": { target: "http://127.0.0.1:8765", changeOrigin: false } },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("echarts") || id.includes("zrender")) return "charts";
          if (id.includes("@xyflow")) return "graphs";
        },
      },
    },
  },
});
