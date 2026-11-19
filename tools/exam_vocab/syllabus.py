#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把专升本 3716 词纲解析成精简释义，供内置词典使用

口径（用户已确认）：
  · 范围：词纲全量 − 已有 314 词库 = 3471
  · 以词纲释义为主，词纲缺失/截断的用内置词典补
  · 出对照表，并允许写回内置词典

词纲源：C:/Users/xuenc/Desktop/DSHworkarou/work/words.json
  字段 page / word / pos / rest；3716 条去重 3715
  1055 条释义被原书截断（以 ... 结尾），371 条截在半个词上

处理链：
  rest ──切内联词性──> [(pos, 义项串)] ──取前 2 义──> groups
       ──T.render──> 文本 ──T.ensure_pos──> 文本
       ──T.trim_meaning──> 最终释义（天然是本脚本自己的不动点）

用法：
  python tools/exam_vocab/syllabus.py            # 生成 5 个产物，不写回
  python tools/exam_vocab/syllabus.py --stats    # 只打印统计
"""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import statistics as st
import sys
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))              # 背词助手/
OUT = os.path.join(ROOT, "docs", "exam_vocab", "syllabus")
HTML_MAIN = os.path.join(os.path.dirname(ROOT), "outputs", "单词复习", "背词助手.html")
DATA_JSON = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"
SYL_SRC = "C:/Users/xuenc/Desktop/DSHworkarou/work/words.json"

sys.path.insert(0, os.path.join(ROOT, "tools"))
import trim_exam_meaning as T                              # noqa: E402

POS_ALIAS = {"n": "n", "v": "v", "vt": "vt", "vi": "vi", "adj": "adj", "adv": "adv",
             "prep": "prep", "conj": "conj", "pron": "pron", "num": "num",
             "art": "art", "int": "int", "interj": "int", "abbr": "abbr", "det": "det"}

# 内联词性标记：前面不能紧贴字母（避免把 "brave" 里的 v. 之类误切）
INLINE = re.compile(r"(?<![A-Za-z])(n|v|vt|vi|adj|adv|prep|conj|pron|num|art|interj|abbr|det)\.\s*")
SENSE_SPLIT = re.compile(r"[,，、;；]")


def pos_family(p):
    """v / vt / vi 是同一族，判断「有没有这个词性」时不能各算各的。"""
    if not p:
        return ""
    return "v" if p in ("v", "vt", "vi") else p


def sha1_file(p):
    return hashlib.sha1(io.open(p, "rb").read()).hexdigest()[:16]


def load_builtin():
    raw = io.open(HTML_MAIN, "rb").read().decode("utf-8")
    line = next(l for l in raw.split("\n") if l.startswith("const BUILTIN = "))
    return json.loads(line[len("const BUILTIN = "):-2])


def load_lib():
    d = json.loads(io.open(DATA_JSON, encoding="utf-8").read())
    return {w["word"].strip().lower() for w in d["words"]}


def parse_entry(o):
    """词纲单条 → [(pos, [义项...])]，每组最多 2 义。"""
    rest = (o.get("rest") or "").strip()
    base = POS_ALIAS.get((o.get("pos") or "").strip().lower())
    marks = [(m.start(), m.end(), m.group(1)) for m in INLINE.finditer(rest)]

    if marks:
        parts = [(base, rest[:marks[0][0]])]
        for i, (s, e, p) in enumerate(marks):
            nxt = marks[i + 1][0] if i + 1 < len(marks) else len(rest)
            parts.append((POS_ALIAS.get(p, p), rest[e:nxt]))
    else:
        parts = [(base, rest)]

    groups = []
    for pos, txt in parts:
        txt = txt.strip().strip(",，;； ").strip()
        if not txt:
            continue
        truncated = bool(re.search(r"(\.{3,}|…+)\s*$", txt))
        txt = re.sub(r"(\.{3,}|…+)\s*$", "", txt).strip()
        senses = [x.strip() for x in SENSE_SPLIT.split(txt) if x.strip()]
        # 截断时最后一段常只写了半个词（homo → "同"），整段丢掉
        if truncated and senses and len(senses[-1]) <= 1:
            senses = senses[:-1]
        senses = senses[:2]
        if senses:
            # 同词性合并：March/march 合并后会出现两个 n 组，不能输出「n. …；n. …」
            for g in groups:
                if g[0] == pos:
                    for x in senses:
                        if len(g[1]) < 2 and x not in g[1]:
                            g[1].append(x)
                    break
            else:
                groups.append((pos, list(senses)))
    return groups


def fill_from_builtin(word, groups, truncated, B):
    """词纲被原书截断时，末尾的词性组可能整组丢失（arm 丢掉「v. 武装」）。
    只在 truncated=True 时补，避免把词纲刻意省略的义项又搬回来。"""
    if not truncated:
        return groups, []
    raw = B.get(word)
    if not raw:
        return groups, []
    have = {pos_family(g[0]) for g in groups}
    filled = []
    for g in T.parse_groups(T.normalize_line(raw)):
        pos = g["pos"]
        if pos_family(pos) in have or not g["senses"]:
            continue
        if len(groups) >= T.MAX_POS_GROUPS:
            break
        senses = [x for x in g["senses"] if x][:2]
        if not senses:
            continue
        groups.append((pos, senses))
        have.add(pos_family(pos))
        filled.append(pos)
    return groups, filled


def finalize(word, groups):
    txt = T.render([{"pos": p or "", "senses": s} for p, s in groups])
    txt = T.ensure_pos(word, T.normalize_line(txt))
    out, _ = T.trim_meaning(txt, word)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    W = json.loads(io.open(SYL_SRC, encoding="utf-8").read())
    B = load_builtin()
    LIB = load_lib()

    # 按小写归并。March(三月) 与 march(行进) 同名不同义，要**合并义项**而不是丢弃后者。
    syl, dup = {}, []
    for o in W:
        k = (o.get("word") or "").strip().lower()
        if not k:
            continue
        if k in syl:
            dup.append((k, syl[k].get("rest"), o.get("rest")))
            p2 = POS_ALIAS.get((o.get("pos") or "").strip().lower())
            syl[k] = {"word": k, "pos": syl[k].get("pos"),
                      "rest": (syl[k].get("rest") or "").rstrip("，,；; ") +
                              " " + (p2 + ". " if p2 else "") + (o.get("rest") or ""),
                      "page": syl[k].get("page")}
            continue
        syl[k] = {"word": k, "pos": o.get("pos"), "rest": o.get("rest"), "page": o.get("page")}
    print("词纲 %d 条 → 归并 %d（同名合并 %d: %s）"
          % (len(W), len(syl), len(dup), [d[0] for d in dup]))

    clean, overrides, additions, rows = {}, {}, {}, []
    n_empty = n_same = n_diff = n_filled = 0
    no_meaning = []

    for k, o in syl.items():
        groups = parse_entry(o)
        if not groups:
            n_empty += 1
            no_meaning.append(k)
            continue
        trunc = bool(re.search(r"(\.{3,}|…+)\s*$", (o.get("rest") or "")))
        groups, filled = fill_from_builtin(k, groups, trunc, B)
        if filled:
            n_filled += 1
        new = finalize(k, groups)
        clean[k] = {"pos": o.get("pos"), "raw": o.get("rest"), "page": o.get("page"),
                    "truncated": trunc, "filled_pos": filled,
                    "groups": [{"pos": p, "senses": s} for p, s in groups],
                    "final": new}

        if k in LIB:                       # 你已有词库，词典这层不动它
            continue
        old = B.get(k)
        if old is None:
            additions[k] = {"meaning": new, "src": "syllabus", "df": 5, "min_df": 1, "in314": 1}
            rows.append((k, "", new, "新增", o.get("rest") or ""))
        elif new == old:
            n_same += 1
            rows.append((k, old, new, "一致", o.get("rest") or ""))
        else:
            n_diff += 1
            overrides[k] = {"meaning": new, "src": "syllabus", "df": 5, "min_df": 1, "in314": 1}
            rows.append((k, old, new, "改", o.get("rest") or ""))

    payload = {
        "_meta": {
            "version": "2026-11-05.1",
            "source": SYL_SRC,
            "source_sha1": sha1_file(SYL_SRC),
            "n_syllabus": len(syl),
            "n_overrides": len(overrides),
            "n_additions": len(additions),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "generator": "tools/exam_vocab/syllabus.py",
            "note": "key 全小写；释义已过 trim_meaning，故为不动点",
        },
        "overrides": dict(sorted(overrides.items())),
    }
    io.open(os.path.join(OUT, "syllabus_overrides.json"), "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=1))
    io.open(os.path.join(OUT, "syllabus_clean.json"), "w", encoding="utf-8").write(
        json.dumps(dict(sorted(clean.items())), ensure_ascii=False, indent=0))
    io.open(os.path.join(OUT, "syllabus_additions.json"), "w", encoding="utf-8").write(
        json.dumps({"_meta": {"n": len(additions), "source_sha1": payload["_meta"]["source_sha1"]},
                    "additions": dict(sorted(additions.items()))}, ensure_ascii=False, indent=1))

    # ---- 对照表：全量 CSV
    with io.open(os.path.join(OUT, "compare.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["word", "type", "orig_len", "new_len", "delta", "orig", "new", "syllabus_raw"])
        for k, old, new, typ, raw in rows:
            w.writerow([k, typ, len(old), len(new), len(new) - len(old), old, new, raw])

    # ---- 需要人看一眼的：压得狠 or 只剩 1 义
    review = []
    for k, old, new, typ, raw in rows:
        if typ != "改":
            continue
        cut = 1 - len(new) / max(1, len(old))
        n_new = len([x for x in re.split(r"[,，]", new) if x.strip()])
        n_old = len([x for x in re.split(r"[,，]", old) if x.strip()])
        # 只有「明显压短」或「原本 3 个以上义项被砍到 1 个」才需要人看；
        # 词纲本来就只有一个义项的词不算风险，否则 1500 条全是噪音。
        if cut >= 0.40 or (n_new <= 1 and n_old >= 3):
            review.append((round(cut, 2), k, old, new, raw))
    review.sort(key=lambda x: -x[0])
    with io.open(os.path.join(OUT, "need_review.tsv"), "w", encoding="utf-8") as f:
        f.write("cut\tword\torig\tnew\tsyllabus_raw\n")
        for cut, k, old, new, raw in review:
            f.write("%.2f\t%s\t%s\t%s\t%s\n" % (cut, k, old, new, raw))

    # ---- 摘要 md
    avg_o = st.mean([len(v) for v in B.values()])
    D2 = dict(B)
    for k, v in overrides.items():
        D2[k] = v["meaning"]
    for k, v in additions.items():
        D2[k] = v["meaning"]
    avg_n = st.mean([len(v) for v in D2.values()])
    b_o = len(json.dumps(B, ensure_ascii=False, separators=(",", ":")))
    b_n = len(json.dumps(D2, ensure_ascii=False, separators=(",", ":")))

    L = ["# 词纲 3716 → 内置词典精简对照\n",
         "> 源：`%s`（sha1 `%s`）\n" % (SYL_SRC, payload["_meta"]["source_sha1"]),
         "## 一、总量\n",
         "| 项 | 值 |\n|---|---|",
         "| 词纲条目 | %d（去重） |" % len(syl),
         "| 其中已在你的 314 词库（词典层不动） | %d |" % (len(syl) - len(overrides) - len(additions) - n_same),
         "| 与现有词典一致 | %d |" % n_same,
         "| **会改** | **%d** |" % n_diff,
         "| **新增词条** | **%d** |" % len(additions),
         "| 解析为空（跳过） | %d %s |" % (n_empty, no_meaning[:8]),
         "",
         "## 二、体积\n",
         "| 项 | 前 | 后 | 变化 |\n|---|---|---|---|",
         "| 条数 | %d | %d | +%d |" % (len(B), len(D2), len(D2) - len(B)),
         "| 平均释义长度 | %.2f | %.2f | %+.2f |" % (avg_o, avg_n, avg_n - avg_o),
         "| BUILTIN JSON 字节 | %d | %d | %+.2f%% |" % (b_o, b_n, (b_n - b_o) * 100.0 / b_o),
         "",
         "## 三、压得最狠的 60 条（供你抽查）\n",
         "| 词 | 原释义 | 新释义 | 词纲原文 |\n|---|---|---|---|"]
    for cut, k, old, new, raw in review[:60]:
        L.append("| **%s** | %s | %s | %s |" % (k, old.replace("|", "\\|"),
                                                new.replace("|", "\\|"), raw[:40].replace("|", "\\|")))
    L.append("")
    L.append("## 四、新增的 %d 条（内置词典原本没有）\n" % len(additions))
    L.append("| 词 | 释义 |\n|---|---|")
    for k, v in sorted(additions.items()):
        L.append("| %s | %s |" % (k, v["meaning"]))
    L.append("")
    L.append("> 全量对照见 `compare.csv`；要人眼确认的 %d 条见 `need_review.tsv`。" % len(review))
    io.open(os.path.join(OUT, "compare.md"), "w", encoding="utf-8").write("\n".join(L))

    print()
    print("一致 %d ｜ 会改 %d ｜ 新增 %d ｜ 跳过 %d ｜ 截断补词性 %d"
          % (n_same, n_diff, len(additions), n_empty, n_filled))
    print("需人眼确认 %d 条（压 ≥40%% 或只剩 1 义）" % len(review))
    print("BUILTIN %d → %d 条，字节 %+.2f%%，均长 %.2f → %.2f"
          % (len(B), len(D2), (b_n - b_o) * 100.0 / b_o, avg_o, avg_n))
    print("产物 →", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
