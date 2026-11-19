#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""汇总报表 + 两档缺口表

缺口 A：内置词典里查不到（多为专名/新词，价值低，只做记录）
缺口 B：词典里有、但词库 314 里没有、且 df≥3 —— **这才是"该背还没背"的名单**

B 档直接输出成背词助手可导入的 TSV：
  第 1 列 单词、第 2 列 释义（必须填，缺口词在词典里可能查不到）、第 3 列 批次（Day01…）
parseImport 只认 \t 分隔，第 3 列形如 Day01 才会被当成批次。

用法：python tools/exam_vocab/report.py
"""
import csv
import io
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXAM = os.path.join(ROOT, "docs", "exam_vocab")
FREQ = os.path.join(EXAM, "freq")
CORPUS = os.path.join(EXAM, "corpus")
CALIB = os.path.join(EXAM, "calib")
GAP = os.path.join(EXAM, "gap")

HTML_MAIN = os.path.join(os.path.dirname(ROOT), "outputs", "单词复习", "背词助手.html")
DATA_JSON = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"


def load_builtin():
    raw = io.open(HTML_MAIN, "rb").read().decode("utf-8")
    line = next(l for l in raw.split("\n") if l.startswith("const BUILTIN = "))
    return json.loads(line[len("const BUILTIN = "):-2])


def main():
    os.makedirs(GAP, exist_ok=True)
    B = load_builtin()
    d = json.loads(io.open(DATA_JSON, encoding="utf-8").read())
    lib = {w["word"].strip().lower(): w for w in d["words"]}

    rows = list(csv.DictReader(io.open(os.path.join(FREQ, "vocab_freq.csv"), encoding="utf-8-sig")))
    oov = list(csv.DictReader(io.open(os.path.join(CORPUS, "oov_log.csv"), encoding="utf-8-sig")))
    pages = [json.loads(l) for l in io.open(os.path.join(CORPUS, "pages.jsonl"), encoding="utf-8") if l.strip()]
    roles = {}
    rp = os.path.join(CALIB, "rule_result.jsonl")
    if os.path.exists(rp):
        for l in io.open(rp, encoding="utf-8"):
            if l.strip():
                o = json.loads(l)
                roles[o["w"]] = o

    # ---- 缺口 A
    real = [o for o in oov if o["class"] == "OOV_REAL"]
    with io.open(os.path.join(GAP, "gap_A_词典里没有的.tsv"), "w", encoding="utf-8") as f:
        f.write("word\tsets\tcount\tnote\n")
        for o in real:
            f.write("%s\t%s\t%s\t待补\n" % (o["surface"], o["df"], o["count"]))

    # ---- 缺口 B：全量 + 重点两档
    # 全量里大量是 china/make/people 这种基础词，直接背没意义；
    # 因此再筛一层「落在有道 CET4 核心词 或 考纲核心词汇表」，才是真正值得背的。
    import sys as _s
    _s.path.insert(0, HERE)
    import adjudicate as A
    cet4w, sylw = set(A.load_cet4()), set(A.load_syllabus())

    gb = [r for r in rows if r["in_builtin"] == "1" and r["in_lib314"] == "0"
          and int(r["df"]) >= 3 and r.get("rubric", "0") == "0"]
    gb.sort(key=lambda r: (-float(r["score"]), -int(r["df"]), r["word"]))
    # 「值得背」口径：在有道 CET4 核心词表里，且不是 say/work 这种两三个字母的日常词。
    # 放宽到「考纲词表」会把 say/work/well 也捞进来，反而没法用。
    key = [r for r in gb if r["word"] in cet4w and len(r["word"]) >= 6]

    with io.open(os.path.join(GAP, "gap_B_重点.tsv"), "w", encoding="utf-8") as f:
        for i, r in enumerate(key):
            f.write("%s\t%s\tDay%02d\n" % (r["word"], r["cur_meaning"] or B.get(r["word"], ""), i // 30 + 1))
    with io.open(os.path.join(GAP, "gap_B_全量.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "word", "tf", "df", "score", "tier", "core", "meaning", "pages"])
        for i, r in enumerate(gb, 1):
            w.writerow([i, r["word"], r["tf"], r["df"], r["score"], r["tier"],
                        "核心" if (r["word"] in cet4w or r["word"] in sylw) else "",
                        r["cur_meaning"] or B.get(r["word"], ""), r["evidence_pages"]])

    # ---- 分层统计
    tier = Counter(r["tier"] for r in rows)
    acts = Counter(v.get("action") for v in roles.values())
    in314 = sum(1 for r in rows if r["in_lib314"] == "1")
    changed = [r for r in rows if r["changed"] == "1"]

    total_words = sum(p["nwords"] for p in pages)
    low = [p["printed"] for p in pages if p["quality"] == "low"]

    L = []
    L.append("# 河南专升本真题 · 词频与释义校准报告\n")
    L.append("> 语料：%d 页 / %d 英文词，5 套卷（2025 真题、2024 真题、2023 真题、模拟一、模拟二）\n"
             % (len(pages), total_words))
    L.append("## 一、语料\n")
    L.append("| 套卷 | 页 | 词数 |\n|---|---|---|")
    by = {}
    for p in pages:
        by.setdefault(p["set"], [0, 0])
        by[p["set"]][0] += 1
        by[p["set"]][1] += p["nwords"]
    for s in ("HN2025", "HN2024", "HN2023", "MOCK1", "MOCK2"):
        if s in by:
            L.append("| %s | %d | %d |" % (s, by[s][0], by[s][1]))
    L.append("| **合计** | **%d** | **%d** |\n" % (len(pages), total_words))
    if low:
        L.append("低质量页（`[?]` 偏多）：%s\n" % ", ".join("p%d" % x for x in low))

    L.append("## 二、词频\n")
    L.append("| tier | 条件 | 词数 |\n|---|---|---|")
    for t, cond in [("T0", "df=5 且 tf≥3"), ("T1", "df≥4"), ("T2", "df≥3"),
                    ("T3", "df≤2 且 tf≥5"), ("T4", "其余")]:
        L.append("| %s | %s | %d |" % (t, cond, tier.get(t, 0)))
    L.append("| **合计** | | **%d** |\n" % len(rows))
    L.append("词库 314 里出现在真题的：**%d 个**（%.0f%%）\n" % (in314, in314 * 100.0 / max(1, len(lib))))

    L.append("## 三、释义裁决\n")
    if acts:
        L.append("| 动作 | 条数 | 含义 |\n|---|---|---|")
        L.append("| no_change | %d | 证据不足或单义项，内容不动 |" % acts.get("no_change", 0))
        L.append("| order_only | %d | 只把常考义项提前 |" % acts.get("order_only", 0))
        L.append("| trim | %d | 有唯一指向，删掉冷僻义项 |\n" % acts.get("trim", 0))
    else:
        L.append("（尚未运行 adjudicate.py）\n")

    L.append("## 四、缺口\n")
    L.append("| 档 | 含义 | 条数 | 文件 |\n|---|---|---|---|")
    L.append("| A | 内置词典里查不到（多为专名/新词） | %d | `gap/gap_A_词典里没有的.tsv` |" % len(real))
    L.append("| B | 词典有、你还没背、df≥3（全量） | %d | `gap/gap_B_全量.csv` |" % len(gb))
    L.append("| **B重点** | 上面这批里，落在 CET4 核心词表且长度≥6 的 | **%d** | `gap/gap_B_重点.tsv`（可直接导入） |\n" % len(key))
    L.append("> 全量表里多数是 china / make / people 这类基础词——它们出现在真题里很正常，"
             "但对你没有背诵价值。重点表才是真正值得进词库的。\n")
    if len(real) > 300:
        L.append("> ⚠ 缺口 A 超过 300 条，通常说明转录/清洗有问题，先别扩词表。\n")

    # ---- 词纲覆盖（syllabus 层）
    SY = os.path.join(EXAM, "syllabus")
    cmp_p = os.path.join(SY, "compare.csv")
    if os.path.exists(cmp_p):
        cr = list(csv.DictReader(io.open(cmp_p, encoding="utf-8-sig")))
        typ = Counter(r["type"] for r in cr)
        L.append("## 五、词纲覆盖（3716 词纲 → 内置词典）\n")
        L.append("| 项 | 条数 |\n|---|---|")
        L.append("| 词纲可解析 | %d |" % len(cr))
        L.append("| 与词典一致（未动） | %d |" % typ.get("一致", 0))
        L.append("| **改写** | **%d** |" % typ.get("改", 0))
        L.append("| **新增进词典** | **%d** |" % typ.get("新增", 0))
        L.append("")
        L.append("> 口径：词纲释义为主、每词性保留 1–2 义；词纲被原书 `...` 截断、导致整组词性"
                 "丢失时，从内置词典补回。明细见 `syllabus/compare.csv`，"
                 "需要人眼确认的见 `syllabus/need_review.tsv`。\n")

    L.append("## 六、健康指标\n")
    L.append("| 指标 | 值 | 参考 |\n|---|---|---|")
    L.append("| 唯一词条 | %d | 3000–4500 正常 |" % len(rows))
    L.append("| OOV 占比 | %.1f%% | <35%% 正常 |"
             % (len(oov) * 100.0 / max(1, len(oov) + len(rows))))
    L.append("| 最高 per10k | %.1f | ≥40 说明语料够密 |"
             % max([float(r["per10k"]) for r in rows], default=0))
    L.append("| low 页 | %d / %d | 越少越好 |\n" % (len(low), len(pages)))

    io.open(os.path.join(EXAM, "report.md"), "w", encoding="utf-8").write("\n".join(L))

    # ---- 词库校准表（314 词全量，标出真题里出现过的 102 个）
    hand_p = os.path.join(CALIB, "hand_decisions.json")
    hand = json.loads(io.open(hand_p, encoding="utf-8").read())["decisions"] if os.path.exists(hand_p) else {}
    C = ["# 词库 314 词 · 真题释义校准\n",
         "> 判定依据：真题原句 + 各义项在语境中的支撑度。**只有 20 条被改动**，其余保持原样（真题用法与现释义一致，或该词未在真题出现）。\n",
         "| 单词 | 套数 | 原释义 | 现释义 | 裁决 | 依据 |",
         "|---|---|---|---|---|---|"]
    for w in d["words"]:
        k = w["word"].strip().lower()
        r = roles.get(k)
        df = int(r["df"]) if r else 0
        cur = w.get("meaning", "")
        if k in hand:
            h = hand[k]
            C.append("| **%s** | %d | %s | %s | ✅ 改 | %s |" % (k, df, cur.replace("|", "\\|"),
                                                                h["meaning"].replace("|", "\\|"), h.get("why", "")))
        elif not r:
            C.append("| %s | — | %s | — | 真题未出现 | — |" % (k, cur.replace("|", "\\|")))
        else:
            ev = (r.get("ev") or [""])[0]
            ev = ev.split(": ", 1)[1][:46] if ": " in ev else ev[:46]
            C.append("| %s | %d | %s | （不变） | ✔ 保持 | %s |"
                     % (k, df, cur.replace("|", "\\|"), ev.replace("|", "\\|")))
    C.append("")
    io.open(os.path.join(CALIB, "word314_calibration.md"), "w", encoding="utf-8").write("\n".join(C))
    print("词库校准表：%d 条改动，%d 词未在真题出现"
          % (len(hand), sum(1 for w in d["words"] if w["word"].strip().lower() not in roles)))

    print("语料 %d 页 / %d 词；词条 %d；词库覆盖 %d" % (len(pages), total_words, len(rows), in314))
    print("缺口 A（词典没有）%d 条；缺口 B（该背还没背）%d 条" % (len(real), len(gb)))
    print("已写 report.md / gap_A / gap_B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
