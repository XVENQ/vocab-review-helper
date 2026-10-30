# 故事配图方案

15 篇故事 × 4 张图 = **60 张**。图片由本地小型模型生成，程序只负责显示与兜底。

---

## 一、可行性：什么能画，什么画不了

小型模型（SD1.5 / SDXL-Turbo / Flux-schnell 这一档）的强项是**具体物体、单人动作、简单场景**，弱项是**手、多人、文字、抽象概念**。所以可行性不取决于「每篇 4 张」这个数量，而取决于**选的场景是否落在它的强项区**。

| 场景类型 | 可行性 | 处理方式 |
|---|---|---|
| 单人 + 一个动作（男孩道歉、老人坐着） | 高 | 直接画 |
| 静物 / 室内（旧收音机、桌上信件、沙发缝里的钱包） | 很高 | 直接画，最稳 |
| 建筑 / 街景 / 山景（社区中心、山路、法院台阶） | 高 | 不要人，或只要剪影 |
| 两人对话 | 中 | 用中远景，不拍脸 |
| 多人场面（科技展、长跑起点） | 中低 | 拉远、虚化背景，主体只留 1–2 人 |
| 抽象概念（justice / capacity / wealth） | 低 | **不直接画**，改画象征物（法槌、文件架、天平） |
| 文字内容（展板数字、路牌） | 极低 | prompt 里写明 `no text, no letters`，画面留白 |

结论：**可行，但不能「照着句子画」**，要「照着句子能看见的东西画」。60 个场景全部按这个原则重写过，见 `tools/story_scenes.py`。

---

## 二、结构：一段一图

原来故事是一整段文本，没有插入点。现在拆成 4 段，每段自带一个图位：

```
故事卡片
├─ 段 1  [图 1]  文 1        ← 图在左，文在右
├─ 段 2  文 2  [图 2]        ← 文在左，图在右（.flip）
├─ 段 3  [图 3]  文 3
└─ 段 4  文 4  [图 4]
```

**为什么是 4 段 / 4 图**：

- 每篇 80–130 词，日均分 4 段 = 每段 20–33 词 ≈ 2–3 行，阅读节奏正好
- 4 张图是「每读一小段就有一张」的密度，再少就断了，再多会喧宾夺主
- 段落边界按句子切（保护 `Mr.` `Ms.` 这类缩写），不切断句子

**图文配比**（渲染实测值，容器 734px 时）：

| 元素 | 尺寸 | 说明 |
|---|---|---|
| 图片 | 228 × 152 | 占宽 31% |
| 正文 | 504 宽 | 占宽 69%，一行约 70 字符 |
| 段块高 | 152 | 由图高决定，文字顶对齐 |

布局随屏宽变化：

| 屏宽 | 布局 |
|---|---|
| < 640px | 单列：图在上（限高 228），文在下 |
| 640–900px | 两列：文 69% / 图 31%，左右交替 |
| > 900px | 两列：同上，图限高 190 |

---

## 三、内容选取逻辑

三条规则，写在 `tools/story_scenes.py` 的注释里：

**1. 只画看得见的东西。**
`Justice is easy to demand and hard to define.` → 画法院台阶（无人），不画「正义」。

**2. 一个场景一个主体。**
`sheltering under a large ancient rock` → 两个背影，不画脸。多人场景一律拉远。

**3. 每张图对应段落的核心动作，不是首句。**
第 3 段讲「老人没现金只有卡，仍然笑着接受」→ 图是「老人展示空钱包和银行卡」，不是「他说了什么」。

配套的统一风格串（保证 60 张像同一本书）：

```
children's storybook illustration, soft watercolor, warm natural light,
muted colors, simple background, no text, no letters, no watermark
```

负向词固定：`text, letters, words, watermark, signature, nsfw, extra fingers, deformed hands, distorted face, multiple heads, lowres, jpeg artifacts`

---

## 四、接口与存储

### 4.1 三种接入方式（互不冲突）

| 方式 | 命令 | 适合 |
|---|---|---|
| 只导出 prompt | `--export` | 用任何工具手动跑、或导入 ComfyUI 队列 |
| 直连 WebUI | `--run --api webui --url http://127.0.0.1:7860` | 最省事，标准 `/sdapi/v1/txt2img` |
| 直连 ComfyUI | `--run --api comfyui --url http://127.0.0.1:8188 --workflow workflow_api.json` | 已有工作流，需 API 格式的 JSON |
| 纯手动 | 自己出图后按命名放进去 | 用别的软件 |

```bash
python tools/make_story_images.py --export              # 先看 60 条 prompt
python tools/make_story_images.py --run --api webui     # 批量生成
python tools/make_story_images.py --check               # 核对缺哪些
python tools/make_story_images.py --sheet               # 生成挑图预览页
python tools/make_story_images.py --run --n 4           # 每条出 4 张候选待挑
```

`--n 4` 会把 4 张候选存到 `_candidates/{id}_c1..c4.webp`，挑好的改名为 `{id}.webp` 放回上级目录即可。

### 4.2 存储约定

```
assets/stories/
├── a-small-accident-1.webp      ← 命名：{slug}-{1..4}.webp
├── a-small-accident-2.webp
├── ...
├── _preview.html                ← --sheet 生成，用来挑图
└── _candidates/                 ← --n>1 时的候选
```

| 项 | 值 | 理由 |
|---|---|---|
| 格式 | WebP q82 | 同画质比 PNG 小 70% |
| 尺寸 | 768 × 512（3:2） | SD1.5 原生比例附近，不易变形 |
| 单张 | 约 40–90 KB | 60 张 3–5 MB |
| 加载 | `loading="lazy"` + `decoding="async"` | 60 张不会同时请求 |
| 位置 | 与 HTML 同级的 `assets/` | `file://` 双击可用；**不要**打进 HTML（会把 1.3MB 变成 6MB） |

**图片不进 git**（`.gitignore` 已挡），但 `prompts.json` 和 `_preview.html` 可以进——它们是文本，方便别人复现。

### 4.3 程序侧的行为

```
img 默认 opacity:0
   ↓ load 成功 → figure 加 .has-img → 图淡入、占位卡隐藏
   ↓ error / 文件不存在 → 保持占位卡（显示「图 N / 4」+ 中文场景说明）
```

**关键**：图片缺失时**版面不变形**。占位卡和图同样尺寸（3:2 + 限高），所以 60 张一张都没有时，故事页看起来依然完整，只是每段多了个灰框——框里写着这段该画什么。

---

## 五、质量不稳定怎么兜底

小模型抽卡，10 张里 3 张能用是常态。按代价从低到高：

| 策略 | 做法 | 适用 |
|---|---|---|
| **固定 seed** | 脚本给每条任务固定 seed（1001–1060），同一场景结果可复现 | 默认，已内置 |
| **多抽挑一** | `--n 4` 出 4 张候选，人眼挑一张改回正式名 | 重要场景 |
| **只换不修** | 哪张不满意就重跑单条：`--only a-small-accident-3` | 局部返工 |
| **降级为占位** | 实在画不好就删掉该文件的 webp，程序自动显示占位卡 | 抽象题材 |
| **改 prompt 重画** | 改 `story_scenes.py` 里对应那条，重跑该条 | 反复出错 |

**三种「画得不对」的处理原则**：

1. **风格不统一**（同一篇 4 张像 4 本书）→ 检查是否漏了 STYLE 后缀，或换了模型/采样器
2. **内容错位**（画的是下一段的事）→ 改这条的 prompt，不要改段落顺序
3. **人物崩坏**（手指、脸）→ prompt 里去掉「脸」相关词，改中远景或背影

**已知边界**：`What Justice Means` 和 `Why We Forget` 两篇是议论体，象征物方案能出「能看的图」，但不可能「准确传达论点」。这两篇的图作用是**分段标记 + 视觉喘息**，不是内容说明——这一点要在预期里说清楚。

---

## 六、现成数据在哪

| 文件 | 内容 |
|---|---|
| `tools/story_scenes.py` | **唯一数据源**：15 篇的段落句数分配 + 60 条场景描述 + 风格串 + 负向词 |
| `_build_stories.py`（工作副本） | 读上面的模块，切段并写入 `_story_hint.json`，再注入 HTML 的 `STORIES` |
| `prompts.json` | `--export` 产物，60 条完整任务（含 seed、尺寸、负向词） |

改内容只需动 `story_scenes.py` 一处，然后重跑 `_build_stories.py` 和注入步骤。
