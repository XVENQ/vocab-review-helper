#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""《21 天突破基础高频词》→ 按天分组的精讲参考文档

为什么单独出一份文档而不往词库里塞：
  这 426 个词有 89% 已经在 3716 词纲里（也就是说词典早就有释义了），
  真正的增量是每条后面的 **【搭配】** 和 **【拓展/词族】** —— 这两样词典里完全没有。
  所以做成可查阅的精讲，而不是再导一批重复的卡片。

源：C:/Users/xuenc/Desktop/26河南专升本电子版赠品/21天突破基础高频词.pdf
  75 页，有文本层，按 Day 1–21 编排，每日 20–22 个词
  每条版式：`序号. 单词 /音标/ 释义` + 【搭配】 + 【拓展】

用法：
  python tools/exam_vocab/highfreq.py
  python tools/exam_vocab/highfreq.py --check   # 只打印统计
"""
import argparse
import csv
import io
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "docs", "exam_vocab", "high_freq")
SRC = "C:/Users/xuenc/Desktop/26河南专升本电子版赠品/21天突破基础高频词.pdf"
HTML_MAIN = os.path.join(os.path.dirname(ROOT), "outputs", "单词复习", "背词助手.html")
DATA_JSON = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"
SYL = "C:/Users/xuenc/Desktop/DSHworkarou/work/words.json"

DAY = re.compile(r"Day\s*(\d{1,2})")
ENTRY = re.compile(r"^[ \t]*(\d{1,3})[.．、][ \t]*([A-Za-z][A-Za-z'\- ]{0,22}?)[ \t]*"
                   r"/([^/\n]{0,44})/[ \t]*(.+)$", re.M)
HEADER = re.compile(r"^\s*(Day\s*\d{1,2}\s*\d{1,3}|\d{1,3}\s*Day\s*\d{1,2})\s*$", re.M)


def read_pdf_text(path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    return "\n".join((doc[i].get_textpage().get_text_bounded() or "").replace("\r", "")
                     for i in range(len(doc)))


def load_sets():
    lib = {w["word"].strip().lower()
           for w in json.loads(io.open(DATA_JSON, encoding="utf-8").read())["words"]}
    syl = {o["word"].strip().lower()
           for o in json.loads(io.open(SYL, encoding="utf-8").read())}
    return lib, syl


def parse(full):
    secs = [(m.start(), int(m.group(1))) for m in DAY.finditer(full)]
    ems = list(ENTRY.finditer(full))

    def day_of(pos):
        d = None
        for p, n in secs:
            if p <= pos:
                d = n
            else:
                break
        return d

    rows = []
    for i, m in enumerate(ems):
        end = ems[i + 1].start() if i + 1 < len(ems) else len(full)
        block = HEADER.sub("", full[m.end():end])
        block = block.replace("中公学员", "").replace("应试指南", "")
        keep = []
        for l in (x.strip() for x in block.split("\n")):
            if not l:
                continue
            if l == "Review" or l.startswith("单词复习表"):
                break
            keep.append(l)
        text = " ".join(keep)

        coll = ext = ""
        mc = re.search(r"【搭配】(.*?)(?=【拓展】|$)", text)
        me = re.search(r"【拓展】(.*)$", text)
        if mc:
            coll = mc.group(1).strip()
        if me:
            ext = me.group(1).strip()

        rows.append({"no": int(m.group(1)), "day": day_of(m.start()),
                     "word": m.group(2).strip(), "phon": m.group(3).strip(),
                     "def": m.group(4).strip().rstrip("。"),
                     "coll": coll, "ext": ext})
    return rows


def tidy(s):
    """搭配用「；」分隔多条，便于阅读"""
    s = re.sub(r"\s+", " ", s).strip()
    # 英文短语之间没有标点，靠 " 中文 " 之后的下一段英文切
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    full = read_pdf_text(SRC)
    rows = parse(full)
    lib, syl = load_sets()
    for r in rows:
        k = r["word"].lower()
        r["in_lib"] = k in lib
        r["in_syl"] = k in syl

    cnt = Counter(r["day"] for r in rows)
    print("词条 %d 条，覆盖 Day %d–%d，每天 %d–%d 个"
          % (len(rows), min(cnt), max(cnt), min(cnt.values()), max(cnt.values())))
    print("带搭配 %d 条，带拓展 %d 条" % (sum(1 for r in rows if r["coll"]),
                                        sum(1 for r in rows if r["ext"])))
    print("已在 314 词库 %d 条；已在 3716 词纲 %d 条（%.0f%%）"
          % (sum(r["in_lib"] for r in rows), sum(r["in_syl"] for r in rows),
             sum(r["in_syl"] for r in rows) * 100.0 / len(rows)))
    no_coll = [r["word"] for r in rows if not r["coll"]]
    no_ext = [r["word"] for r in rows if not r["ext"]]
    print("无搭配：%d %s" % (len(no_coll), no_coll[:8]))
    print("无拓展：%d %s" % (len(no_ext), no_ext[:8]))
    if a.check:
        return 0

    os.makedirs(OUT, exist_ok=True)

    # ---- CSV 全量
    with io.open(os.path.join(OUT, "highfreq_21days.csv"), "w",
                 encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "no", "word", "phonetic", "meaning", "collocation",
                    "extension", "in_lib314", "in_syllabus3716"])
        for r in rows:
            w.writerow([r["day"], r["no"], r["word"], r["phon"], r["def"],
                        r["coll"], r["ext"], int(r["in_lib"]), int(r["in_syl"])])

    # ---- JSON
    io.open(os.path.join(OUT, "highfreq_21days.json"), "w", encoding="utf-8").write(
        json.dumps({"_meta": {"source": SRC, "n": len(rows),
                              "days": [min(cnt), max(cnt)],
                              "note": "搭配=collocation 拓展=word family"},
                    "words": rows}, ensure_ascii=False, indent=1))

    # ---- Markdown 精讲
    L = ["# 专升本基础高频词 · 21 天精讲\n",
         "> 源：《21 天突破基础高频词》（%d 词，Day 1–21，每日 20–22 个）。\n" % len(rows),
         "> 这份文档给的是**词典里查不到的东西**：搭配和词族。释义本身词典已有。\n",
         "| Day | 词数 | 覆盖 |\n|---|---|---|"]
    for d in sorted(cnt):
        L.append("| Day %d | %d | 第 %d–%d 个 |" % (d, cnt[d],
                 min(r["no"] for r in rows if r["day"] == d),
                 max(r["no"] for r in rows if r["day"] == d)))
    L.append("")
    L.append("> ✱ = 已在你 314 张卡里；✓ = 已在 3716 词纲（词典能查到释义）。\n")

    for d in sorted(cnt):
        L.append("\n---\n\n## Day %d\n" % d)
        for r in [x for x in rows if x["day"] == d]:
            mark = (" ✱" if r["in_lib"] else "") + (" ✓" if r["in_syl"] else "")
            L.append("### %s%s  `/%s/`\n" % (r["word"], mark, r["phon"]))
            L.append("%s\n" % r["def"])
            if r["coll"]:
                L.append("- **搭配**　%s" % r["coll"])
            if r["ext"]:
                L.append("- **拓展**　%s" % r["ext"])
            L.append("")

    io.open(os.path.join(OUT, "highfreq_21days.md"), "w", encoding="utf-8").write("\n".join(L))
    print("产物 →", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
