#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""专升本释义精简：每个词性只留 1–2 个常考义项

背景：内置词典 21329 条是 ECDICT 整条搬运（平均 22.7 字，最长 165 字），
      词库里 97 条还和原文一模一样。专升本只看常考义，多余义项是噪声。

做法：pre_normalize → parse_groups → select → render → post_normalize → ensure_pos
      前后各归一化一次，保证输出与页面里 normalizeMeaningLine 的规范完全一致
      （否则 cleanMeaning 每次载入都会再改一遍，文件就 drift 了）。

用法：
  python tools/trim_exam_meaning.py --report          # 只读，生成对照表
  python tools/trim_exam_meaning.py --verify          # 只读，幂等/一致性检查
  python tools/trim_exam_meaning.py --apply-data      # 写回词库 JSON
  python tools/trim_exam_meaning.py --apply-builtin   # 写回 HTML 内置词典

对照表输出到 docs/meaning_trim/
"""
import argparse
import ast
import csv
import io
import json
import os
import random
import re
import sys
import time

# ---------------------------------------------------------------- 路径

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)                       # 背词助手/
BASE = os.path.dirname(ROOT)                        # wokBuddy/
HTML_MAIN = os.path.join(BASE, "outputs", "单词复习", "背词助手.html")
HTML_REPO = os.path.join(ROOT, "背词助手.html")
BUILTIN_JSON = os.path.join(BASE, "outputs", "单词复习", "_builtin_dict.json")
DATA_JSON = "C:/Users/xuenc/Desktop/英语学习方法/studyEnglish/背词助手数据.json"
DOCS = os.path.join(ROOT, "docs", "meaning_trim")
OLD_TRIM = os.path.join(TOOLS, "trim_meanings.py")

# ---------------------------------------------------------------- 参数

MAX_SENSES_MAJOR = 2      # n / v / vt / vi / adj / adv
MAX_SENSES_MINOR = 1      # prep / conj / pron / num / art / int / pl / abbr / aux
MAX_POS_GROUPS = 3
MAX_CHARS = 36
RARE_ONLY_AFTER_FIRST = True   # 黑名单只对非首组生效（law 的「法律」在首位，永不被删）

# 词性组超过上限时，保留首组（决定 autoExample 的句型），其余按这个优先级留
POS_RANK = {"n": 0, "v": 1, "vt": 1, "vi": 2, "adj": 3, "adv": 4}

MAJOR = {"n", "v", "vt", "vi", "adj", "adv"}
CANON = {"a": "adj", "ad": "adv", "na": "n", "interj": "int", "vbl": "v",
         "vt": "vt", "vi": "vi"}

TECH = re.compile(r"DOS|批处理|命令行|内部命令|外部命令|寄存器|存储器|汇编|编译器|"
                  r"总线|母线|弥撒|圣歌|纹章|解剖|植物学|航海|军械")
MORPH = re.compile(r"的过去式|的过去分词|的复数|的现在分词|的第三人称|复数形式")

POS_LY_ADJ = set(("friendly lovely lively lonely likely deadly silly ugly early daily weekly "
                  "monthly yearly hourly costly orderly elderly heavenly earthly homely cowardly kindly manly "
                  "motherly fatherly brotherly sisterly bodily worldly timely comely stately leisurely").split())

# ---------------------------------------------------------------- 归一化（复刻 JS）

def normalize_line(line):
    """复刻 normalizeMeaningLine（背词助手.html L1334）。"""
    t = str(line or "")
    t = re.sub(r"(^|[；;，,]\s*)a\.(?=\s|$|[^\x00-\x7F])", r"\g<1>adj.", t)
    t = re.sub(r"(^|[；;，,]\s*)ad\.(?=\s|$|[^\x00-\x7F])", r"\g<1>adv.", t)
    t = re.sub(r"[;,，](?=\s*[a-z]{1,6}\.\s)", "；", t)
    t = re.sub(r"([\u4e00-\u9fa5])\s+(n|vt|vi|v|adj|adv|prep|conj|pron|num|int|art|abbr)\.\s",
               r"\g<1>；\g<2>. ", t)
    t = re.sub(r"\s+", " ", t).strip()

    parts = [p.strip() for p in t.split("；") if p.strip()]
    seen_core, seen_pair, out = set(), set(), []
    for p in parts:
        m = re.match(r"^([a-z]{1,6})\.\s*(.*)$", p, re.I)
        if m:
            pos, core = m.group(1).lower(), m.group(2).strip()
            if not core:
                continue
            pair = pos + "|" + core
            if pair in seen_pair:
                continue
            seen_pair.add(pair)
            seen_core.add(core)
            out.append(p)
        else:
            core = p.strip()
            if not core or core in seen_core:
                continue
            seen_core.add(core)
            out.append(p)
    return "；".join(out)


def ensure_pos(word, meaning):
    """复刻 ensurePos（L1380）：无词性时按词尾补一个高置信度的。"""
    m = str(meaning or "").strip()
    if not m:
        return m
    if re.match(r"^[a-z]{1,6}\.\s", m, re.I):
        return m
    if re.match(r"^(pl|interj|aux|abbr|phr)\.\s?", m, re.I):
        return m
    k = str(word or "").lower()
    if not re.match(r"^[a-z][a-z'-]*$", k):
        return m
    if re.search(r"(tion|sion|ment|ness|ity|ance|ence|ship|hood|ism)$", k):
        return "n. " + m
    if re.search(r"(ous|ful|less|able|ible|ive|ical|ic)$", k):
        return "adj. " + m
    if re.search(r"(ize|ise|ify)$", k):
        return "v. " + m
    if k.endswith("ly") and k not in POS_LY_ADJ:
        return "adv. " + m
    return m


# ---------------------------------------------------------------- 解析 / 选取 / 渲染

POS_RE = re.compile(r"^([a-z]{1,6})\.\s*(.*)$", re.I)


def split_senses(body):
    body = re.sub(r",\s*(?=(?:vt|vi|v|n|adj|adv|prep|conj|pron|num|art|int|abbr)\.\s)", "；", body)
    parts = re.split(r"[,，、]", body)
    out = []
    for p in parts:
        p = p.strip().strip("。")
        if p:
            out.append(p)
    return out


def parse_groups(s):
    groups = []
    for g in re.split(r"[；;]", s):
        g = g.strip()
        if not g:
            continue
        # vt.& vi. / vt.vi. → v.
        g2 = re.sub(r"^vt\.\s*(?:&\s*)?vi\.\s*", "v. ", g, flags=re.I)
        m = POS_RE.match(g2)
        if m:
            pos = CANON.get(m.group(1).lower(), m.group(1).lower())
            body = re.sub(r"^(?:&\s*)?(vt|vi|v)\.\s*", "", m.group(2).strip())
            groups.append({"pos": pos, "senses": split_senses(body), "bare": False, "raw": g})
        else:
            groups.append({"pos": None, "senses": split_senses(g), "bare": True, "raw": g})
    return groups


def select(groups):
    out, dropped = [], []

    for gi, g in enumerate(groups):
        if g["bare"]:
            if gi == 0:
                senses = []
                for s in g["senses"]:
                    if len(senses) >= MAX_SENSES_MAJOR:
                        break
                    if s.lower() in {x.lower() for x in senses}:
                        continue
                    senses.append(s)
                if senses:
                    out.append({"pos": None, "senses": senses})
            else:
                dropped.append({"group": g, "reason": "裸尾"})
            continue

        limit = MAX_SENSES_MAJOR if g["pos"] in MAJOR else MAX_SENSES_MINOR
        senses, local = [], set()
        for s in g["senses"]:
            if len(senses) >= limit:
                dropped.append({"group": g, "sense": s, "reason": "义项超限"})
                continue
            if RARE_ONLY_AFTER_FIRST and gi > 0 and TECH.search(s):
                dropped.append({"group": g, "sense": s, "reason": "专业义"})
                continue
            if RARE_ONLY_AFTER_FIRST and gi > 0 and MORPH.search(s):
                dropped.append({"group": g, "sense": s, "reason": "词形说明"})
                continue
            # 只在同一词性组内去重。跨词性去重会把 wear/sweep 的核心义项当成
            # 「已在名词组出现过」而跳过，结果 vt 只剩「留(须、发等)」这种冷僻义。
            if s.lower() in local:
                dropped.append({"group": g, "sense": s, "reason": "同组重复"})
                continue
            senses.append(s)
            local.add(s.lower())

        # 整组被删空：只有「词形说明」才回退保留（led = 的过去式），
        # 专业义（gradual 的「弥撒升阶圣歌」）删空就删空，别捡回来。
        if not senses and g["senses"]:
            reasons = {d.get("reason") for d in dropped if d.get("group") is g}
            if reasons and reasons <= {"词形说明"}:
                senses = g["senses"][:1]
                dropped = [d for d in dropped if d.get("group") is not g]

        if senses:
            out.append({"pos": g["pos"], "senses": senses, "orig": gi})

    # 词性组超上限：首组固定（它决定 autoExample 的句型），其余按 POS_RANK 优先
    if len(out) > MAX_POS_GROUPS:
        head, rest = out[:1], out[1:]
        rest.sort(key=lambda x: (POS_RANK.get(x["pos"], 5), x["orig"]))
        for g in rest[MAX_POS_GROUPS - 1:]:
            dropped.append({"group": {"pos": g["pos"], "senses": g["senses"]}, "reason": "词性组超 3"})
        out = head + rest[:MAX_POS_GROUPS - 1]

    return out, dropped


def render(groups):
    parts = []
    for g in groups:
        body = ", ".join(g["senses"])
        parts.append(((g["pos"] + ". ") if g["pos"] else "") + body)
    while len("；".join(parts)) > MAX_CHARS and len(parts) > 1:
        parts.pop()
    return "；".join(parts)


def trim_meaning(s, word=""):
    n = normalize_line(s)
    sel, dropped = select(parse_groups(n))
    out = normalize_line(render(sel))
    return ensure_pos(word, out), dropped


def first_sense(m):
    s = re.sub(r"^[a-z]{1,4}\.\s*", "", str(m or ""), flags=re.I)
    s = re.split(r"[；;,，。（(]", s)[0].strip()
    return re.sub(r"[的地]$", "", s)


# ---------------------------------------------------------------- 数据装载

def load_builtin(path):
    raw = io.open(path, "rb").read()
    txt = raw.decode("utf-8")
    lines = txt.split("\n")
    idx = next(i for i, l in enumerate(lines) if l.startswith("const BUILTIN = "))
    line = lines[idx]
    prefix = "const BUILTIN = "
    assert line.startswith(prefix + "{"), "BUILTIN 行开头不符"
    assert line.endswith("};\r"), "BUILTIN 行结尾不符（应为 };\\r）"
    js = line[len(prefix):-2]
    D = json.loads(js)
    assert json.dumps(D, ensure_ascii=False, separators=(",", ":")) == js, "BUILTIN 往返序列化不一致"
    return raw, txt, lines, idx, D


def load_base_overrides():
    """从 trim_meanings.py 里读出 133 条人工映射，作为 OVERRIDES_BASE。"""
    if not os.path.exists(OLD_TRIM):
        return {}
    src = io.open(OLD_TRIM, encoding="utf-8").read()
    m = re.search(r"^S\s*=\s*(\{)", src, re.M)
    if not m:
        return {}
    start = m.start(1)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return ast.literal_eval(src[start:i + 1])
                except Exception:
                    return {}
    return {}


def load_story_words():
    p = os.path.join(BASE, "outputs", "单词复习", "_story_hint.json")
    if not os.path.exists(p):
        return set()
    try:
        c = json.loads(io.open(p, encoding="utf-8").read())
        out = set()
        for st in c.get("stories", []):
            for w in st.get("words", []):
                out.add(w.lower())
        return out
    except Exception:
        return set()


BASE_OV = load_base_overrides()
STORY_WORDS = load_story_words()

# 高频多义词：ECDICT 的首位义项本身冷僻（set=日落、mean=低劣的、take=吃掉对方棋子），
# 位置规则治不了，只能人工拍平。覆盖范围只挑「考试一定考、而且规则会答错」的词。
EXTRA_OVERRIDES = {
    "set":        "v. 放, 设置；n. 一套, 集合",
    "mean":       "v. 意思是, 意味着；adj. 吝啬的, 刻薄的",
    "take":       "vt. 拿, 拿走, 花费",
    "fine":       "adj. 好的, 晴朗的；n. 罚款",
    "right":      "adj. 正确的, 右边的；n. 权利",
    "light":      "n. 光, 灯；adj. 轻的",
    "well":       "adv. 好地；adj. 健康的",
    "like":       "v. 喜欢；prep. 像",
    "last":       "adj. 最后的；v. 持续",
    "present":    "adj. 出席的, 现在的；n. 礼物",
    "order":      "n. 顺序, 命令；v. 命令, 订购",
    "matter":     "n. 事情, 物质；v. 要紧",
    "book":       "n. 书；v. 预订",
    "spring":     "n. 春天, 泉水；v. 跳",
    "bear":       "v. 忍受, 承受；n. 熊",
    "great":      "adj. 伟大的, 极好的",
    "appearance": "n. 出现, 外观, 外表",
    "justice":    "n. 正义, 公平；司法",
    "widespread": "adj. 广泛的, 普遍的",
    "width":      "n. 宽度, 宽阔",
    "poor":       "adj. 贫穷的, 可怜的",
    "up-to-date": "adj. 最新的, 现代的",
    "boil":       "v. 煮沸, 沸腾",
    "receipt":    "n. 收据, 收到",
    "ache":       "n. 疼痛；vi. 疼",
}


# ---------------------------------------------------------------- 真题 override 层
# 来源：tools/exam_vocab/build_overrides.py（从河南专升本真题语料裁决得出）
# 优先级：用户确认 > exam approved > EXTRA > BASE > exam auto > 规则
# 三道护栏防"草稿被当确认值"：
#   1. 生成只写 exam_overrides.new.json，--promote 才改名
#   2. _meta.corpus_sha1 与当前语料不符 → 整体失效
#   3. status == rejected 粘性跳过
EXAM_DIR = os.path.join(ROOT, "docs", "exam_vocab")
EXAM_OV_PATH = os.path.join(EXAM_DIR, "exam_overrides.json")
EXAM_CORPUS = os.path.join(EXAM_DIR, "corpus", "pages.jsonl")


def _corpus_sha1():
    if not os.path.exists(EXAM_CORPUS):
        return ""
    import hashlib
    return hashlib.sha1(io.open(EXAM_CORPUS, "rb").read()).hexdigest()[:16]


def load_exam_overrides():
    if not os.path.exists(EXAM_OV_PATH):
        return {}, {}
    try:
        cfg = json.loads(io.open(EXAM_OV_PATH, encoding="utf-8").read())
    except Exception as e:
        print("[WARN] exam_overrides.json 解析失败（%s），按空处理" % e)
        return {}, {}
    meta = cfg.get("_meta", {})
    want = meta.get("corpus_sha1")
    if want and want != _corpus_sha1():
        print("[WARN] exam_overrides 与当前语料不一致（%s != %s），整体失效" % (want, _corpus_sha1()))
        return meta, {}
    ov = {}
    for k, v in (cfg.get("overrides") or {}).items():
        if v.get("status") == "rejected":
            continue
        ov[str(k).strip().lower()] = v
    return meta, ov


EXAM_META, EXAM_OV = load_exam_overrides()

# ---------------------------------------------------------------- 词纲 override 层
# 来源：tools/exam_vocab/syllabus.py（专升本 3716 词纲，口径「词纲为主、词典补空缺」）
# 优先级：高于 EXAM auto 与规则，低于 BASE/EXTRA（那两者是人工修 ECDICT 首义项偏移的产物）
# 护栏：_meta.source_sha1 与当前词纲源不符 → 整层失效
SYL_DIR = os.path.join(EXAM_DIR, "syllabus")
SYL_OV_PATH = os.path.join(SYL_DIR, "syllabus_overrides.json")
SYL_ADD_PATH = os.path.join(SYL_DIR, "syllabus_additions.json")
SYL_SRC = "C:/Users/xuenc/Desktop/DSHworkarou/work/words.json"


def _syl_sha1():
    if not os.path.exists(SYL_SRC):
        return ""
    import hashlib
    return hashlib.sha1(io.open(SYL_SRC, "rb").read()).hexdigest()[:16]


def load_syllabus():
    """返回 (meta, 释义字典, 新增词条集合)。"""
    if not os.path.exists(SYL_OV_PATH):
        return {}, {}, set()
    try:
        cfg = json.loads(io.open(SYL_OV_PATH, encoding="utf-8").read())
    except Exception as e:
        print("[WARN] syllabus_overrides.json 解析失败（%s），按空处理" % e)
        return {}, {}, set()
    meta = cfg.get("_meta", {})
    want = meta.get("source_sha1")
    if want and _syl_sha1() and want != _syl_sha1():
        print("[WARN] 词纲 override 与当前词纲源不一致（%s != %s），整体失效" % (want, _syl_sha1()))
        return meta, {}, set()
    # 源文件已移走/删除时不失效：override 是从源生成的成品，数据本身仍然有效
    ov = {k: v for k, v in (cfg.get("overrides") or {}).items() if v.get("meaning")}
    add = set()
    if os.path.exists(SYL_ADD_PATH):
        try:
            ac = json.loads(io.open(SYL_ADD_PATH, encoding="utf-8").read())
            for k, v in (ac.get("additions") or {}).items():
                if v.get("meaning"):
                    ov[k] = v
                    add.add(k)
        except Exception as e:
            print("[WARN] syllabus_additions.json 解析失败（%s）" % e)
    return meta, ov, add


SYL_META, SYL_OV, SYL_NEW = load_syllabus()

# ---------------------------------------------------------------- 短语层
# 来源：tools/exam_vocab/phrases.py（《河南专升本英语短语常备 465 组》）
# 内置词典原本一条短语都没有，而考纲明写「短语搭配」是直接考查内容。
PH_DIR = os.path.join(EXAM_DIR, "phrases")
PH_PATH = os.path.join(PH_DIR, "phrases_additions.json")
PH_SRC = "C:/Users/xuenc/Desktop/26河南专升本电子版赠品/河南专升本英语短语常备465组.pdf"


def _ph_sha1():
    if not os.path.exists(PH_SRC):
        return ""
    import hashlib
    return hashlib.sha1(io.open(PH_SRC, "rb").read()).hexdigest()[:16]


def load_phrases():
    if not os.path.exists(PH_PATH):
        return {}, {}, set()
    try:
        cfg = json.loads(io.open(PH_PATH, encoding="utf-8").read())
    except Exception as e:
        print("[WARN] phrases_additions.json 解析失败（%s），按空处理" % e)
        return {}, {}, set()
    meta = cfg.get("_meta", {})
    want = meta.get("source_sha1")
    if want and _ph_sha1() and want != _ph_sha1():
        print("[WARN] 短语层与源 PDF 不一致（%s != %s），整体失效" % (want, _ph_sha1()))
        return meta, {}, set()
    # 源 PDF 已删时不失效：短语已经在词典里，层只是保护它们不被规则改写
    ov, new = {}, set()
    for k, v in (cfg.get("additions") or {}).items():
        m = (v.get("meaning") or "").strip()
        if m:
            ov[k] = m
            new.add(k)
    return meta, ov, new


PH_META, PH_OV, PH_NEW = load_phrases()




def _exam_ok(k, e):
    """条目级边界：频次不达标不生效。"""
    try:
        if int(e.get("df", 0)) < int(e.get("min_df", 2)):
            return None
    except Exception:
        return None
    s = str(e.get("meaning", "")).strip()
    return normalize_line(s) if s else None


def final_meaning(k, v, user_ov):
    if k in user_ov:
        return normalize_line(user_ov[k]), []
    e = EXAM_OV.get(k)
    if e and e.get("status") == "approved":
        m = _exam_ok(k, e)
        return (m, []) if m else trim_meaning(v, k)
    if k in EXTRA_OVERRIDES:
        return normalize_line(EXTRA_OVERRIDES[k]), []
    if k in BASE_OV:
        return normalize_line(BASE_OV[k]), []
    sy = SYL_OV.get(k)
    if sy:
        m = str(sy.get("meaning", "")).strip()
        return (normalize_line(m), []) if m else trim_meaning(v, k)
    ph = PH_OV.get(k)
    if ph:
        return normalize_line(ph), []
    if e and e.get("status") == "auto":
        m = _exam_ok(k, e)
        return (m, []) if m else trim_meaning(v, k)
    return trim_meaning(v, k)


# ---------------------------------------------------------------- 报告

def md_escape(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_stats(D, data, user_ov):
    new = {k: final_meaning(k, v, user_ov)[0] for k, v in D.items()}
    changed = [k for k in D if new[k] != D[k]]
    lens_o = [len(v) for v in D.values()]
    lens_n = [len(new[k]) for k in D]
    risks = [k for k in D if len(D[k]) > 40 and len(new[k]) < 12]
    long_new = [k for k in D if len(new[k]) >= 30]
    short_new = [k for k in D if len(new[k]) <= 8]

    dw = [w for w in data["words"]]
    w_new = {w["word"].lower(): final_meaning(w["word"].lower(), w.get("meaning", ""), user_ov)[0] for w in dw}
    w_changed = [w for w in dw if w_new[w["word"].lower()] != w.get("meaning", "")]
    fs_o = sum(1 for w in dw if not first_sense(w.get("meaning", "")))
    fs_n = sum(1 for w in dw if not first_sense(w_new[w["word"].lower()]))

    L = []
    L.append("# 释义精简 · 统计摘要\n")
    L.append("> 只读生成，未写回任何数据。写回前请先看 `01_词库对照.md` 与 `02_内置抽样.md`。\n")
    L.append("## 内置词典 BUILTIN（%d 条）\n" % len(D))
    L.append("| 指标 | 精简前 | 精简后 |")
    L.append("|---|---|---|")
    L.append("| 总字数 | %d | %d |" % (sum(lens_o), sum(lens_n)))
    L.append("| 平均 | %.1f | %.1f |" % (sum(lens_o) / len(lens_o), sum(lens_n) / len(lens_n)))
    L.append("| 中位 | %d | %d |" % (sorted(lens_o)[len(lens_o) // 2], sorted(lens_n)[len(lens_n) // 2]))
    L.append("| 最长 | %d | %d |" % (max(lens_o), max(lens_n)))
    L.append("| 变化条目 | — | %d（%.1f%%）|" % (len(changed), len(changed) * 100.0 / len(D)))
    L.append("")
    L.append("## 词库（%d 词）\n" % len(dw))
    L.append("| 指标 | 精简前 | 精简后 |")
    L.append("|---|---|---|")
    L.append("| 总字数 | %d | %d |" % (sum(len(w.get("meaning", "")) for w in dw),
                                     sum(len(w_new[w["word"].lower()]) for w in dw)))
    L.append("| 变化条目 | — | %d |" % len(w_changed))
    L.append("| 首义项取不到（例句会空） | %d | %d |" % (fs_o, fs_n))
    L.append("")
    L.append("## 风险清单（全量见 02_ / 05_）\n")
    L.append("| 类型 | 条数 |")
    L.append("|---|---|")
    L.append("| 原长>40 且 新<12（可能压过头） | %d |" % len(risks))
    L.append("| 新释义 ≥30 字 | %d |" % len(long_new))
    L.append("| 新释义 ≤8 字 | %d |" % len(short_new))
    L.append("")
    L.append("## 抽样 10 条\n")
    L.append("| 词 | 原 | 新 |")
    L.append("|---|---|---|")
    rnd = random.Random(20261105)
    for k in rnd.sample(list(D), 10):
        L.append("| %s | %s | %s |" % (k, md_escape(D[k]), md_escape(new[k])))
    L.append("")
    L.append("## override\n")
    L.append("- 内置映射（旧 `trim_meanings.py`）：%d 条" % len(BASE_OV))
    L.append("- 用户确认表：%d 条" % len(user_ov))
    L.append("")
    io.open(os.path.join(DOCS, "00_统计摘要.md"), "w", encoding="utf-8").write("\n".join(L))
    return new, changed


def write_word_diff(data, user_ov):
    rows = []
    for w in data["words"]:
        k = w["word"].strip().lower()
        orig = w.get("meaning", "")
        new, dropped = final_meaning(k, orig, user_ov)
        if new == orig:
            continue
        lost = len({d["group"]["pos"] for d in dropped if d.get("group", {}).get("pos")})
        warn = []
        # 只标真正需要人看的：压太短、删了专业义、故事里出现过、原长被压得狠。
        # 「丢词性」几乎每条多词性词都会命中，标了反而没人看，只留在「丢组」列里。
        if len(new) <= 8:
            warn.append("过短")
        if any(d.get("reason") == "专业义" for d in dropped):
            warn.append("删专业义")
        if k in STORY_WORDS:
            warn.append("故事词")
        if len(orig) >= 40 and len(new) <= 15:
            warn.append("压得狠")
        rows.append({"k": k, "orig": orig, "new": new, "lost": lost,
                     "save": len(orig) - len(new), "warn": warn})

    rows.sort(key=lambda r: (r["save"], r["lost"]), reverse=True)
    L = ["# 词库对照（%d 词，只列有变化的 %d 条）\n" % (len(data["words"]), len(rows)),
         "> 裁决列填 `□退` 表示这条保留原释义。改完把 `04_overrides_draft.json` 复制成 "
         "`04_overrides.json` 并把我标 `□退` 的词改成原释义即可。\n",
         "| # | 单词 | 原→新(字) | 丢组 | 原释义 | 新释义 | 裁决 |",
         "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows, 1):
        flag = (" ⚠" + "/".join(r["warn"])) if r["warn"] else ""
        L.append("| %d | %s%s | %d→%d | %d | %s | %s | □收 |" % (
            i, r["k"], flag, len(r["orig"]), len(r["new"]), r["lost"],
            md_escape(r["orig"]), md_escape(r["new"])))
    L.append("")
    io.open(os.path.join(DOCS, "01_词库对照.md"), "w", encoding="utf-8").write("\n".join(L))
    return rows


def write_builtin_sample(D, user_ov):
    new = {k: final_meaning(k, v, user_ov)[0] for k, v in D.items()}
    layers = [
        ("L1 原长 > 40（压得够不够）", lambda v: len(v) > 40),
        ("L2 原长 31–40", lambda v: 31 <= len(v) <= 40),
        ("L3 原长 21–30", lambda v: 21 <= len(v) <= 30),
        ("L4 原长 ≤ 20（有没有压过头）", lambda v: len(v) <= 20),
    ]
    L = ["# 内置词典抽样（各层 50 条，seed=20261105）\n",
         "> 只读抽样，全量在 `03_内置全量.csv`。\n"]
    rnd = random.Random(20261105)
    for title, cond in layers:
        pool = [k for k, v in D.items() if cond(v)]
        pick = rnd.sample(pool, min(50, len(pool)))
        L.append("## %s（共 %d 条，抽 %d）\n" % (title, len(pool), len(pick)))
        L.append("| 词 | 原 | 新 |")
        L.append("|---|---|---|")
        for k in pick:
            L.append("| %s | %s | %s |" % (k, md_escape(D[k]), md_escape(new[k])))
        L.append("")

    risks = [k for k in D if len(D[k]) > 40 and len(new[k]) < 12]
    L.append("## 风险：原长>40 且 新<12（%d 条）\n" % len(risks))
    L.append("| 词 | 原 | 新 |")
    L.append("|---|---|---|")
    for k in risks:
        L.append("| %s | %s | %s |" % (k, md_escape(D[k]), md_escape(new[k])))
    L.append("")
    io.open(os.path.join(DOCS, "02_内置抽样.md"), "w", encoding="utf-8").write("\n".join(L))


def write_builtin_csv(D, user_ov):
    p = os.path.join(DOCS, "03_内置全量.csv")
    with io.open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["word", "orig_len", "new_len", "orig", "new"])
        for k, v in D.items():
            n = final_meaning(k, v, user_ov)[0]
            w.writerow([k, len(v), len(n), v, n])


def write_overrides_draft(data, user_ov):
    draft = {}
    for w in data["words"]:
        k = w["word"].strip().lower()
        draft[k] = final_meaning(k, w.get("meaning", ""), user_ov)[0]
    p = os.path.join(DOCS, "04_overrides_draft.json")
    io.open(p, "w", encoding="utf-8").write(json.dumps(draft, ensure_ascii=False, indent=1))
    return draft


def write_blacklist(D, user_ov):
    rows = []
    for k, v in D.items():
        _, dropped = final_meaning(k, v, user_ov)
        for d in dropped:
            if d.get("reason") in ("专业义", "词形说明"):
                rows.append((k, d.get("sense", ""), d["reason"], v))
    L = ["# 黑名单命中（%d 条）\n" % len(rows),
         "> 这些义项被规则判为专业义/词形说明而删除。若认为误删，在 "
         "`04_overrides.json` 里给该词指定完整释义。\n",
         "| 词 | 被删义项 | 原因 | 原释义 |", "|---|---|---|---|"]
    for k, s, r, v in rows:
        L.append("| %s | %s | %s | %s |" % (k, md_escape(s), r, md_escape(v)))
    L.append("")
    io.open(os.path.join(DOCS, "05_黑名单命中.md"), "w", encoding="utf-8").write("\n".join(L))


def report():
    os.makedirs(DOCS, exist_ok=True)
    _, _, _, _, D = load_builtin(HTML_MAIN)
    data = json.loads(io.open(DATA_JSON, encoding="utf-8").read())
    user_ov = load_user_overrides(include_draft=False)

    new, changed = write_stats(D, data, user_ov)
    wdiff = write_word_diff(data, user_ov)
    write_builtin_sample(D, user_ov)
    write_builtin_csv(D, user_ov)
    draft = write_overrides_draft(data, user_ov)
    write_blacklist(D, user_ov)

    # 内部幂等自检（不依赖浏览器）
    drift = sum(1 for k, v in new.items() if normalize_line(v) != v)
    drift2 = sum(1 for k, v in new.items() if ensure_pos(k, v) != v)
    print("内置 %d 条，变化 %d 条（%.1f%%）" % (len(D), len(changed), len(changed) * 100.0 / len(D)))
    print("词库 %d 词，有变化 %d 条，override 草稿 %d 条" % (len(data["words"]), len(wdiff), len(draft)))
    print("内置自检：normalize 偏移 %d，ensurePos 偏移 %d（都应为 0）" % (drift, drift2))
    print("报表已写入 %s" % DOCS)


# ---------------------------------------------------------------- 写回

def load_user_overrides(include_draft=False):
    """用户确认表。报告阶段不能读 draft —— 否则上一次生成的草稿会被当成
    人工确认值，把新规则的结果反向锁死（踩过一次）。"""
    names = ("04_overrides.json", "04_overrides_draft.json") if include_draft else ("04_overrides.json",)
    for name in names:
        p = os.path.join(DOCS, name)
        if os.path.exists(p):
            try:
                d = json.loads(io.open(p, encoding="utf-8").read())
                return {str(k).strip().lower(): v for k, v in d.items()}
            except Exception:
                pass
    return {}


def apply_data():
    data = json.loads(io.open(DATA_JSON, encoding="utf-8").read())
    user_ov = load_user_overrides(include_draft=True)
    n = 0
    for w in data["words"]:
        k = w["word"].strip().lower()
        new, _ = final_meaning(k, w.get("meaning", ""), user_ov)
        if new != w.get("meaning", ""):
            w["meaning"] = new
            n += 1
    data["updatedAt"] = int(time.time() * 1000)
    tmp = DATA_JSON + ".tmp"
    io.open(tmp, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, DATA_JSON)
    print("词库写回 %d 条，updatedAt=%d" % (n, data["updatedAt"]))


def with_syllabus_new(D):
    """词纲/短语里新增的条目，先并进来再统一计算。"""
    D2 = dict(D)
    for k in list(SYL_NEW) + list(PH_NEW):
        if k not in D2:
            D2[k] = ""
    return D2


def apply_builtin():
    raw, txt, lines, idx, D = load_builtin(HTML_MAIN)
    user_ov = load_user_overrides(include_draft=True)
    D = with_syllabus_new(D)
    D2 = {k: final_meaning(k, v, user_ov)[0] for k, v in D.items()}
    new_js = json.dumps(D2, ensure_ascii=False, separators=(",", ":"))
    lines[idx] = "const BUILTIN = " + new_js + ";\r"
    out = "\n".join(lines)

    assert len(lines) == len(txt.split("\n")), "行数变了"
    assert sum(1 for a, b in zip(lines, txt.split("\n")) if a != b) == 1, "改了不止一行"

    tmp = HTML_MAIN + ".tmp"
    io.open(tmp, "wb").write(out.encode("utf-8"))
    os.replace(tmp, HTML_MAIN)

    # 仓库副本：直接复制主程序字节
    import shutil
    shutil.copyfile(HTML_MAIN, HTML_REPO)

    # JSON 副本从 D2 派生
    io.open(BUILTIN_JSON, "w", encoding="utf-8").write(json.dumps(D2, ensure_ascii=False))
    print("BUILTIN 写回 %d 条；已同步仓库副本与 _builtin_dict.json" % len(D2))


def verify():
    _, _, _, _, D = load_builtin(HTML_MAIN)
    D = with_syllabus_new(D)
    user_ov = load_user_overrides(include_draft=True)
    new = {k: final_meaning(k, v, user_ov)[0] for k, v in D.items()}
    a = [k for k in new if normalize_line(new[k]) != new[k]]
    b = [k for k in new if ensure_pos(k, new[k]) != new[k]]
    empty = [k for k in new if not new[k].strip()]
    print("条数 %d" % len(D))
    print("normalize 偏移 %d %s" % (len(a), a[:5]))
    print("ensurePos 偏移 %d %s" % (len(b), b[:5]))
    print("空释义 %d %s" % (len(empty), empty[:5]))
    return 0 if not (a or b or empty) else 1


# ---------------------------------------------------------------- CLI

def exam_stats():
    """各层实际生效条数，用来验证优先级真的按设计走。"""
    _, _, _, _, D = load_builtin(HTML_MAIN)
    data = json.loads(io.open(DATA_JSON, encoding="utf-8").read())
    user_ov = load_user_overrides(include_draft=True)
    keys = set(D) | {w["word"].strip().lower() for w in data["words"]}
    from collections import Counter
    c = Counter()
    for k in keys:
        if k in user_ov:
            c["1 用户确认"] += 1
        elif EXAM_OV.get(k, {}).get("status") == "approved":
            c["2 exam approved"] += 1
        elif k in EXTRA_OVERRIDES:
            c["3 EXTRA"] += 1
        elif k in BASE_OV:
            c["4 BASE"] += 1
        elif k in SYL_OV:
            c["5 词纲"] += 1
        elif EXAM_OV.get(k, {}).get("status") == "auto":
            c["6 exam auto"] += 1
        else:
            c["7 规则"] += 1
    print("exam_overrides: %d 条（meta: %s）"
          % (len(EXAM_OV), json.dumps(EXAM_META, ensure_ascii=False)[:120] if EXAM_META else "无"))
    for k in sorted(c):
        print("  %-16s %d" % (k, c[k]))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--apply-data", action="store_true")
    ap.add_argument("--apply-builtin", action="store_true")
    ap.add_argument("--exam-stats", action="store_true")
    ap.add_argument("--syllabus-stats", action="store_true")
    ap.add_argument("--phrase-stats", action="store_true")
    a = ap.parse_args()
    if a.phrase_stats:
        print("短语层：%d 条（%s）" % (len(PH_OV), json.dumps(PH_META, ensure_ascii=False)[:100]))
        return 0
    if a.syllabus_stats:
        print("syllabus_overrides: %d 条 + 新增 %d 条（%s）"
              % (len(SYL_OV) - len(SYL_NEW), len(SYL_NEW),
                 json.dumps(SYL_META, ensure_ascii=False)[:110] if SYL_META else "无"))
        return 0
    if a.exam_stats:
        return exam_stats()
    if a.apply_builtin:
        return apply_builtin()
    if a.apply_data:
        return apply_data()
    if a.verify:
        return verify()
    report()
    return 0


if __name__ == "__main__":
    sys.exit(main())
