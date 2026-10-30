# -*- coding: utf-8 -*-
"""故事配图流水线：导出 prompt → 调本地模型 → 转 webp → 核对 → 挑图。

设计原则：本脚本不绑定任何具体生图软件。
  1. --export  把 60 条场景导出成 prompts.json，任何工具都能读
  2. --run     直接调本地 HTTP 接口（webui / comfyui），也可跳过自己手动生成
  3. --check   核对缺图、尺寸、格式
  4. --sheet   生成一张预览页，方便肉眼挑图

常用：
  python tools/make_story_images.py --export
  python tools/make_story_images.py --run --api webui --url http://127.0.0.1:7860
  python tools/make_story_images.py --run --api comfyui --url http://127.0.0.1:8188 --workflow workflow_api.json
  python tools/make_story_images.py --check
  python tools/make_story_images.py --sheet

图片约定：
  输出目录      assets/stories/
  文件名        {slug}-{1..4}.webp      例：a-small-accident-1.webp
  尺寸          768×512（3:2）
  单张体积      约 40–90 KB，60 张合计 3–5 MB
"""
import argparse
import base64
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import story_scenes as S  # noqa: E402

W, H = 768, 512
DEFAULT_OUT = os.path.join(ROOT, "assets", "stories")

# 故事 -> slug，须与 _build_stories.py 生成的 slug 一致
SLUG = {
    "A Small Accident": "a-small-accident",
    "Up the Mountain": "up-the-mountain",
    "The Old Man Next Door": "the-old-man-next-door",
    "The Science Fair": "the-science-fair",
    "A Letter from Abroad": "a-letter-from-abroad",
    "The Race": "the-race",
    "A Quiet Evening": "a-quiet-evening",
    "The Missing Wallet": "the-missing-wallet",
    "The New Community Center": "the-new-community-center",
    "The Letter That Was Never Sent": "the-letter-that-was-never-sent",
    "Fourth Place": "fourth-place",
    "The Old Radio": "the-old-radio",
    "Why We Forget": "why-we-forget",
    "The Cost of Convenience": "the-cost-of-convenience",
    "What Justice Means": "what-justice-means",
}


def jobs():
    """展开成 60 条任务，顺序固定，seed 可复现。"""
    out = []
    for title, scenes in S.SCENES.items():
        slug = SLUG[title]
        for k, (p, z) in enumerate(scenes, 1):
            out.append({
                "id": "%s-%d" % (slug, k),
                "story": title,
                "idx": k,
                "prompt": p + ", " + S.STYLE,
                "negative": S.NEGATIVE,
                "width": W,
                "height": H,
                "seed": 1000 + len(out),      # 固定 seed：同一场景反复跑结果一致
                "zh": z,
            })
    return out


# ---------------- export ----------------
def cmd_export(out_dir, path):
    js = jobs()
    data = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(js),
        "width": W, "height": H,
        "output_dir": os.path.relpath(out_dir, ROOT).replace("\\", "/"),
        "naming": "<id>.webp",
        "jobs": js,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("已导出 %d 条 → %s" % (len(js), path))
    print("前两条：")
    for j in js[:2]:
        print("  %s\n    prompt: %s" % (j["id"], j["prompt"][:120]))
    return 0


# ---------------- 生图：通用 HTTP ----------------
def _post(url, payload, timeout=300):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _save_webp(raw, dest, quality=82):
    try:
        from PIL import Image
    except ImportError:
        # 没有 Pillow 就存原图，前端认不出 webp 时可在 --check 里发现
        alt = dest.replace(".webp", ".png")
        open(alt, "wb").write(raw)
        return alt, "（未安装 Pillow，存为 png）"
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    im.save(dest, "WEBP", quality=quality, method=4)
    return dest, "%d KB" % (os.path.getsize(dest) // 1024)


def gen_webui(job, url, n=1, steps=24, cfg=6.5):
    payload = {
        "prompt": job["prompt"], "negative_prompt": job["negative"],
        "width": job["width"], "height": job["height"],
        "steps": steps, "cfg_scale": cfg, "sampler_name": "DPM++ 2M Karras",
        "seed": job["seed"], "batch_size": n, "n_iter": 1,
    }
    r = _post(url.rstrip("/") + "/sdapi/v1/txt2img", payload)
    return [base64.b64decode(x.split(",", 1)[-1]) for x in r.get("images", [])]


def gen_comfyui(job, url, workflow_path, n=1):
    """ComfyUI：读 workflow_api.json，替换文本与尺寸后入队。"""
    wf = json.load(open(workflow_path, encoding="utf-8"))
    pos_ids, neg_ids, size_ids = [], [], []
    for nid, node in wf.items():
        ct = node.get("class_type", "")
        if ct == "CLIPTextEncode":
            txt = json.dumps(node.get("inputs", {}), ensure_ascii=False)
            (neg_ids if "negative" in txt.lower() or job["negative"][:20] in txt else pos_ids).append(nid)
        if ct in ("EmptyLatentImage", "EmptySD3LatentImage"):
            size_ids.append(nid)
    for nid in pos_ids[:1]:
        wf[nid]["inputs"]["text"] = job["prompt"]
    for nid in neg_ids[:1]:
        wf[nid]["inputs"]["text"] = job["negative"]
    for nid in size_ids[:1]:
        wf[nid]["inputs"].update({"width": job["width"], "height": job["height"],
                                  "batch_size": n})

    r = _post(url.rstrip("/") + "/prompt", {"prompt": wf})
    pid = r.get("prompt_id")
    if not pid:
        raise RuntimeError("ComfyUI 未返回 prompt_id: %s" % r)
    imgs = []
    for _ in range(120):                     # 最多等 6 分钟
        time.sleep(3)
        hist = json.loads(urllib.request.urlopen(
            url.rstrip("/") + "/history/" + pid, timeout=30).read().decode("utf-8"))
        if pid in hist:
            for out in hist[pid].get("outputs", {}).values():
                for im in out.get("images", []):
                    q = ("/view?filename=%s&subfolder=%s&type=%s"
                         % (urllib.parse.quote(im["filename"]),
                            urllib.parse.quote(im.get("subfolder", "")),
                            im.get("type", "output")))
                    imgs.append(urllib.request.urlopen(
                        url.rstrip("/") + q, timeout=60).read())
            if imgs:
                break
    return imgs


# ---------------- run ----------------
def cmd_run(out_dir, api, url, workflow, only, n, steps, cfg, dry):
    os.makedirs(out_dir, exist_ok=True)
    js = jobs()
    if only:
        js = [j for j in js if any(j["id"].startswith(o) for o in only)]
    todo = [j for j in js if not os.path.exists(os.path.join(out_dir, j["id"] + ".webp"))]
    print("任务 %d 条，已存在跳过 %d 条，本次生成 %d 条" % (len(js), len(js) - len(todo), len(todo)))
    if dry:
        for j in todo[:5]:
            print("  [dry] %s ← %s" % (j["id"], j["prompt"][:90]))
        return 0

    ok = fail = 0
    for j in todo:
        try:
            if api == "comfyui":
                imgs = gen_comfyui(j, url, workflow, n)
            else:
                imgs = gen_webui(j, url, n, steps, cfg)
            if not imgs:
                raise RuntimeError("接口返回 0 张图")
            if n > 1:                        # 多抽几张，挑一张，其余留作候选
                cand = os.path.join(out_dir, "_candidates")
                os.makedirs(cand, exist_ok=True)
                for ci, raw in enumerate(imgs, 1):
                    p = os.path.join(cand, "%s_c%d.webp" % (j["id"], ci))
                    _save_webp(raw, p)
                print("  %-34s 生成 %d 张候选 → _candidates/" % (j["id"], len(imgs)))
            else:
                dest = os.path.join(out_dir, j["id"] + ".webp")
                p, note = _save_webp(imgs[0], dest)
                print("  %-34s ✓ %s" % (j["id"], note))
            ok += 1
        except urllib.error.URLError as e:
            fail += 1
            print("  %-34s ✗ 连不上 %s" % (j["id"], e.reason))
            print("    检查：模型服务是否已启动？--url 端口对不对？")
            break                            # 连接类错误只报一次，别刷屏
        except Exception as e:
            fail += 1
            print("  %-34s ✗ %s" % (j["id"], e))
    print("\n完成 %d，失败 %d" % (ok, fail))
    if ok:
        print("下一步：python tools/make_story_images.py --check")
    return 0


# ---------------- check ----------------
def cmd_check(out_dir):
    need = jobs()
    miss, bad, extra = [], [], []
    for j in need:
        p = os.path.join(out_dir, j["id"] + ".webp")
        if not os.path.exists(p):
            miss.append(j["id"])
            continue
        try:
            from PIL import Image
            im = Image.open(p)
            if im.size != (W, H):
                bad.append("%s 尺寸 %s（应为 %dx%d）" % (j["id"], im.size, W, H))
        except ImportError:
            pass
    if os.path.isdir(out_dir):
        want = {j["id"] + ".webp" for j in need}
        for f in os.listdir(out_dir):
            if f.endswith((".webp", ".png", ".jpg")) and f not in want:
                extra.append(f)
    print("需要 %d 张 | 已有 %d 张 | 缺 %d 张" % (len(need), len(need) - len(miss), len(miss)))
    if miss:
        print("\n缺图（按故事分组）：")
        for j in need:
            if j["id"] in miss:
                print("  %s" % j["id"])
    if bad:
        print("\n尺寸不对：")
        for b in bad:
            print("  " + b)
    if extra:
        print("\n多余文件（可删）：")
        for e in extra[:20]:
            print("  " + e)
    if not miss and not bad:
        print("\n✓ 图片齐全，格式尺寸都对")
    return 0


# ---------------- sheet ----------------
def cmd_sheet(out_dir):
    js = jobs()
    rows = []
    for j in js:
        p = os.path.join(out_dir, j["id"] + ".webp")
        has = os.path.exists(p)
        block = ('<img src="%(id)s.webp" loading="lazy">' % {"id": j["id"]}) if has \
            else '<div class="ph">未生成</div>'
        rows.append("""<figure class="%(cls)s">
  <div class="im">%(im)s</div>
  <figcaption><b>%(id)s</b><span>%(zh)s</span><code>%(p)s</code></figcaption>
</figure>""" % {
            "cls": "ok" if has else "miss",
            "im": block,
            "id": j["id"], "zh": j["zh"], "p": j["prompt"][:150],
        })
    html = """<!DOCTYPE html><meta charset="utf-8">
<title>故事配图 · 60 格预览</title>
<style>
body{margin:0;padding:24px;background:#faf9f6;color:#1f1f1f;
  font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
h1{font-size:18px;margin:0 0 4px}
p.sub{color:#8a8880;margin:0 0 20px;font-size:13px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
figure{margin:0;background:#fff;border:1px solid rgba(0,0,0,.1);border-radius:10px;overflow:hidden}
.im{aspect-ratio:3/2;background:#f2f1ec;display:flex;align-items:center;justify-content:center}
.im img{width:100%;height:100%;object-fit:cover;display:block}
.ph{color:#a9a79f;font-size:12px}
figcaption{padding:8px 10px 10px;display:flex;flex-direction:column;gap:3px}
figcaption b{font-size:12px}
figcaption span{font-size:11.5px;color:#5F5E5A}
figcaption code{font-size:10.5px;color:#a9a79f;line-height:1.4;
  display:block;max-height:3.2em;overflow:hidden}
figure.miss{border-style:dashed}
</style>
<h1>故事配图 · 60 格</h1>
<p class="sub">共 @@N@@ 格，已生成 @@OK@@ 张。虚线框 = 还没画。每格下方是给模型的原始描述。</p>
<div class="grid">@@GRID@@</div>
"""
    html = (html.replace("@@N@@", str(len(js)))
                .replace("@@OK@@", str(sum(1 for j in js if os.path.exists(os.path.join(out_dir, j["id"] + ".webp")))))
                .replace("@@GRID@@", "".join(rows)))
    dest = os.path.join(out_dir, "_preview.html")
    os.makedirs(out_dir, exist_ok=True)
    open(dest, "w", encoding="utf-8").write(html)
    print("预览页 → %s" % dest)
    return 0


def main():
    ap = argparse.ArgumentParser(description="故事配图流水线")
    ap.add_argument("--export", nargs="?", const="prompts.json", metavar="PATH",
                    help="导出 prompts.json（默认写到仓库根）")
    ap.add_argument("--run", action="store_true", help="调本地接口批量生成")
    ap.add_argument("--check", action="store_true", help="核对缺图")
    ap.add_argument("--sheet", action="store_true", help="生成预览页")
    ap.add_argument("--api", default="webui", choices=["webui", "comfyui"])
    ap.add_argument("--url", default="", help="默认 webui=7860 / comfyui=8188")
    ap.add_argument("--workflow", default="workflow_api.json", help="ComfyUI 的 API 格式工作流")
    ap.add_argument("--out", default=DEFAULT_OUT, help="图片输出目录")
    ap.add_argument("--only", nargs="*", default=[], help="只跑指定 id 前缀，如 a-small-accident")
    ap.add_argument("--n", type=int, default=1, help="每条抽几张（>1 存到 _candidates 待挑）")
    ap.add_argument("--steps", type=int, default=24)
    ap.add_argument("--cfg", type=float, default=6.5)
    ap.add_argument("--dry", action="store_true", help="只列任务不生成")
    a = ap.parse_args()

    out_dir = a.out if os.path.isabs(a.out) else os.path.join(ROOT, a.out)
    url = a.url or ("http://127.0.0.1:8188" if a.api == "comfyui" else "http://127.0.0.1:7860")

    if a.export:
        p = a.export if os.path.isabs(a.export) else os.path.join(ROOT, a.export)
        return cmd_export(out_dir, p)
    if a.run:
        return cmd_run(out_dir, a.api, url, a.workflow, a.only, a.n, a.steps, a.cfg, a.dry)
    if a.check:
        return cmd_check(out_dir)
    if a.sheet:
        return cmd_sheet(out_dir)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
