# 背词助手 · 开发速查

> 读完这一页就能改代码，不必翻聊天记录。改动前先看第 5 节，避免重复造轮子。

## 1. 文件在哪

| 用途 | 路径 |
|---|---|
| 工作副本（每天用） | `outputs/单词复习/背词助手.html`（1.9 MB 单文件） |
| 发布仓库 | `背词助手/` → github.com/XVENQ/vocab-review-helper |
| 学习数据（**个人，不入库**） | 本地 `studyEnglish/背词助手数据.json`，与程序分开存放 |
| 内容源 | `_story_hint.json`（故事/提示）、`_builtin_dict.json`、`_phonetic_dj.json`、`_cmudict.dict` |

## 2. 三条铁律

1. **`save()` 必须刷新 `updatedAt`** —— 否则浏览器缓存会被判定为"更新"，反向覆盖磁盘。
2. **排期只认 `nextDate`**，绝不能拿 `lastRated` 去筛队列（评「重来」时 `nextDate` 仍停在今天，用 `lastRated` 过滤会让这些词集体消失）。
3. **改完同步两处**：`outputs` 副本 → `cp` 到仓库 → `git commit` → `push`。

## 3. 代码结构（按注释段 grep，不要记行号）

| 注释段 | 关键函数 |
|---|---|
| `// ---------- 时长格式化` | `fmtShort` / `fmtDur` |
| `// ---------- 发音` | `speak` / `ttsSpeak` / `curAccent` |
| `// ---------- 故事复习` | `renderStories` / `storyHtml` / `morphHint` / `hintBody` / `startHint` |
| `// ---------- 单卡计时` | `timerStart` / `timerPause` / `timerTake` |
| `// ---------- 复习会话` | `nextCard` / `reveal` / `answer` / `studyDone` / `finishReview` |
| `// ---------- 排期算法` | `rate` / `ensureDayPlan` / `buildQueue` |
| 数据常量 | `BUILTIN`(21329) / `PHONETIC`(21042) / `STORIES` / `HINT_EN` / `HINT_SOUND` |
| 存储 | localStorage `cihui_review_v1` + IndexedDB `cihui/kv.dataHandle` |

## 4. 数据模型

```js
state { words[], settings{ maxReview, accent, preview }, updatedAt,
        dayPlan{ date, ids }, todayTime{ date, ms } }
word  { id, word, meaning, phonetic, batch, added, step, nextDate, lapse,
        lastRated, example, exampleZh, note, needMean, timeMs, previewAt }
```

## 5. 已实现（改之前先确认没有）

排期阶梯 / 四档评分 / 每日上限 / 批次乱序 / 内置词库 / DJ 音标 /
有道发音+本地 TTS 降级 / 单词计时 / 顽固词 / 生词预习（hard·all·off）/
故事复习 / 渐进提示（12s 例句，22s 英释+构词+联想）/ 每日快照 / 导出备份

## 6. 改内容从哪下手

- **加故事 / 提示**：改 `_story_hint.json` → 用 Python 重写 `const STORIES / HINT_EN / HINT_SOUND` 三行。
- **加词 / 改释义**：改 `_builtin_dict.json` → 重写 `const BUILTIN` 行（顺带同步 `PHONETIC`）。
- **重算音标**：`tools/build_dj_phonetic.py`（需要 `cmudict.dict`），输出 `phonetic_dj.json`。

## 7. 调试

- 语法：把 `<script>` 抽成 `_c.js` → `node --check`。
- 行为：node + `vm` + 假 DOM 跑真实数据（模板见记忆 2026-10-26 条目）。
- **不要整文件 Read（1.9 MB）**，用 `grep` 定位到段再读局部。

## 8. 已知坑

- 该目录文件常被浏览器句柄占用：`open(w)` / `os.replace` / 删除都会 PermissionError。
  可行路径：**写新文件 → rename 旧文件 → rename 新文件就位**。
- 页面必须用 `file://` 打开才能用 File System Access；预览面板里不行。
- 多个标签页同开会互相覆盖数据。
