#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""形近词对比提示：从你自己的词库里找「必然混淆」的词组，写进背词助手

为什么用它替换谐音：
  谐音助记必须先把发音扭曲成中文、再把中文硬凑回词义，两步都在扭曲，
  所以天然容易牵强（receipt → "瑞西普特 → 结账撕下的一张小票"）。
  而 receipt 真正的难点是它跟 receive / receiver 长得像——这是客观事实，
  不需要编。本脚本就是把这种客观事实找出来。

找法（三条规则，命中任一即归为一组）：
  1. 公共前缀 ≥ 5        receipt / receive / receiver
  2. 一个词是另一个的前缀  appear / appearance、threat / threaten
  3. 编辑距离 ≤ 1        quite / quiet、loose / lose（如果词库里有的话）

用法：
  python tools/hints_confusable.py            # 生成 JSON 并预览分组
  python tools/hints_confusable.py --apply    # 写进背词助手.html（替换谐音层）
"""
import argparse
import io
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                                   # wokBuddy/
BASE = os.path.dirname(ROOT)
OUT_DIR = os.path.join(ROOT, "docs", "hints")
DATA = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"
HTML_MAIN = os.path.join(BASE, "outputs", "单词复习", "背词助手.html")


def lev(a, b):
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 1:
        return 2
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def build():
    d = json.loads(io.open(DATA, encoding="utf-8").read())
    words = {}
    for w in d["words"]:
        k = w["word"].strip().lower()
        words[k] = (w.get("meaning") or "").strip()

    ks = sorted(words)
    uf = UF()
    reasons = {}
    n = len(ks)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = ks[i], ks[j]
            # ① 公共前缀 ≥ 5
            if common_prefix(a, b) >= 5:
                uf.union(a, b); reasons[(a, b)] = "前缀"
            # ② 一个是另一个的前缀（短词 ≥ 4）
            elif (a.startswith(b) or b.startswith(a)) and min(len(a), len(b)) >= 4:
                uf.union(a, b); reasons[(a, b)] = "派生"
            # ③ 编辑距离 ≤ 1，且**首字母相同、长度相同**
            #    （adapt/adopt、great/greet、bald/bold 这种才是真形近；
            #     不加限制会把 cash/cast/clash/crash/dash/flash 押韵词串成一串）
            elif (min(len(a), len(b)) >= 4 and lev(a, b) <= 1
                  and a[0] == b[0] and len(a) == len(b)):
                uf.union(a, b); reasons[(a, b)] = "近形"

    fams = {}
    for k in ks:
        fams.setdefault(uf.find(k), []).append(k)
    fams = {k: sorted(v) for k, v in fams.items() if len(v) >= 2}
    return words, fams, reasons


def first_sense(meaning, limit=16):
    """取第一个词性的第一个义项，够对比就行，别把卡片撑爆"""
    m = re.split(r"[；;]", meaning or "")[0]
    m = re.sub(r"^[a-z]{1,6}\.\s*", "", m.strip())
    m = re.split(r"[,，]", m)[0].strip()
    return (m[:limit] + "…") if len(m) > limit else m


import re  # noqa: E402  (放后面是为了让上面的函数紧跟数据结构)


def build_hints(words, fams):
    """word -> [[其他词, 短释义], ...]（按字母序，排除自己）"""
    out = {}
    for _, members in fams.items():
        for w in members:
            others = [[o, first_sense(words[o])] for o in members if o != w]
            if others:
                out[w] = others
    return out


def preview(words, fams, hints):
    print("形近词组 %d 组，覆盖 %d / %d 个词（%.0f%%）\n"
          % (len(fams), len(hints), len(words), len(hints) * 100.0 / len(words)))
    for k in sorted(fams):
        members = fams[k]
        line = "  " + "  ".join("%s（%s）" % (m, first_sense(words[m])) for m in members)
        print(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    words, fams, _ = build()
    hints = build_hints(words, fams)
    preview(words, fams, hints)
    if not a.apply:
        print("\n（加 --apply 写进背词助手.html）")
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    io.open(os.path.join(OUT_DIR, "confusable.json"), "w", encoding="utf-8").write(
        json.dumps({"_meta": {"source": DATA, "n_groups": len(fams), "n_words": len(hints),
                              "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                    "hints": hints}, ensure_ascii=False, indent=1))

    raw = io.open(HTML_MAIN, "rb").read().decode("utf-8")
    lines = raw.split("\n")
    idx = next((i for i, l in enumerate(lines) if l.startswith("const HINT_SOUND = ")), None)
    if idx is None:
        print("HTML 里没找到 HINT_SOUND 行，未写入")
        return 1
    # 换变量名也换语义：HINT_FAM = 易混词族
    lines[idx] = "const HINT_FAM = " + json.dumps(hints, ensure_ascii=False, separators=(",", ":")) + ";"

    # hintBody 里的联想行换成易混行
    old = '  if (HINT_SOUND[k]) out.push(\'<div class="hint-line"><b>联想</b>\' + esc(HINT_SOUND[k]) + "</div>");'
    new = ('  if (HINT_FAM[k]) out.push(\'<div class="hint-line"><b>易混</b>\' + '
           'HINT_FAM[k].map(function (x) { return x[0] + "（" + esc(x[1]) + "）"; }).join(" · ") + "</div>");')
    hit = [i for i, l in enumerate(lines) if l.strip() == old.strip()]
    if not hit:
        print("HTML 里没找到联想行，未改渲染逻辑")
        return 1
    lines[hit[0]] = new

    out = "\n".join(lines)
    tmp = HTML_MAIN + ".tmp"
    io.open(tmp, "wb").write(out.encode("utf-8"))
    os.replace(tmp, HTML_MAIN)
    import shutil
    shutil.copyfile(HTML_MAIN, os.path.join(ROOT, "背词助手.html"))
    print("\n已写入：HINT_SOUND（38 条谐音）→ HINT_FAM（%d 词易混）" % len(hints))
    print("提醒：check_all 的 HTML 基线需要前滚到本次修改之后。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
