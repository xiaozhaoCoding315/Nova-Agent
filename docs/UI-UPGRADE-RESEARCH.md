# Nova Agent 界面优化调研：LeiBox 组件适配评估

> 调研日期：2026-11-10 · 对象：`https://leibox.pantoria.cn`（58 个组件）
> 范围：宣传/下载页（`frontend/src/views/LoginView.tsx` + `backend/app/main.py` 的 `/downloads`）
> 与登录后内部界面（`frontend/src/shell/*`、`timeline/*`、`composer/*`）

---

## 0. 先说明两条边界

**依赖成本。** LeiBox 的演示大量依赖 `gsap`、`@base-ui/react`、`@radix-ui/react-slider`、`framer` 一类包。
Nova 前端当前只有 `react` / `clsx` / `lucide-react` / `zustand` / `react-markdown` / `highlight.js`，
构建产物已经接近 chunk 告警线。**建议只吸收布局与交互语义，用现有 Tailwind + CSS 重写，不引入新依赖。**

**许可。** LeiBox 自述「仅供学习使用」，并明确说「公开链接、署名、免费提供或改写实现，本身都不等于取得
受保护内容的使用授权」，各条目遵循各自来源许可。所以本文全部按「参考版式与交互模式」处理，
不整段搬运其源码；确实要复用的纯 CSS 技法（如立体按压按钮）需逐条核对来源许可后再决定。

---

## 1. 现状盘点

### 1.1 宣传/下载页

| 位置 | 现状 | 问题 |
|---|---|---|
| `LoginView.tsx:38-114` `RunLedger` | 右侧 hero 是**静态**的 run 账本卡片（grep→read→edit→run→cite） | 很有说服力，但它是"画出来的"，不是产品本身。访客看不到真正的输入框长什么样 |
| `LoginView.tsx:294-341` | 左文案 + 右卡片的两栏 hero | 版式偏"技术博客"，缺少可交互的第一触点 |
| `LoginView.tsx:343-353` `PROOFS` | 三栏证据条（REFERENCE / EXECUTION / APPROVAL） | 信息好，但纯文字，无层次 |
| `LoginView.tsx:355-394` `RunMode` | 桌面端 / 自托管两张卡 | 结构清晰，可保留 |
| `backend/app/main.py:284-330` `/downloads` | 后端直接吐一段内联 HTML 的极简列表 | **与前端设计语言脱节**：手写 CSS、无品牌网格背景、无平台图标、无版本说明；且不在 React 应用内，无法复用组件 |

### 1.2 登录后内部界面

| 组件 | 结构 | 可优化点 |
|---|---|---|
| `shell/AppShell.tsx` | ProjectRail(264px) + main(ChatHeader + Workbench) + ContextRail(320px) | 两侧栏宽度**写死**，不能拖拽；`ContextRail.tsx:219`、`ProjectRail.tsx:139` |
| `shell/ChatHeader.tsx` | 项目名 + git 分支 + 权限 + 模型 + 轨迹 + 本机 + 新对话 + 命令面板 + 健康 + 两个面板按钮 | 一行塞 9 个控件，1280px 下已开始挤 |
| `shell/Workbench.tsx:282-345` | 空状态：图标 + 标题 + 3 张能力卡 + 3 个示例问题 | 层次偏平，3+3 两组卡视觉重复 |
| `composer/Composer.tsx:429-567` | 底栏一行：附件 / 斜杠 / 模型 / 权限 / 上下文计量 / 仓库数 / 快捷键提示 / 发送 | **最挤的地方**，7 个元素挤在 `text-xs` 一行；附件按钮是方形描边块，发送是 32px 方块 |
| `composer/ModelPicker.tsx:406-428` | 推理强度是 4 个平铺 chip（自动/低/中/高） | 与"强度"这个连续量不匹配，且占一整行 |
| `components/ContextMeterChip.tsx` | 按钮 + 展开分解面板，带进度条 | 功能完整，但**展开面板**是点击弹层，与输入框里的"环形容量"习惯不一致 |
| `timeline/SignalGutter.tsx` | 28px 竖轨：`T01` 编号 + 工具小方点 + 证据圆点 | 设计感很好，是本项目的差异化，**建议保留** |
| `timeline/TurnView.tsx:282-286` | 轮末元信息是一行 `3 个工具 · 1.2s · 证据 4/4` | 信息被压成一串等宽文字，扫读性差 |
| `timeline/TurnView.tsx:208-213` | 流式等待是 `Spinner` + 一行文案 | 旋转圆环对"Agent 正在思考"的表达力弱 |
| `components/AuthPanel.tsx:201-231` | 邮箱验证码是普通输入框 + 右侧按钮 | 6 位定长验证码用普通输入框，错误反馈只能是红字 |
| `components/AdminUsersPanel.tsx` | 管理员可建号、看用量 | 没有"邀请成员"面板，邀请码只能手工分发 |

---

## 2. LeiBox 组件适配矩阵

评级：**A** = 直接该做；**B** = 值得做但要改写；**C** = 只借一个细节；**D** = 不建议。

### 2.1 Agent 对话输入框（`deep-agent-composer`）— **A**

这是用户指定的参照，也是本次最大收益点。它把"输入框"从"一个 textarea"变成"一张控制面板"：

```
┌──────────────────────────────────────────────┐
│  尽管问…                                      │
│                                              │
│  ⊕   请求批准 ⌄          ◯  deepseek-chat 中度 ⌄   ↑ │
└──────────────────────────────────────────────┘
```

对照 Nova 现状（`Composer.tsx:429-567`）的差距：

| 参照 | Nova 现状 | 改法 |
|---|---|---|
| 输入区在上、工具行在下，整体一张圆角大卡 | 已经是这个结构 | 保留 |
| `+` 是**圆形**无边框按钮 | 附件是 28px **方形描边** | 改圆形、去描边，hover 才显底色 |
| 权限是**一个胶囊**「请求批准 ⌄」 | 权限是描边小按钮，带盾牌图标 + 文字 | 合并为胶囊，图标常驻、文字 12px |
| 上下文容量是**小圆环**（点击展开） | 是带数字 + 进度条的长按钮 | 圆环 + hover 显示 `12.4k / 200k` |
| 模型是**胶囊**「deepseek-chat 中度 ⌄」 | 模型 chip 与权限按钮**并列**，两个都是描边 | 合并为一个胶囊：模型名 + 当前强度，点开同一个浮层 |
| 发送是**圆形** `↑` | 32px 圆角方块 | 改 32px 圆形 |
| 模型浮层里「模型列表 + 推理强度滑块」同层 | ModelPicker 是长表单：厂商、模型、推理 chip、上下文、温度、默认 | 浮层首屏只留「模型 + 推理强度」，其余折叠到「更多参数」 |

**关键约束（用户明确要求）：功能一个不能少。** 附件上限 5、斜杠菜单、`@` 文件引用、
拖拽上传、流式停止、Enter/Shift+Enter、`ContextMeter` 分解、`ModelPicker` 全部能力都要留住，
只改排布与视觉层级。

### 2.2 模型思考强度滑块（`reasoning-effort-slider`）— **B**

三档滑块，拖拽时有果冻形变与吸附。Nova 的 `reasoning_effort` 是四值（`'' | low | medium | high`）。

- **建议**：`自动` 拆成独立开关（表示"不覆盖，继承默认"），`低/中/高` 三档做滑块，正好对上参照的三档语义。
- **不建议**照搬星空填充与果冻形变 —— 那是营销页气质，与 Nova 的终端质感冲突。保留滑块 + 档位文字 +
  键盘 `←/→/Home/End` 可达即可。
- 落点：`composer/ModelPicker.tsx:406-428`。

### 2.3 点阵加载（`ai-generating`）— **B**

20×20 点阵围绕两个移动焦点呼吸。这是**最贴"Agent 正在工作"的一个**，而且实现成本低（纯 CSS/Canvas，无依赖）。

- 落点：`timeline/TurnView.tsx:208-213` 的流式等待态；`Workbench` 里 `/fix` 运行中的等待态。
- 做法：不要 20×20 全屏铺开，缩到 `48×16` 的小点阵，放在状态文字左侧替代 `Spinner`。
- 尊重 `prefers-reduced-motion`（项目 `globals.css:96` 已有全局兜底）。

### 2.4 弹性面板缩放（`elastic-panel-resize`）— **B**

把手靠近才显现、拖动调整宽度、双击/Esc 重置、方向键可达。

- 落点：`ContextRail`（写死 320px）与 `ProjectRail`（写死 264px）。
- **只取交互语义，不取弹性弯曲**：给两侧栏加一条 4px 拖拽把手，宽度存 `localStorage`（项目已有
  `nova.rail.collapsed` 的先例），双击复位，`role="separator"` + `aria-valuenow`。
- 这是真实可用性收益：宽屏看 diff 时右栏 320px 太窄。

### 2.5 标签叠放展开（`stacked-metadata`）— **C**

优先级/日期/负责人标签叠放，悬停向左展开。

- 落点：`timeline/TurnView.tsx:282-286` 的轮末元信息，以及 `ChatHeader` 的 git 分支 + 脏标记。
- **只取"折叠成一簇、悬停展开"** 的思路：默认显示 `3 工具 · 1.2s`，悬停/聚焦展开
  `证据 4/4 · 引用 3 · 沙箱实测`。避免等宽文字串。

### 2.6 验证码输入验证（`otp-verification`）— **B**

胶囊展开为 6 位分格输入，错误摇动，成功变绿。

- 落点：`components/AuthPanel.tsx:201-231` 的邮箱验证码（注册 / 邮箱重置密码）。
- 这正好补上 Nova 现在"6 位定长却用普通输入框"的不一致；错误反馈从红字升级为摇动 + 红框。
- 成本低、纯前端，无新依赖。**注意**：自动提交要防误触，粘贴 6 位应一次性填满。

### 2.7 分享邀请面板（`share-invite`）— **B**

可展开收拢的成员面板：邮箱邀请、权限选择、复制链接。

- 落点：`components/AdminUsersPanel.tsx`。Nova 已有 `REGISTRATION_MODE=invite` 与邀请码机制，
  但管理员只能手工发码。做成"生成邀请码 → 复制链接 → 列表展示已用/未用"最贴现有后端能力。
- **需要后端配合**（邀请码列表接口），属于功能增量，不只是 UI。建议单独立项。

### 2.8 组件环游 404（`orbit-not-found`）— **C**

Nova 是 SPA，未匹配路由目前回落到首页。加一个 404 页成本很低，环形卡片对开发者有记忆点。
优先级低，但"做一次就永久存在"。

### 2.9 立体按压按钮（`tactile-push-button`）— **C**

纯 CSS 立体按压。Nova 是扁平终端美学，**不建议**用整块立体按钮；但可以取其"按下时下沉 1px + 内阴影"
用在主 CTA（`下载 Windows 版`）与发送按钮上，让点击有触感。一个 `:active` 规则的事。

### 2.10 玻璃标签栏展开菜单（`glass-tab-menu`）— **C**

四项标签栏展开为六宫格。Nova 的 `ContextRail` 恰好是 4 个页签（文件/引用/影响/变更）。

- 但 4 个页签在 320px 里已经排得下，展开成宫格反而多一次点击。
- **可取的只有一点**：窄屏下把 4 个页签收成一个"更多"宫格，避免挤成 2 个字。

### 2.11 其余组件的结论

| 组件 | 结论 | 理由 |
|---|---|---|
| 思考步骤粒子变形 `thinking-particles` | **D** | 810px 高的画布演示，搬进对话流会打断阅读；且依赖 canvas 重绘 |
| 轨道与点阵动效 `cosmic-panels` | **D** | 纯装饰，与"证据优先"的产品气质相反 |
| 像素日夜开关 `pixel-toggle` | **D（暂缓）** | Nova 无浅色主题，引入等于重做整套 token；如要做主题切换应作为独立设计项目 |
| 列表卡片堆叠切换 `collection-layout-morph` | **D** | 项目/会话列表密度已经合适，切换视图增加认知负担 |
| 流体提示气泡 `fluid-tooltip` | **C** | 可做 landing 导航的移动胶囊；内部界面不需要 |
| 帆船滚动目录 `sailing-toc` | **C** | landing 可加一条滚动进度轨，帆船本身太俏皮 |
| 玻璃文件夹 `glass-folder` | **D** | 落地页项目展示用，与"本机/自托管"两张卡重复 |
| 字符透镜 / 冰霜 / 玻璃透镜 / 粒子物体 / 流体物体 / 字符雨 | **D** | 都是覆盖全页的 WebGL 覆盖层，放进 IDE 类界面会干扰选中与滚动 |
| 内联词组变形 / 文字选区开花 / 文字选区调色器 | **D** | 营销页把戏，工具界面里是噪音 |
| 访问申请展开 `bouncy-access` | **D** | Nova 没有访问申请流程 |
| 拖甩照片卡片 / 专辑封面隧道 / 蜘蛛切歌 / 字符鲨鱼 … | **D** | 与产品无关 |

---

## 3. 实施顺序与完成情况

按"收益 ÷ 成本"排；P1–P6 已全部落地（2026-11-10）。

| 阶段 | 内容 | 涉及文件 | 状态 |
|---|---|---|---|
| **P1** | Composer 版式重构（2.1）：圆形 `+`、权限胶囊、上下文圆环、模型+强度胶囊、圆形发送；ModelPicker 浮层首屏收敛 + 推理强度分段控件（2.2） | `composer/Composer.tsx`、`composer/ModelPicker.tsx`、`components/ContextMeterChip.tsx` | ✅ |
| **P2** | 流式/等待态点阵加载（2.3） + 轮末元信息折叠（2.5） | `timeline/TurnView.tsx`、`timeline/DotLoader.tsx`、`styles/globals.css` | ✅ |
| **P3** | 两侧栏可拖拽调宽（2.4） | `shell/RailResizer.tsx`、`shell/AppShell.tsx`、`shell/ContextRail.tsx`、`shell/ProjectRail.tsx` | ✅ |
| **P4** | 登录/注册的 6 位验证码分格输入（2.6） | `components/OtpInput.tsx`、`components/AuthPanel.tsx` | ✅ |
| **P5** | 宣传页 hero 换成"活的"输入框演示 + `/downloads` 迁进前端 | `components/HeroComposer.tsx`、`views/LoginView.tsx`、`views/DownloadsView.tsx`、`backend/app/api/v1/downloads.py`、`backend/app/main.py` | ✅ |
| **P6** | 邀请面板（2.7）、404 页（2.8） | `components/AdminUsersPanel.tsx`、`views/NotFoundView.tsx`、`App.tsx` | ✅ |

### P5 的方向选择：`/downloads` 迁进前端（原第 4 节的结论）

原先是后端 `main.py` 里 100 行内联 HTML（`_DOWNLOADS_STYLE`），与前端设计系统脱节。
最终选了「迁进前端」：

- 新增公开接口 `GET /api/v1/downloads`，实时读 `DOWNLOADS_DIR`，返回文件名/平台/大小/时间/直链；
- `views/DownloadsView.tsx` 用 Nova 的 token 重画，含三步接入、两种运行方式、服务器地址一键复制；
- `backend/app/main.py` 删掉内联 HTML，改成一条兜底路由：有对应文件就返回文件，
  无扩展名的路径一律返回 `index.html` 交给 SPA（`/downloads` 与 404 页都靠它），
  带扩展名且缺文件的仍然是真 404（避免把 HTML 当 JS 返回）。
- `contracts/openapi.json` 与 `api-schema.d.ts` 已同步，`npm run contract:check` 通过。

---

## 5. 不做什么

- 不引入 gsap / radix / base-ui / framer —— 现有依赖集刻意很窄，加包会让首屏变大。
- 不改 `SignalGutter` 的竖轨设计，它是本项目最有辨识度的部分。
- 不为了动效而动效：所有动画必须在 `prefers-reduced-motion` 下退化为静帧（项目已有全局兜底，新代码不要绕开）。
- 不搬运 LeiBox 源码。只参考版式与交互模式，用 Nova 自己的 token 重写。
