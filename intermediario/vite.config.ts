import { cloudflare } from "@cloudflare/vite-plugin";
import { defineConfig } from "vite";

// Con SITO (cloudflare.config.ts) il Worker pubblica anche i file del sito: la build di web/ (npm run build là).
const sito = process.env.SITO_DIST ?? (process.env.SITO ? "../web/dist" : false);

export default defineConfig({
  plugins: [cloudflare()],
  publicDir: sito,
});
