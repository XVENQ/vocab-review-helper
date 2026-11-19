#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真题语料清洗、分词、词频

输入：docs/exam_vocab/corpus/pages.jsonl（由 parse_pages.py 生成）
输出：
  freq/vocab_freq.csv        全量词频（Phase 3 会回填 pos_guess / proposed_meaning 等列）
  freq/vocab_freq.md         可读版 top N
  corpus/lemma_log.csv       词形还原轨迹（人工只扫 top300）
  corpus/oov_log.csv         未入词典的词（专名/噪声/真缺口）
  corpus/cleanup_stats.md    丢弃统计

词汇闸门三分类：HIT（原形命中）/ LEMMA（还原后命中）/ OOV（都不中）
OOV 不进主表，但**留着**做缺口表，所以不能"一律丢弃"。

词频打分：
  per10k = tf / N * 10000
  df_rate = df / 5
  score = 0.7*df_rate + 0.3*min(1, per10k/20)
跨卷覆盖硬主导：一套卷堆 30 次（0.335）必须低于五套各 1 次（0.733）。
"""
import argparse
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CORPUS = os.path.join(ROOT, "docs", "exam_vocab", "corpus")
FREQ = os.path.join(ROOT, "docs", "exam_vocab", "freq")
HTML_MAIN = os.path.join(os.path.dirname(ROOT), "outputs", "单词复习", "背词助手.html")
DATA_JSON = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"
CET4 = os.path.join(os.path.dirname(ROOT), "专升本知识库", "99-附录", "数据源", "CET4luan_1.json")

SETS = ["HN2025", "HN2024", "HN2023", "MOCK1", "MOCK2"]
TOKEN_RE = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*")

# 还原目标禁止落到这些纯功能词上（being→be、does→do 之类）。
# 不用"长度<4 一律拒绝"来挡——那会把 use/get/set/day/way/old/big 也挡掉。
FUNCTION_WORDS = set("""be do does did is are was were am being been it its a an the
to of in on at by as or if so no not nor than then this that these those
me my he she we us them they their our your his her i you
would could should will shall may might must can""".split())

# 内容短词白名单：允许还原目标长度 3
CONTENT_SHORT = set("""have make take give come find know look work help need want show call
feel keep hold turn play read move live love hate open close start stop send sell tell ask
speak write build bring break carry catch choose drive eat fall fight grow hear lead learn
leave lose meet pay put rise run say see seek sit stand teach think throw understand wear win""".split())


# 不规则动词的过去式/过去分词，在词典里常被收成另一个罕见词条
# （said = adj. 上述的、given = adj. 沉溺的），高频场景下必须强制归并到原形。
# 只收「同形词条几乎不是真题里那个意思」的，像 left / found / thought / saw
# 这类真正有实义的歧义词一律不收，宁可保持原样。
FORCE_LEMMA = {
    "said": "say", "gave": "give", "given": "give", "took": "take", "taken": "take",
    "made": "make", "came": "come", "went": "go", "gone": "go", "got": "get",
    "knew": "know", "known": "know", "became": "become", "began": "begin",
    "begun": "begin", "brought": "bring", "bought": "buy", "held": "hold",
    "kept": "keep", "told": "tell", "wrote": "write", "written": "write",
    "spoke": "speak", "spoken": "speak", "ran": "run", "grew": "grow",
    "grown": "grow", "fell": "fall", "fallen": "fall", "rose": "rise",
    "sent": "send", "built": "build", "spent": "spend", "won": "win",
    "met": "meet", "paid": "pay", "sat": "sit", "stood": "stand",
    "heard": "hear", "felt": "feel", "meant": "mean", "lost": "lose",
    "led": "lead", "taught": "teach", "caught": "catch", "sold": "sell",
    "drove": "drive", "driven": "drive", "ate": "eat", "eaten": "eat",
    "chose": "choose", "chosen": "choose", "threw": "throw", "thrown": "throw",
    "shown": "show", "risen": "rise", "broken": "break", "lives": "life",
    "using": "use", "used": "use", "goes": "go", "gets": "get",
}


# 即使 surface 不在 BUILTIN 也不许还原的词（还原会把它们并到错误的基础词上）
NO_LEMMA = set("""being left means works findings news series species physics mathematics
economics politics ethics thanks goods clothes customs remains savings premises arms glasses
children women men people lives knives wives halves selves""".split())

CLEAN = [
    (r"^\s*\d{1,3}\s*[.)、]\s*", ""),            # 题号 61.
    (r"^\s*[A-H]\s*[.)]\s*", ""),                 # 选项字母 A.
    (r"_{2,}\d*_{2,}", " BLANK "),                # 空号 ___54___
    (r"\[[^\]\n]*\?[^\]\n]*\]", " UNK "),         # [?] 标记
    (r"[\u201c\u201d]", '"'),
    (r"[\u2018\u2019]", "'"),
    (r"[\u2013\u2014]", "-"),
    (r"\u2026", "..."),
]


def undouble(s):
    return re.sub(r"(bb|dd|ff|gg|mm|nn|pp|rr|tt|zz)$", lambda m: m.group(1)[0], s)


# 词形还原规则：**必须先检查词尾**，再套变换函数。
# （第一版漏了词尾检查，导致 brands→bray、underlined→underlie 这类错误，
#   因为 ies→y 的变换被无差别套用到所有词上。）
# 顺序：长的后缀先试，命中一个且结果在词典里就停。
LEMMA_RULES = [
    ("ies", lambda s: s[:-3] + "y"),
    ("ied", lambda s: s[:-3] + "y"),
    ("ying", lambda s: s[:-4] + "ie"),
    ("ing", lambda s: s[:-3] + "e"),
    ("ing", lambda s: undouble(s[:-3])),
    ("ing", lambda s: s[:-3]),
    ("ied", lambda s: s[:-1]),
    ("ed", lambda s: s[:-1]),
    ("ed", lambda s: undouble(s[:-2])),
    ("ed", lambda s: s[:-2]),
    ("es", lambda s: s[:-2]),
    ("es", lambda s: s[:-1]),
    ("s", lambda s: s[:-1]),
    ("ily", lambda s: s[:-3] + "y"),
    ("ly", lambda s: s[:-2]),
    ("ly", lambda s: s[:-1] + "e"),
    ("ness", lambda s: s[:-4]),
    ("ment", lambda s: s[:-4]),
    ("ation", lambda s: s[:-5] + "ate"),
    ("tion", lambda s: s[:-4]),
    ("sion", lambda s: s[:-4]),
    ("ity", lambda s: s[:-3] + "e"),
    ("ity", lambda s: s[:-3]),
    ("iest", lambda s: s[:-4] + "y"),
    ("est", lambda s: undouble(s[:-3])),
    ("est", lambda s: s[:-3]),
    ("est", lambda s: s[:-2]),
    ("ier", lambda s: s[:-3] + "y"),
    ("er", lambda s: undouble(s[:-2])),
    ("er", lambda s: s[:-2]),
    ("er", lambda s: s[:-1]),
    ("able", lambda s: s[:-4] + "e"),
    ("able", lambda s: s[:-4]),
    ("ible", lambda s: s[:-4] + "e"),
    ("ful", lambda s: s[:-3]),
    ("less", lambda s: s[:-4]),
    ("ive", lambda s: s[:-3]),
    ("ous", lambda s: s[:-3]),
    ("ize", lambda s: s[:-3]),
    ("ise", lambda s: s[:-3]),
]


def load_builtin():
    raw = io.open(HTML_MAIN, "rb").read().decode("utf-8")
    line = next(l for l in raw.split("\n") if l.startswith("const BUILTIN = "))
    return json.loads(line[len("const BUILTIN = "):-2])


def load_stoplist():
    p = os.path.join(HERE, "stoplist.txt")
    out = set()
    for line in io.open(p, encoding="utf-8"):
        w = line.strip()
        if w and not w.startswith("#"):
            out.add(w.lower())
    return out


def load_rubric():
    p = os.path.join(HERE, "rubric.txt")
    if not os.path.exists(p):
        return set()
    return {w.strip().lower() for w in io.open(p, encoding="utf-8")
            if w.strip() and not w.startswith("#")}


def load_lib314():
    d = json.loads(io.open(DATA_JSON, encoding="utf-8").read())
    return {w["word"].strip().lower() for w in d["words"]}


def load_cet4():
    out = set()
    for ln in io.open(CET4, encoding="utf-8"):
        ln = ln.strip()
        if ln:
            out.add(json.loads(ln)["headWord"].strip().lower())
    return out


def lemma_of(surface, BUILTIN):
    """返回 (lemma, rule) 或 (None, None)。surface 已在词典则原样返回。"""
    low = surface.lower()
    if low in FORCE_LEMMA and FORCE_LEMMA[low] in BUILTIN:
        return FORCE_LEMMA[low], "FORCE"
    if low in BUILTIN:
        return low, "HIT"
    if low in NO_LEMMA or len(low) < 4:
        return None, None
    for suf, fn in LEMMA_RULES:
        if not low.endswith(suf):
            continue
        try:
            cand = fn(low)
        except Exception:
            continue
        if not cand or cand == low or len(cand) < 3:
            continue
        if cand in FUNCTION_WORDS:
            continue
        if cand in BUILTIN:
            return cand, suf + "->"
    return None, None


def clean_line(s):
    for pat, rep in CLEAN:
        s = re.sub(pat, rep, s)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-md", type=int, default=800, help="可读版列前 N 词")
    a = ap.parse_args()

    os.makedirs(FREQ, exist_ok=True)
    pages_p = os.path.join(CORPUS, "pages.jsonl")
    if not os.path.exists(pages_p):
        print("缺少 pages.jsonl，先跑 parse_pages.py")
        return 1

    BUILTIN = load_builtin()
    STOP = load_stoplist()
    LIB314 = load_lib314()
    RUBRIC = load_rubric()
    CET4 = load_cet4()
    print("词典 %d 条 / 停用词 %d / 词库314 %d / 有道CET4 %d"
          % (len(BUILTIN), len(STOP), len(LIB314), len(CET4)))

    pages = [json.loads(l) for l in io.open(pages_p, encoding="utf-8") if l.strip()]

    # ---- 统计容器
    tf = {}                      # lemma -> 总次数
    cap = {}                     # lemma -> 首字母大写次数
    forms = {}                   # lemma -> {surface: count}
    per_set = {}                 # lemma -> {set: count}
    page_hit = {}                # lemma -> [printed...]
    lemma_log = {}               # (surface, lemma, rule) -> count
    oov = {}                     # surface_low -> {"n":, "cap":, "sets":set()}
    hyphen_split, apos_drop, stop_drop = [], 0, 0
    total_tokens = 0

    for pg in pages:
        pset = pg["set"]
        for line in clean_line(pg["text_en"]).split("\n"):
            for tok in TOKEN_RE.findall(line):
                total_tokens += 1
                low = tok.lower()
                # 连字符
                if "-" in tok:
                    if low in BUILTIN:
                        pass                     # 整体在词典里，按 1 词
                    else:
                        for part in low.split("-"):
                            if part and part not in STOP:
                                hyphen_split.append((tok, part))
                        continue
                # 撒号
                if "'" in tok and low not in BUILTIN:
                    apos_drop += 1
                    continue
                if low in STOP:
                    stop_drop += 1
                    continue

                lemma, rule = lemma_of(tok, BUILTIN)
                if lemma is None:
                    o = oov.setdefault(low, {"n": 0, "cap": 0, "sets": set()})
                    o["n"] += 1
                    o["sets"].add(pset)
                    if tok[0].isupper():
                        o["cap"] += 1
                    continue

                tf[lemma] = tf.get(lemma, 0) + 1
                forms.setdefault(lemma, {})
                forms[lemma][tok] = forms[lemma].get(tok, 0) + 1
                cap[lemma] = cap.get(lemma, 0) + (1 if tok[0].isupper() else 0)
                per_set.setdefault(lemma, {})
                per_set[lemma][pset] = per_set[lemma].get(pset, 0) + 1
                page_hit.setdefault(lemma, [])
                if not page_hit[lemma] or page_hit[lemma][-1] != pg["printed"]:
                    page_hit[lemma].append(pg["printed"])
                if rule != "HIT":
                    lemma_log[(tok, lemma, rule)] = lemma_log.get((tok, lemma, rule), 0) + 1

    # ---- 打分
    rows = []
    for w, n in tf.items():
        sets = per_set.get(w, {})
        df = len(sets)
        per10k = n / total_tokens * 10000 if total_tokens else 0
        score = 0.7 * (df / 5.0) + 0.3 * min(1.0, per10k / 20.0)
        if df == 5 and n >= 3:
            tier = "T0"
        elif df >= 4:
            tier = "T1"
        elif df >= 3:
            tier = "T2"
        elif df <= 2 and n >= 5:
            tier = "T3"
        else:
            tier = "T4"
        rows.append({
            "word": w, "tf": n, "df": df, "per10k": per10k, "score": score, "tier": tier,
            "s1": sets.get("HN2025", 0), "s2": sets.get("HN2024", 0), "s3": sets.get("HN2023", 0),
            "s4": sets.get("MOCK1", 0), "s5": sets.get("MOCK2", 0),
            "in_lib314": 1 if w in LIB314 else 0,
            "in_cet4": 1 if w in CET4 else 0,
            "cur": BUILTIN.get(w, ""),
            "rubric": 1 if w in RUBRIC else 0,
            "pages": page_hit.get(w, [])[:12],
        })
    rows.sort(key=lambda r: (-r["score"], -r["df"], -r["tf"], r["word"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i

    # 候选集
    cand = [r for r in rows if (r["df"] >= 2 or r["in_lib314"])]
    tight = [r for r in rows if (r["df"] >= 3 or r["in_lib314"])]
    used = cand if len(cand) <= 2500 else tight

    # ---- 写 vocab_freq.csv
    cols = ["rank", "word", "lemma", "pos_guess", "tf", "df", "s1", "s2", "s3", "s4", "s5",
            "per10k", "score", "tier", "rubric", "in_builtin", "in_lib314", "in_cet4", "in_syllabus",
            "cur_meaning", "proposed_meaning", "changed", "decision_src", "conf",
            "review_flag", "evidence_pages"]
    fp = os.path.join(FREQ, "vocab_freq.csv")
    with io.open(fp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r["rank"], r["word"], r["word"], "", r["tf"], r["df"],
                        r["s1"], r["s2"], r["s3"], r["s4"], r["s5"],
                        round(r["per10k"], 2), round(r["score"], 4), r["tier"], r["rubric"],
                        1, r["in_lib314"], r["in_cet4"], "",
                        r["cur"], "", "", "", "", "", ",".join(map(str, r["pages"]))])

    # ---- 写 vocab_freq.md
    md = os.path.join(FREQ, "vocab_freq.md")
    with io.open(md, "w", encoding="utf-8") as f:
        f.write("# 河南专升本真题词频（%d 页 / %d 词 / %d 个词条）\n\n" % (len(pages), total_tokens, len(rows)))
        f.write("> score = 0.7·(df/5) + 0.3·min(1, per10k/20)。df = 出现在几套卷里。\n\n")
        f.write("| tier | 条件 | 词数 |\n|---|---|---|\n")
        for t, cond in [("T0", "df=5 且 tf≥3"), ("T1", "df≥4"), ("T2", "df≥3"),
                        ("T3", "df≤2 且 tf≥5（单卷堆积）"), ("T4", "其余")]:
            f.write("| %s | %s | %d |\n" % (t, cond, sum(1 for r in rows if r["tier"] == t)))
        body = [r for r in rows if not r["rubric"]]
        f.write("\n> 已排除题干套话 %d 个（passage / statement / blank …），原表见 CSV。\n" % (len(rows) - len(body)))
        f.write("\n## 前 %d 词\n\n| # | 词 | 频次 | 套数 | 每万词 | score | 在词库 | 现释义 |\n" % a.top_md)
        f.write("|---|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(body[:a.top_md], 1):
            f.write("| %d | %s | %d | %d | %.1f | %.3f | %s | %s |\n"
                    % (i, r["word"], r["tf"], r["df"], r["per10k"], r["score"],
                       "✓" if r["in_lib314"] else "", r["cur"].replace("|", "\\|")[:34]))

    # ---- lemma_log
    lp = os.path.join(CORPUS, "lemma_log.csv")
    with io.open(lp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["surface", "lemma", "rule", "count"])
        for (s, l, r), c in sorted(lemma_log.items(), key=lambda x: -x[1]):
            w.writerow([s, l, r, c])

    # ---- oov_log
    op = os.path.join(CORPUS, "oov_log.csv")
    oov_rows = []
    for s, o in oov.items():
        capr = o["cap"] / o["n"] if o["n"] else 0
        if capr >= 0.8:
            cls = "OOV_PROPER"
        elif o["n"] >= 2 and len(o["sets"]) >= 2 and re.search(r"[aeiouy]", s):
            cls = "OOV_REAL"
        else:
            cls = "OOV_NOISE"
        oov_rows.append((s, o["n"], len(o["sets"]), round(capr, 2), cls))
    oov_rows.sort(key=lambda x: (x[4] != "OOV_REAL", -x[1]))
    with io.open(op, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["surface", "count", "df", "cap_ratio", "class"])
        for r in oov_rows:
            w.writerow(r)

    # ---- cleanup_stats
    real = [r for r in oov_rows if r[4] == "OOV_REAL"]
    sp = os.path.join(CORPUS, "cleanup_stats.md")
    with io.open(sp, "w", encoding="utf-8") as f:
        f.write("# 清洗统计\n\n")
        f.write("| 指标 | 数值 |\n|---|---|\n")
        f.write("| 总 token（未过滤） | %d |\n" % total_tokens)
        f.write("| 停用词丢弃 | %d |\n" % stop_drop)
        f.write("| 撒号词丢弃（不在词典） | %d |\n" % apos_drop)
        f.write("| 连字符拆分 | %d |\n" % len(hyphen_split))
        f.write("| 词典命中词条 | %d |\n" % len(rows))
        f.write("| 词形还原条目 | %d |\n" % len(lemma_log))
        f.write("| OOV 唯一词 | %d |\n" % len(oov_rows))
        f.write("| └ OOV_REAL（疑似真缺口） | %d |\n" % len(real))
        f.write("| OOV 占唯一词比例 | %.1f%% |\n" % (len(oov_rows) * 100.0 / max(1, len(oov_rows) + len(rows))))
        f.write("\n## 连字符拆分 Top 30\n\n")
        from collections import Counter
        cc = Counter(x[1] for x in hyphen_split)
        f.write(", ".join("%s×%d" % (k, v) for k, v in cc.most_common(30)) or "（无）")
        f.write("\n\n## OOV_REAL Top 60（这些才是词典里没有的词）\n\n")
        f.write(", ".join("%s×%d" % (r[0], r[1]) for r in real[:60]) or "（无）")
        f.write("\n")

    print("\n总计 %d 页 / %d token → %d 个词条" % (len(pages), total_tokens, len(rows)))
    print("候选集 df≥2 或 314：%d 条（上限 2500，实际用 %d 条档）" % (len(cand), len(used)))
    print("tier 分布：" + "  ".join("%s=%d" % (t, sum(1 for r in rows if r["tier"] == t))
                                 for t in ("T0", "T1", "T2", "T3", "T4")))
    print("OOV：%d 条，其中疑似真缺口 %d 条" % (len(oov_rows), len(real)))
    print("产物：%s" % FREQ)
    print("      %s" % CORPUS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
