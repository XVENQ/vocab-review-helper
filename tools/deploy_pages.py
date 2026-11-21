#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一键部署背词助手到 GitHub Pages（XVENQ/vocab-review-helper）。

流程：HTML→index.html、assets/stories 增量同步、tts/ 静态发音构建（增量）、
data/vocab.json 播种、sw.js/manifest 生成、git commit+push、自动开启 Pages。

用法：
  python tools/deploy_pages.py            # 全量部署
  python tools/deploy_pages.py --no-tts   # 跳过音频构建（快）
  python tools/deploy_pages.py --no-push  # 只准备文件不推
"""
import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                       # 背词助手/
APP = os.path.normpath(os.path.join(ROOT, "..", "outputs", "单词复习", "背词助手.html"))
APP_ASSETS = os.path.normpath(os.path.join(ROOT, "..", "outputs", "单词复习", "assets", "stories"))
DATA = r"C:\Users\xuenc\Desktop\英语学习方法\studyEnglish\背词助手数据.json"
TTS_CACHE = os.path.join(ROOT, ".tts_cache")
REPO = ROOT                                         # 仓库根 = 背词助手/
REPO_USER, REPO_NAME = "XVENQ", "vocab-review-helper"

WORDS = None
ARGS = None


def _http_get(url, timeout=15):
    """直连外网；证书验证失败时降级不验签（本机中间人软件场景）。"""
    import ssl
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", "") or e)
        if "CERTIFICATE" in reason.upper() or isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            with urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
                return r.read()
        raise


def git_token():
    """从 Git 凭据管理器拿 gho_ token（GCM 已登录）。拿不到返回 None。"""
    try:
        p = subprocess.run(["git", "credential", "fill"],
                           input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=20)
        d = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l)
        return d.get("password") or None
    except Exception:
        return None


def api(method, path, token, payload=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 headers={"Authorization": "Bearer " + token,
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "beici-deploy"})
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data, timeout=30) as r:
        body = r.read().decode("utf-8")
        return json.loads(body) if body else {}


def sync_assets():
    """assets/stories 增量同步：按文件名补齐，删仓库多余 webp。"""
    dst = os.path.join(REPO, "assets", "stories")
    os.makedirs(dst, exist_ok=True)
    n_add = n_del = 0
    src_set = set()
    for f in os.listdir(APP_ASSETS):
        if not f.endswith(".webp"):
            continue
        src_set.add(f)
        src_p, dst_p = os.path.join(APP_ASSETS, f), os.path.join(dst, f)
        if not os.path.exists(dst_p) or os.path.getmtime(dst_p) < os.path.getmtime(src_p):
            shutil.copyfile(src_p, dst_p)
            n_add += 1
    for f in os.listdir(dst):
        if f.endswith((".webp", ".png", ".jpg")) and f not in src_set:
            os.remove(os.path.join(dst, f))
            n_del += 1
    print("assets：新增/更新 %d，删除多余 %d" % (n_add, n_del))


def sync_html():
    shutil.copyfile(APP, os.path.join(REPO, "index.html"))
    print("index.html ← %d B" % os.path.getsize(APP))


def build_tts():
    """构建同源静态发音 tts/<acc>/<word>.mp3（增量：.tts_cache 有则复制，无则拉有道）。"""
    global WORDS
    n_new = n_copy = 0
    for acc in ("uk", "us"):
        dst_dir = os.path.join(REPO, "tts", acc)
        os.makedirs(dst_dir, exist_ok=True)
        for w in WORDS:
            dst_p = os.path.join(dst_dir, w + ".mp3")
            if os.path.exists(dst_p):
                continue
            key = hashlib.sha1((acc + "|" + w).encode("utf-8")).hexdigest()[:24]
            cache_p = os.path.join(TTS_CACHE, key + ".mp3")
            try:
                if os.path.exists(cache_p):
                    shutil.copyfile(cache_p, dst_p)
                    n_copy += 1
                else:
                    url = ("https://dict.youdao.com/dictvoice?audio=" + w +
                           "&type=" + ("2" if acc == "us" else "1"))
                    data = _http_get(url)
                    if data and len(data) > 500:
                        io.open(dst_p, "wb").write(data)
                        n_new += 1
                    else:
                        print("  ⚠ 音频异常跳过：%s/%s" % (acc, w))
            except Exception as e:
                print("  ⚠ 拉取失败 %s/%s：%s" % (acc, w, e))
    print("tts：新增 %d，缓存复制 %d" % (n_new, n_copy))


def write_pwa_files():
    ts = time.strftime("%Y%m%d_%H%M")
    os.makedirs(os.path.join(REPO, "icons"), exist_ok=True)
    for size in (192, 512):
        src = os.path.join(REPO, "icons", "icon-%d.png" % size)
        if not os.path.exists(src):
            raise SystemExit("缺图标 icons/icon-%d.png——先运行图标生成" % size)
    manifest = {
        "name": "背词助手", "short_name": "背词",
        "start_url": "./", "scope": "./", "display": "standalone",
        "background_color": "#FAF9F6", "theme_color": "#FAF9F6",
        "icons": [{"src": "icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "icons/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }
    io.open(os.path.join(REPO, "manifest.json"), "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=1))
    sw = '''/* 背词助手 Service Worker —— deploy_pages.py 自动生成，勿手改 */
const CACHE = "beici-v__BUILD__";
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
'''
    io.open(os.path.join(REPO, "sw.js"), "w", encoding="utf-8").write(sw.replace("__BUILD__", ts))
    print("sw.js / manifest.json 已生成（cache beici-v%s）" % ts)


def deploy():
    global WORDS, ARGS
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ARGS = ap.parse_args()

    # 词集：优先数据文件（真实词库），缺失时退回 STORIES+内置扫描
    d = json.loads(io.open(DATA, encoding="utf-8").read())
    WORDS = sorted({w["word"].strip().lower() for w in d.get("words", []) if w.get("word")})
    print("词集 %d 个" % len(WORDS))

    sync_html()
    sync_assets()
    if not ARGS.no_tts:
        build_tts()
    write_pwa_files()
    # data/vocab.json 播种（云中转源）
    dst_data = os.path.join(REPO, "data", "vocab.json")
    os.makedirs(os.path.dirname(dst_data), exist_ok=True)
    shutil.copyfile(DATA, dst_data)
    print("data/vocab.json ← %d B" % os.path.getsize(DATA))

    if ARGS.no_push:
        print("（--no-push：文件已就绪，未推送）")
        return 0

    token = git_token()
    if not token:
        print("⚠ 拿不到 GitHub token（git credential），无法 push——请手动 git push")
        return 1

    # 自动开启 Pages（幂等：已开启时 API 返回即可）
    try:
        api("GET", "/repos/%s/%s/pages" % (REPO_USER, REPO_NAME), token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            api("POST", "/repos/%s/%s/pages" % (REPO_USER, REPO_NAME), token,
                {"source": {"branch": "main", "path": "/"}})
            print("✓ Pages 已开启")

    def git(*a):
        r = subprocess.run(["git"] + list(a), capture_output=True, text=True, cwd=REPO)
        if r.returncode != 0:
            print("git %s 失败：%s" % (a[0], (r.stderr or r.stdout).strip()[:300]))
        return r.returncode

    git("add", "-A")
    st = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=REPO)
    if not st.stdout.strip():
        print("无需部署：全部文件无变化")
        return 0
    ts = time.strftime("%Y-%m-%d %H:%M")
    if git("commit", "-m", "deploy %s（PWA + 云中转）" % ts) != 0:
        return 1
    if git("push", "origin", "main") != 0:
        return 1
    print("✓ 已推送。Pages 生效：https://%s.github.io/%s/" % (REPO_USER, REPO_NAME))
    return 0


if __name__ == "__main__":
    sys.exit(deploy())
