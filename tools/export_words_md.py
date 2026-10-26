# -*- coding: utf-8 -*-
"""把背词助手的数据导出成 Markdown 词表（按批次 + 顽固词清单）。

用法：
  python tools/export_words_md.py [数据文件] [输出md]
默认读写当前目录下的 背词助手数据.json → 我的词库.md
"""
import json, collections, datetime, sys, os

_argv = sys.argv[1:]
DATA = _argv[0] if len(_argv) > 0 else "背词助手数据.json"
OUT = _argv[1] if len(_argv) > 1 else "我的词库.md"
BATCH_ORDER = []      # 留空 = 按批次名自动排序（"库存-未学" 永远排最后）

d = json.load(open(DATA, encoding='utf-8'))
ws = d['words']
now = datetime.datetime.now()

def step_label(w):
    st = w.get('step', 0)
    nd = (w.get('nextDate') or '')[-5:]
    return ('第 %d 次' % (st + 1)) + (' · ' + nd if nd else '')

def esc(s):
    return str(s or '').replace('|', '\\|').replace('\n', ' ').strip()

by_batch = collections.defaultdict(list)
for w in ws:
    by_batch[w.get('batch', '未分组')].append(w)
names = [b for b in BATCH_ORDER if b in by_batch] + [b for b in by_batch if b not in BATCH_ORDER]
names.sort(key=lambda b: (b == "库存-未学", b))

lapse = sorted([w for w in ws if (w.get('lapse') or 0) >= 2],
               key=lambda w: -(w.get('lapse') or 0))
steps = collections.Counter(w.get('step', 0) for w in ws)

L = []
L.append('# 05 · 我的词库（背词助手导出）\n')
L.append('> 数据源：`英语学习方法/studyEnglish/背词助手数据.json` · 导出时间 %s' % now.strftime('%Y-%m-%d %H:%M'))
L.append('> 与 `02-核心词汇表.md` 的分工：那份是**考纲词表**（该背什么范围），这份是**已导入复习计划的具体单词**（我背了哪些、背到什么程度）。')
L.append('\n---\n')
L.append('## 一、总览\n')
L.append('| 项目 | 数值 |')
L.append('|---|---|')
L.append('| 单词总数 | %d |' % len(ws))
L.append('| 批次数 | %d |' % len(names))
L.append('| 带例句 | %d |' % sum(1 for w in ws if w.get('example')))
L.append('| 未进入第 2 次复习 | %d |' % steps.get(0, 0))
L.append('| 已到第 2 次 | %d |' % steps.get(1, 0))
L.append('| 已到第 3 次 | %d |' % steps.get(2, 0))
L.append('| 错 2 次以上（顽固词） | %d |' % len(lapse))
L.append('\n**批次分布**\n')
L.append('| 批次 | 词数 | 说明 |')
L.append('|---|---|---|')
for b in names:
    note = '导入后尚未开始' if b == '库存-未学' else '按日期/课次导入'
    L.append('| %s | %d | %s |' % (b, len(by_batch[b]), note))
L.append('\n> 复习进度里的日期是该词**下次出现**的日子；`第 N 次` 指间隔阶梯（1→2→4→7→15→30→60→120 天）走到第几档。')
L.append('\n---\n')

L.append('## 二、按批次列出\n')
for b in names:
    words = sorted(by_batch[b], key=lambda w: w['word'].lower())
    L.append('### %s（%d 词）\n' % (b, len(words)))
    L.append('| 单词 | 音标 | 释义 | 例句 | 进度 |')
    L.append('|---|---|---|---|---|')
    for w in words:
        ex = w.get('example') or ''
        exzh = w.get('exampleZh') or ''
        ex_cell = esc(ex) + ('（' + esc(exzh) + '）' if exzh else '')
        L.append('| **%s** | /%s/ | %s | %s | %s |' % (
            esc(w['word']), esc(w.get('phonetic')), esc(w.get('meaning')),
            ex_cell or '—', step_label(w)))
    L.append('')

L.append('---\n')
L.append('## 三、顽固词清单（错 2 次以上）\n')
L.append('这批词**只靠多刷没用**，要写区分点、造短句，或者回头看 `01-语法考点清单.md` 里相关的构词法部分。\n')
if lapse:
    L.append('| 单词 | 音标 | 释义 | 错次 | 下次复习 |')
    L.append('|---|---|---|---|---|')
    for w in lapse:
        L.append('| **%s** | /%s/ | %s | %d | %s |' % (
            esc(w['word']), esc(w.get('phonetic')), esc(w.get('meaning')),
            w.get('lapse') or 0, (w.get('nextDate') or '')[-5:]))
else:
    L.append('（暂无）')
L.append('\n---\n')

L.append('## 四、怎么用这份表\n')
L.append('1. **查词**：复习时想不起某个词，直接搜这里，比翻程序快。')
L.append('2. **辨析**：同一批里形近/近义的词已经排在一起（按字母序），比如 `receive / receiver / reception / receipt`。')
L.append('3. **写作素材**：例句都是短句，可以直接拿去套 `04-写作模板与素材.md` 里的句型。')
L.append('4. **进度参考**：这里的进度是**导出那一刻的快照**，会过期；真实进度以 `背词助手` 程序为准，需要更新时重新导出即可。')
L.append('\n---\n')
L.append('## 附：数据口径\n')
L.append('- 释义已按专升本范围精简过（删专业义项、生僻义、重复义项），保留每个词性的常用义。')
L.append('- 音标统一为**英式 DJ 体系**（非儿化、ɒ/ɔː 分化），与专升本教材一致。')
L.append('- 例句优先用手写/内置例句，缺失的按词性自动生成最简句型。')

open(OUT, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
print('已写入', OUT)
print('行数', len(L), '| 字数', len('\n'.join(L)))
