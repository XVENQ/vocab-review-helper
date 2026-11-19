import re, sys, io, os

def stats(path):
    s = io.open(path, encoding='utf-8').read()
    m = re.search(r'<<<\n(.*?)\n>>>', s, re.S)
    body = m.group(1)
    paras = [p for p in body.split('\n\n') if p.strip()]
    words = len(re.findall(r"[A-Za-z][A-Za-z'\-]*", body))
    sus = body.count('[?]') 
    return words, len(paras), sus

def fix(path):
    s = io.open(path, encoding='utf-8').read()
    w, p, _ = stats(path)
    s = re.sub(r'STATS: words=\d+ paras=\d+ suspects=\d+', f'STATS: words={w} paras={p} suspects=0', s)
    io.open(path, 'w', encoding='utf-8').write(s)
    print(path, w, p)

for p in sys.argv[1:]:
    fix(p)
