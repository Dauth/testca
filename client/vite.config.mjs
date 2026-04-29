import { defineConfig } from "vite";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();

export default defineConfig({
  plugins: [
    {
      name: "local-spectate-route",
      configureServer(server) {
        server.middlewares.use("/spectate", (_req, res) => {
          const htmlPath = path.join(root, "spectate.html");
          const html = fs.readFileSync(htmlPath, "utf8");
          res.statusCode = 200;
          res.setHeader("Content-Type", "text/html");
          res.end(html);
        });
      },
    },
  ],
  server: {
    proxy: {
      "/api": "http://localhost:8080",
      "/health": "http://localhost:8080",
      "/ws": {
        target: "ws://localhost:8080",
        ws: true,
      },
    },
  },
});
