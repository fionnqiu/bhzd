# 学生与运营工作台 · 设计规范（v5）

> **事实来源**：`docs/dev/student-workbench-layout-demo.html`（标航智导 · 学生工作台演示原型，行号以最终交付的 demo 为准）
> **适用范围**：学生工作台「Agent 指挥舱」欢迎界面 + 「会话视图」两屏，以及教师端、RAG 管理、系统管理共用的运营工作台壳层。
> **读者**：设计师（视觉与交互）、前端工程师（组件与 Token）、产品评审（验收）
> **非目标**：预设学习 / 能力图谱 / 学习任务 / 标注诊断 / 知识问答 五个子模块的内部细节（demo 中仅以占位 nav-link 出现）
> **版本**：v5 · 2026-08-08（学生会话输入与侧栏收敛）

---

## 0. 文档导读

本规范按 **「原则 → Token → 模式 → 组件 → 内容 → 验收 → 映射」** 的顺序组织，遵循三段式心智模型：

1. **是什么**：§1 设计原则 + §2 视觉语言 + §3 Token（颜色 / 字号 / 间距 / 圆角 / 阴影 / 缓动）；
2. **怎么用**：§4 字体排版阶梯 + §5 间距 / 尺寸 / 栅格 / 层级 + §6 桌面 / 平板 / 移动响应式 + §7 信息架构；
3. **怎么造**：§8 组件清单（含每个组件的结构、尺寸、状态、交互、无障碍） + §9 两屏布局 + §10 消息 / 活动线 / 计划卡 + §11 动效 + §12 内容规范 + §13 验收清单 + §14 demo 行号映射。

任何设计师或前端拿到这份文档，应能：

- 不打开 demo 即可 1:1 复现两屏的视觉与交互；
- 复用同一套 Token 把规范扩展到子模块卡片、列表、弹窗；
- 在评审中凭 §14「demo 行号映射」逐条追溯到 demo 的具体行。

---

## 1. 设计原则

| #   | 原则                            | 解释                                                                                         | 在 demo 中的体现                                                                           |
| --- | ------------------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1   | **学生是操作者，不是被引导者**  | 把控制权交给学生：输入框永远居中、永远最大、永远是页面绝对主角                               | prompt 居中、宽 `min(900px, 100%)`，textarea 17px，是页面最大字号                          |
| 2   | **学习画布先于框架**            | 侧栏只是"工作区锚点"，永远不与画布争夺视觉注意                                               | `--surface-soft` 侧栏底 + 浅 1px `--line` 分隔                                             |
| 3   | **中性灰白 · 学术冷静**         | 用一种冷蓝做单一强调，警示色仅备用；活动状态用青，结构信号用灰                               | 全站仅 `--accent #2477d6` 一种品牌强调；`--teal #159b91` 做活动点；`--amber` 仅 token 预留 |
| 4   | **短促克制动效**                | 所有 hover / 状态变化 < 200ms；空间变化（抽屉、展开）允许到 180ms；超过 200ms 必须有物理意义 | hover 140ms；focus / Prompt 边框 160ms；抽屉 180ms；send 按下 100ms                        |
| 5   | **弱对比 hover，强对比 active** | hover 只换底色、字色变化极小；active 用更明显的标记（蓝条 / 字重 / 图标染色）                | nav-link hover 仅 `#eef2f6` 底，active 加 `inset 2px 0 0 var(--accent)`                    |
| 6   | **形状 = 语义**                 | 圆角不是审美选择，而是组件语义：输入最大圆角、控件中圆角、快捷入口胶囊                       | `--radius-input 16` / `--radius-control 8` / quick-link `999px`                            |
| 7   | **响应式不破坏信息层级**        | 小屏仅收紧边距与字号，不重组信息结构                                                         | 手机下消息气泡 100% 宽、setting 文字截断 112，但仍是气泡 + 文字                            |
| 8   | **键盘可达 = 默认态**           | 全局 2px 蓝色焦点描边、`role` / `aria-label` 默认就位                                        | `button:focus-visible { outline: 2px solid var(--accent) }`                                |
| 9   | **占位 ≠ 隐性默认**             | 所有"看起来是默认"的行为必须有明确的状态类（`.has-value`、`.active`、`.sidebar-collapsed`）  | send-button 用 `.has-value` 切换灰色与蓝色                                                 |
| 10  | **导航不变成第二个模态**        | 折叠态只缩窄，不弹出菜单 / 蒙层 / 二级面板                                                   | demo 注释 L76–L77 明示                                                                     |

---

## 2. 视觉语言总览

| 维度 | 关键词                                           | 在 demo 中的体现                                                                        |
| ---- | ------------------------------------------------ | --------------------------------------------------------------------------------------- |
| 色调 | 中性灰白 · 学术冷静                              | `--canvas #f7f8fa` 整页底 + `--surface #fff` 卡片；仅一种冷蓝 `--accent #2477d6` 做强调 |
| 角色 | 学生是「操作者」                                 | 输入框居中、最大字号 17px，是页面绝对主角                                               |
| 节奏 | 大量留白 + 8/12/18/28 的间距阶梯                 | 章节间 `margin-top: 20/24/44`；`gap: 2/7/8/11/18`                                       |
| 形状 | 大圆角输入 + 中圆角控件 + 胶囊快捷入口           | `--radius-input: 16` / `--radius-control: 8` / quick-link `999px`                       |
| 动效 | 短促、克制、`< 200ms`                            | 几乎所有 hover/active 都是 `140ms` ease-out                                             |
| 反馈 | 弱对比 hover、强对比 active、聚焦用蓝色 2px 描边 | nav-link active 用 `inset 2px 0 0 var(--accent)`                                        |

---

## 3. Token

> 所有 Token 来自 demo `:root`（L8–L26）。**禁止擅自修改数值**。如需新增，挂在 `:root` 并补 §14 对照表。

### 3.1 颜色 Token

| Token            | 值                              | 角色                                                  | 关键出现    |
| ---------------- | ------------------------------- | ----------------------------------------------------- | ----------- |
| `--canvas`       | `#f7f8fa`                       | 整页底色（body 背景）                                 | L9          |
| `--surface`      | `#ffffff`                       | 卡片 / 输入框 / 侧栏中的内嵌白面                      | L10         |
| `--surface-soft` | `#fbfcfd`                       | 侧栏背景、计划卡内嵌底                                | L11         |
| `--line`         | `#e5e8ec`                       | 常规分割线、控件边                                    | L12         |
| `--line-strong`  | `#d4d9e0`                       | 输入框边、new-session 边                              | L13         |
| `--ink`          | `#17212b`                       | 主文字、icon 强调                                     | L14         |
| `--ink-soft`     | `#5f6b76`                       | 次级文字、按钮静默态                                  | L15         |
| `--ink-faint`    | `#98a2ad`                       | 辅助文字（标签、时间戳、placeholder 偏弱版）          | L16         |
| `--accent`       | `#2477d6`                       | 唯一品牌强调色（链接、active、focus 描边、send 按钮） | L17         |
| `--accent-soft`  | `#edf5ff`                       | 强调态浅底（quick-link hover、user 消息气泡）         | L18         |
| `--teal`         | `#159b91`                       | 进行中活动点（activity-dot）                          | L19         |
| `--amber`        | `#bf7417`                       | 警示色备用（本规范未在 demo 中实际出现）              | L20         |
| `#dcefe9`        | 头像底                          | 仅一处                                                | L336        |
| `#126f68`        | 头像字                          | 仅一处                                                | L338        |
| `#a7afb8`        | textarea placeholder 字色       | 略弱于 `--ink-faint`                                  | L503        |
| `#b8c9dc`        | new-session hover 边            | 偏蓝灰                                                | L203        |
| `#9dbde2`        | prompt focus 边                 | focus 蓝                                              | L485        |
| `#d9dde2`        | send-button 默认背景（未输入）  | 中性灰                                                | L555        |
| `#eef2f6`        | nav-link / recent-item hover 底 | 浅灰                                                  | L243 / L304 |
| `#f0f3f6`        | prompt-toolbar 按钮 hover 底    | 比 nav 浅一档                                         | L539        |
| `#d9dee5`        | capability-mark 默认方块        | 灰                                                    | L434        |
| `#b4c8e3`        | capability-mark 着色 · 蓝       | nth-child(7n+2)                                       | L438        |
| `#8ed3cb`        | capability-mark 着色 · 青       | nth-child(11n+4)                                      | L442        |
| `#efc281`        | capability-mark 着色 · 暖       | nth-child(13n+5)                                      | L446        |
| `#cde5e0`        | activity-line 左边线            | 浅青                                                  | L724        |
| `#235f9f`        | user 消息气泡字色               | 比 accent 深的蓝                                      | L701        |
| `#edf5ff`        | user 消息气泡底色               | = `--accent-soft`                                     | L700        |

### 3.2 颜色语义（功能映射）

| 语义     | Token           | 用法                                    | 反例                               |
| -------- | --------------- | --------------------------------------- | ---------------------------------- |
| 主文字   | `--ink`         | 标题、用户名、品牌、消息正文            | 不要用作按钮 hover 底色            |
| 次文字   | `--ink-soft`    | 按钮静默字、消息正文、段落              | 不要用作背景                       |
| 辅助文字 | `--ink-faint`   | 标签、时间戳、breadcrumb 弱项           | 不要承载关键信息（对比度仅 3.4:1） |
| 主品牌   | `--accent`      | 强调链接、focus、active 蓝条、send 启用 | 不要全屏铺底                       |
| 品牌浅底 | `--accent-soft` | hover 强调态、user 气泡                 | 不要做边框                         |
| 进行中   | `--teal`        | activity-dot、活动线强调                | 不要做按钮字色                     |
| 警示     | `--amber`       | 备用，本期未启用                        | 不要与 `--accent` 同时出现于同一行 |

### 3.3 颜色对比度（已实测）

| 前景                  | 背景                    | 比值     | 等级     | 允许用法                                                     |
| --------------------- | ----------------------- | -------- | -------- | ------------------------------------------------------------ |
| `--ink #17212b`       | `--surface #fff`        | ≈ 15.4:1 | AAA      | 标题、关键正文                                               |
| `--ink-soft #5f6b76`  | `--surface #fff`        | ≈ 7.0:1  | AAA      | 次级正文、按钮静默字                                         |
| `--accent #2477d6`    | `--surface #fff`        | ≈ 5.0:1  | AA       | 链接、强调字、active 蓝条                                    |
| `#235f9f`             | `--accent-soft #edf5ff` | ≈ 6.8:1  | AAA      | user 气泡字                                                  |
| `--ink-faint #98a2ad` | `--surface #fff`        | ≈ 3.4:1  | AA Large | 11px 大写小标签、时间戳、placeholder（>18px 才允许承载信息） |
| `#a7afb8` placeholder | `--surface`             | ≈ 3.2:1  | 装饰     | placeholder 必须随输入被覆盖                                 |

### 3.4 尺寸 / 布局 Token

| Token             | 值                         | 用途                                |
| ----------------- | -------------------------- | ----------------------------------- |
| `--sidebar-width` | `272px`                    | 侧栏展开宽度                        |
| 折叠态侧栏        | `68px`                     | 仅留 icon 列                        |
| 侧栏 header 高    | `68px`                     | 侧栏品牌区基线；通知不占用额外顶栏  |
| 移动端侧栏        | `min(272px, 84vw)`         | 抽屉式                              |
| 内容主区最大宽    | `min(900px, 100%)`         | hero / prompt / conversation 居中   |
| quick-link 行宽   | `min(980px, 100%)`         | 比主区宽 80px，允许两端溢出         |
| hero 顶部 padding | `clamp(76px, 15vh, 146px)` | 让首屏在 1080p / 1440p 上都不"贴顶" |

### 3.5 圆角 Token

| Token              | 值                   | 适用对象                                                |
| ------------------ | -------------------- | ------------------------------------------------------- |
| `--radius-control` | `8px`                | 侧栏内按钮、icon 按钮、recent-item、new-session、toast  |
| `--radius-input`   | `16px`               | Prompt 输入框                                           |
| 圆角 6px           | `6px`                | prompt 工具栏小按钮                                     |
| 圆角 10px          | `10px`               | plan-inline 内嵌卡                                      |
| 圆角 14px          | `14px 14px 4px 14px` | user 消息气泡（三个角大、左下小，传递"从我发起"的语气） |
| 胶囊 999px         | `999px`              | quick-link 快捷入口                                     |
| 圆                 | `50%`                | 头像、send-button                                       |

### 3.6 阴影 Token

| Token             | 值                                     | 用途                  |
| ----------------- | -------------------------------------- | --------------------- |
| `--shadow-input`  | `0 18px 42px rgba(26, 39, 52, 0.08)`   | prompt 输入框静默阴影 |
| prompt focus 阴影 | `0 18px 42px rgba(36, 119, 214, 0.12)` | 蓝色更浓的 focus 阴影 |
| new-session 阴影  | `0 1px 2px rgba(26, 39, 52, 0.03)`     | 极轻提示              |
| Toast 阴影        | `0 12px 30px rgba(20, 29, 38, 0.17)`   | 浮层                  |

### 3.7 缓动 Token

| Token        | 值                              | 用途                           |
| ------------ | ------------------------------- | ------------------------------ |
| `--ease-out` | `cubic-bezier(0.16, 1, 0.3, 1)` | 所有 transition 默认           |
| `140ms`      | hover / 颜色变化                | 侧栏、按钮、quick-link、recent |
| `160ms`      | prompt 边框 + 阴影              | Prompt / Toast                 |
| `180ms`      | 移动端侧栏抽屉                  | 抽屉滑入                       |
| `100ms`      | `transform: scale(0.96)`        | send-button 按下               |

> **规则**：新组件默认 `140ms var(--ease-out)`。仅在"明显大状态变化"才用 `160ms` 以上。**禁止**新增 `200ms+` 的 hover。

---

## 4. 字体与排版阶梯

### 4.1 字体栈

```css
font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
```

- 正文 14px；标题 720；导航激活 650；主按钮 600；小标签 700 + `letter-spacing: 0.04em` + `text-transform: uppercase`。
- 整页 `letter-spacing: 0`，**仅** 11px 大写小标签例外。

### 4.2 字号阶梯与角色

| 角色                                                | 字号                       | 字重 | 行高 | 出现位置              |
| --------------------------------------------------- | -------------------------- | ---- | ---- | --------------------- |
| 正文 base                                           | `14px`                     | 400  | 1.5  | body 全局             |
| hero h1（桌面）                                     | `clamp(30px, 3.2vw, 48px)` | 720  | 1.15 | 欢迎页大标题          |
| hero h1（≤900）                                     | `32px` 固定                | 720  | 1.15 | 中屏                  |
| hero 副标题（桌面）                                 | `15px`                     | 400  | 1.7  | 欢迎页 p              |
| hero 副标题（≤560）                                 | `14px`                     | 400  | 1.7  | 手机                  |
| Prompt textarea（桌面）                             | `17px`                     | 400  | 1.6  | 学生输入              |
| Prompt textarea（≤560）                             | `16px`                     | 400  | 1.6  | 手机（避免 iOS 缩放） |
| 消息正文                                            | `15px`                     | 400  | 1.75 | assistant / user      |
| plan h2                                             | `13px`                     | 700  | 1.5  | plan-inline 标题      |
| recent title                                        | `13px`                     | 400  | 1.4  | recent-item           |
| toolbar context / setting 文字 / 活动说明 / toast   | `12px`                     | 400  | 1.5  | 次级                  |
| nav-label / recent-meta / user-role / message-label | `11px`                     | 700  | 1.4  | 大写 + 0.04em         |

### 4.3 字重使用

| 字重  | 用法                                                                   |
| ----- | ---------------------------------------------------------------------- |
| `400` | 正文、消息、按钮静默字                                                 |
| `600` | NewSession 主按钮文字                                                  |
| `650` | nav-link active、user-name（介于 600 与 700 之间的"准粗体"，避免过重） |
| `700` | 品牌、消息小标签、avatar 缩写                                          |
| `720` | hero h1（仅此处用 720，强调"招牌感"）                                  |

### 4.4 段落与对齐

- 段落最大宽：hero p `560px`、消息气泡 ≤ 82%（user ≤ 72%）、prompt-wrap `900px`。
- 默认左对齐；hero 与 quick-links 居中。
- 消息行高 **必须 1.75**，确保对话节奏。

---

## 5. 间距 / 尺寸 / 栅格 / 层级

### 5.1 间距阶梯（demo 中反复出现的语义值）

| 语义             | 值                     | 例子                                                      |
| ---------------- | ---------------------- | --------------------------------------------------------- |
| 控制条内 padding | `0 18px` / `0 28px`    | sidebar-header / stage-toolbar                            |
| 块级垂直间距     | `18px` / `24px`        | new-session 底 / quick-links 顶；会话列表使用独立内部滚动 |
| 控件内 gap       | `2px` / `7px` / `11px` | nav-list / prompt-toolbar / nav-link 内                   |
| 章节距离         | `34px` / `38px`        | conversation-heading 底 / conversation-prompt 顶          |
| 段落内部         | `13px` / `15px`        | plan-inline 边 / message-list gap                         |

### 5.2 间距基线（推荐用于扩展组件）

| 用途             | 数值                                                      |
| ---------------- | --------------------------------------------------------- |
| 同组内紧贴       | `2 / 3 px`                                                |
| 控件内部 padding | `4 / 6 / 7 / 8 / 9 / 10 / 12 / 13 / 14 / 15 / 16 / 18 px` |
| 控件之间 gap     | `7 / 8 / 11 / 18 px`                                      |
| 章节顶部间距     | `20 / 24 / 30 / 38 / 44 / 48 px`                          |
| 容器内 padding   | `28px`（桌面）/ `16px`（移动）                            |
| 装饰顶距         | `76 ~ 146 px`（hero 首屏）                                |

### 5.3 栅格

- 整页为 **「侧栏 + 主区」两列栅格**：`grid-template-columns: var(--sidebar-width) minmax(0, 1fr)`。
- 主区内部无强栅格，靠 `width: min(900px, 100%); margin: 0 auto;` 自居中。
- capability-mark 是 **9 列等距 7px 方块** 的视觉点阵（`grid-template-columns: repeat(9, 7px); gap: 5px`），非数据栅格。

### 5.4 层级（z-index）

| 层  | z-index | 用途                                |
| --- | ------- | ----------------------------------- |
| 1   | base    | stage / sidebar 内容                |
| 2   | `2`     | 移动端遮罩 `::after`                |
| 3   | `3`     | sidebar（移动端抽屉态盖在遮罩之上） |
| 10  | `10`    | Toast                               |

### 5.5 层级（视觉层级 · 字号 + 字重 + 留白）

| 层          | 字号    | 字重      | 留白               |
| ----------- | ------- | --------- | ------------------ |
| L1 招牌     | 30–48px | 720       | hero 顶部 76–146px |
| L2 区块标题 | 13–17px | 400–700   | 上 24–38px         |
| L3 内容     | 14–15px | 400       | 行高 1.5–1.75      |
| L4 辅助     | 11–12px | 700 / 400 | 大写或灰色         |

---

## 6. 响应式

### 6.1 断点总览

| 断点                             | 触发        | 关键变化                                                                                                     |
| -------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------ |
| `≤ 900px`                        | 中屏 / 平板 | shell 改 block；侧栏 fixed 抽屉 + 蒙层；对话顶部栏覆盖主区并容纳通知；其他学生页通知保持右上固定入口；hero h1 32px；最近会话保留侧栏内部滚动   |
| `≤ 560px`                        | 手机        | 通知浮层保持可见且面板受视口宽度约束；hero p 14px；prompt 内边距更紧；setting 文字截断 112；消息气泡 100% 宽 |
| `prefers-reduced-motion: reduce` | 减弱动效    | `transition-duration: 1ms !important`，关闭 smooth scroll                                                    |

### 6.2 桌面（≥ 901px）

```
┌────────────────────┬──────────────────────────────────────┐
│  Sidebar 272px     │  Stage (1fr)                         │
│  1. header 68px    │  │  view（welcome / conversation）│ │
│  2. new-session    │  │                                │ │
│  3. nav            │  │  通知：右上 fixed 浮层          │ │
│  4. recent         │  │  （不占布局高度）               │ │
│  5. footer         │  │                                │ │
└────────────────────┴──────────────────────────────────────┘
```

- 外层 `.demo-shell`：`grid-template-columns: var(--sidebar-width) minmax(0, 1fr)`（L70–L71）。
- stage `min-height: 100dvh; overflow: hidden`（L365–L371），内部 view 自带滚动。
- 欢迎页 `padding: clamp(76px, 15vh, 146px) 28px 48px`（L414）。

### 6.3 平板 / 中屏（≤ 900px）

- shell 改 `display: block`（L791）。
- 侧栏转 fixed 抽屉：`transform: translateX(-100%)` → `-open` 时 `0`（L798–L804）。
- 抽屉打开加 `::after` 蒙层 `rgba(23, 33, 43, 0.22)`（L806–L812）。
- 学生端不新增独立操作栏；已有对话的信息栏覆盖侧栏之外的主区顶部并在右侧容纳通知铃铛与下拉列表，其他学生页继续使用 `position: fixed` 的右上通知入口；欢迎页内边距改为 `80px 16px 32px`。
- h1 改 `32px` 固定值（不再 clamp）。
- 最近会话继续位于侧栏内部滚动区；欢迎页不新增历史会话副本。
- 侧栏滚动区保持鼠标、触屏和键盘滚动，但通过 `scrollbar-width: none` 与 WebKit 规则隐藏滚动条。

### 6.4 手机（≤ 560px）

- 对话页顶部栏内的通知铃铛保持右上可见；下拉面板以视口宽度为上限，避免在窄屏向左溢出。
- hero p 改 `14px`。
- 仅已有对话 Composer 改为 `min-height: 140px`；欢迎页 Hero 保持 `162px`，两者内边距均为 `14px 12px 10px`，textarea 字号 `16px`（避免 iOS 缩放）。
- setting-button 文字最大 `112px` 截断省略。
- 消息气泡最大宽 `100%`。
- welcome 顶部 padding 缩到 `54px`。

### 6.5 折叠态（与断点正交）

- 折叠态仅在 ≥ 901 生效；≤ 900 不折叠，直接走抽屉。
- 折叠后侧栏宽度 `68px`，隐藏所有文案，仅保留图标与头像。

---

## 7. 信息架构

### 7.1 侧栏

```
Sidebar
├── Header（品牌 + 折叠按钮）
├── NewSession（新建会话 + Ctrl K 提示）
├── Nav
│   ├── 学习空间
│   │   ├── Agent 指挥舱  ← 当前激活
│   │   ├── 预设学习
│   │   ├── 能力图谱
│   │   └── 学习任务
│   └── 资料与诊断
│       ├── 标注诊断
│       └── 知识问答
├── Recent（最近会话 · 列表，max-height 220px）
└── Footer（头像 + 用户名 + 角色 + more）
```

- 三组 `.nav-label` 分别是「学习空间」/「资料与诊断」/「账户」。
- 折叠态：仅显示 icon + 头像 + 折叠按钮，其余文案 `display: none`。
- `nav-link.active` 用「左侧 2px 蓝条 + 字色变 ink + 字重 650 + icon 染 accent」四件套标识。

### 7.2 Stage

```
Stage
├── StudentFloatingNotification（固定于视口右上，不占常规布局流）
└── View（一次只显示一个 .is-active）
    ├── WelcomeView   （欢迎 / 首屏）
    └── ConversationView（会话）
```

- 视图切换靠 `setView(view)`（demo JS）：给对应 view 加 `.is-active`、给对应 nav-link / recent-item 加 `.active`、改 `location.hash`。
- 切换到 conversation 会自动 focus 输入框。
- mobile 下切换后会移除 `sidebar-open`，抽屉关闭。

### 7.3 WelcomeView 内部信息层级

```
1. capability-mark  9×N 点阵装饰（纯视觉，aria-hidden）
2. h1 主标题
3. p 副标题
4. Prompt（输入 + 工具）
5. quick-links  快捷入口胶囊
```

### 7.4 ConversationView 内部信息层级

```
1. conversation-heading  会话标题 + 当前场景
2. message-list
   ├── message.user          蓝色气泡，右对齐
   ├── message.assistant     白底，左对齐
   ├── activity-line         青点 + 文字
   ├── plan-inline           内嵌计划卡
   └── …循环…
3. conversation-prompt       复用 .prompt 组件
```

### 7.5 方案 C：全局会话与运营工作台壳层

本节优先于此前文档中的 WelcomeView `continue-row` 描述；其目的是让会话成为学生端任意页面均可访问的稳定导航，而不是只在指挥舱首屏出现的重复内容。

- 学生侧栏固定顺序为：品牌与折叠控制 → 新建会话 → 分组导航 → 最近会话 → 账户菜单。
- 「账户」分组必须包含既有 `/profile` 的「个人中心」入口；不新增第二个资料页入口。
- 「最近会话」是学生工作台的全局槽位，最多在 `220px` 的内部滚动区显示；空态、加载失败、删除确认和选中态均在任意学生路由可访问。
- 从非指挥舱学生页触发新建或打开历史会话时，先路由至 `/`，由 Cockpit 消费一次性 `new/open` 意图。新建仅清空本地会话状态与输入并聚焦 Composer；不得调用 `POST /api/conversations` 创建空会话。
- Agent 运行、确认门或 SSE 恢复期间，侧栏的新建、切换与删除操作必须禁用，避免中断未完成会话。
- 欢迎页仅保留 Hero、Composer 与快捷入口，**不得再渲染「继续学习」/ ContinueRow 或任何会话副本**。

共享运营工作台使用同一组 Token、`272px` 展开侧栏、`68px` 顶栏与折叠图标栏、`≤900px` 移动抽屉、Esc 关闭与焦点回归；但员工端主内容必须保持页面纵向滚动与表格局部横向滚动，不能继承学生指挥舱的内部滚动约束。

| 门户     | 导航分组                     | 壳层边界                                                                                  |
| -------- | ---------------------------- | ----------------------------------------------------------------------------------------- |
| 学生端   | 学习空间、资料与诊断、账户   | 允许会话槽位、场景选择器与固定 Composer。                                                 |
| 教师端   | 教学总览、教学管理、教学洞察 | 复用数据加载与编辑流程；不承载学生会话。                                                  |
| RAG 管理 | 资料管理、检索与质量         | 复用资料、队列、评测与审核页面；表格自行滚动；切片编辑器宽屏三栏、中屏两栏、≤720px 单列。 |
| 系统管理 | 模型与检索、组织与审计       | 复用供应商、参数、权限、安全和审计页面；仅账户菜单提供身份、门户切换和退出。              |

员工端不新增会被角色门禁阻断的「个人中心」路由；身份、门户切换和退出登录均位于侧栏账户菜单。

**v3 升级说明**：以下四个 `§X` 新增章节位于设计原则之后、原组件章节之前；v2 原有章节、功能、数值与行号映射全部保留，新增内容以补充方式叠加。

---

## X. Token 命名规范（v3 新增）

本章只新增命名与提交流程，不改写 v2 的 Token 数值。Token 分三层：**基础（primitive）→ 语义（semantic）→ 组件别名（component alias）**。组件 CSS 只消费语义 Token 或组件别名；禁止在组件规则内直接写 hex、rgb 或 rgba 颜色值。v2 中已经存在的硬编码颜色继续作为迁移对象，迁移时必须保持视觉结果不变。

### X.1 三层模型与命名规则

| 层级       | 责任                                                           | 命名规则                                                                          | 组件使用规则                                       | demo 追溯                                                                |
| ---------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------ |
| 基础层     | 保存可复用的原始色板、尺寸、圆角、阴影、缓动值，不表达业务含义 | `--{category}-{scale-or-role}`，全小写 kebab-case；如 `--blue-600`、`--space-4`   | 只供语义层引用，禁止组件直接依赖                   | demo `:root` L8–L25 已有颜色、尺寸、圆角、shadow、ease 原始值            |
| 语义层     | 表达页面角色或反馈语义，可按主题重映射                         | `--{role}` 或 `--{role}-{variant}`；如 `--canvas`、`--ink-soft`、`--success-soft` | 页面级与通用组件优先使用这一层                     | body L37–L45、prompt L470–L487、activity-line L718–L734、toast L759–L783 |
| 组件别名层 | 将语义角色绑定到具体组件，避免组件内出现上下文判断             | `--{component}-{property-or-state}`；如 `--prompt-border-focus`、`--nav-hover-bg` | 仅对应组件及其变体消费；新组件需先声明别名再写样式 | prompt L470–L487、nav-link L228–L261、toolbar/button L159–L180           |

### X.2 当前 Token 层级清单

下表覆盖 v2 §3 已命名的当前 Token。v2 没有显式基础色板名，因此原始 hex 目前直接挂在语义 Token 上；这属于**兼容现状**，不是新增组件写法。组件别名层目前没有完整的 `:root` 声明，v3 以迁移清单的形式正式预留。

**颜色 Token**

| 当前 Token                     | 当前层级 | v3 归类 / 规则                         | demo 位置                                         |
| ------------------------------ | -------- | -------------------------------------- | ------------------------------------------------- |
| `--canvas`                     | 语义     | 页面画布角色；值来自基础冷灰蓝色板     | L9、body L37–L40                                  |
| `--surface`                    | 语义     | 卡片、输入框与侧栏内嵌白面角色         | L10、prompt L470–L478                             |
| `--surface-soft`               | 语义     | 侧栏与计划卡的弱表面角色               | L11、plan-inline L736–L742                        |
| `--line`                       | 语义     | 常规分割线与控件边角色                 | L12、plan-inline L738–L740                        |
| `--line-strong`                | 语义     | 输入框与主要控件边角色                 | L13、prompt L475–L476                             |
| `--ink`                        | 语义     | 主文字与强 icon 角色                   | L14、body L39–L44                                 |
| `--ink-soft`                   | 语义     | 次级文字与静默按钮字角色               | L15、hero p L457–L463、message L688–L693          |
| `--ink-faint`                  | 语义     | 标签、时间戳、placeholder 弱化角色     | L16、message-label L708–L716                      |
| `--accent`                     | 语义     | 唯一品牌强调、focus、active、send 角色 | L17、focus L57–L62、send-button L550–L569         |
| `--accent-soft`                | 语义     | 强调浅底与 user 气泡浅底角色           | L18、quick-link L571–L612、user message L695–L702 |
| `--teal`                       | 语义     | 活动状态与进行中角色                   | L19、activity-dot L729–L734                       |
| `--amber`                      | 语义     | 警告备用角色                           | L20；v2 demo 未实际使用                           |
| `--success` / `--success-soft` | 语义     | v3 状态色；分别为成功前景与成功浅底    | 新增；映射见 §X+1                                 |
| `--warn` / `--warn-soft`       | 语义     | v3 状态色；分别为警告前景与警告浅底    | 新增；映射见 §X+1                                 |
| `--error` / `--error-soft`     | 语义     | v3 状态色；分别为错误前景与错误浅底    | 新增；映射见 §X+1                                 |
| `--info` / `--info-soft`       | 语义     | v3 状态色；分别为提示前景与提示浅底    | 新增；映射见 §X+1                                 |

v2 §3.1 中列出的 `#dcefe9`、`#126f68`、`#a7afb8`、`#b8c9dc`、`#9dbde2`、`#d9dde2`、`#eef2f6`、`#f0f3f6`、`#d9dee5`、`#b4c8e3`、`#8ed3cb`、`#efc281`、`#cde5e0`、`#235f9f` 以及 `#edf5ff`，当前均为**未命名的语义/组件局部值**。新增或改造组件不得复制这些 hex；应先提升为基础 Token，再通过语义 Token 或组件别名引用。原始出现点与 v2 §14.1 的 L336、L338、L503、L203、L485、L555、L243/L304、L539、L434/L438/L442/L446、L724、L701、L700 对应。

**非颜色 Token**

| 当前 Token / 值                   | 当前层级     | v3 归类 / 规则                                                   | demo 位置                                         |
| --------------------------------- | ------------ | ---------------------------------------------------------------- | ------------------------------------------------- |
| `--shadow-input`                  | 语义         | 输入卡静默阴影；未来可拆基础阴影 + `--prompt-shadow` 别名        | L21、L478                                         |
| `--sidebar-width`                 | 语义         | 工作台布局角色；折叠 `68px` 与移动 `min(272px, 84vw)` 是响应式值 | L22、L69–L74、L794–L800                           |
| `--radius-control`                | 基础         | 当前直接作为通用控件圆角；语义消费名保持不变                     | L23、IconButton L381–L385                         |
| `--radius-input`                  | 基础         | 当前直接作为输入圆角；语义消费名保持不变                         | L24、Prompt L470–L478                             |
| `--ease-out`                      | 基础         | 通用缓动基础 Token                                               | L25、全局 transition 与 L902–L909                 |
| `6px / 10px / 14px / 999px / 50%` | 基础未命名值 | v3 新增时按 `--radius-{role}` 命名，不在组件内新增裸值           | v2 §3.5、prompt toolbar L521–L529、plan L736–L742 |
| `140ms / 160ms / 180ms / 100ms`   | 基础未命名值 | v3 新增时按 `--duration-{role}` 命名；保持 v2 时长档             | v2 §3.7、动效 L623–L637                           |

### X.3 命名硬规则

- [ ] 只用 kebab-case：允许 `--accent-soft`、`--prompt-border-focus`，禁止 `--accentSoft`、`--PromptBorder`。
- [ ] Token 名称只描述角色，不把页面文案、业务实体或临时状态写进基础层；例如用 `--success`，不用 `---green-for-plan`。
- [ ] 组件内禁止直接写 hex / rgb / rgba；必须引用 `var(--semantic-token)` 或 `var(--component-alias)`。
- [ ] 同一语义只保留一个正式 Token；兼容别名必须标注迁移目标与删除条件。
- [ ] 暗色主题只在主题作用域重映射 Token，不复制一套带 `-dark` 后缀的组件 CSS；策略见 §X+2。
- [ ] 新增颜色必须同时说明前景 / 背景、对比度、使用场景和 demo 映射；不能只提交一个色值。

### X.4 新增 Token 提交流程

1. **提出语义**：说明要解决的 UI 角色、组件、默认态与主题态，先判断是否可复用已有 Token。
2. **确定层级**：基础值进入基础层；页面/反馈角色进入语义层；仅组件专用的属性进入组件别名层。
3. **命名与对比度检查**：按 kebab-case 命名，禁止组件内 hex；检查正文 ≥4.5:1、非正文与边界的可辨识度，并记录计算结果。
4. **补齐主题与状态**：如颜色 Token，同时给出 `:root` 与 `:root[data-theme="dark"]` 值；如有 soft 变体，成对提交。
5. **补 demo 映射**：在本规范对应章节与 §14 增加 demo 文件行号、选择器或属性；若 demo 尚未使用，明确写“v3 预留”。
6. **实现与验证**：先在 `:root` 声明，再替换组件中的硬编码值；验证桌面、≤900、≤560、键盘 focus 和 reduced-motion。
7. **评审与合并**：设计评审确认语义与视觉，前端评审确认命名、主题覆盖和无障碍，合并后更新末尾变更记录。

**与 demo 的追溯入口**：Token 源头为 `student-workbench-layout-demo.html` L8–L26；消费入口重点为 body L37–L45、nav L228–L261、prompt L465–L569、quick-links L571–L612、message L682–L753、toast L759–L783。

---

## X+1. 状态色 Token（v3 新增）

v3 在 `--accent`、`--teal`、`--amber` 之外正式补齐四组状态 Token。数值参考 Tailwind / IBM 的冷静、可读状态体系，并收敛到本规范的冷蓝灰语义：实色用于文字、icon、点、边或小面积控件，soft 色用于浅底；禁止以状态色大面积替代 `--canvas` 或 `--surface`。

### X+1.1 正式定义

```css
:root {
  --success: #159b91;
  --success-soft: #e7f6f4;
  --warn: #bf7417;
  --warn-soft: #fff3df;
  --error: #a33a45;
  --error-soft: #fbecee;
  --info: #2477d6;
  --info-soft: #edf5ff;
}
```

| Token            | 值        | 角色                                     | 与既有 Token 的关系                                       | demo 追溯                                |
| ---------------- | --------- | ---------------------------------------- | --------------------------------------------------------- | ---------------------------------------- |
| `--success`      | `#159b91` | 成功文字、图标、完成点                   | 与 `--teal` 同值，`--teal` 保留为活动点兼容名             | `--teal` L19；activity-dot L729–L734     |
| `--success-soft` | `#e7f6f4` | 成功提示、完成状态浅底                   | v2 无同名 Token；基于 `#cde5e0` 活动线浅青扩展            | activity-line L718–L727                  |
| `--warn`         | `#bf7417` | 警告文字、图标、边                       | 与 `--amber` 同值，`--amber` 保留为警示备用兼容名         | `--amber` L20；v2 §3.1                   |
| `--warn-soft`    | `#fff3df` | 警告提示浅底                             | v2 无同名 Token；v3 预留                                  | `--amber` L20（语义源）                  |
| `--error`        | `#a33a45` | 错误文字、错误 icon、错误边              | 自定义深红，避免与 accent / amber 混淆                    | v3 预留；demo 暂无错误态                 |
| `--error-soft`   | `#fbecee` | 错误提示浅底                             | v3 预留                                                   | v3 预留；demo 暂无错误态                 |
| `--info`         | `#2477d6` | 信息文字、提示 icon、focus / link 延续色 | 与 `--accent` 同值，`--accent` 仍是品牌命名               | `--accent` L17、focus L57–L62            |
| `--info-soft`    | `#edf5ff` | 信息提示浅底、user 气泡浅底              | 与 `--accent-soft` 同值，`--accent-soft` 仍是品牌浅底命名 | `--accent-soft` L18、user 气泡 L695–L702 |

### X+1.2 使用场景映射

| 用户可感知语义 | 正式 Token                     | 兼容 / 具体映射                                                       | 允许场景                                   | 不允许场景                                 | demo 证据                                                 |
| -------------- | ------------------------------ | --------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------ | --------------------------------------------------------- |
| 成功           | `--success` / `--success-soft` | 成功 → teal；`--success` = `--teal`                                   | 完成 toast、完成点、成功反馈、已完成活动线 | 不用作品牌按钮或整屏底色                   | activity-line 的青点与完成文案 L718–L734；toast L759–L783 |
| 警告           | `--warn` / `--warn-soft`       | 警告 → amber；`--warn` = `--amber`                                    | 风险提醒、需要注意的输入、未完成前置条件   | 不用作错误、品牌 active 或正文大面积底色   | `--amber` L20；demo 当前未启用                            |
| 错误           | `--error` / `--error-soft`     | 自定义深红                                                            | 发送失败、校验失败、不可恢复错误           | 不用替代警告；必须配文字说明，不能只靠颜色 | demo 当前无错误态，v3 预留                                |
| 提示 / 信息    | `--info` / `--info-soft`       | 提示 → accent；`--info` = `--accent`，`--info-soft` = `--accent-soft` | 普通提示、链接、focus、user 气泡           | 不把普通提示误标为成功或警告               | focus L57–L62；quick-link L571–L612；user 气泡 L695–L702  |

**状态组合规则**：实色与 soft 色成对出现；状态消息必须同时包含文字或可访问名称；状态不可仅用青 / 琥珀 / 深红区分。demo 的默认视觉仍保持单一品牌蓝、青色活动点、琥珀预留的 v2 结果。

**与 demo 的追溯入口**：基础定义对应 demo `:root` L17–L20；成功消费对应 activity-line L718–L734；信息消费对应 focus L57–L62、quick-link L571–L612、user message L695–L702；Toast 语义对应 L759–L783；warn/error 为 v3 预留。

---

## X+2. 深色模式（v3 新增）

深色模式只替换颜色 Token，不复制组件结构。激活方式为在工作台根节点挂属性：

```html
<html data-theme="dark">
  <!-- demo-shell 与应用内容 -->
</html>
```

应用应把 `data-theme="dark"` 设置在 `html` 根元素上；CSS 统一使用 `:root[data-theme="dark"]`，避免组件树级联不一致。**不得使用 `prefers-color-scheme` 自动跟随操作系统**；亮色是默认结果，暗色只能由明确的用户或产品设置触发。

### X+2.1 深色 Token 映射表

| Token                | 亮色 v2 值              | 深色 v3 值 | 暗色用途与对比说明                         | demo 追溯                            |
| -------------------- | ----------------------- | ---------- | ------------------------------------------ | ------------------------------------ |
| `--canvas`           | `#f7f8fa`               | `#0f1720`  | 页面冷蓝黑画布                             | body L37–L40                         |
| `--surface`          | `#ffffff`               | `#17212b`  | 卡片、输入框、侧栏主面                     | shell L69–L74、prompt L470–L478      |
| `--surface-soft`     | `#fbfcfd`               | `#202b36`  | 侧栏弱面、计划卡弱面                       | sidebar / plan L736–L742             |
| `--line`             | `#e5e8ec`               | `#30404e`  | 常规分割线                                 | Token L12、plan L738–L740            |
| `--line-strong`      | `#d4d9e0`               | `#465868`  | 输入框与主要控件边                         | prompt L475–L476                     |
| `--ink`              | `#17212b`               | `#f3f6f8`  | 主标题、关键正文                           | body / hero L448–L455                |
| `--ink-soft`         | `#5f6b76`               | `#c4ced6`  | 次级正文、消息正文                         | hero p L457–L463、message L688–L693  |
| `--ink-faint`        | `#98a2ad`               | `#8f9eaa`  | 标签与时间戳；不得承载唯一关键信息         | message-label L708–L716              |
| `--accent`           | `#2477d6`               | `#66a9f5`  | 暗色链接、active、focus；提高亮度保留约 AA | focus L57–L62、send L550–L569        |
| `--accent-soft`      | `#edf5ff`               | `#1e3a5f`  | 蓝色弱底、品牌 hover、user 气泡底          | quick-link L571–L612、user L695–L702 |
| `--teal`             | `#159b91`               | `#46c7bd`  | 活动点与成功色                             | activity-dot L729–L734               |
| `--amber`            | `#bf7417`               | `#e5a54a`  | 警告色；深色背景上保持可见                 | `--amber` L20                        |
| `--success`          | `#159b91`               | `#46c7bd`  | 成功实色                                   | v3 状态定义                          |
| `--success-soft`     | `#e7f6f4`               | `#173d3b`  | 成功弱底                                   | v3 状态定义                          |
| `--warn`             | `#bf7417`               | `#e5a54a`  | 警告实色                                   | v3 状态定义                          |
| `--warn-soft`        | `#fff3df`               | `#4a351b`  | 警告弱底                                   | v3 状态定义                          |
| `--error`            | `#a33a45`               | `#ef8290`  | 错误实色                                   | v3 状态定义                          |
| `--error-soft`       | `#fbecee`               | `#48252d`  | 错误弱底                                   | v3 状态定义                          |
| `--info`             | `#2477d6`               | `#66a9f5`  | 信息实色，暗色下映射到 accent              | v3 状态定义                          |
| `--info-soft`        | `#edf5ff`               | `#1e3a5f`  | 信息弱底，暗色下映射到 accent-soft         | v3 状态定义                          |
| `--user-bubble`      | `#edf5ff`（当前硬编码） | `#1e3a5f`  | user 消息气泡底；新代码使用别名            | user L695–L702                       |
| `--user-ink`         | `#235f9f`（当前硬编码） | `#b9dcff`  | user 消息文字；确保与 bubble 对比          | user L700–L701                       |
| `--nav-hover`        | `#eef2f6`（当前硬编码） | `#263746`  | 导航 / recent hover 底                     | nav / recent v2 §14.1 L243、L304     |
| `--prompt-btn-hover` | `#f0f3f6`（当前硬编码） | `#2a3947`  | prompt toolbar 按钮 hover 底               | toolbar L521–L529；v2 §14.1 L539     |

```css
:root[data-theme="dark"] {
  --canvas: #0f1720;
  --surface: #17212b;
  --surface-soft: #202b36;
  --line: #30404e;
  --line-strong: #465868;
  --ink: #f3f6f8;
  --ink-soft: #c4ced6;
  --ink-faint: #8f9eaa;
  --accent: #66a9f5;
  --accent-soft: #1e3a5f;
  --teal: #46c7bd;
  --amber: #e5a54a;
  --success: #46c7bd;
  --success-soft: #173d3b;
  --warn: #e5a54a;
  --warn-soft: #4a351b;
  --error: #ef8290;
  --error-soft: #48252d;
  --info: #66a9f5;
  --info-soft: #1e3a5f;
  --user-bubble: #1e3a5f;
  --user-ink: #b9dcff;
  --nav-hover: #263746;
  --prompt-btn-hover: #2a3947;
}
```

迁移要求：将 demo 中 user 气泡、nav hover、prompt toolbar hover、prompt focus 边等硬编码颜色提升为对应语义 / 组件别名后，暗色主题才能完整生效。暗色下仍要复核实际对比度，尤其是 `--ink-faint`、边框与状态 soft 底；不得因“看得见”而跳过文字对比度验收。

### X+2.2 激活与保持不变的 Token

- [ ] 默认不带 `data-theme` 时保持 v2 亮色结果。
- [ ] `html[data-theme="dark"]` 或规范根节点 `:root[data-theme="dark"]` 激活暗色映射；切换主题不改变 URL、视图、输入内容或会话状态。
- [ ] 颜色过渡沿用 v2 的 140ms / 160ms 档；不新增超过 200ms 的 hover。
- [ ] 深色模式下**所有尺寸、间距、圆角、字号、字重、行高与动效契约均保持不变**；只允许颜色 Token 与对应阴影颜色按主题映射变化。
- [ ] 以下在深色下保持不变：侧栏 272px、折叠 68px、toolbar 68px / 移动 60px、主区最大宽 900px、quick-link 最大宽 980px。
- [ ] 以下在深色下保持不变：所有 v2 间距阶梯、容器 padding、断点 `≤900px` / `≤560px`、圆角 6 / 8 / 10 / 14 / 16 / 999px / 50%。
- [ ] 以下在深色下保持不变：字体栈、字号阶梯、字重、行高、消息气泡宽度、`--ease-out` 与 100 / 140 / 160 / 180ms 动效档。

**与 demo 的追溯入口**：主题根变量对应 demo L8–L26；页面消费对应 body L37–L45、shell L69–L74、prompt L470–L503、nav L228–L261、消息 L695–L702；响应式尺寸与动效保持规则对应 L789–L909。

---

## X+3. 无障碍清单（v3 新增）

本章把 v2 §8、§11、§13 与 §15 的零散要求合并成可执行清单。每次新增组件、主题或交互都要逐项勾选，并在验收记录中附 demo 行号或测试证据。

### X+3.1 感知与对比度

- [ ] 正文文字与背景对比度 ≥ 4.5:1；大字号文字按产品验收策略单独记录，不以低对比度辅助色承载关键信息。
- [ ] 主文字、次级正文、链接、按钮文字、user 气泡文字在亮色与深色主题分别复核；`--ink-faint` 只用于标签 / 时间戳 / 装饰性辅助信息。
- [ ] 状态不只依赖颜色：success / warn / error / info 必须同时有文字、icon、形状或位置等非颜色线索。
- [ ] focus、active、hover 与 disabled 的状态在 `--canvas`、`--surface`、`--surface-soft` 上均可辨识；边框不能只靠 1px 低对比度灰线。
- [ ] `capability-mark` 等纯装饰元素标记 `aria-hidden="true"`，不向读屏器暴露无意义点阵。

**demo 映射**：v2 对比度表 §3.3；主文字 / 次文字消费 body L37–L45、hero L448–L463；user 气泡 L695–L702；装饰点阵 L450–L455；状态色正式值与主题值见 §X+1 / §X+2。

### X+3.2 键盘与焦点

- [ ] 所有按钮、链接、textarea、抽屉关闭入口和可点击 recent-item 均可通过键盘到达，并具有可见的操作顺序。
- [ ] 所有交互元素均提供 `:focus-visible` **2px 描边**，颜色使用 `--accent`，并保留 **2px offset**；禁止用 `outline: 0` 消除唯一焦点提示。
- [ ] Enter 发送、Shift+Enter 换行的键盘契约与鼠标提交一致；快捷键提示若未实现必须标注占位，不得误导用户。
- [ ] 打开移动抽屉后焦点进入抽屉，Esc 可关闭，关闭后焦点回到 mobile-menu；抽屉打开时背景内容不可被键盘误操作。
- [ ] 折叠态隐藏文案后，仍为可操作 icon 保留 `aria-label` / `title`；纯装饰 icon 使用 `aria-hidden="true"`。

**demo 映射**：focus 规则 L57–L62；IconButton L159–L180；Prompt L465–L569；mobile drawer L789–L812 与 JS L1378–L1393；Ctrl K 占位 JS L1402–L1411。

### X+3.3 动态内容与语义

- [ ] Toast 使用 `role="status" aria-live="polite"`，只播报状态，不抢占用户当前输入焦点。
- [ ] message-list 使用 `aria-live="polite"`；新 assistant / activity / plan 内容按自然顺序播报，避免每次 DOM 重排重复朗读全部历史。
- [ ] 消息来源、活动线、计划卡有可读结构：user / assistant label、状态文字和标题不能只存在于颜色或装饰中。
- [ ] 视图切换更新可感知标题 / 当前区域；切到 conversation 后 focus 输入框的行为不打断用户已主动聚焦的控件。
- [ ] 表单提交失败、输入为空、状态切换等反馈有可读文本，并能被键盘和读屏器感知。

**demo 映射**：Toast DOM 与语义 L759–L783 及 L1245–L1253；message-list L682–L686、L1293–L1310（v3 要补 `aria-live="polite"`）；视图切换与 focus JS L1255–L1268。

### X+3.4 触控、缩放与动效

- [ ] icon-button、send-button、mobile-menu、关闭抽屉和其它主要点击目标的可点击区域 ≥ **34×34px**；图标可小于点击区域，但不可缩小承载区域。
- [ ] 布局支持字号缩放与内容增长，不用固定高度裁切正文；长文、中文换行、横向 quick-links 均不丢失内容。
- [ ] ≤560 时 prompt textarea 字号为 **16px**，避免 iOS Safari 因小于 16px 自动缩放；用户可正常放大页面，不得禁用 viewport 缩放。
- [ ] `prefers-reduced-motion: reduce` 下关闭 smooth scroll，将 transition-duration 压到 1ms 或等效无动效；关键状态不可依赖动画完成才可用。
- [ ] 不使用 `transition: all`、循环装饰动画或超过 200ms 的 hover；按下反馈仍为短促的 scale 变化。

**demo 映射**：IconButton 34×34 L159–L180；send-button 38×38 L550–L569；prompt ≤560 字号与内边距 L859–L889；responsive 与字号 L789–L900；reduced-motion L902–L909；动效契约 L623–L643。

### X+3.5 验收签名

- [ ] 设计评审：亮 / 暗主题、状态色、对比度与非颜色线索已确认。
- [ ] 前端评审：键盘顺序、focus-visible 2px、ARIA live、点击区域与缩放已验证。
- [ ] QA 评审：桌面 / 平板 / 手机、键盘、读屏器、reduced-motion 与主题切换均有记录。
- [ ] 回归完成：新增 Token 已按 §X.4 提交，demo 映射已补入 §14，且 v2 原有功能与默认亮色结果未改变。

**与 demo 的追溯入口**：全局 focus L57–L62、交互语义 L914–L1060、动态消息 JS L1245–L1326、响应式 L789–L909；v2 原有可访问性验收仍保留在 §13.4。

---

## 8. 组件清单

> 下列每个组件都来自 demo。所有尺寸、状态、token 写明，**实现时不要再凭感觉调**。每节给出：结构 / 尺寸 / 状态 / 交互 / 无障碍。

### 8.1 IconButton

- **结构**：`<button class="icon-button">`，内放 18×18 Lucide 图标。
- **尺寸**：34×34，圆角 `--radius-control`，`display: inline-grid; place-items: center`。
- **状态**：默认透明 / `--ink-soft` 字；hover `--line` 底 / `--ink` 字；focus-visible 2px accent + 2px offset。
- **交互**：click 触发业务；mobile-menu 变体默认 `display: none`，≤900 显示。
- **无障碍**：所有变体必须有 `aria-label` 与 `title`，icon 自身 `aria-hidden` 由按钮承接语义。

### 8.2 Brand

- **结构**：`<a class="brand" href="#welcome">` 含 32×32 logo + `.brand-copy` 文字。
- **尺寸**：`display: inline-flex; gap: 10px; align-items: center; min-width: 0`。
- **状态**：折叠态 `.brand-copy { display: none }`，整条 brand 居中；其它无 hover 态。
- **交互**：点击回到欢迎视图（`#welcome`）。
- **无障碍**：`aria-label="标航智导首页"`；logo `alt=""`（纯装饰）。

### 8.3 NewSession

- **结构**：`<button class="new-session">` 含 plus-circle 图标 + 「新建会话」文案 + `Ctrl K` 提示。
- **尺寸**：高 46px，`width: calc(100% - 24px); margin: 4px 12px 18px; padding: 0 14px`；圆角 `--radius-control`。
- **样式**：边 `--line-strong`，白底，`box-shadow: 0 1px 2px rgba(26, 39, 52, 0.03)`；icon `--accent` 色。
- **状态**：hover 边 `#b8c9dc`、底 `--accent-soft`；focus-visible 2px accent。
- **交互**：click 清空两个 textarea + `setView("welcome")` + toast「已开始新会话」。
- **折叠态**：变成 44×44 圆形居中按钮，文案隐藏。
- **无障碍**：`id="newSessionButton"`；`Ctrl K` 是**设计占位**，**不绑定快捷键**（上线前要么去掉、要么真绑定并同步规范）。

### 8.4 NavLink

- **结构**：`<a class="nav-link" data-view="..."><i icon/><span>文案</span></a>`。
- **尺寸**：高 `min-height: 38px; padding: 0 10px; gap: 11px`；圆角 `--radius-control`。
- **样式**：icon 17×17，默认 `--ink-faint`。
- **状态**：hover / active `#eef2f6` 底 + `--ink` 字；active 额外 `box-shadow: inset 2px 0 0 var(--accent)` + `font-weight: 650` + icon 变 `--accent`。
- **折叠态**：所有文字 `display: none`，整条居中。
- **交互**：href=`#welcome` / `#conversation`（其它 demo nav 触发 toast「演示原型只展示指挥舱布局」）。
- **无障碍**：`<nav aria-label="学习空间">`；折叠态隐藏后，screen reader 仍能读到（CSS display: none 同步隐藏 a11y 树）。

### 8.5 NavLabel（分组标题）

- **结构**：`<span class="nav-label">`。
- **样式**：`margin: 14px 10px 7px; 11px / 700 / letter-spacing 0.04em / uppercase / --ink-faint`。
- **折叠态**：`display: none`。

### 8.6 RecentList

- **结构**：`<section class="recent">` 内 `.recent-header`（标题 + ellipsis icon）+ `.recent-list`（若干 `.recent-item`）。
- **尺寸**：`.recent-list` `max-height: 220px; overflow: auto`。
- **recent-item**：`padding: 9px 10px; gap: 3px; border-radius: 8px`；`.recent-title` `13px` 单行省略；`.recent-meta` `11px --ink-faint`。
- **状态**：hover / active 同 nav-link 的 `#eef2f6` 底。
- **交互**：点击触发 `setView("conversation")` 并 focus 输入框。
- **无障碍**：`<section aria-labelledby="recentTitle">`；item 用 `<button>` 包裹，可键盘操作。

### 8.7 SidebarFooter

- **结构**：`<footer class="sidebar-footer">` 含 32×32 圆形头像缩写 + 用户名 + 角色 + more icon 按钮。
- **尺寸**：`margin-top: auto; padding: 16px 18px 18px; border-top: 1px solid var(--line)`。
- **样式**：头像 `#dcefe9` 底 / `#126f68` 字；`.user-name` `650 / --ink`；`.user-role` `11px / --ink-faint`。
- **折叠态**：`.user-copy` 与 footer icon 隐藏。
- **交互**：more 按钮打开个人菜单（本期未实现，预留）。
- **无障碍**：头像 `aria-hidden="true"`（避免与 user-name 重复读屏）。

### 8.8 StudentFloatingNotification

- **结构**：学生侧栏继续承载品牌、导航与账户；通知铃铛通过 `.student-workbench-floating-actions` 渲染。对话路由将该入口视觉对齐到 `.conversation-info-bar` 右侧，其他学生路由不新增顶部操作栏。
- **定位**：对话页顶部栏覆盖侧栏之外的主区宽度，通知入口位于栏右侧；其他路由容器继续使用 `position: fixed` 固定在视口右上，均不占用 Composer 的布局高度。
- **交互**：通知铃铛保留未读计数、下拉列表、轮询、已读操作和运行中禁用状态。
- **无障碍**：icon-button 带 `aria-label` 与 `title`；下拉面板保持现有焦点与键盘行为。
- **移动端**：≤560 仍保持可见；下拉面板以视口宽度为上限，避免向左溢出，不依赖“最后一个子项”等脆弱选择器。

### 8.9 Hero

- **结构**：`.hero` 居中容器，内含 `.capability-mark` + h1 + p。
- **尺寸**：`width: min(900px, 100%); text-align: center`。
- **capability-mark**：`grid-template-columns: repeat(9, 7px); gap: 5px`；默认方块 `#d9dee5`；三条 nth-child 公式分别着 `#b4c8e3 / #8ed3cb / #efc281`。
- **h1**：`clamp(30px, 3.2vw, 48px) / 720 / 1.15 / --ink`，≤900 改 32px 固定。
- **p**：`max-width: 560px; margin: 15px auto 30px; 15px / 1.7 / --ink-soft`，≤560 改 14px。
- **无障碍**：`.capability-mark` 整块 `aria-hidden="true"`（纯装饰）。

### 8.10 Prompt（核心输入组件）

- **结构**：`<form class="prompt-wrap">` 内 `.prompt` 容器，上 textarea，下 `.prompt-toolbar`（左 `.prompt-tools`、右 `.prompt-settings`）。
- **尺寸（欢迎页 Hero）**：宽 `min(900px, 100%)`、居中、`min-height: 188px`（移动端 `162px`）；`padding: 18px 18px 12px`（移动端 `14px 12px 10px`）；圆角 `--radius-input 16px`，白底。
- **尺寸（已有对话 Composer）**：仅在已有对话态压缩为约 `144px` 总高，textarea 最小高度约 `64px`；欢迎页 Hero 必须保持上述既有尺寸，不随该变体缩小。
- **样式**：边 `--line-strong`，静默态有 `--shadow-input`；`:focus-within` 边变 `#9dbde2`、阴影换成蓝色 `0 18px 42px rgba(36,119,214,0.12)`。

#### 子组件（详见 §8.10.1 / 8.10.2）

| 元素     | 类                          | 尺寸                                                                                                                   | 状态                                                                       |
| -------- | --------------------------- | ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| textarea | —                           | Hero `min-height: 90px`；已有对话 Composer `min-height: 64px`；`font: 17px / 1.6; border: 0; outline: 0; resize: none` | `placeholder` `#a7afb8`                                                    |
| 加号按钮 | `.tool-button`              | `min-height: 32px; padding: 0 9px; border-radius: 6px; gap: 7px`                                                       | 透明 / hover `#f0f3f6 + --ink`                                             |
| 场景切换 | `.composer-scenario-select` | 输入框下方与上传、发送同排；键盘可操作；不显示额外 FolderOpen 装饰图标；最大宽度 `160px`                              | ≤560 保持可见并允许文本截断                                                |
| 发送按钮 | `.send-button`              | `38×38` 圆形                                                                                                           | 默认 `#d9dde2 + 白 icon`；`has-value`/hover `--accent`；按下 `scale(0.96)` |

#### 8.10.2 行为契约

- `Enter` 发送；`Shift+Enter` 换行。
- 输入为空时发送按钮灰色（`#d9dde2`），输入有值时（`.has-value`）变蓝（`--accent`）。
- 提交时由 form `requestSubmit()` 触发（`bindComposer`，demo JS）。
- 设置场景后，setting-button 文字要更新为「当前场景 · xxx」。

### 8.11 QuickLinks

- **结构**：容器 `display: flex; justify-content: center; gap: 8px`，内若干 `.quick-link`。
- **按钮**：胶囊 `border-radius: 999px`、`min-height: 36px`、`padding: 0 13px`、边 `--line`、白底；icon `15×15`；文字 `--ink-soft`。
- **状态**：hover 边 `#aec7e4`、底 `--accent-soft`、字 `--accent`。
- **间距**：上 `margin: 24px auto 0`。
- **滚动**：横向滚动 + 隐藏滚动条（`scrollbar-width: none` + webkit 隐藏）；≤900 `justify-content: flex-start`（贴左横滚）。
- **交互**：点击把 `data-fill` 文本填入 textarea 并 focus。
- **无障碍**：容器 `aria-label="快捷入口"`；按钮含可见文字 + icon（icon `aria-hidden`）。

### 8.12 ContinueRow（已废弃）

- **状态**：方案 C 起不再实现。历史会话统一由侧栏 `RecentList` 提供，避免欢迎页和全局导航同时显示同一份会话数据。
- **替代交互**：最近会话点击后通过一次性 `open` 意图切换至 `/` 并恢复会话；该行为在运行中禁用。

### 8.13 MessageList

- **结构**：`<div class="message-list" id="messageList">`，内含若干 `.message` / `.activity-line` / `.plan-inline`。
- **容器**：`display: grid; gap: 22px; flex: 1`。
- **message 默认**：`max-width: 82%; font: 15px / 1.75; color: var(--ink-soft)`。
- **message.user**：`max-width: 72%; justify-self: end; padding: 12px 15px; border-radius: 14px 14px 4px 14px; background: --accent-soft; color: #235f9f`。
- **message.assistant**：`padding-left: 2px`（无气泡）。
- **message-label**：块级、`11px / 700 / uppercase / --ink-faint / 0.04em / margin-bottom: 5px`。
- **响应式**：≤560 两个气泡都 `max-width: 100%`。
- **无障碍**：消息列表使用 `aria-live="polite"`；对话信息栏使用 `role="status"`，标题与继续场景变更可被读屏感知。

### 8.14 ActivityLine

- **结构**：`<div class="activity-line">` 含 7×7 青点 + 文字。
- **样式**：左边线 `border-left: 2px solid #cde5e0; padding-left: 12px; margin: 4px 0 0 2px`；文字 `--ink-faint 12px`；圆点 `var(--teal)`。
- **语义**：表示 Agent 内部活动（已完成的子任务），区别于对话消息。
- **响应式**：与 message-list 共用网格（`gap: 22px`）。

### 8.15 PlanInline

- **结构**：`<div class="plan-inline">` 含 h2「今天的练习路径」+ 若干 p（步骤列表）。
- **尺寸**：`margin-top: 13px; padding: 15px 16px`；边 `--line`；圆角 10px；底 `--surface-soft`。
- **样式**：h2 `13px / --ink`；p `13px / --ink-soft / margin: 7px 0 0`。
- **语义**：从对话中内嵌出来的"任务卡"，可在未来拆为独立卡片组件。
- **响应式**：宽度跟随 message-list，移动端 padding 不变。

### 8.16 DemoToast

- **结构**：`<div class="demo-toast" role="status" aria-live="polite">`。
- **位置**：`fixed; right: 22px; bottom: 22px; z-index: 10`；宽 `max-width: min(320px, calc(100vw - 44px))`。
- **样式**：`padding: 10px 13px; border: 1px solid var(--line); border-radius: 8px; background: var(--ink); color: #fff; box-shadow: 0 12px 30px rgba(20,29,38,0.17); font-size: 12px`。
- **状态**：默认 `opacity: 0; transform: translateY(8px); pointer-events: none`；`.is-visible` 切到 `opacity: 1; transform: translateY(0)`。
- **动画**：`160ms var(--ease-out)`。
- **持续**：`setTimeout 1800ms` 后移除 `.is-visible`。
- **无障碍**：`role="status" aria-live="polite"`；文本可被 SR 自动播报。

### 8.17 Sidebar Collapse 行为

- **触发**：header 右侧 `panel-left-close` 按钮；点击后根 `.demo-shell` 加 `.sidebar-collapsed`。
- **效果**：`grid-template-columns: 68px minmax(0, 1fr)`。
- **折叠态隐藏**：`.brand-copy / .new-session span / .nav-label / .nav-link span / .recent / .user-copy / .sidebar-footer .icon-button`。
- **new-session 折叠**：变成 44×44 居中按钮；`.sidebar-nav` padding 缩到 `0 12px`；footer padding 改成 `16px 0 18px`。
- **响应式约束**：≤900 不折叠（直接走抽屉）。
- **设计红线**：折叠态不要变成模态 / 二级菜单做导航替代（demo 注释 L76–L77 明示）。

---

## 9. 两套界面布局

### 9.1 Welcome View（首屏）

| 区           | 数值                                                                           | 说明                             |
| ------------ | ------------------------------------------------------------------------------ | -------------------------------- |
| 容器         | `width: min(900px, 100%); margin: 0 auto`                                      | hero 与 prompt 居中              |
| 外层 padding | `clamp(76px, 15vh, 146px) 28px 48px`                                           | 中屏 `80 16 32`、手机 `54 16 32` |
| 章节间距     | hero 与 prompt 之间 0；prompt 与 quick-links 之间 `24px`；最近会话不进入欢迎页 |                                  |
| 焦点         | prompt 是页面焦点                                                              | textarea、focus 描边、阴影三件套 |

### 9.2 Conversation View（会话）

| 区           | 数值                                                               | 说明                                                                           |
| ------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| 容器         | `width: min(900px, 100%); margin: 0 auto; padding: 58px 28px 28px` | 中屏 `36 16 20`                                                                |
| info bar     | 当前对话标题，覆盖侧栏之外的主区顶部，并在右侧容纳通知入口              | 有会话时才出现，作为 `.cockpit-content-scroll` 外的常驻 sibling，不随消息历史滚动 |
| message-list | `display: grid; gap: 22px; flex: 1; overflow-y: auto`              | 仅消息区滚动，输入框保持可见                                                   |
| Composer     | 消息区外的固定 sibling，场景 Select 放在文本输入框下方             | 仅已有对话态约 `144px` 总高、textarea 约 `64px`；欢迎页 Hero 维持 §8.10 原尺寸 |

路由页（除 `/` 对话界面）统一由学生工作台主区提供 `28px` 顶部留白（移动端 `68px` 菜单安全区），对话页关闭这层顶部留白，由自身消息区和 Composer 管理高度。
| 消息气泡 | assistant `max-width: 82%`、user `max-width: 72%`，≤560 都改 `100%` | |
| conversation-prompt | `margin-top: 38px` | 复用 `.prompt` 组件 |
| 焦点 | 切换到本视图自动 focus 输入框 | |

### 9.3 切换行为契约

1. toggle 两个 view 的 `.is-active`；
2. toggle 对应 `[data-view]` 元素的 `.active`（仅 nav-link 着色，recent-item 也会亮，但样式与 nav-link 共享）；
3. 若切换到 conversation，自动 `conversationInput.focus()`；
4. 改 `location.hash` 为 `welcome` 或 `conversation`；
5. mobile 下切换后移除 `.sidebar-open`，关闭抽屉；
6. 进入页面时若 `location.hash === "#conversation"` 自动切到会话视图。

---

## 10. 会话消息 / 活动线 / 计划卡

### 10.1 消息（message）

| 类型      | 位置                      | 容器               | 圆角                 | 文字                                   | 行号      |
| --------- | ------------------------- | ------------------ | -------------------- | -------------------------------------- | --------- |
| assistant | 左对齐                    | 透明（无气泡）     | —                    | `--ink-soft`                           | L704–L706 |
| user      | 右对齐                    | `--accent-soft` 底 | `14px 14px 4px 14px` | `#235f9f`                              | L695–L702 |
| label     | 块级，位于 assistant 顶部 | —                  | —                    | `11px / 700 / uppercase / --ink-faint` | L708–L716 |

**消息间距**：`gap: 22px`；消息内段落不留额外 margin（demo 中纯文本无 `<p>` 包裹，单段间距靠 line-height 1.75）。

**响应式**：≤560 两类气泡都 `max-width: 100%`，避免窄屏出现"右对齐气泡撞满边缘"的视觉冲突。

### 10.2 活动线（activity-line）

形态：**「左边 2px 青线 + 7px 青点 + 12px 文字」**。表达"Agent 内部完成了一个子步骤"，与 user/assistant 消息**不互换**。

- 实现：`.activity-line { border-left: 2px solid #cde5e0; padding-left: 12px; margin: 4px 0 0 2px; }`
- 颜色：`#cde5e0` 边线，`var(--teal)` 圆点，`--ink-faint 12px` 文字。
- 何时出现：仅当 Agent 在生成消息过程中产生了可被记录的活动（"已完成能力定位 · 找到 2 个适合今天练习的主题"）。

### 10.3 计划卡（plan-inline）

形态：**内嵌于 assistant 消息之后、内边距 15×16、圆角 10、白底浅灰、1px `--line` 边** 的任务卡。

- h2：「今天的练习路径」13px。
- p：步骤列表，13px `--ink-soft`，行间距 7px。
- 何时出现：Agent 完成能力定位后，给出可执行步骤时。
- 未来拆分：可独立成 `<article class="plan-card">`，与对话流平级，本期保持内嵌以保持视觉轻盈。

### 10.4 顺序示例（demo 中默认 session）

```
[user] 我想从 NER 和分类规范开始学习文本标注。
[assistant · 标航智导] 好的。我会先定位你的学习起点，再按规范、示例和练习安排一条可执行的路径。
[activity-line] 已完成能力定位 · 找到 2 个适合今天练习的主题
[plan-inline] 今天的练习路径：1. NER 实体边界识别 2. 分类标签选择 3. 用一组样例完成自测
[assistant · 下一步] 先从实体边界开始。你可以继续提问，也可以让我生成一张练习任务卡。
```

---

## 11. 动效

### 11.1 时长档

| 场景               | 属性                      | 时长    | 缓动              |
| ------------------ | ------------------------- | ------- | ----------------- |
| 颜色 hover         | bg / color / border-color | `140ms` | `var(--ease-out)` |
| Prompt 边框 / 阴影 | border / box-shadow       | `160ms` | `var(--ease-out)` |
| 抽屉               | transform                 | `180ms` | `var(--ease-out)` |
| Send 按钮按下      | `transform: scale(0.96)`  | `100ms` | `var(--ease-out)` |
| Toast 浮起         | opacity / transform       | `160ms` | `var(--ease-out)` |

### 11.2 原则

- **时长档**：`100 / 140 / 160 / 180`。**禁止**新增 `200ms+` 的 hover。
- **空间变化例外**：抽屉、展开、收起等"明显空间位移"可放宽到 `180ms`，但仍不得 > `200ms`。
- **按下反馈**：只允许 `transform: scale(0.96)` + `100ms`。
- **缓动**：默认 `cubic-bezier(0.16, 1, 0.3, 1)`（`--ease-out`）。**禁止**给同一组件混用多种缓动。
- **减弱动效**：`@media (prefers-reduced-motion: reduce)` 强制 `transition-duration: 1ms !important`，并关闭 smooth scroll。新组件必须保持兼容（不要依赖 transition 来承载关键状态）。

### 11.3 不应出现的动效

- `transition: all`（必须显式列出属性）。
- `animation` 循环装饰（除 capability-mark 静态点阵外）。
- 任何超过 200ms 的 hover。
- 与 `box-shadow` 同步的 hover 颜色变化（会引发性能抖动）。

---

## 12. 内容规范

### 12.1 文案语气

- 角色：标航智导（Agent）对学生，像一位「耐心的学长 / 学姐」，不端着、不堆术语、不催促。
- 句式：短句、主动语态、明确动作（「先从实体边界开始」「我会先定位你的学习起点」）。
- 称呼：默认用「你」，避免「用户 / 同学 / 您」。

### 12.2 标题与按钮

| 位置           | 写法                      | 示例                                                             |
| -------------- | ------------------------- | ---------------------------------------------------------------- |
| 欢迎页 h1      | 产品名 / 招牌语，不加句号 | 「标航智导」                                                     |
| 欢迎页 p       | 一句话价值主张            | 「把学习目标交给指挥舱，生成清晰的练习路径、任务卡和诊断建议。」 |
| NewSession     | 动词 + 名词               | 「新建会话」                                                     |
| QuickLink      | 2~4 字场景词              | 「文本标注」「图像标注」「结果诊断」「薄弱补强」「规范问答」     |
| ContinueRow    | 复用 recent title，单行   | 「文本标注入门路径」                                             |
| Message label  | Agent 名 / 段落主题       | 「标航智导」「下一步」                                           |
| ActivityLine   | 完成时态 + 数量 + 主题    | 「已完成能力定位 · 找到 2 个适合今天练习的主题」                 |
| PlanInline h2  | 「今天的练习路径」        | 固定句式                                                         |
| PlanInline p   | 步骤编号 + 主题           | 「1. NER 实体边界识别」                                          |
| ScenarioSelect | 「继续场景：文本标注」    | 位于输入框下方，当前会话的信息栏同步展示继续场景                 |
| Toast          | 短状态说明，不超过 18 字  | 「已把目标加入演示会话」                                         |

### 12.3 占位与示例

- 欢迎页 textarea：`输入你的学习目标，或输入 / 选择能力`（提示可走命令面板）。
- 会话 textarea：`继续描述你的学习问题`。
- setting 文字在 ≤560 截断到 112px，但**不要在更宽屏上截断**（保留信息完整）。

### 12.4 文本长度

- hero p ≤ 56 字（中文字符）。
- 消息单条 ≤ 200 字。
- Toast ≤ 18 字。
- quick-link 文字 ≤ 6 字。

### 12.5 不要做的事

- 不要在 h1 上加句号、感叹号、营销词（「最强」「一键搞定」）。
- 不要给 user 气泡文字加 emoji（保持冷静学术感）。
- 不要把 capability-mark 的方块换成 logo / 数据图表（它就是装饰点阵）。
- 不要在新会话按钮旁加引导问号、问句——它就是动作按钮。

---

## 13. 验收清单

### 13.1 视觉验收

- [ ] 整页底色为 `#f7f8fa`，所有卡片为纯白。
- [ ] 全站仅出现 `--accent #2477d6` 一种品牌强调色；警示未出现，`--amber` 仅 token 存在。
- [ ] 侧栏展开 272px、折叠 68px；侧栏 header 与主区基线等高 68px。
- [ ] 桌面欢迎页顶部 padding 在 1080p 上 ≥ 76px、1440p 上 ≤ 146px。
- [ ] hero h1 桌面 clamp(30, 3.2vw, 48)、≤900 = 32。
- [ ] prompt 圆角 16、边框 `--line-strong`；focus 边 `#9dbde2` + 蓝色阴影。
- [ ] 欢迎页 Hero Prompt 保持既有 `188px` / `90px` 尺寸；仅已有对话 Composer 压缩至约 `144px` 总高、`64px` 文本区。
- [ ] 对话页顶部信息栏覆盖侧栏之外的完整主区宽度，右侧包含通知铃铛；其他学生页通知入口仍脱离常规布局流且不新增操作栏。
- [ ] quick-link 是胶囊；hover 变 `--accent-soft` 底 + 蓝字。
- [ ] send-button 圆形 38×38；空 = 灰、有值 = 蓝；按下 scale 0.96。
- [ ] 消息气泡 assistant 左 / user 右；user 圆角三同一异（左下小）；消息行高 1.75。
- [ ] 有会话时顶部仅显示当前对话标题；信息栏位于 `.cockpit-content-scroll` 外，消息列表可独立滚动，Composer 不随历史滚动。
- [ ] 能力图谱的全图/局部/路径标签仅隐藏视觉滚动条；窄屏仍可横向滚动，其他页面 Tabs 不受影响。

### 13.2 交互验收

- [ ] Enter 发送，Shift+Enter 换行。
- [ ] 输入空时 send-button 灰色；有值时变蓝；场景 Select 位于输入框下方、最大宽度 `160px` 并可键盘操作。
- [ ] 点击 quick-link 把对应文本填入 textarea 并 focus。
- [ ] 从 `/profile`、`/tasks`、`/diagnostics` 点击最近会话，自动进入指挥舱并恢复该会话；欢迎页不重复显示会话列表。
- [ ] 从任意学生页点击 NewSession，清空本地输入和转录状态、回到欢迎态并聚焦 Composer，且不创建空会话。
- [ ] 通知铃铛保留未读数、下拉面板、轮询、已读和运行中禁用；窄屏下其面板不越出视口。
- [ ] 点击侧栏折叠按钮：≥901 折叠侧栏，≤900 关闭抽屉（不折叠）。
- [ ] mobile ≤900：抽屉可从左侧滑入；点击遮罩关闭；按 Esc 关闭。
- [ ] hash = `#conversation` 进入页面时自动展示会话视图。

### 13.3 响应式验收

- [ ] 桌面（1440）：侧栏 272 + 主区，prompt 居中 900。
- [ ] 中屏（900）：侧栏抽屉，对话顶部栏覆盖主区并包含通知入口，其他学生页通知入口仍为右上 fixed 浮层，hero 顶部 80。
- [ ] 手机（375）：通知铃铛保持可见且下拉面板受视口宽度约束；prompt 内边距收紧；setting 文字截断 112；消息气泡 100% 宽。
- [ ] 折叠态下所有文字隐藏，仅 icon 列 68px。

### 13.4 可访问性验收

- [ ] 所有 button / a / textarea 有 `aria-label` 或可见文字。
- [ ] 全局 `focus-visible` 2px accent + 2px offset。
- [ ] 装饰元素（capability-mark）`aria-hidden="true"`。
- [ ] Toast `role="status" aria-live="polite"`，自动播报。
- [ ] 主文字 ≥ 15:1、次文字 ≥ 7:1、辅助文字仅 11px 大写标签用。
- [ ] `prefers-reduced-motion` 下 transition ≤ 1ms。

### 13.5 内容验收

- [ ] 欢迎页 h1 = 「标航智导」；p = 「把学习目标交给指挥舱，生成清晰的练习路径、任务卡和诊断建议。」。
- [ ] NewSession 文案「新建会话」+「Ctrl K」提示（如未绑定真快捷键，需在 PR 描述中标注「设计占位」）。
- [ ] 5 个 quick-link 顺序与文案与 §12.2 完全一致。
- [ ] message label 形如「标航智导」「下一步」。
- [ ] plan-inline h2 = 「今天的练习路径」。

### 13.6 实施约束

- [ ] 不新增 200ms+ hover。
- [ ] 不给 nav-link 加下划线 / 圆点（已有左 2px 蓝条 + 字色 + 字重 + icon 染色的四件套）。
- [ ] 不在折叠态用模态或二级菜单做导航替代。
- [ ] 新组件按 §3.5 圆角表选值；按 §3.6 阴影表选值。
- [ ] 颜色仅 1 个主蓝（`--accent`），活动点 `--teal`，警示 `--amber` 备用。

---

## 14. 基准映射（demo 行号对照表）

> 用于评审时"在 demo 里搜啥能找到这条规范"。

### 14.1 Token ↔ 行号

| 规范章节        | demo 位置                                                                                                                                       |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| §3.1 颜色 Token | L8–L26                                                                                                                                          |
| §3.4 尺寸 Token | L22 / L79 / L134 / L797                                                                                                                         |
| §3.5 圆角 Token | L23 / L24                                                                                                                                       |
| §3.6 阴影 Token | L21 / L196 / L478 / L486 / L770                                                                                                                 |
| §3.7 缓动 Token | L25 / 多处                                                                                                                                      |
| §4.2 字号阶梯   | L43 / L222 / L275 / L310 / L317 / L362 / L388 / L452 / L461 / L498 / L628 / L679 / L691 / L712 / L726 / L746 / L752 / L771 / L834 / L874 / L883 |

### 14.2 组件 ↔ 行号

| 规范章节                         | demo 位置                                    |
| -------------------------------- | -------------------------------------------- |
| §8.1 IconButton                  | L159–L180                                    |
| §8.2 Brand                       | L138–L157                                    |
| §8.3 NewSession                  | L182–L211 / 折叠态 L97–L102                  |
| §8.4 NavLink                     | L228–L261                                    |
| §8.5 NavLabel                    | L219–L226                                    |
| §8.6 RecentList                  | L263–L318                                    |
| §8.7 SidebarFooter               | L320–L363                                    |
| §8.8 StudentFloatingNotification | 应用实现：固定浮层；不沿用 demo toolbar 映射 |
| §8.9 Hero                        | L411–L463                                    |
| §8.10 Prompt                     | L465–L569                                    |
| §8.11 QuickLinks                 | L571–L612                                    |
| §8.12 ContinueRow（已废弃）      | 无；会话入口见 RecentList L263–L318          |
| §8.13 MessageList                | L662–L716                                    |
| §8.14 ActivityLine               | L718–L734                                    |
| §8.15 PlanInline                 | L736–L753                                    |
| §8.16 Toast                      | L759–L783                                    |
| §8.17 折叠行为                   | L78–L116 / 移动端 L789–L812                  |

### 14.3 响应式 ↔ 行号

| 断点                   | demo 位置 |
| ---------------------- | --------- |
| ≤ 900                  | L789–L857 |
| ≤ 560                  | L859–L900 |
| prefers-reduced-motion | L902–L909 |

### 14.4 关键交互逻辑 ↔ 行号

| 行为                         | demo 位置           |
| ---------------------------- | ------------------- |
| 视图切换 setView             | demo JS L1255–L1268 |
| 折叠侧栏                     | demo JS L1362–L1376 |
| 移动抽屉                     | demo JS L1378–L1393 |
| Ctrl K 监听（占位）          | demo JS L1402–L1411 |
| hash 进入自动切视图          | demo JS L1413       |
| bindComposer / syncSendState | demo JS L1314–L1326 |

---

## 15. 实施注意事项（给前端同学）

1. **不要新增 hover 时长**：默认 140ms。少数 160ms 留给"边框 + 阴影同时变化"（只有 Prompt）。
2. **不要给 nav-link 加下划线或圆点强调**：active 已经用「左 2px 蓝条 + 字色 + 字重 + icon 染色」四件套，不要再加。
3. **不要把 capability-mark 做成可点击**：它纯装饰，`aria-hidden="true"`。
4. **user 气泡的圆角不对称**是设计意图：右上大、左下小，传递"从我发起"的语气。
5. **侧栏的折叠态不要变成模态/二级菜单**（demo 注释 L76–L77 明示）。
6. **Ctrl K 是设计占位**：当前只是 new-session 上的文字提示，**不绑定快捷键**；上线前要么去掉、要么真绑定，并同步规范。
7. **新组件的圆角选择**：
   - 6px：prompt 工具栏小按钮。
   - 8px：所有侧栏内控件、icon-button、recent-item、new-session、toast。
   - 10px：内嵌卡（plan-inline）。
   - 16px：核心输入框（Prompt）。
   - 圆：头像、send-button。
   - 胶囊：快捷入口。
8. **新组件的阴影选择**：极轻 `0 1px 2px / 3%`（new-session）；输入卡 `0 18px 42px / 8%`（Prompt）；浮层 `0 12px 30px / 17%`（Toast）。
9. **消息气泡宽度**：assistant `82%`、user `72%`，≤560 改 `100%`。气泡不要撑满到边缘。
10. **本页颜色仅 1 个主蓝**：所有"强调"都走 `--accent`；警示场景才用 `--amber`（demo 中暂未实际使用），活动点用 `--teal`。
11. **messageList 建议挂 `aria-live="polite"`**：demo 中仅 toast 挂了 a11y，生产化时建议给 messageList 加上，避免新消息被 SR 漏读。
12. **新组件默认遵循"无障碍默认值"**：button / a / textarea 必带可读标签，icon 自身 `aria-hidden`，由承载元素承担语义。

---

## 16. 后续可扩展（不在本期范围）

- **主题切换 UI**：暗色 Token 已定义，但只有显式 `html[data-theme="dark"]` 设置才会启用；不得跟随操作系统自动切换。保持圆角 / 字号 / 间距不动。
- **五个子模块**（预设学习 / 能力图谱 / 学习任务 / 标注诊断 / 知识问答）：沿用同套 Token + §8 组件库；本期 nav-link 是占位样式。
- **Ctrl K 真绑定**：将 `Ctrl/Cmd + K` 绑到 new-session（demo 已为它预留提示位）。
- **plan-inline 升级为独立卡片**：从 conversation 流中独立成 `<article class="plan-card">`，与消息平级，可在卡片内嵌更多交互。
- **toast 队列**：当前 toast 是单例替换，多事件并发会丢失；生产化时建议改成队列。
- **键盘命令面板**：welcome textarea placeholder 提到「输入 / 选择能力」，暗示未来要做命令面板（`/` 唤起），届时可复用 QuickLink 视觉。

---

## 17. 变更记录

| 日期       | 版本 | 变更                                                                                                                                                                                                                                                        |
| ---------- | ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-08-08 | v1   | 初版，基于 `student-workbench-layout-demo.html` 反推                                                                                                                                                                                                        |
| 2026-08-08 | v2   | 覆盖重写：补齐设计原则、颜色语义、字号阶梯表、间距基线、栅格与 z-index 层级、桌面 / 平板 / 移动响应式、组件结构 / 尺寸 / 状态 / 交互 / 无障碍、两屏布局契约、消息 / 活动线 / 计划卡、动效原则、内容规范、验收清单、基准映射；保留 demo 全部视觉语言与数值。 |
| 2026-08-08 | v3   | 新增 Token 命名规范、状态色 Token、深色模式与无障碍清单，并为每章补充 demo 可追溯映射；完整保留 v2 章节与功能。                                                                                                                                             |
| 2026-08-08 | v4   | 方案 C：最近会话升级为全局学生侧栏能力，欢迎页移除 ContinueRow；补充个人中心导航、一次性会话意图、运行中禁用、显式深色主题与学生/教师/RAG/系统管理的运营工作台壳层映射。                                                                                    |
| 2026-08-08 | v5   | 侧栏收窄至 272px；保留通知并移除帮助入口；场景选择器移入 Composer 下方；补充会话信息栏、固定 Composer、侧栏隐藏滚动条及非对话学生页顶部留白约束。                                                                                                           |
| 2026-08-08 | v6   | 通知铃铛从学生侧栏迁移到共享页面 toolbar 右上角；保留通知面板、未读数与移动端可见性约束。                                                                                                                                                                   |
| 2026-08-08 | v7   | 取代 v6 的学生端顶部 toolbar 方案：通知铃铛改为视口右上 `position: fixed` 浮层并脱离正常布局流；保留未读数、下拉面板、移动端可见性和窄屏宽度约束。仅已有对话态 Composer 压缩至约 `144px` 总高、`64px` 文本区，欢迎页 Hero 保持既有尺寸。                    |
| 2026-08-08 | v8   | 会话信息栏移至消息滚动区外的页面顶部常驻区；Composer 场景选择移除 FolderOpen 装饰图标；能力图谱视图标签仅隐藏视觉滚动条并保留窄屏横向滚动。                                                                                                                    |
| 2026-08-08 | v9   | 会话信息栏仅保留当前对话标题；Composer 场景选择最大宽度收窄至 `160px`，保留键盘交互、完整 title 与长文本省略。                                                                                                                                                |
| 2026-08-08 | v10  | 对话信息栏扩展至侧栏之外的完整主区顶部，并在右侧囊括通知铃铛与下拉列表；其他学生子路由继续保留右上固定通知入口。                                                                                                                                                |
| 2026-08-08 | v11  | 修复顶部栏被负顶部外边距裁切的问题；信息栏提升为 Cockpit 页面级节点，仅扩展左右宽度，不再受 900px 对话列约束。                                                                                                                                                |
