// Local proxy replacing nginx — routes /livekit-ws/ to LiveKit server, everything else to Next.js
const http = require("http");
const httpProxy = require("http-proxy");

const LISTEN_PORT = 5333;
const NEXTJS_PORT = 5334;
const LIVEKIT_PORT = 7880;

const nextProxy = httpProxy.createProxyServer({ target: `http://127.0.0.1:${NEXTJS_PORT}`, ws: true });
const livekitProxy = httpProxy.createProxyServer({ target: `http://127.0.0.1:${LIVEKIT_PORT}`, ws: true });

nextProxy.on("error", (err) => console.error("next proxy error:", err.message));
livekitProxy.on("error", (err) => console.error("livekit proxy error:", err.message));

const server = http.createServer((req, res) => {
  if (req.url.startsWith("/livekit-ws/")) {
    req.url = req.url.replace(/^\/livekit-ws\//, "/");
    livekitProxy.web(req, res);
  } else {
    nextProxy.web(req, res);
  }
});

server.on("upgrade", (req, socket, head) => {
  if (req.url.startsWith("/livekit-ws/")) {
    req.url = req.url.replace(/^\/livekit-ws\//, "/");
    livekitProxy.ws(req, socket, head);
  } else {
    nextProxy.ws(req, socket, head);
  }
});

server.listen(LISTEN_PORT, "0.0.0.0", () => {
  console.log(`Proxy listening on :${LISTEN_PORT} -> Next.js :${NEXTJS_PORT} + LiveKit :${LIVEKIT_PORT}`);
});
