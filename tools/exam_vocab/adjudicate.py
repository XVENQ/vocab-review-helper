#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""释义裁决：候选义项池 + 规则打分 + 分批送模型

核心约定（"真题语境优先"的可判定定义）：
  对词 w，义项 c 的证据支持度 S(c) ∈ [0,1]。
  **当且仅当** ∃c* 使 S(c*) ≥ 0.30 且 S(c*) − S(次高) ≥ 0.25，才允许"删除其余义项"；
  否则内容一字不改，只允许把高支持度义项提前（order-only）；
  df < 2 且不在词库 314 的词，彻底不动。

三个信号：
  S1 词性一致性（0.20）：不装 POS tagger，用形态 + 上下文统计
  S2 中文概念簇线索共现（0.35）：cues.json
  S3 英释 token-IDF 匹配（0.45）：只有有道词表带 tranOther 时才有

用法：
  python tools/exam_vocab/adjudicate.py            # 出候选池 + 规则结论 + 复核队列
  python tools/exam_vocab/adjudicate.py --stats    # 只看统计
"""
import argparse
import csv
import io
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CORPUS = os.path.join(ROOT, "docs", "exam_vocab", "corpus")
FREQ = os.path.join(ROOT, "docs", "exam_vocab", "freq")
CALIB = os.path.join(ROOT, "docs", "exam_vocab", "calib")
KB = os.path.join(os.path.dirname(ROOT), "专升本知识库")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import trim_exam_meaning as T                      # noqa: E402  复用归一化与拆组

CET4 = os.path.join(KB, "99-附录", "数据源", "CET4luan_1.json")
SYLLABUS = os.path.join(KB, "01-公共英语", "02-核心词汇表.md")

TOKEN_RE = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

W_S1, W_S2, W_S3 = 0.20, 0.35, 0.45
TH_TOPN, TH_MARGIN, TH_MIN = 0.30, 0.25, 0.15


# ---------------------------------------------------------------- 语料与索引

def load_pages():
    pages = [json.loads(l) for l in io.open(os.path.join(CORPUS, "pages.jsonl"), encoding="utf-8") if l.strip()]
    sents = []                                    # [{pid, page, set, q, text}]
    for p in pages:
        for s in SENT_SPLIT.split(p["text_en"].replace("\n", " ")):
            s = s.strip()
            if 15 <= len(s) <= 320:
                sents.append({"page": p["printed"], "set": p["set"], "q": p["quality"], "text": s})
    return pages, sents


def build_index(sents):
    idx = {}
    for i, s in enumerate(sents):
        for t in set(TOKEN_RE.findall(s["text"])):
            idx.setdefault(t.lower(), []).append(i)
    return idx


def evidence_for(word, idx, sents, limit=8, per_set=2):
    """同一页最多 2 句、每套最多 2 句，quality=ok 优先。"""
    hits = idx.get(word, [])
    out, per_page, per_st = [], {}, {}
    for i in sorted(hits, key=lambda i: (sents[i]["q"] != "ok", sents[i]["page"])):
        s = sents[i]
        if per_page.get(s["page"], 0) >= 2:
            continue
        if per_st.get(s["set"], 0) >= per_set:
            continue
        per_page[s["page"]] = per_page.get(s["page"], 0) + 1
        per_st[s["set"]] = per_st.get(s["set"], 0) + 1
        out.append(s)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 候选池

def load_cet4():
    out = {}
    for ln in io.open(CET4, encoding="utf-8"):
        ln = ln.strip()
        if not ln:
            continue
        o = json.loads(ln)
        w = o["headWord"].strip().lower()
        c = o.get("content", {}).get("word", {}).get("content", {})
        trans = []
        for t in c.get("trans") or []:
            pos = (t.get("pos") or "").strip().lower() or None
            cn = (t.get("tranCn") or "").strip()
            en = (t.get("tranOther") or "").strip()
            if cn:
                trans.append({"pos": pos, "cn": cn, "en": en})
        out[w] = trans
    return out


def load_syllabus():
    """从考纲核心词汇表里抓「词 | 僻义」的表格行，只要单词类条目。"""
    p = SYLLABUS
    out = {}
    if not os.path.exists(p):
        return out
    for line in io.open(p, encoding="utf-8"):
        line = line.strip()
        if not line.startswith("|") or line.startswith("|--") or "---" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        w = cells[0].replace("*", "").strip().lower()
        if not re.fullmatch(r"[a-z][a-z\- ]{1,20}", w):
            continue
        if w in ("短语", "含义", "词", "单词"):
            continue
        out[w] = " ".join(cells[1:]).strip()
    return out


def candidates(word, cur):
    """返回 [{pos, senses:[...], src}]，按 (pos, 首义项) 去重。"""
    out = []
    for g in T.parse_groups(T.normalize_line(cur)):
        if g["senses"]:
            out.append({"pos": g["pos"], "senses": g["senses"][:3], "src": "builtin"})
    for t in CET4_MAP.get(word, []):
        out.append({"pos": t["pos"], "senses": [t["cn"]], "src": "cet4", "en": t["en"]})
    return out


# ---------------------------------------------------------------- 词性推断

CTX_V = r"\b(?:to|will|would|can|could|should|must|may|might|shall|do|does|did|not|been|be)\s+%s\b"
CTX_N = r"\b(?:the|a|an|this|that|these|those|my|your|his|her|its|our|their|some|any|no|every|many|more)\s+%s\b"
CTX_ADJ = r"\b(?:more|most|very|too|so|quite|rather|extremely|really)\s+%s\b"
CTX_ADV = r"\b%s\s+(?:of|in|for|to|that|which|who|with|and)\b"


def pos_guess(word, ev):
    txt = " ".join(s["text"] for s in ev).lower()
    w = re.escape(word)
    d = {
        "v": len(re.findall(CTX_V % w, txt)) + len(re.findall(r"\b%s(?:s|ed|ing)\b" % w, txt)),
        "n": len(re.findall(CTX_N % w, txt)) + len(re.findall(CTX_ADV % w, txt)),
        "adj": len(re.findall(CTX_ADJ % w, txt)),
    }
    tot = sum(d.values())
    if not tot:
        return None, 0.0
    k = max(d, key=d.get)
    return k, d[k] / tot


# ---------------------------------------------------------------- 打分

def s1_score(pos, top_pos, conf):
    if not pos or not top_pos:
        return None
    if pos == top_pos:
        return conf
    if {pos, top_pos} <= {"v", "vt", "vi"}:
        return conf * 0.9
    if {pos, top_pos} <= {"n", "adj"}:
        return conf * 0.3
    return 0.0


def s2_score(sense, ev_text_tokens, exclude=""):
    zh_hit = []
    for cl in CLUSTERS:
        if any(z and z in sense for z in cl["zh"]):
            zh_hit.append(cl)
    if not zh_hit:
        return None
    best = 0.0
    for cl in zh_hit:
        cues = [c for c in cl["en"] if " " not in c]
        if not cues:
            continue
        hit = len({c for c in cues if c in ev_text_tokens and c != exclude})
        best = max(best, min(1.0, hit / min(len(cues), 8)))
    return best


def s3_score(en_def, ev_text_tokens, idf):
    toks = [t.lower() for t in TOKEN_RE.findall(en_def or "") if t.lower() not in STOP]
    toks = [t for t in toks if t not in ("to", "of", "the", "a", "an", "in", "on", "that", "which")]
    if not toks:
        return None
    num = sum(idf.get(t, 1.0) for t in set(toks) if t in ev_text_tokens)
    den = sum(idf.get(t, 1.0) for t in set(toks))
    return num / den if den else None


def combine(s1, s2, s3, avail=(True, True, True)):
    """avail = 该词层面"哪些信号至少对某一个候选是有值的"。
    ⚠ 不能用"每个候选各自归一化"——那会让只有一个信号的冷僻义项拿到满分，
       反而压过有真实语境证据的常用义项（country→乡村 就是这么错的）。"""
    w = (W_S1 if avail[0] else 0) + (W_S2 if avail[1] else 0) + (W_S3 if avail[2] else 0)
    if not w:
        return 0.0
    return ((W_S1 * (s1 or 0) if avail[0] else 0)
            + (W_S2 * (s2 or 0) if avail[1] else 0)
            + (W_S3 * (s3 or 0) if avail[2] else 0)) / w


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    global CLUSTERS, CET4_MAP, STOP
    CLUSTERS = json.loads(io.open(os.path.join(HERE, "cues.json"), encoding="utf-8").read())["clusters"]
    CET4_MAP = load_cet4()
    SYL = load_syllabus()
    STOP = set(w.lower() for w in io.open(os.path.join(HERE, "stoplist.txt"), encoding="utf-8")
               if w.strip() and not w.startswith("#"))

    pages, sents = load_pages()
    idx = build_index(sents)
    print("语料 %d 页 / %d 句" % (len(pages), len(sents)))

    # idf
    df = {}
    for s in sents:
        for t in set(x.lower() for x in TOKEN_RE.findall(s["text"])):
            df[t] = df.get(t, 0) + 1
    N = len(sents)
    idf = {t: math.log((N + 1) / (c + 0.5)) for t, c in df.items()}

    rows = list(csv.DictReader(io.open(os.path.join(FREQ, "vocab_freq.csv"), encoding="utf-8-sig")))
    print("词频表 %d 条" % len(rows))

    results = []
    for r in rows:
        w = r["word"]
        df_ = int(r["df"])
        tf_ = int(r["tf"])
        in314 = r["in_lib314"] == "1"
        if not (df_ >= 2 or in314):
            continue

        ev = evidence_for(w, idx, sents)
        if not ev:
            results.append({"w": w, "action": "no_change", "why": "无证据句", "conf": "high",
                            "df": df_, "tf": tf_, "in314": in314, "scores": {}, "ev": [],
                            "cur": r["cur_meaning"], "top": "", "top_s": 0, "margin": 0})
            continue

        ev_tokens = set()
        for s in ev:
            ev_tokens |= {t.lower() for t in TOKEN_RE.findall(s["text"])}

        cands = candidates(w, r["cur_meaning"])
        # 合并 cet4 的 en 字段到对应义项
        flat = []
        for c in cands:
            for i, sn in enumerate(c["senses"]):
                flat.append({"pos": c["pos"], "sense": sn, "src": c["src"],
                             "en": c.get("en", "") if i == 0 else ""})
        if not flat:
            continue

        top_pos, conf = pos_guess(w, ev)
        # 第一遍：算出每个候选的三个信号（保留 None 以区分「没信号」与「信号为 0」）
        sig = []
        for f in flat:
            sig.append((s1_score(f["pos"], top_pos, conf),
                        s2_score(f["sense"], ev_tokens, exclude=w),
                        s3_score(f["en"], ev_tokens, idf) if f["en"] else None))
        avail = tuple(any(sig[i][k] is not None for i in range(len(sig))) for k in range(3))
        for f, (a, b, c) in zip(flat, sig):
            f["s1"], f["s2"], f["s3"] = a, b, c
            f["s"] = combine(a, b, c, avail)

        ranked = sorted(flat, key=lambda x: -x["s"])
        top = ranked[0]
        second = ranked[1]["s"] if len(ranked) > 1 else 0.0

        rec = {"w": w, "df": df_, "tf": tf_, "in314": in314,
               "scores": {(f["pos"] or "") + "|" + f["sense"]: round(f["s"], 3) for f in flat},
               "top": (top["pos"] or "") + "|" + top["sense"], "top_s": round(top["s"], 3),
               "margin": round(top["s"] - second, 3),
               "ev": ["p%d: %s" % (s["page"], s["text"][:120]) for s in ev],
               "cur": r["cur_meaning"]}

        if len(flat) == 1:
            rec.update(action="no_change", why="单义项", conf="high")
        elif top["s"] < TH_MIN:
            rec.update(action="no_change", why="证据不足", conf="low")
        elif (top["s"] >= TH_TOPN and (top["s"] - second) >= TH_MARGIN
              and max(top.get("s2") or 0, top.get("s3") or 0) >= 0.10):
            # 必须有语境语义证据（S2/S3），只靠词性一致性不足以删义项
            rec.update(action="trim", why="唯一指向", conf="high" if top["s"] >= 0.5 else "mid")
        elif (top["s"] >= TH_TOPN and (top["s"] - second) >= TH_MARGIN):
            rec.update(action="order_only", why="仅词性一致，不删", conf="mid")
        elif top["s"] >= TH_MIN:
            rec.update(action="order_only", why="仅重排", conf="mid")
        else:
            rec.update(action="no_change", why="证据不足", conf="low")
        results.append(rec)

    # ---- 统计
    from collections import Counter
    c = Counter(x["action"] for x in results)
    print("候选 %d 条：%s" % (len(results), dict(c)))
    print("其中 词库314 %d 条" % sum(1 for x in results if x["in314"]))

    # ---- 复核优先级
    def rp(x):
        dis = 1.0 - min(1.0, x.get("margin", 0) / 0.5) if x["action"] != "no_change" else 0.3
        v = 0.0
        v += 3.0 if x["in314"] else 0.0
        v += 2.0 * (x["df"] / 5.0)
        v += 2.0 * dis
        v += 1.5 if x.get("conf") == "low" else 0.0
        v += 1.0 if x["action"] == "trim" else 0.0
        v += 0.5 if x["w"] in SYL else 0.0
        return round(v, 2)

    for x in results:
        x["rp"] = rp(x)
        x["syllabus"] = 1 if x["w"] in SYL else 0
    results.sort(key=lambda x: (-x["rp"], -x["df"], x["w"]))

    # ---- 写 rule_result.jsonl
    with io.open(os.path.join(CALIB, "rule_result.jsonl"), "w", encoding="utf-8") as f:
        for x in results:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    # ---- 写 candidates（送模型的批次输入）
    todo = [x for x in results if x["action"] in ("trim", "order_only")]
    with io.open(os.path.join(CALIB, "model_input.jsonl"), "w", encoding="utf-8") as f:
        for x in todo:
            f.write(json.dumps({"w": x["w"], "cur": x["cur"], "scores": x["scores"],
                                "ev": x["ev"], "df": x["df"], "in314": x["in314"]},
                               ensure_ascii=False) + "\n")

    # ---- 复核队列（只出必看的：314 全进 + 其余 rp≥6）
    mst = [x for x in results if x["in314"] or x["rp"] >= 6.0]
    with io.open(os.path.join(CALIB, "review_queue.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rp", "word", "df", "tf", "in314", "action", "conf", "top", "top_s", "margin",
                    "cur_meaning", "scores", "evidence", "verdict"])
        for x in mst:
            w.writerow([x["rp"], x["w"], x["df"], x["tf"], x["in314"], x["action"], x["conf"],
                        x.get("top", ""), x.get("top_s", ""), x.get("margin", ""),
                        x["cur"], json.dumps(x["scores"], ensure_ascii=False),
                        " / ".join(x["ev"][:3]), "□收"])
    print("必看清单 %d 条 → calib/review_queue.csv" % len(mst))
    print("送模型 %d 条 → calib/model_input.jsonl" % len(todo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
