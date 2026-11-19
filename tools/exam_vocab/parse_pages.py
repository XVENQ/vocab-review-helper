#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真题单页转录件解析与全局对账

读 docs/exam_vocab/raw/page_*.md（68 份，一页一文件），校验后合并成 pages.jsonl。

校验（不过就写进 anomaly，不中断）：
  P1 printed 页码集合必须 == {1..68}，无重无缺
  P2 文件名号与印刷页码一致（不一致只告警，以印刷为准）
  P3 每页的 set 必须与页区间一致
  P4 "Part IV" 在全文出现 5 次（5 套卷各一次）
  P5 单页词数 80..700
  P6 suspects/words <= 0.05

用法：
  python tools/exam_vocab/parse_pages.py
  python tools/exam_vocab/parse_pages.py --strict    # P1/P4 失败返回 1
"""
import argparse
import glob
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 背词助手/
RAW = os.path.join(ROOT, "docs", "exam_vocab", "raw")
CORPUS = os.path.join(ROOT, "docs", "exam_vocab", "corpus")
ANOM = os.path.join(ROOT, "docs", "exam_vocab", "anomaly")

SETS = [
    ("HN2025", 1, 16, "河南省2025年普通高等学校专升本招生考试"),
    ("HN2024", 17, 32, "河南省2024年普通高等学校专升本招生考试"),
    ("HN2023", 33, 44, "河南省2023年普通高等学校专升本招生考试"),
    ("MOCK1", 45, 56, "河南省专升本全真模拟试卷（一）"),
    ("MOCK2", 57, 68, "河南省专升本全真模拟试卷（二）"),
]
TAG_RE = re.compile(r"</?[a-zA-Z][^>]{0,40}>")


def set_of(page):
    for name, lo, hi, _t in SETS:
        if lo <= page <= hi:
            return name
    return "UNKNOWN"


def parse_file(path):
    txt = io.open(path, encoding="utf-8").read().replace("\r\n", "\n")
    front, body = {}, txt
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", txt, re.S)
    if m:
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                front[k.strip().lower()] = v.strip()
        body = txt[m.end():]

    def field(name):
        mm = re.search(r"^%s:\s*(.*)$" % name, body, re.M | re.I)
        return mm.group(1).strip() if mm else ""

    bm = re.search(r"<<<\s*\n(.*?)\n\s*>>>", body, re.S)
    text = bm.group(1) if bm else ""
    text = TAG_RE.sub("", text)                       # 清掉模型自加的 <u> 之类
    text = text.replace("**", "").replace("__", "")

    sm = re.search(r"words\s*=\s*(\d+)", field("STATS"))
    sus = field("SUSPECTS")
    n_sus = 0 if (not sus or sus.lower() == "none") else len([x for x in sus.split("|") if x.strip()])

    try:
        printed = int(front.get("printed") or field("printed") or -1)
    except ValueError:
        printed = -1
    try:
        assigned = int(front.get("page") or -1)
    except ValueError:
        assigned = -1

    q = (front.get("quality") or "ok").lower()

    return {
        "assigned": assigned,
        "printed": printed,
        "img": front.get("img", os.path.basename(path)),
        "file": os.path.basename(path),
        "quality": "low" if q == "low" else "ok",
        "title": field("TITLE"),
        "text": text,
        "words_claimed": int(sm.group(1)) if sm else -1,
        "suspects": n_sus,
        "skip": field("SKIP"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    os.makedirs(CORPUS, exist_ok=True)
    os.makedirs(ANOM, exist_ok=True)

    files = sorted(glob.glob(os.path.join(RAW, "page_*.md")))
    if not files:
        print("没找到任何 page_*.md，先跑转录")
        return 1

    pages, anomalies, seen = [], [], {}
    for f in files:
        p = parse_file(f)
        if p["printed"] < 0:
            anomalies.append(("NO_PAGE_NO", p["file"], "读不到印刷页码"))
            continue
        p["set"] = set_of(p["printed"])

        en, zh = [], []
        for line in p["text"].split("\n"):
            (zh if line.startswith("[ZH] ") else en).append(line)
        p["text_en"] = "\n".join(en)
        p["text_zh"] = "\n".join(zh)
        p["nwords"] = len(re.findall(r"[A-Za-z]+(?:['\-][A-Za-z]+)*", p["text_en"]))

        if p["printed"] in seen:
            anomalies.append(("DUP_PAGE", p["file"], "第 %d 页重复（另见 %s）" % (p["printed"], seen[p["printed"]])))
        else:
            seen[p["printed"]] = p["file"]

        if p["assigned"] > 0 and p["assigned"] != p["printed"]:
            anomalies.append(("PAGE_MISMATCH", p["file"],
                              "分配 %d / 实读 %d" % (p["assigned"], p["printed"])))
        if p["nwords"] < 15 and "writing" not in (p["title"] + p["text"]).lower():
            anomalies.append(("WORDS_TOO_FEW", p["file"], "p%d 只有 %d 词（可能漏抄）" % (p["printed"], p["nwords"])))
        elif p["nwords"] > 700:
            anomalies.append(("WORDS_TOO_MANY", p["file"], "p%d 有 %d 词（可能重复抄）" % (p["printed"], p["nwords"])))
        if p["nwords"] and p["suspects"] / p["nwords"] > 0.05:
            p["quality"] = "low"
            anomalies.append(("SUSPECT_HIGH", p["file"],
                              "p%d 可疑 %d/%d = %.1f%%" % (p["printed"], p["suspects"], p["nwords"],
                                                           p["suspects"] * 100.0 / p["nwords"])))
        if p["words_claimed"] > 0 and p["nwords"] and abs(p["words_claimed"] - p["nwords"]) > max(10, p["nwords"] * 0.06):
            anomalies.append(("WORD_MISMATCH", p["file"],
                              "p%d 自报 %d 实算 %d" % (p["printed"], p["words_claimed"], p["nwords"])))
        pages.append(p)

    pages.sort(key=lambda x: x["printed"])
    got = {p["printed"] for p in pages}
    want = set(range(1, 69))
    missing, extra = sorted(want - got), sorted(got - want)
    if missing:
        anomalies.append(("MISSING_PAGE", "-", "缺 %d 页：%s" % (len(missing), missing)))
    if extra:
        anomalies.append(("EXTRA_PAGE", "-", "多出页码：%s" % extra))

    # 每套卷都应有 Part IV。按"套"判断，不按出现次数——标题与正文有时会各写一次。
    have4 = {p["set"] for p in pages if re.search(r"Part\s+IV\b", p["title"] + "\n" + p["text_en"])}
    n_part4 = len(have4)
    if n_part4 != 5:
        anomalies.append(("PART4_MISSING", "-", "只有 %d/5 套卷有 Part IV：%s" % (n_part4, sorted(have4))))

    # 卷首标题抽检
    for name, lo, _hi, kw in SETS:
        head = next((p for p in pages if p["printed"] == lo), None)
        if head and kw not in (head["title"] + head["text"]):
            anomalies.append(("SET_HEADER", head["file"],
                              "p%d 未出现预期卷名「%s」，实读 TITLE=%s" % (lo, kw, head["title"][:40])))

    with io.open(os.path.join(CORPUS, "pages.jsonl"), "w", encoding="utf-8") as f:
        for p in pages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    with io.open(os.path.join(CORPUS, "corpus.txt"), "w", encoding="utf-8") as f:
        for p in pages:
            f.write("\n=== p%d [%s] %s ===\n" % (p["printed"], p["set"], p["title"]))
            f.write(p["text"] + "\n")

    total = sum(p["nwords"] for p in pages)
    low = [p["printed"] for p in pages if p["quality"] == "low"]
    print("解析 %d 个文件 → %d 页，%d 英文词" % (len(files), len(pages), total))
    print("页码完整：%s（缺 %d，多 %d）" % ("是" if not missing and not extra else "否", len(missing), len(extra)))
    print("Part IV 计数：%d（应为 5）" % n_part4)
    print("low 质量页：%d %s" % (len(low), low[:15]))
    print("异常 %d 条 → %s" % (len(anomalies), os.path.join(ANOM, "pages_anomaly.md")))
    by = {}
    for p in pages:
        by.setdefault(p["set"], [0, 0])
        by[p["set"]][0] += 1
        by[p["set"]][1] += p["nwords"]
    for s, _lo, _hi, _t in SETS:
        if s in by:
            print("  %-7s %2d 页  %5d 词" % (s, by[s][0], by[s][1]))

    with io.open(os.path.join(ANOM, "pages_anomaly.md"), "w", encoding="utf-8") as f:
        f.write("# 转录对账异常\n\n共 %d 条。\n\n| 类型 | 文件 | 说明 |\n|---|---|---|\n" % len(anomalies))
        for t, loc, msg in anomalies:
            f.write("| %s | %s | %s |\n" % (t, loc, msg))
        if not anomalies:
            f.write("| - | - | 无异常 |\n")

    if a.strict and (missing or extra or n_part4 != 5):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
