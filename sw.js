/* 背词助手 Service Worker —— deploy_pages.py 自动生成，勿手改 */
const CACHE = "beici-v20261121_1511";
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
  if (e.request.mode === "navigate") {
    // 壳 SWR：有缓存壳立即返回（秒开，不再每次全量下载），后台静默校新；
    // 内容变了 → 更新缓存 + 通知页面提示刷新。无壳（首次）才走网络并落缓存。
    const bgCheck = (async () => {
      try {
        const c = await caches.open(CACHE);
        const hit = await c.match(base + "index.html");
        if (!hit) return;                     // 首次无壳：respondWith 自己会拉并落缓存，不重复下载
        const r = await fetch(e.request, { cache: "no-store" });
        if (!r.ok) return;
        const fresh = await r.text();
        const oldText = await hit.clone().text();
        if (fresh !== oldText) {
          await c.put(base + "index.html", new Response(fresh, { headers: { "Content-Type": "text/html; charset=utf-8" } }));
          const cs = await self.clients.matchAll();
          cs.forEach(cl => cl.postMessage({ type: "app-update" }));
        }
      } catch (err) {}
    })();
    e.respondWith((async () => {
      try {
        const c = await caches.open(CACHE);
        const hit = await c.match(base + "index.html");
        if (hit) return hit;                  // 秒开：缓存壳直接回
        return await fetch(e.request, { cache: "no-store" });   // 首次：网络拉取
      } catch (err) {
        try {
          const c = await caches.open(CACHE);
          const hit = await c.match(base + "index.html");
          if (hit) return hit;
        } catch (e2) {}
        throw err;
      }
    })());
    e.waitUntil(bgCheck);
    return;
  }
  e.respondWith(caches.open(CACHE).then(c => c.match(e.request).then(hit => {   // 其余 SWR
    const f = fetch(e.request).then(r => { if (r.ok) c.put(e.request, r.clone()); return r; })
                               .catch(() => hit);
    return hit || f;
  })));
});
