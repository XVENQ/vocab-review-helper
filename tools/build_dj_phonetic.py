# -*- coding: utf-8 -*-
"""用 CMUdict(ARPAbet) + 规则生成 DJ（英式）音标。

前置文件（放在仓库根目录）：
  cmudict.dict          CMU 发音词典，https://github.com/cmusphinx/cmudict
  phonetic_us_old.json  旧的美式音标表（作为 CMU 未覆盖词的兜底），可由 ECDICT 音标字段生成

产出：
  phonetic_dj.json      单词 -> 不带斜杠的 DJ 音标串

用法：python tools/build_dj_phonetic.py
"""
import json, re, sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = ROOT + os.sep

# ---------------- 词表：靠拼写才能判的分化 ----------------
# bath 分裂：AmE æ → BrE ɑː
BATH = set("""
after afternoon afterward ask answer basket basketball bath bathe bathroom brass
branch can't cast castle chance class classroom contrast dance demand advance
advantage disadvantage disadvantages example fast fasten father glance glass grass grasp half halves last
lastly laugh laughter mask master nasty pass passage past path plant rather
sample staff task vast
""".split())

# thought 类里英音读短 ɒ 的（其余 AO 走 ɔː）
O_SHORT = set("""
dog dogs long song songs wrong strong off soft lost cost costs cross across
boss loss cloth clothes coffee office officer often gone doll log logs fog frog
borrow sorry tomorrow sorrow orange forest foreign quality quantity holiday
holidays wash watch what cough trough knowledge acknowledge
""".split())

# father 类：AA 在英音是长 ɑː（不是 ɒ）
FATHER = set("""
father calm palm psalm spa bra drama saga pasta plaza lava llama mafia banana
aha blah pa ma tomato drama
""".split())

# 拼写归一：英式拼法 → 美式拼法（只为查 CMU，音标仍按英音出）
SPELL_FIX = {
    "aeroplane": "airplane", "beancurd": "beancurd", "grey": "gray", "cheque": "check",
    "tyre": "tire", "kerb": "curb", "plough": "plow", "mould": "mold", "smoulder": "smolder",
    "sceptical": "skeptical", "aluminium": "aluminum", "cosy": "cozy", "draught": "draft",
    "gaol": "jail", "jewellery": "jewelry", "moustache": "mustache", "pyjamas": "pajamas",
    "storey": "story", "whisky": "whiskey", "speciality": "specialty", "judgement": "judgment",
    "acknowledgement": "acknowledgment", "ageing": "aging", "likeable": "likable",
    "sizeable": "sizable", "programme": "program", "catalogue": "catalog", "dialogue": "dialog",
    "monologue": "monolog", "defence": "defense", "offence": "offense", "pretence": "pretense",
    "licence": "license", "practise": "practice", "analyse": "analyze", "paralyse": "paralyze",
    "appal": "appall", "distil": "distill", "enrol": "enroll", "fulfil": "fulfill",
    "instalment": "installment", "skilful": "skillful", "wilful": "willful",
}

def spell_variants(w):
    """给出用于查 CMU 的候选拼写"""
    w = w.lower()
    out = [w]
    if w in SPELL_FIX:
        out.append(SPELL_FIX[w])
    v = w
    v = re.sub(r"our(s?)$", r"or\1", v)
    v = re.sub(r"our(s?)(ed|ing|able|ful|ite|ous)$", r"or\1\2", v)
    v = re.sub(r"isation$", "ization", v)
    v = re.sub(r"ise(s|d)?$", r"ize\1", v)
    v = re.sub(r"ising$", "izing", v)
    v = re.sub(r"yse(s|d)?$", r"yze\1", v)
    v = re.sub(r"ysing$", "yzing", v)
    v = re.sub(r"tre$", "ter", v)
    v = re.sub(r"bre$", "ber", v)
    v = re.sub(r"ogue$", "og", v)
    v = re.sub(r"ll(ing|ed|er|ers|or)$", r"l\1", v)
    v = re.sub(r"ae", "e", v)
    v = re.sub(r"oe", "e", v)
    if v != w:
        out.append(v)
    return out

# ---------------- ARPAbet → DJ ----------------
VOWELS = {
    "AA": "ɒ", "AE": "æ", "AH": "ʌ", "AO": "ɔː", "AW": "aʊ", "AY": "aɪ",
    "EH": "e", "ER": "ɜː", "EY": "eɪ", "IH": "ɪ", "IY": "iː", "OW": "əʊ",
    "OY": "ɔɪ", "UH": "ʊ", "UW": "uː",
}
VOWEL_KEYS = set(VOWELS) | {"AH0"}
CONS = {
    "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "g", "HH": "h",
    "JH": "dʒ", "K": "k", "L": "l", "M": "m", "N": "n", "NG": "ŋ", "P": "p",
    "R": "r", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v", "W": "w",
    "Y": "j", "Z": "z", "ZH": "ʒ",
}
LEGAL_ONSET = set("""pr pl br bl tr dr kr kl gr gl fr fl θr ʃr sp st sk sm sn sl sw
tw dw kw gw θw ʃw spr str skr spl skw spj stj skj pj bj kj fj vj mj nj lj hj""".split())

def parse_cmu(ph):
    toks = ph.split()
    out = []
    for t in toks:
        m = re.match(r"^([A-Z]+)([0-2])?$", t)
        if not m:
            continue
        p, s = m.group(1), int(m.group(2) or 0)
        out.append((p, s))
    return out

def word_flags(w):
    wl = re.sub(r"[^a-z']", "", w.lower())
    return wl

def ao_is_long(w, idx, toks):
    """判断该 AO 在英音里是 ɔː 还是 ɒ"""
    wl = word_flags(w)
    if wl in O_SHORT or wl.rstrip("s") in O_SHORT:
        return False
    if wl in ("water", "broad", "abroad", "watery"):
        return True
    if re.search(r"au|aw|ough|augh|alk|all|alt|ald|oar|oor|our|ore|quar", wl):
        return True
    # AO 后面跟 R（horse / north / port 类）→ ɔː
    for p, _ in toks[idx + 1:]:
        if p == "R":
            return True
        break
    return False

# 同形异音词：按「动词/常用义」取音（CMU 默认给的是名词读音）
OVERRIDE = {
    "combine": "kəmˈbaɪn", "address": "əˈdres", "record": "rɪˈkɔːd", "present": "prɪˈzent",
    "produce": "prəˈdjuːs", "progress": "ˈprəʊgres", "project": "ˈprɒdʒekt",
    "increase": "ɪnˈkriːs", "decrease": "dɪˈkriːs", "permit": "pəˈmɪt",
    "object": "ˈɒbdʒɪkt", "subject": "ˈsʌbdʒɪkt", "contract": "ˈkɒntrækt",
    "transfer": "trænsˈfɜː", "transport": "ˈtrænspɔːt", "suspect": "səˈspekt",
    "refuse": "rɪˈfjuːz", "use": "juːz", "close": "kləʊz", "live": "lɪv",
    "lead": "liːd", "read": "riːd", "wound": "wuːnd", "tear": "tɪə",
    # 英式与美式读音不同的常见词（按英音取）
    "schedule": "ˈʃedjuːl", "clerk": "klɑːk", "tomato": "təˈmɑːtəʊ",
    "vase": "vɑːz", "advertisement": "ədˈvɜːtɪsmənt", "garage": "ˈgærɑːʒ",
    "privacy": "ˈprɪvəsi", "vitamin": "ˈvɪtəmɪn", "process": "ˈprəʊses",
    "mobile": "ˈməʊbaɪl", "brochure": "ˈbrəʊʃə", "dynasty": "ˈdɪnəsti",
}

MERGE = {("IH","R"):"ɪə", ("EH","R"):"eə", ("UH","R"):"ʊə",
         ("IY","R"):"ɪə", ("AA","R"):"ɑː", ("AO","R"):"ɔː", ("UW","R"):"ʊə"}

def convert(ph, word):
    toks = parse_cmu(ph)
    if not toks:
        return ""
    wl = word_flags(word)
    n = len(toks)
    sym = []          # [符号, 重音, 是否元音]
    i = 0
    while i < n:
        p, s = toks[i]
        nx = toks[i+1][0] if i+1 < n else None
        nx2 = toks[i+2][0] if i+2 < n else None
        # --- ER：后接元音时 r 发音（worry /ˈwʌri/）---
        if p == "ER":
            if nx in VOWELS:
                sym.append(["ʌ" if s == 1 else "ə", s, True])
                sym.append(["r", 0, False])
            else:
                sym.append(["ɜː" if s == 1 else "ə", s, True])
            i += 1; continue
        # --- 元音 + R + 非元音：合成中元音（fire/sure/north）---
        if p in VOWELS and nx == "R" and nx2 not in VOWELS:
            m = MERGE.get((p, "R"))
            if m:
                sym.append([m, s, True]); i += 2; continue
        if p in VOWELS:
            v = VOWELS[p]
            if p == "AH":
                v = "ʌ" if s == 1 else "ə"
                if s == 0 and i < 3 and not any(x[2] for x in sym):
                    if re.match(r"^un(?![a-z]{0,0}$)", wl):
                        v = "ʌ"
                    elif re.match(r"^(be|de|re|pre|se|e[xn]?)", wl):
                        v = "ɪ"
            elif p == "AO":
                v = "ɔː" if ao_is_long(word, i, toks) else "ɒ"
            elif p == "IY" and s in (0, 2):
                v = "i" if i >= n - 2 else "ɪ"
            elif p == "UW" and s == 0:
                v = "u"
            elif p == "AE":
                if s == 0:
                    v = "ə"
                elif wl in BATH or wl.rstrip("s") in BATH:
                    v = "ɑː"
            elif p == "AA" and (wl in FATHER or wl.rstrip("s") in FATHER):
                v = "ɑː"
            sym.append([v, s, True]); i += 1; continue
        if p in CONS:
            sym.append([CONS[p], 0, False]); i += 1; continue
        i += 1
    # r 只在元音前发音
    for k, item in enumerate(sym):
        if item[0] == "r":
            nxt = next((x for x in sym[k+1:] if x[0]), None)
            if not nxt or not nxt[2]:
                item[0] = ""
    # 切音节
    sylls, cur = [], []
    for item in sym:
        if not item[0]:
            continue
        if item[2]:
            cur.append(item); sylls.append(cur); cur = []
        else:
            cur.append(item)
    if cur:
        (sylls[-1].extend(cur) if sylls else sylls.append(cur))
    # 最大音节首原则
    for k in range(1, len(sylls)):
        s2 = sylls[k]
        vi = next((j for j, x in enumerate(s2) if x[2]), len(s2) - 1)
        while vi >= 2:
            cluster = "".join(x[0] for x in s2[:vi])
            if cluster in LEGAL_ONSET:
                break
            sylls[k-1].append(s2.pop(0)); vi -= 1
    out = ""
    for s2 in sylls:
        vi = next((j for j, x in enumerate(s2) if x[2]), len(s2) - 1)
        mark = "ˈ" if s2[vi][1] == 1 else ""
        out += mark + "".join(x[0] for x in s2)
    out = out.replace("ˌ", "")
    if out.count("ˈ") > 1:
        last = out.rfind("ˈ")
        out = out[:last].replace("ˈ", "") + out[last:]
    return OVERRIDE.get(wl, out)

# ---------------- 老词典兜底转换（少量 CMU 未覆盖词）----------------
def convert_old(s, word):
    raw = str(s).strip()
    # 老词典里这些条目本身是残缺/多读音混排的，宁可不出音标也不要出错
    if not raw or "TODO" in raw or re.search(r"[,;/]", raw):
        return ""
    s = raw.replace("\\", "").replace("(", "").replace(")", "").replace(" ", "")
    s = s.replace(":", "ː").replace("ε", "e").replace("ɐ", "ə").replace("ɡ", "g")
    s = s.replace("ɹ", "r").replace("ɾ", "t")
    s = s.replace("ei", "eɪ").replace("ai", "aɪ").replace("ɔi", "ɔɪ").replace("əu", "əʊ")
    s = re.sub(r"[^a-zæðŋɑɔəɛɜɝɪʊʌʒʃθɡˈˌː]", "", s)
    if not s:
        return ""
    s = s.replace("əː", "ɜː").replace("oʊ", "əʊ").replace("ɛ", "e")
    s = s.replace("ɝ", "ɜː").replace("ɚ", "ə")
    s = (s.replace("ɪr", "ɪə").replace("er", "eə").replace("ʊr", "ʊə")
          .replace("ɔr", "ɔː").replace("ɑr", "ɑː").replace("ɜːr", "ɜː"))
    s = re.sub(r"ər(?![aeiouæɑɔəɜɛɪʊʌ])", "ə", s)
    s = re.sub(r"r(?![aeiouæɑɔəɜɛɪʊʌ])", "", s)
    wl = word_flags(word)
    s = s.replace("ɑː", "\x01").replace("ɑ", "ɒ").replace("\x01", "ɑː")
    if wl == "water" or re.search(r"au|aw|ough|alk|all|oar|oor|our|ore", wl):
        s = s.replace("ɔ", "ɔː")
    else:
        s = s.replace("ɔ", "ɒ" if (wl in O_SHORT or wl.rstrip("s") in O_SHORT) else "ɔː")
    if wl in BATH or wl.rstrip("s") in BATH:
        s = s.replace("æ", "ɑː")
    s = s.replace("ːː", "ː")
    if not re.search(r"[aeiouæɑɔəɜɛɪʊʌ]", s) or len(s) < 2:
        return ""
    return s.strip("ˌ")


def main():
    cmu = {}
    for line in open(D + "_cmudict.dict", encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line or line.startswith(";;;"):
            continue
        parts = line.split()
        w = parts[0]
        if re.search(r"\(\d\)$", w):
            continue
        cmu.setdefault(w.lower(), " ".join(parts[1:]))
    old = json.load(open(D + "_phonetic_us_old.json", encoding="utf-8"))
    out, from_cmu, from_old, failed = {}, 0, 0, []
    for w, oldp in old.items():
        ph = None
        for cand in spell_variants(w):
            if cand in cmu:
                ph = convert(cmu[cand], w)
                if ph:
                    from_cmu += 1
                    break
        if not ph:
            ph = convert_old(oldp, w)
            if ph:
                from_old += 1
            else:
                failed.append(w)
        if ph:
            out[w] = ph
    with open(D + "_phonetic_dj.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("CMU 生成:", from_cmu, "| 老词典兜底:", from_old, "| 失败:", len(failed), "| 合计:", len(out))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "show":
        out = json.load(open(D + "_phonetic_dj.json", encoding="utf-8"))
        for w in sys.argv[2:]:
            print(w.ljust(14), "/" + out.get(w, "（无）") + "/")
    else:
        main()
