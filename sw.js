/* 背词助手 Service Worker —— deploy_pages.py 自动生成，勿手改 */
const CACHE = "beici-v20261119_2048";
const SHELL = ["./", "index.html", "manifest.json", "icons/icon-192.png", "icons/icon-512.png"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;               // POST（LAN 同步）全放行
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;           // 跨源全放行：/api、api.github.com、有道
  const base = new URL(self.registration.scope).pathname;
  const p = url.pathname.startsWith(base) ? url.pathname.slice(base.length - 1) : url.pathname;
  if (p.startsWith("/data/") || p.startsWith("/api/") || p.startsWith("/tts/")) return;   // 数据与音频永不缓存（音频走浏览器直连 + IndexedDB）
  if (p.startsWith("/assets/")) {                        // 仅图片 cache-first（音频不进 SW：Edge PWA 下 SW 内 fetch 必挂，
    e.respondWith(caches.open(CACHE).then(c => c.match(e.request).then(hit => {   // 音频直连走 /data/ 同款路径 + IndexedDB 持久缓存）
      if (hit) return hit;
      return fetch(e.request, { cache: "reload" }).then(r => {
        if (r.ok) { try { c.put(e.request, r.clone()).catch(() => {}); } catch (e2) {} }
        return r;
      });
    }).catch(() => fetch(e.request, { cache: "reload" }))));
    return;
  }
  if (e.request.mode === "navigate") {                  // 导航 network-first 且禁 HTTP 缓存(Pages max-age=600 会拿到旧壳)，离线回壳
    e.respondWith(fetch(e.request, { cache: "no-store" }).catch(() =>
      caches.match(base + "index.html").then(m => m || caches.match("index.html"))));
    return;
  }
  e.respondWith(caches.open(CACHE).then(c => c.match(e.request).then(hit => {   // 其余 SWR
    const f = fetch(e.request).then(r => { if (r.ok) c.put(e.request, r.clone()); return r; })
                               .catch(() => hit);
    return hit || f;
  })));
});
