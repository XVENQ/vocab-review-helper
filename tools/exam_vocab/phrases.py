#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把《河南专升本英语短语常备 465 组》解析成词典可用的短语条目

为什么单独做这一层：
  内置词典 21366 条里**一条短语都没有**（只有之前手工加的 5 条），
  而《1 图看懂知识框架》明确写着词汇的考查内容包含「短语搭配」，
  直接题型是完形填空、选词填空（十选五）、改错。这是结构性缺口。

源：C:/Users/xuenc/Desktop/26河南专升本电子版赠品/河南专升本英语短语常备465组.pdf
  · 有文本层，14 页，编号 1–465
  · 版式坑：① 有 6 条与上一条挤在同一行（用 ", NNN " 分隔）
            ② 页脚「中公专升本词组打卡第 N 天」会插进正文
            ③ 同一短语出现两次、释义不同

解析策略：**顺序扫描**——只接受「期望的下一个编号」，天然过滤正文里的杂号。

用法：
  python tools/exam_vocab/phrases.py          # 生成产物
  python tools/exam_vocab/phrases.py --show   # 只打印样例与统计
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "docs", "exam_vocab", "phrases")
SRC = "C:/Users/xuenc/Desktop/26河南专升本电子版赠品/河南专升本英语短语常备465组.pdf"
HTML_MAIN = os.path.join(os.path.dirname(ROOT), "outputs", "单词复习", "背词助手.html")

ZH = re.compile(r"[\u4e00-\u9fa5]")
# 短语 key 只允许英文字母、撇号、连字符、空格
KEY_OK = re.compile(r"^[a-z][a-z'\- ]*$")
HEADER = re.compile(r"中公专升本词组打卡第\s*\d+\s*天")
PROMO = re.compile(r"更多信息请关注公众号[^\n]*")


def load_builtin():
    raw = io.open(HTML_MAIN, "rb").read().decode("utf-8")
    line = next(l for l in raw.split("\n") if l.startswith("const BUILTIN = "))
    return json.loads(line[len("const BUILTIN = "):-2])


def read_pdf_text(path):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(path)
    return "\n".join((doc[i].get_textpage().get_text_bounded() or "") for i in range(len(doc)))


def clean_phrase(p):
    # ① 先把弯引号/省略号统一，否则 one’s 这类会被判成非英文字符
    p = p.replace("’", "'").replace("‘", "'").replace("“", " ").replace("”", " ")
    p = p.replace("…", " ")
    p = re.sub(r"\([^)]*$", " ", p)                          # 未闭合的左括号（原书截断处）
    p = re.sub(r"\(=[^)]*\)", " ", p)                        # (=gloss) 英文同义注释
    p = re.sub(r"\([A-Za-z][A-Za-z '\-]{0,16}\)", " ", p)    # (be) (a) (on) (or sb)
    p = re.sub(r"\s+'s\b", "'s", p)                          # one 's → one's
    p = re.sub(r"[^a-z' \-]", " ", p.lower())                # 兜底：只保留英文可查字符
    p = re.sub(r"\s+", " ", p).strip(" ,'-")
    return p


def clean_meaning(m):
    m = re.sub(r"\s+", " ", m).strip(" ,，;；")
    m = re.sub(r"\s+\d{1,3}$", "", m)          # 页脚页码窜进释义（如「内心深处,事实上 14」）
    m = re.sub(r"\([^)]*$", "", m).strip()     # 未闭合括号（原书截断处）
    return m


def parse(path):
    t = read_pdf_text(path).replace("\r", "")
    t = HEADER.sub(" ", t)
    t = PROMO.sub(" ", t)

    marks, expect = [], 1
    for m in re.finditer(r"(?<!\d)(\d{1,3})\s+(?=\S)", t):
        if int(m.group(1)) == expect:
            marks.append((expect, m.start(), m.end()))
            expect += 1

    rows, anomalies = [], []
    for i, (n, s, e) in enumerate(marks):
        end = marks[i + 1][1] if i + 1 < len(marks) else len(t)
        body = HEADER.sub(" ", t[e:end]).strip()
        hit = ZH.search(body)
        if not hit:
            anomalies.append((n, "无中文释义", body[:40]))
            continue
        rows.append({"no": n, "raw": body[:hit.start()].strip(), "meaning": body[hit.start():].strip()})
    return rows, anomalies, expect - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    B = load_builtin()
    rows, anomalies, n_seen = parse(SRC)
    print("PDF 顺序扫描到编号 1..%d，切出 %d 条" % (n_seen, len(rows)))

    merged, order, bad = {}, [], []
    for r in rows:
        key = clean_phrase(r["raw"])
        mean = clean_meaning(r["meaning"])
        if not KEY_OK.match(key):
            bad.append((r["no"], key, mean, "含非英文字符")); continue
        if " " not in key:
            bad.append((r["no"], key, mean, "清洗后成了单词，不是短语")); continue
        if len(key) < 4:
            bad.append((r["no"], key, mean, "太短")); continue
        if not mean:
            bad.append((r["no"], key, mean, "释义为空")); continue
        if key in merged:
            # 同短语两次出现、释义不同 → 合并而不是丢弃
            if mean not in merged[key]:
                merged[key] = merged[key] + "；" + mean
        else:
            merged[key] = mean
            order.append(key)

    n_exist = sum(1 for k in merged if k in B)
    print("清洗后唯一短语 %d 条；其中词典已有 %d 条，需新增 %d 条"
          % (len(merged), n_exist, len(merged) - n_exist))
    print("剔出异常 %d 条：" % len(bad))
    for x in bad[:10]:
        print("    #%-3d %-28s %s" % (x[0], x[1][:26], x[3]))

    if a.show:
        print()
        for k in order[:15]:
            print("  %-32s %s" % (k, merged[k][:30]))
        return 0

    payload = {
        "_meta": {
            "version": "2026-11-06.1",
            "source": SRC,
            "source_sha1": hashlib.sha1(io.open(SRC, "rb").read()).hexdigest()[:16],
            "n_source_entries": n_seen,
            "n_phrases": len(merged),
            "generator": "tools/exam_vocab/phrases.py",
            "note": "key 已去 (be)/(a)/(on) 等可选词与 (=gloss)；同短语多释义用；合并",
        },
        "phrases": {k: merged[k] for k in sorted(merged)},
    }
    io.open(os.path.join(OUT, "phrases.json"), "w", encoding="utf-8").write(
        json.dumps(payload, ensure_ascii=False, indent=1))

    io.open(os.path.join(OUT, "phrases_additions.json"), "w", encoding="utf-8").write(
        json.dumps({"_meta": {"n": len(merged) - n_exist,
                              "source_sha1": payload["_meta"]["source_sha1"]},
                    "additions": {k: {"meaning": v, "src": "phrase"} for k, v in sorted(merged.items())}},
                   ensure_ascii=False, indent=1))

    with io.open(os.path.join(OUT, "phrases_anomaly.tsv"), "w", encoding="utf-8") as f:
        f.write("no\tkey\tmeaning\treason\n")
        for n, k, m, why in bad:
            f.write("%d\t%s\t%s\t%s\n" % (n, k, m, why))

    print("产物 →", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
