#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""写回后的全套断言（A1–A14）

基线取 backups/20261105_examvocab/ 里的四份 .bak。

用法：
  python tools/exam_vocab/check_all.py --stage pre      # 写回前，只做只读体检
  python tools/exam_vocab/check_all.py --stage data     # 写完词库之后
  python tools/exam_vocab/check_all.py --stage builtin  # 写完 BUILTIN 之后
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))                    # 背词助手/
BASE = os.path.dirname(ROOT)                                     # wokBuddy/
HTML_MAIN = os.path.join(BASE, "outputs", "单词复习", "背词助手.html")
HTML_REPO = os.path.join(ROOT, "背词助手.html")
BJ = os.path.join(BASE, "outputs", "单词复习", "_builtin_dict.json")
DATA = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"
BAK = os.path.join(ROOT, "backups", "20261105_examvocab")      # 数据 JSON 基线
# HTML 基线要跟着每轮「非 BUILTIN 行」的修改前滚，否则 A1 的「只改 1 行」会失真。
# 2026-11-07 hints_confusable 把 HINT_SOUND 换成 HINT_FAM，基线前滚到这里。
BAK_HTML = os.path.join(ROOT, "backups", "20261114_prof")  # prof 机制轮次基线
EXAM_OV = os.path.join(ROOT, "docs", "exam_vocab", "exam_overrides.json")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import trim_exam_meaning as T                                    # noqa: E402

PROTECTED = (set(T.EXTRA_OVERRIDES) | set(T.BASE_OV)
             | {k for k, v in T.EXAM_OV.items() if v.get("status") == "approved"}
             | set(T.SYL_OV) | set(T.PH_OV))


def sha(p):
    return hashlib.sha256(io.open(p, "rb").read()).hexdigest()


def load_builtin(p):
    raw = io.open(p, "rb").read()
    txt = raw.decode("utf-8")
    lines = txt.split("\n")
    i = next(k for k, l in enumerate(lines) if l.startswith("const BUILTIN = "))
    D = json.loads(lines[i][len("const BUILTIN = "):-2])
    return raw, lines, i, D


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="pre", choices=["pre", "data", "builtin"])
    a = ap.parse_args()

    ok, fail = [], []

    def chk(code, cond, msg):
        (ok if cond else fail).append("%s %s" % (code, msg))

    raw, lines, idx, D = load_builtin(HTML_MAIN)
    braw, blines, bidx, BD = load_builtin(os.path.join(BAK_HTML, "背词助手.html.outputs.bak"))
    d = json.loads(io.open(DATA, encoding="utf-8").read())
    bd = json.loads(io.open(os.path.join(BAK, "背词助手数据.json.bak"), encoding="utf-8").read())
    ws = d["words"]

    # A2 条数
    chk("A2", len(D) == 21801, "BUILTIN 条数 %d（应 21801 = 21329 + 词纲 37 + 短语 435）" % len(D))
    # A3 往返
    js = json.dumps(D, ensure_ascii=False, separators=(",", ":"))
    chk("A3", json.loads(js) == D, "BUILTIN 往返序列化一致")
    # A4/A5 幂等
    a4 = [k for k, v in D.items() if T.normalize_line(v) != v]
    a5 = [k for k, v in D.items() if T.ensure_pos(k, v) != v]
    chk("A4", not a4, "normalize 偏移 %d %s" % (len(a4), a4[:3]))
    chk("A5", not a5, "ensurePos 偏移 %d %s" % (len(a5), a5[:3]))
    # A6 空释义
    empty = [k for k, v in D.items() if not str(v).strip()]
    fs_empty = [w["word"] for w in ws if not T.first_sense(w.get("meaning", ""))]
    chk("A6", not empty and not fs_empty,
        "空释义 %d / 314 词首义项为空 %d %s" % (len(empty), len(fs_empty), fs_empty[:5]))

    if a.stage == "pre":
        print("【pre】只读体检")
        print("BUILTIN %d 条，均长 %.1f，314 词释义与词典一致 %d/%d"
              % (len(D), sum(len(v) for v in D.values()) / len(D),
                 sum(1 for w in ws if D.get(w["word"].lower()) == w.get("meaning")), len(ws)))
        return 0

    if a.stage == "data":
        # A10 非释义字段不变
        bmap = {w["id"]: w for w in bd["words"]}
        bad = []
        for w in ws:
            o = bmap.get(w["id"])
            if not o:
                bad.append(w["word"])
                continue
            for k in ("word", "phonetic", "step", "nextDate", "lapse", "lastRated",
                      "timeMs", "needMean", "example", "exampleZh", "batch", "added"):
                if w.get(k) != o.get(k):
                    bad.append("%s.%s" % (w["word"], k))
        chk("A10", not bad, "非释义字段变化 %d 处 %s" % (len(bad), bad[:5]))
        # A11 updatedAt
        chk("A11", d.get("updatedAt", 0) > bd.get("updatedAt", 0)
            and abs(time.time() * 1000 - d.get("updatedAt", 0)) < 300000,
            "updatedAt %s（基线 %s）" % (d.get("updatedAt"), bd.get("updatedAt")))
        changed = [w["word"] for w in ws if bmap.get(w["id"], {}).get("meaning") != w.get("meaning")]
        chk("A14d", 0 < len(changed) <= 314, "词库改动 %d 条" % len(changed))
        print("词库改动 %d 条" % len(changed))

    if a.stage == "builtin":
        diff = sum(1 for x, y in zip(lines, blines) if x != y)
        # diff==0 = 本轮没动 HTML（如只跑体检）；>1 = 大面积重写，必须拦
        chk("A1", diff <= 1 and len(lines) == len(blines),
            "改动了 %d 行（应 ≤1），行数 %d→%d" % (diff, len(blines), len(lines)))
        chk("A7", abs(len(raw) - len(braw)) / max(1, len(braw)) < 0.03,
            "体积 %.1f%%（基线 %d）" % (abs(len(raw) - len(braw)) * 100.0 / max(1, len(braw)), len(braw)))
        chk("A8", sha(HTML_MAIN) == sha(HTML_REPO), "两份 HTML sha256 一致")
        try:
            J = json.loads(io.open(BJ, encoding="utf-8").read())
            chk("A9", J == D, "_builtin_dict.json 与 BUILTIN 相等")
        except Exception as e:
            chk("A9", False, "_builtin_dict.json 读取失败 %s" % e)
        bmap = {k: v for k, v in BD.items()}
        changed = [k for k in D if D[k] != bmap.get(k)]
        # A14b 只在「释义精简轮」有意义；纯加词条/改提示的轮次 changed 可能是 0，不应报错
        chk("A14b", len(changed) == 0 or 300 <= len(changed) <= 4400,
            "BUILTIN 改动 %d 条（精简轮应 300-4400；0 = 本轮未动释义）" % len(changed))
        print("BUILTIN 改动 %d 条" % len(changed))
        # A13 二次 trim 漂移
        drift = [k for k, v in D.items() if T.trim_meaning(v, k)[0] != v]
        extra = [k for k in drift if k not in PROTECTED]
        chk("A13", not extra, "二次 trim 漂移 %d 条，超出受保护集合 %d %s" % (len(drift), len(extra), extra[:5]))

    # A12 override 边界
    if os.path.exists(EXAM_OV):
        cfg = json.loads(io.open(EXAM_OV, encoding="utf-8").read())
        bad = [k for k, v in cfg["overrides"].items() if v.get("status") != "rejected" and int(v.get("df", 0)) < int(v.get("min_df", 2))]
        chk("A12", not bad, "df<min_df 仍生效 %d 条 %s" % (len(bad), bad[:5]))

    print("\n通过 %d 条：" % len(ok))
    for x in ok:
        print("  ✓ " + x)
    if fail:
        print("\n失败 %d 条：" % len(fail))
        for x in fail:
            print("  ✗ " + x)
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
