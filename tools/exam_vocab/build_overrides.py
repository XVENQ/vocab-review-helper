#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把裁决结果打包成 exam_overrides.json

三条护栏（防"草稿被当确认值"，上一轮踩过）：
  1. 生成只写 exam_overrides.new.json；--promote 才 rename 成 .json
  2. _meta.corpus_sha1 与当前 pages.jsonl 不符 → loader 整体失效
  3. status 三态 auto / approved / rejected，rejected 是粘性的

用法：
  python tools/exam_vocab/build_overrides.py            # 生成 .new.json + 统计
  python tools/exam_vocab/build_overrides.py --promote  # 改名为正式文件
  python tools/exam_vocab/build_overrides.py --stats    # 只看当前分布
"""
import argparse
import glob
import hashlib
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXAM = os.path.join(ROOT, "docs", "exam_vocab")
CALIB = os.path.join(EXAM, "calib")
CORPUS = os.path.join(EXAM, "corpus")
NEW = os.path.join(EXAM, "exam_overrides.new.json")
LIVE = os.path.join(EXAM, "exam_overrides.json")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import trim_exam_meaning as T                      # noqa: E402


def corpus_sha1():
    p = os.path.join(CORPUS, "pages.jsonl")
    if not os.path.exists(p):
        return ""
    return hashlib.sha1(io.open(p, "rb").read()).hexdigest()[:16]


def rules_sha1():
    p = os.path.join(ROOT, "tools", "trim_exam_meaning.py")
    src = io.open(p, encoding="utf-8").read()
    m = re.search(r"MAX_SENSES_MAJOR.*?POS_RANK = \{[^}]*\}", src, re.S)
    return hashlib.sha1((m.group(0) if m else src[:2000]).encode("utf-8")).hexdigest()[:12]


def load_jsonl(p):
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in io.open(p, encoding="utf-8") if l.strip()]


def render_from_scores(word, cur, scores, action):
    """按分数重排/裁剪义项，返回新释义（已归一化）。"""
    groups = T.parse_groups(T.normalize_line(cur))
    if not groups:
        return None

    def sc(pos, sense):
        return scores.get((pos or "") + "|" + sense, 0.0)

    scored = []
    for gi, g in enumerate(groups):
        senses = [(s, sc(g["pos"], s)) for s in g["senses"]]
        best = max([v for _, v in senses], default=0.0)
        scored.append({"pos": g["pos"], "senses": senses, "best": best, "gi": gi})

    scored.sort(key=lambda x: (-x["best"], x["gi"]))
    out = []
    if action == "order_only":
        # 只重排，绝不增删：所有词性组、所有义项原样保留
        for g in scored:
            out.append({"pos": g["pos"], "senses": [s for s, _ in g["senses"]]})
    else:
        for i, g in enumerate(scored):
            keep = [(s, v) for s, v in g["senses"] if v >= 0.15]
            if i == 0:
                keep = sorted(g["senses"], key=lambda x: -x[1])[:2]      # 首组最多 2 义
            if not keep:
                continue
            out.append({"pos": g["pos"], "senses": [s for s, _ in keep]})

    if not out:
        return None
    txt = T.normalize_line(T.render(out))
    return T.ensure_pos(word, txt)


HAND314 = {"corresponding", "judgement", "found", "appearance", "care", "prevent",
           "senior", "approach", "complete", "exact", "wide", "fortune", "content",
           "threat", "spread", "fight", "item", "junior", "advantage", "ease"}


def load_hand():
    p = os.path.join(CALIB, "hand_decisions.json")
    if not os.path.exists(p):
        return {}
    return json.loads(io.open(p, encoding="utf-8").read()).get("decisions", {})


def build(only_hand=True):
    rules = load_jsonl(os.path.join(CALIB, "rule_result.jsonl"))
    if not rules:
        print("缺 calib/rule_result.jsonl，先跑 adjudicate.py")
        return 1

    model = {}
    for p in sorted(glob.glob(os.path.join(CALIB, "model_out", "*.jsonl"))):
        for r in load_jsonl(p):
            w = (r.get("w") or "").strip().lower()
            if w:
                model[w] = r

    # 已有的 approved / rejected 要粘住
    prev = {}
    if os.path.exists(NEW):
        try:
            prev = json.loads(io.open(NEW, encoding="utf-8").read()).get("overrides", {})
        except Exception:
            prev = {}
    if os.path.exists(LIVE):
        try:
            for k, v in json.loads(io.open(LIVE, encoding="utf-8").read()).get("overrides", {}).items():
                prev[k] = v
        except Exception:
            pass

    hand = load_hand()
    byw = {r["w"]: r for r in rules}
    overrides, stat = {}, {"no_change": 0, "skip_same": 0, "skip_lowdf": 0,
                           "order_only": 0, "trim": 0, "rejected": 0, "approved": 0}

    # ① 人工裁决优先落盘（status=approved）
    for w, h in hand.items():
        m = T.normalize_line(h["meaning"])
        assert T.normalize_line(m) == m, "人工释义不幂等：%s" % w
        assert T.ensure_pos(w, m) == m, "人工释义缺词性：%s" % w
        r = byw.get(w, {})
        overrides[w] = {
            "meaning": m,
            "df": int(r.get("df", 5)), "tf": int(r.get("tf", 0)),
            "min_df": 1 if (r.get("in314") or w in HAND314) else 2,
            "status": "approved", "action": "hand", "conf": "high",
            "in314": 1 if (r.get("in314") or w in HAND314) else 0,
            "evidence": ["p%s" % x for x in h.get("pages", [])][:8],
            "why": h.get("why", "")[:40],
        }
        stat["approved"] += 1

    if only_hand:
        # 自动结论一律不入库：POS 推断噪音太大，实测把 best 判成名词「最好的人」、
        # 把 like 的介词「像」删掉。规则层只作为候选提示留在 rule_result.jsonl 里供查。
        print("只收录人工裁决（自动结论见 calib/rule_result.jsonl，不入库）")
        rules = []

    for r in rules:
        w = r["w"]
        if w in overrides:                     # 已被人工裁决覆盖
            continue
        df = int(r["df"])
        min_df = 1 if r["in314"] else 2
        if df < min_df:
            stat["skip_lowdf"] += 1
            continue

        old = prev.get(w, {})
        if old.get("status") == "rejected":
            overrides[w] = old
            stat["rejected"] += 1
            continue

        m = model.get(w)
        if m and m.get("order"):
            # 模型只做选择与排序，措辞取自候选池
            keep = [s for s in m["order"] if s]
            pos_map = {}
            for k, v in (r.get("scores") or {}).items():
                pos, _, sense = k.partition("|")
                pos_map[sense] = pos
            groups = []
            for s in keep:
                pos = pos_map.get(s)
                if groups and groups[-1]["pos"] == pos:
                    groups[-1]["senses"].append(s)
                else:
                    groups.append({"pos": pos, "senses": [s]})
            newm = T.ensure_pos(w, T.normalize_line(T.render(groups)))
            action = "trim" if len(keep) < len(r.get("scores") or {}) else "order_only"
            conf = m.get("conf", "mid")
            why = (m.get("why") or "")[:40]
        elif r["action"] in ("trim", "order_only"):
            newm = render_from_scores(w, r["cur"], r.get("scores") or {}, r["action"])
            action = r["action"]
            conf = r.get("conf", "mid")
            why = r.get("why", "")[:40]
        else:
            stat["no_change"] += 1
            continue

        if not newm or newm == T.normalize_line(r["cur"]):
            stat["skip_same"] += 1
            continue

        status = old.get("status", "auto")
        if status == "approved":
            stat["approved"] += 1
        else:
            stat["order_only" if action == "order_only" else "trim"] += 1
        overrides[w] = {
            "meaning": newm,
            "df": df, "tf": int(r["tf"]), "min_df": min_df,
            "status": status, "action": action, "conf": conf,
            "in314": 1 if r["in314"] else 0,
            "evidence": [e.split(":")[0] for e in (r.get("ev") or [])][:8],
            "why": why,
        }

    payload = {
        "_meta": {
            "version": "2026-11-05.1",
            "corpus_sha1": corpus_sha1(),
            "rules_sha1": rules_sha1(),
            "default_min_df": 2,
            "n_entries": len(overrides),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "generator": "tools/exam_vocab/build_overrides.py",
        },
        "overrides": dict(sorted(overrides.items())),
    }
    io.open(NEW, "w", encoding="utf-8").write(json.dumps(payload, ensure_ascii=False, indent=1))

    print("生成 exam_overrides.new.json：%d 条" % len(overrides))
    print("分类：" + "  ".join("%s=%d" % (k, v) for k, v in stat.items() if v))
    print("corpus_sha1=%s  rules_sha1=%s" % (payload["_meta"]["corpus_sha1"], payload["_meta"]["rules_sha1"]))
    n314 = sum(1 for v in overrides.values() if v["in314"])
    print("其中词库 314 覆盖 %d 条" % n314)
    return 0


def promote():
    if not os.path.exists(NEW):
        print("没有 exam_overrides.new.json")
        return 1
    cfg = json.loads(io.open(NEW, encoding="utf-8").read())
    if cfg["_meta"]["corpus_sha1"] != corpus_sha1():
        print("拒绝提升：语料已变化（sha1 不符），请重新生成")
        return 1
    if os.path.exists(LIVE):
        os.replace(LIVE, LIVE + ".bak")
    os.replace(NEW, LIVE)
    print("已提升 → %s（%d 条）" % (LIVE, cfg["_meta"]["n_entries"]))
    return 0


def stats():
    p = LIVE if os.path.exists(LIVE) else NEW
    if not os.path.exists(p):
        print("还没有 override 文件")
        return 1
    cfg = json.loads(io.open(p, encoding="utf-8").read())
    ov = cfg["overrides"]
    from collections import Counter
    print("文件 %s  %d 条  sha1=%s" % (os.path.basename(p), len(ov), cfg["_meta"]["corpus_sha1"]))
    print("status:", dict(Counter(v["status"] for v in ov.values())))
    print("action:", dict(Counter(v["action"] for v in ov.values())))
    print("conf:  ", dict(Counter(v["conf"] for v in ov.values())))
    print("词库314:", sum(1 for v in ov.values() if v.get("in314")))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--with-auto", action="store_true", help="把机器结论也收进来（默认不收）")
    a = ap.parse_args()
    if a.promote:
        return promote()
    if a.stats:
        return stats()
    return build(only_hand=not a.with_auto)


if __name__ == "__main__":
    sys.exit(main())
