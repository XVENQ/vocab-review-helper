#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""背词助手局域网同步服务器（纯标准库，零依赖）

架构：电脑跑本服务，管着那份 JSON 数据文件；手机浏览器打开电脑的地址，
用同一份数据。手机离线背的进度存在手机浏览器本地，回到同网后自动按词合并。

协议：
  GET  /api/ping   → {ok, rev, ip, port}          客户端探测
  GET  /api/data   → {rev, data}                  全量拉取
  POST /api/data   → body {rev, data}             推送
      · body.rev < 服务器 rev → 409 {rev, data}（客户端按词合并后重推）
      · 接受 → 服务器盖 updatedAt/rev，原子写盘，备份轮换（保留 30 份）
  GET  /           → 背词助手.html
  GET  /assets/*   → 静态资源（后缀白名单 + 防路径穿越）

版本：用单调递增的 `rev` 计数器（存 JSON 顶层），不用 updatedAt 当版本
      ——毫秒时间戳在快速连续 push 下可能碰撞。
外部改动检测：每次写盘前核对磁盘 mtime，被外部（如 file:// 模式）改过就先
      备份 + 读入为基线 + rev+1，保证外部修改进入合并流程而不是被覆盖。

用法：
  python tools/sync_server.py [数据文件路径]
  默认数据文件：C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json
"""
import base64
import hashlib
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                    # 背词助手/
STATIC_ROOT = os.path.join(os.path.dirname(ROOT), "outputs", "单词复习")
DEFAULT_DATA = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"
BACKUP_DIR = os.path.join(ROOT, "backups", "sync")
TTS_CACHE = os.path.join(ROOT, ".tts_cache")          # 有道发音的磁盘缓存（一词一次）
PORT = 8765
MAX_BODY = 8 * 1024 * 1024
KEEP_BACKUPS = 30
CT = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
      ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
      ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
      ".ico": "image/x-icon", ".woff2": "font/woff2"}

# ---------------- 数据层 ----------------

class Store:
    """数据文件的内存镜像 + 单调 rev。lock 保护一切读写。"""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.rev = 0
        self.data = None
        self.mtime = 0.0
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.makedirs(BACKUP_DIR, exist_ok=True)
        self.reload(initial=True)

    def _read_disk(self):
        with io.open(self.path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))

    def reload(self, initial=False):
        """从磁盘读入。initial=True 时文件可不存在。"""
        if not os.path.exists(self.path):
            if initial:
                self.data = {"words": [], "settings": {"maxReview": 40}, "updatedAt": 0, "rev": 0}
                self._write(self.data)
            else:
                raise FileNotFoundError(self.path)
        else:
            self.data = self._read_disk()
        self.rev = int(self.data.get("rev") or 0)
        self.mtime = os.path.getmtime(self.path)

    def check_external(self):
        """磁盘被外部（file:// 模式）改过 → 备份外部版、读入为基线、rev+1。
        必须项：否则外部修改会被下一次 push 直接覆盖。"""
        if not os.path.exists(self.path):
            return False
        mt = os.path.getmtime(self.path)
        if abs(mt - self.mtime) < 1e-6:
            return False
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(BACKUP_DIR, "外部改动_%s.json" % stamp)
        external = self._read_disk()
        # 内容完全相同 → 只是 file:// 模式正常落盘，收编 mtime 即可，不涨 rev 不留备份
        if json.dumps(external, sort_keys=True, ensure_ascii=False) == \
           json.dumps(self.data, sort_keys=True, ensure_ascii=False):
            self.mtime = mt
            return False
        try:
            with io.open(self.path, "rb") as f, io.open(backup, "wb") as g:
                g.write(f.read())
            self.data = external
            self.rev = max(self.rev, int(self.data.get("rev") or 0)) + 1
            self.data["rev"] = self.rev
            self.mtime = mt
            print("[sync] 检测到磁盘文件被外部修改，已备份并读入为新基线 rev=%d" % self.rev)
            return True
        except Exception as e:
            print("[sync] 外部改动检测读盘失败：", e)
            return False

    def rotate_backup(self):
        if not os.path.exists(self.path):
            return
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, "数据_%s.json" % stamp)
        try:
            with io.open(self.path, "rb") as f, io.open(dst, "wb") as g:
                g.write(f.read())
            olds = sorted(f for f in os.listdir(BACKUP_DIR) if f.startswith("数据_"))
            for old in olds[:-KEEP_BACKUPS]:
                os.remove(os.path.join(BACKUP_DIR, old))
        except OSError as e:
            print("[sync] 备份失败（继续写盘）：", e)

    def _write(self, data):
        tmp = self.path + ".tmp"
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def accept(self, data):
        """接受一份客户端全量（调用方已确认 rev 不落后）。返回新 rev。
        ⚠ 先与磁盘现状按词合并再写盘：客户端整包可能漏掉别处刚产生的进度，
          直接采用就是 2026-11-09 那次覆盖事故的根源。"""
        with self.lock:
            self.check_external()
            self.rotate_backup()
            m = merge_words(data.get("words") or [], self.data.get("words") or [],
                            data.get("deleted") or [], self.data.get("deleted") or [])
            data = dict(data)
            data["words"] = m["words"]
            data["deleted"] = m["deleted"]
            # todayTime（今日用时）：同一天取较大者，避免两台设备来回打架
            cur_tt = self.data.get("todayTime") or {}
            inc_tt = data.get("todayTime") or {}
            if isinstance(cur_tt, dict) and isinstance(inc_tt, dict) \
                    and cur_tt.get("date") == inc_tt.get("date"):
                data["todayTime"] = {"date": inc_tt.get("date"),
                                     "ms": max(int(cur_tt.get("ms") or 0), int(inc_tt.get("ms") or 0))}
            data["updatedAt"] = int(time.time() * 1000)
            self.rev += 1
            data["rev"] = self.rev
            # 时钟钳制：手机时钟不准时把过未来的 mt 压回
            now_ms = int(time.time() * 1000)
            for w in data.get("words", []):
                if isinstance(w.get("mt"), (int, float)) and w["mt"] > now_ms + 5 * 60 * 1000:
                    w["mt"] = now_ms
            self._write(data)
            self.data, self.mtime = data, os.path.getmtime(self.path)
            return self.rev

    def snapshot(self):
        with self.lock:
            self.check_external()
            return self.rev, self.data



# ---------------- 按词合并（与应用端 mergeWords 同语义） ----------------
# 背景：2026-11-09 事故——客户端拿着「rev 相同但内容更旧」的整包推送，把磁盘上更新的
# 学习进度整个盖掉了。修法：服务器在 accept 前先按词合并，谁新用谁，永远不回退。

def _d2ms(v):
    """日期字符串 → 毫秒。纯日期（≤10 位）按当天正午算，与应用端一致。"""
    if not v:
        return 0
    t = str(v)
    if len(t) <= 10:
        t += "T12:00:00"
    try:
        import datetime
        return int(datetime.datetime.fromisoformat(t).timestamp() * 1000)
    except ValueError:
        return 0


def _recency(w):
    mt = w.get("mt")
    if isinstance(mt, (int, float)) and mt > 0:
        return mt
    return max(_d2ms(w.get("lastRated")), _d2ms(w.get("added")))


def _newer(a, b):
    """a 是否比 b 新：mt → lastRated/added → step → timeMs；全平不算新（保幂等）。"""
    ra, rb = _recency(a), _recency(b)
    if ra != rb:
        return ra > rb
    sa, sb = int(a.get("step") or 0), int(b.get("step") or 0)
    if sa != sb:
        return sa > sb
    return int(a.get("timeMs") or 0) > int(b.get("timeMs") or 0)


def _tomb_key(t):
    return "%s|%s" % (t.get("id"), str(t.get("word") or "").lower())


def _merge_deleted(a, b):
    seen, out = {}, []
    for t in list(a or []) + list(b or []):
        if not isinstance(t, dict) or t.get("id") is None:
            continue
        k = _tomb_key(t)
        at = int(t.get("at") or 0)
        if k not in seen:
            seen[k] = {"id": t.get("id"), "word": t.get("word") or "", "at": at}
            out.append(seen[k])
        elif at > seen[k]["at"]:
            seen[k]["at"] = at
    out.sort(key=lambda x: x["at"])
    return out[-2000:]


def merge_words(local_words, server_words, local_tomb, server_tomb):
    """返回 {words, deleted}。local = 推送方，server = 磁盘现状。"""
    tombs = _merge_deleted(local_tomb, server_tomb)
    tmap = {}
    for t in tombs:
        tmap[_tomb_key(t)] = t["at"]

    def alive(ws):
        out = []
        for w in ws:
            k = "%s|%s" % (w.get("id"), str(w.get("word") or "").lower())
            at = tmap.get(k)
            if at is None or _recency(w) > at:      # 比墓碑新 → 复活
                out.append(dict(w))
        return out

    L2, S2 = alive(local_words or []), alive(server_words or [])
    by_id = {}
    id_seed = max([0] + [int(w.get("id") or 0) for w in L2 + S2]
                  + [int(t.get("id") or 0) for t in tombs])
    for w in L2:
        by_id[str(w.get("id"))] = w
    now_ms = int(time.time() * 1000)
    for sw in S2:
        k = str(sw.get("id"))
        lw = by_id.get(k)
        if lw is None:
            by_id[k] = sw
        elif str(lw.get("word") or "").lower() == str(sw.get("word") or "").lower():
            if _newer(sw, lw):                       # 平局取 local（幂等关键）
                by_id[k] = sw
        else:                                        # id 撞车且词不同：server 词重编号
            id_seed += 1
            sw = dict(sw, id=id_seed)
            by_id[str(id_seed)] = sw

    by_word, words2, del2 = {}, [], []
    for w in by_id.values():                         # 同词文去重（两设备各自导入同一个词）
        k = str(w.get("word") or "").lower()
        cur = by_word.get(k)
        if cur is None:
            by_word[k] = w
            words2.append(w)
            continue
        keep, lose = (w, cur) if _newer(w, cur) else (cur, w)
        if keep is w:
            words2[words2.index(cur)] = w
        by_word[k] = keep
        del2.append({"id": lose.get("id"), "word": lose.get("word"), "at": now_ms})

    words2.sort(key=lambda w: int(w.get("id") or 0))
    return {"words": words2, "deleted": _merge_deleted(tombs, del2)}


STORE = None

# ---------------- GitHub 云桥接（可选：拿到 token 才启用） ----------------
CLOUD_RAW = "https://raw.githubusercontent.com/XVENQ/vocab-review-helper/main/data/vocab.json"
CLOUD_API = "https://api.github.com/repos/XVENQ/vocab-review-helper/contents/data/vocab.json"


def git_credential_fill():
    """从 Git 凭据管理器取 gho_ token（GCM 已登录）。失败返回 None。"""
    try:
        p = subprocess.run(["git", "credential", "fill"],
                           input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=20)
        d = dict(l.split("=", 1) for l in p.stdout.splitlines() if "=" in l)
        return d.get("password") or None
    except Exception:
        return None


def _api(method, path, token, payload=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 headers={"Authorization": "Bearer " + token,
                                          "Accept": "application/vnd.github+json",
                                          "User-Agent": "beici-server"})
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, data, timeout=30) as r:
        body = r.read().decode("utf-8")
        return json.loads(body) if body else {}


def cloud_sync_once(token):
    """拉云 → accept 收编（内部 merge+备份+写盘）→ 磁盘有新内容则推回云。"""
    try:
        cloud = json.loads(_http_get(CLOUD_RAW + "?t=%d" % int(time.time())).decode("utf-8"))
    except Exception as e:
        print("[cloud] 拉取失败:", e)
        return
    if not isinstance(cloud, dict) or not isinstance(cloud.get("words"), list):
        print("[cloud] 云端数据格式异常，跳过")
        return
    before = json.dumps(STORE.data, sort_keys=True, ensure_ascii=False)
    STORE.accept(cloud)
    after = json.dumps(STORE.data, sort_keys=True, ensure_ascii=False)
    if after != before:
        print("[cloud] 已合并云端进度（rev=%d）" % STORE.rev)
    try:
        meta = _api("GET", "/repos/XVENQ/vocab-review-helper/contents/data/vocab.json", token)
        cloud_now = json.loads(base64.b64decode(meta["content"]).decode("utf-8"))
        if json.dumps(cloud_now, sort_keys=True, ensure_ascii=False) == after:
            return
        merged = merge_words(STORE.data.get("words") or [], cloud_now.get("words") or [],
                             STORE.data.get("deleted") or [], cloud_now.get("deleted") or [])
        out = dict(STORE.data)
        out["words"] = merged["words"]
        out["deleted"] = merged["deleted"]
        _api("PUT", "/repos/XVENQ/vocab-review-helper/contents/data/vocab.json", token,
             {"message": "bridge sync " + time.strftime("%H:%M"),
              "content": base64.b64encode(json.dumps(out, ensure_ascii=False).encode("utf-8")).decode("ascii"),
              "sha": meta["sha"]})
        print("[cloud] 已推送合并结果到云（词 %d）" % len(out["words"]))
    except Exception as e:
        print("[cloud] 推送失败:", e)


def poll_cloud(token, stop):
    """10 分钟轮询：云端 etag 变化或磁盘被外部改动 → 双向同步一次。"""
    last_mtime = os.path.getmtime(STORE.path)
    while not stop.wait(600):
        try:
            mt = os.path.getmtime(STORE.path)
            disk_changed = abs(mt - last_mtime) > 1
            cloud_sync_once(token)
            last_mtime = os.path.getmtime(STORE.path)
            if disk_changed:
                print("[cloud] 磁盘有 LAN 推送的新进度，已中转上云")
        except Exception as e:
            print("[cloud] 轮询异常:", e)

# ---------------- HTTP ----------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BeiciSync/1.0"

    def log_message(self, fmt, *args):        # 安静模式：只打非 200
        if args and args[1] != "200":
            print("[http]", fmt % args)

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # 手机离线副本（file:// → Origin: null）跨域访问 /api/*。
        # 只放行 "null"，普通网站的跨域请求仍然被浏览器拦住。
        if (self.path.startswith("/api") or self.path.startswith("/tts")) \
                and (self.headers.get("Origin") or "") == "null":
            self.send_header("Access-Control-Allow-Origin", "null")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    _tls_hits = {"n": 0}

    def send_error(self, code, message=None, explain=None):
        # TLS 握手打到纯 HTTP 端口时，解析阶段会调 send_error(400, "Bad request version …")。
        # 手机浏览器对地址栏输入默认「HTTPS 优先」，不打回退——日志里全是乱码 400 就是这个。
        if code == 400 and message and "Bad request" in str(message):
            self._tls_hits["n"] += 1
            n = self._tls_hits["n"]
            if n == 1 or n % 20 == 0:
                print("[sync] ⚠ 第 %d 次：收到 HTTPS 打到纯 HTTP 端口——"
                      "手机地址栏必须以 http:// 开头，例：http://%s:%d/" % (n, LAN_IP, PORT))
        super().send_error(code, message, explain)

    def do_OPTIONS(self):
        # 跨域 POST（Content-Type: application/json）会先发预检
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        if (self.headers.get("Origin") or "") == "null":
            self.send_header("Access-Control-Allow-Origin", "null")
        self.end_headers()

    def _serve_word(self, word, acc):
        """按词+口音出音频：磁盘缓存 → 有道 → 落盘（供 /tts?word= 与 /tts/<acc>/<word>.mp3 双路由）。"""
        import urllib.parse as _up
        if not re.match(r"^[a-z][a-z'’\\-]{0,39}$", word):
            return self._send(400, {"error": "bad word"})
        if acc not in ("us", "uk"):
            acc = "uk"
        key = hashlib.sha1((acc + "|" + word).encode("utf-8")).hexdigest()[:24]
        mp3 = os.path.join(TTS_CACHE, key + ".mp3")
        if not os.path.exists(mp3):
            url = "https://dict.youdao.com/dictvoice?audio=%s&type=%d" % (_up.quote(word), 2 if acc == "us" else 1)
            data, last_err = None, None
            for _ in range(3):
                try:
                    data = _http_get(url)
                    break
                except Exception as e:
                    last_err = e
                    time.sleep(0.8)
            if data is None:
                print("[tts] 拉取失败:", last_err)
                return self._send(502, {"error": "upstream failed"})
            try:
                tmp = mp3 + ".tmp"
                with io.open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, mp3)
            except OSError as e:
                print("[tts] 缓存写盘失败（继续返回音频）:", e)
        with io.open(mp3, "rb") as f:
            self._send(200, f.read(), "audio/mpeg", {"Cache-Control": "max-age=31536000"})

    def _tts(self, full_path):
        """query 版入口：/tts?word=&acc="""
        from urllib.parse import urlparse, parse_qs
        try:
            qs = parse_qs(urlparse(full_path).query)
        except Exception:
            return self._send(400, {"error": "bad query"})
        word = (qs.get("word") or [""])[0].strip().lower()
        acc = (qs.get("acc") or ["uk"])[0]
        return self._serve_word(word, acc)

    def _static(self, rel):
        rel = rel.lstrip("/").replace("\\", "/")
        path = os.path.normpath(os.path.join(STATIC_ROOT, rel))
        if not path.startswith(os.path.normpath(STATIC_ROOT)):     # 防穿越
            return self._send(403, {"error": "forbidden"})
        if not os.path.isfile(path):
            return self._send(404, {"error": "not found"})
        ext = os.path.splitext(path)[1].lower()
        if ext not in CT:
            return self._send(403, {"error": "type not allowed"})
        with io.open(path, "rb") as f:
            self._send(200, f.read(), CT[ext])

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/ping":
            rev, _ = STORE.snapshot()
            return self._send(200, {"ok": True, "rev": rev, "ip": LAN_IP, "port": PORT})
        if path == "/api/data":
            rev, data = STORE.snapshot()
            return self._send(200, {"rev": rev, "data": data})
        if path == "/favicon.ico":
            return self._send(204, b"", "text/plain")   # 浏览器自动请求，没有图标也别刷 404
        m = re.match(r"^/tts/(uk|us)/([a-z][a-z'\\-]{0,39})\.mp3$", path)
        if m:
            return self._serve_word(m.group(2), m.group(1))
        if path == "/tts":
            return self._tts(self.path)
        if path in ("/", "/index.html", "/背词助手.html"):
            return self._static("背词助手.html")
        if path == "/download":
            fp = os.path.join(STATIC_ROOT, "背词助手.html")
            if not os.path.isfile(fp):
                return self._send(404, {"error": "not found"})
            from urllib.parse import quote
            with io.open(fp, "rb") as f:
                body = f.read()
            # 把「离线副本回家用的服务器地址」和「下载那一刻的全量数据」写进副本：
            # 前者让它回得了家，后者保证断网第一次打开就有完整数据（开箱即用）
            body = body.replace(b'const SYNC_HOME = "__SYNC_HOME__";',
                                ('const SYNC_HOME = "%s";' % ("http://%s:%d" % (LAN_IP, PORT))).encode("utf-8"))
            embed = json.dumps(STORE.data, ensure_ascii=False).replace("<", "\\u003c").encode("utf-8")
            body = body.replace(b'const EMBED_DATA = null;', b'const EMBED_DATA = ' + embed + b';')
            body = body.replace(b'const SYNC_STAMP = "__SYNC_STAMP__";',
                                ('const SYNC_STAMP = "%s";' % time.strftime("%m-%d %H:%M")).encode("utf-8"))
            # 文件名带时间戳：浏览器对同名文件会自动加 (1)(2) 另存，带时间戳才能一眼认出最新副本
            stamp = time.strftime("%m%d_%H%M")
            cd = "attachment; filename=beici_%s.html; filename*=UTF-8''%s" % (
                stamp, quote("背词助手_%s.html" % stamp))
            return self._send(200, body, "text/html; charset=utf-8", {"Content-Disposition": cd})
        if path.startswith("/assets/"):
            return self._static(path)
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/api/data":
            return self._send(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self._send(413 if n > MAX_BODY else 400, {"error": "bad size"})
        try:
            body = json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return self._send(400, {"error": "bad json"})
        if not isinstance(body, dict) or not isinstance(body.get("data"), dict) \
                or not isinstance(body["data"].get("words"), list):
            return self._send(400, {"error": "missing words"})
        try:
            base = int(body.get("rev") or 0)
        except (TypeError, ValueError):
            base = 0
        cur_rev, cur_data = STORE.snapshot()
        if base < cur_rev:                      # 客户端落后 → 冲突，附全量让它合并
            return self._send(409, {"rev": cur_rev, "data": cur_data})
        new_rev = STORE.accept(body["data"])
        # 带回合并后的全量：客户端据此吸收其他设备的新进度、实时修剪自己的队列
        return self._send(200, {"rev": new_rev, "data": STORE.data})


def _http_get(url, timeout=10):
    """直连外部 HTTPS。证书验证失败时（本机装了做 TLS 中间的软件）降级为不验签——
    只用于拉公开音频，内容风险可忽略。"""
    import urllib.request
    import ssl
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", "") or e)
        if "CERTIFICATE" in reason.upper() or isinstance(getattr(e, "reason", None), ssl.SSLCertVerificationError):
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        raise


def lan_ip():
    """UDP connect 技巧取出口 IP，不真正发包。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main():
    global STORE, LAN_IP
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    data_path = args[0] if args else DEFAULT_DATA
    STORE = Store(data_path)
    try:
        os.makedirs(TTS_CACHE, exist_ok=True)
    except OSError:
        pass
    # 云桥接（可选）：从凭据管理器拿 token，启动时双向同步一次，之后 10 分钟轮询
    _token = git_credential_fill()
    if _token:
        print("[cloud] GitHub token 已从凭据管理器读取——云桥接启动")
        _stop = threading.Event()

        def _cloud_starter():
            cloud_sync_once(_token)
            threading.Thread(target=poll_cloud, args=(_token, _stop), daemon=True).start()

        threading.Thread(target=_cloud_starter, daemon=True).start()
    else:
        print("[cloud] 未获取到 GitHub token——云桥接关闭（纯局域网模式照常）")
    LAN_IP = lan_ip()
    url = "http://%s:%d/" % (LAN_IP, PORT)
    print("=" * 56)
    print(" 背词助手同步服务器")
    print("   数据文件 :", data_path)
    print("   当前词条 :", len(STORE.data.get("words", [])), "| rev =", STORE.rev)
    print("   本机访问 :", "http://localhost:%d/" % PORT)
    print("   手机访问 :", url, "（需与电脑同一网络）")
    if LAN_IP == "127.0.0.1":
        print("   ⚠ 未探测到局域网 IP（当前可能没联网）——上面的二维码/地址手机用不了，联网后重启本程序")
    print("   防火墙   : 手机连不上时，用管理员运行——")
    print('     netsh advfirewall firewall add rule name="BeiciSync" dir=in action=allow protocol=TCP localport=%d' % PORT)
    print("=" * 56)
    print(" 手机一次配置：扫下方二维码 → 浏览器打开 → 菜单里「添加到主屏幕」，以后点图标直达")

    qr_png = None
    try:                                     # 终端 ASCII 二维码默认即可扫；大图仅 --qr 时弹出
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(url)
        qr.make(fit=True)
        qr_png = os.path.join(os.environ.get("TEMP", os.path.dirname(data_path)), "beici_qr.png")
        qr.make_image().save(qr_png)         # 仍会存一份 PNG 备用，但不自动弹相册
        if "--qr" in sys.argv:
            try:
                os.startfile(qr_png)         # 只在想看大图时用：python sync_server.py --qr
            except (AttributeError, OSError):
                pass
        qr.print_ascii(invert=True)
    except ImportError:
        print("（装 qrcode + pillow 可出二维码：pip install qrcode pillow -i https://mirrors.aliyun.com/pypi/simple/）")
    except Exception as e:                   # 二维码出任何问题都不能挡住服务器启动
        print("（二维码生成失败，不影响服务：", e, "）")
    if "--no-open" not in sys.argv:
        try:
            webbrowser.open("http://localhost:%d/" % PORT)
        except Exception:
            pass
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    except OSError as e:
        print("[sync] 端口 %d 被占用（%s）" % (PORT, e))
        print("       服务器多半已经开着了——不要重复启动，直接用 http://localhost:%d/" % PORT)
        return 1
    print("[sync] 服务已启动，Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[sync] 已停止")


LAN_IP = "127.0.0.1"
if __name__ == "__main__":
    main()
