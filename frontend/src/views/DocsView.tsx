import {
  AlertTriangle, ArrowLeft, ArrowUpRight, BookOpen, Check, FileText, Info,
  MonitorDown, ShieldCheck, Terminal,
} from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

const CHAPTERS = [
  { id: 'start', title: '开始使用' },
  { id: 'dev', title: '开发模式' },
  { id: 'thesis', title: '论文模式' },
  { id: 'documents', title: '文档工作区' },
  { id: 'local', title: '本地模式' },
  { id: 'models', title: '模型与密钥' },
  { id: 'deploy', title: '部署与运维' },
  { id: 'boundaries', title: '边界与合规' },
  { id: 'faq', title: '常见问题' },
]

const CHAPTER_IDS = CHAPTERS.map((chapter) => chapter.id)

function useActiveChapter() {
  const [active, setActive] = useState(CHAPTER_IDS[0])
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '-12% 0px -70% 0px', threshold: [0, 1] },
    )
    for (const id of CHAPTER_IDS) {
      const node = document.getElementById(id)
      if (node) observer.observe(node)
    }
    return () => observer.disconnect()
  }, [])
  return active
}

function H2({ id, children }: { id: string; children: ReactNode }) {
  return (
    <h2 id={id} className="scroll-mt-24 text-2xl font-semibold tracking-tight text-ink">
      {children}
    </h2>
  )
}

function H3({ children }: { children: ReactNode }) {
  return <h3 className="mt-7 text-base font-semibold text-ink">{children}</h3>
}

function P({ children }: { children: ReactNode }) {
  return <p className="mt-3 text-sm leading-6 text-dim">{children}</p>
}

function UL({ items }: { items: ReactNode[] }) {
  return (
    <ul className="mt-3 space-y-2 text-sm leading-6 text-dim">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2">
          <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-accent/70" aria-hidden="true" />
          <span className="min-w-0">{item}</span>
        </li>
      ))}
    </ul>
  )
}

function Code({ children }: { children: string }) {
  return (
    <pre className="mt-3 overflow-x-auto rounded-md border border-edge bg-panel px-3.5 py-3 font-mono text-xs leading-6 text-ink">
      <code>{children}</code>
    </pre>
  )
}

function Callout({
  tone = 'note',
  title,
  children,
}: {
  tone?: 'note' | 'warn' | 'stop'
  title: string
  children: ReactNode
}) {
  const styles = {
    note: 'border-accent/40 bg-accentSoft/20 text-accent',
    warn: 'border-warn/40 bg-warn/10 text-warn',
    stop: 'border-err/40 bg-err/10 text-err',
  }[tone]
  const Icon = tone === 'stop' ? AlertTriangle : tone === 'warn' ? AlertTriangle : Info
  return (
    <div className={`mt-5 rounded-md border px-3.5 py-3 ${styles}`}>
      <p className="flex items-center gap-2 text-xs font-medium">
        <Icon size={13} className="shrink-0" />
        {title}
      </p>
      <div className="mt-1.5 text-xs leading-5 text-dim">{children}</div>
    </div>
  )
}

function Table({
  head,
  rows,
}: {
  head: string[]
  rows: ReactNode[][]
}) {
  return (
    <div className="mt-4 overflow-x-auto rounded-md border border-edge">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="bg-raised/60 text-faint">
            {head.map((cell) => (
              <th key={cell} className="border-b border-edge px-3 py-2 font-medium">{cell}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-edge/60 last:border-b-0">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="align-top px-3 py-2 leading-5 text-dim">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Chapter({ children }: { children: ReactNode }) {
  return <section className="scroll-mt-24 border-t border-edge/60 pt-9">{children}</section>
}

export function DocsView() {
  const active = useActiveChapter()

  // 从宣传页的 /guide#thesis 这类深链进入时，React 渲染完成前浏览器
  // 可能找不到锚点；渲染后再补一次滚动，保证直接落到对应章节。
  useEffect(() => {
    document.title = '使用文档 · Nova Agent'
    const hash = window.location.hash.slice(1)
    if (!hash) return
    const timer = window.setTimeout(() => {
      document.getElementById(hash)?.scrollIntoView()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])

  return (
    <div className="relative min-h-screen bg-base">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          backgroundImage:
            'linear-gradient(to right, rgba(237,232,222,0.04) 1px, transparent 1px), linear-gradient(to bottom, rgba(237,232,222,0.04) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse 70% 45% at 50% 0%, black 0%, transparent 100%)',
          WebkitMaskImage: 'radial-gradient(ellipse 70% 45% at 50% 0%, black 0%, transparent 100%)',
        }}
      />

      <header className="relative z-10 mx-auto flex w-full max-w-6xl flex-wrap items-center gap-3 px-5 py-5 md:px-8">
        <a href="/" className="flex items-center gap-2.5" aria-label="Nova Agent 首页">
          <span className="grid h-7 w-7 place-items-center rounded-sm border border-accent/40 bg-accentSoft/40 font-mono text-sm font-semibold text-accent">
            N
          </span>
          <span className="font-mono text-xs font-medium uppercase tracking-[0.22em] text-ink">
            Nova Agent
          </span>
        </a>
        <span className="rounded-sm border border-edge px-1.5 py-0.5 font-mono text-2xs text-dim">
          使用文档
        </span>
        <div className="ml-auto flex items-center gap-2">
          <a href="/" className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-dim transition-colors hover:text-ink">
            <ArrowLeft size={13} />
            返回首页
          </a>
          <a
            href="/downloads"
            className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-graphite transition-colors hover:bg-accent/85"
          >
            <MonitorDown size={13} />
            下载
          </a>
        </div>
      </header>

      <main className="relative z-10 mx-auto w-full max-w-6xl px-5 pb-24 md:px-8">
        <div className="max-w-2xl py-10 md:py-14">
          <p className="flex items-center gap-2 font-mono text-2xs tracking-[0.08em] text-dim">
            <BookOpen size={13} className="text-accent" />
            适用于当前部署的 Nova Agent
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
            使用文档
          </h1>
          <p className="mt-3 text-md leading-7 text-dim">
            从第一次登录到论文定稿包，按任务说明每一步做什么、结果在哪里看。
            开发模式与论文模式共用模型和权限配置，但工作区、会话与产物完全分开。
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <a href="#start" className="rounded-md border border-accent/40 bg-accentSoft/30 px-2.5 py-1.5 text-xs text-accent">
              5 分钟开始
            </a>
            <a href="#dev" className="rounded-md border border-edge px-2.5 py-1.5 text-xs text-dim hover:text-ink">
              开发模式
            </a>
            <a href="#thesis" className="rounded-md border border-warn/40 bg-warn/10 px-2.5 py-1.5 text-xs text-warn">
              论文模式
            </a>
            <a href="#deploy" className="rounded-md border border-edge px-2.5 py-1.5 text-xs text-dim hover:text-ink">
              自己部署
            </a>
          </div>
        </div>

        <div className="lg:grid lg:grid-cols-[190px_minmax(0,1fr)] lg:gap-12">
          <aside className="hidden lg:block">
            <nav aria-label="文档目录" className="sticky top-8 space-y-0.5">
              {CHAPTERS.map((chapter, index) => (
                <a
                  key={chapter.id}
                  href={`#${chapter.id}`}
                  aria-current={active === chapter.id ? 'true' : undefined}
                  className={`flex items-center gap-3 rounded-sm px-2 py-1.5 text-xs transition-colors ${
                    active === chapter.id
                      ? 'bg-panel text-ink'
                      : 'text-dim hover:bg-panel/60 hover:text-ink'
                  }`}
                >
                  <span className={`font-mono text-2xs ${active === chapter.id ? 'text-accent' : 'text-faint'}`}>
                    {String(index + 1).padStart(2, '0')}
                  </span>
                  {chapter.title}
                </a>
              ))}
            </nav>
          </aside>

          <div className="min-w-0 max-w-[760px]">
            <nav aria-label="文档目录（移动端）" className="mb-8 flex gap-1.5 overflow-x-auto pb-1 lg:hidden">
              {CHAPTERS.map((chapter) => (
                <a
                  key={chapter.id}
                  href={`#${chapter.id}`}
                  className="shrink-0 rounded-sm border border-edge px-2.5 py-1.5 text-2xs text-dim hover:text-ink"
                >
                  {chapter.title}
                </a>
              ))}
            </nav>

            <div className="space-y-10">
              <Chapter>
                <H2 id="start">开始使用</H2>
                <P>
                  Nova Agent 有三种进入方式。无论哪一种，登录后看到的都是同一个工作台：
                  左侧项目与会话，中间对话与工具卡，右侧文件、引用、影响面与变更。
                </P>
                <Table
                  head={['方式', '适合谁', '注意']}
                  rows={[
                    ['游客试用', '只想先看看效果', '24 小时临时账号，额度低于正式用户；论文模式默认不对游客开放'],
                    ['注册账号', '日常使用或小团队', '注册方式由部署方决定：开放注册、邀请码或关闭注册'],
                    ['桌面客户端', '希望数据留在本机', '可在本机运行完整后端，也可以连接已有服务器'],
                  ]}
                />
                <H3>第一次对话</H3>
                <UL items={[
                  '登录后，在左侧新建或导入一个项目（ZIP、Git 仓库，桌面端还可直接选择本机文件夹）。',
                  '选中项目，在输入框里描述任务。也可以直接粘贴报错堆栈。',
                  '回答里的 文件:行号 会核验；工具调用、命令输出与退出码在消息下方展开。',
                  '涉及写入时，先看 diff，再决定批准或拒绝。',
                ]} />
                <Callout tone="note" title="没有 API Key 也能先看论文格式">
                  论文模式的 DOCX 解析、格式体检与引用 L1 不依赖模型；需要 AI 写作或联网核验时，
                  再到设置里配置自己的 Key。
                </Callout>
              </Chapter>

              <Chapter>
                <H2 id="dev">开发模式</H2>
                <P>
                  开发模式面向代码仓库。它不是“把整段代码丢给模型”，而是先建立符号索引与依赖关系，
                  再让 Agent 用工具去读、搜、改、运行。
                </P>

                <H3>导入与索引</H3>
                <UL items={[
                  'ZIP 包或 Git URL：在项目栏新建项目，服务端会克隆并建立索引。',
                  '桌面端本机文件夹：直接选择目录，文件原地读写，不复制到服务器。',
                  '索引包含符号表、依赖图与全文检索；重建索引会更新项目大脑。',
                ]} />

                <H3>引用与证据</H3>
                <P>
                  回答中的 文件:行号 会逐条核验：文件是否存在、行号是否越界。
                  不存在的引用会直接标红；涉及运行的结论会标注命令、输出与退出码。
                  每轮结束还有一份确定性交付报告，列出改动文件、命令、引用与未验证项。
                </P>

                <H3>权限模式</H3>
                <Table
                  head={['模式', '能做什么', '适合场景']}
                  rows={[
                    ['只读', '读文件、搜索、回答，不写入、不执行', '审阅陌生仓库、先摸清结构'],
                    ['询问', '写入或执行前逐次确认', '日常开发，默认推荐'],
                    ['自动', '自动应用安全范围内的修改', '信任当前会话与仓库时'],
                    ['完全', '不逐条确认，解锁联网装依赖等受限工具', '隔离环境里的批处理任务'],
                  ]}
                />
                <Callout tone="warn" title="任何模式都不会放开的东西">
                  密钥路径、路径逃逸、沙箱边界与危险命令在所有权限档位都被拒绝。
                  服务端模式下，命令只进 Docker 沙箱；本地模式没有容器隔离，命令会直接影响你的电脑。
                </Callout>

                <H3>红-绿修复（/fix）</H3>
                <UL items={[
                  '输入 /fix 描述一个 bug，Agent 先写一个失败测试并确认它真的失败。',
                  '再产出最小补丁，复跑全量测试；失败摘要会回喂，最多自动修复 3 轮。',
                  '只读 Reviewer 先审查 diff，最后由你批准写入并重建索引。',
                  '生成后文件被改动过，提交会被拒绝覆盖。',
                ]} />

                <H3>并行调研与图片</H3>
                <UL items={[
                  '主 Agent 可以派发 1–4 个只读子代理，并行阅读不同模块；子代理不能写文件、执行命令或联网，返回结果带引用与 token 用量。',
                  'PNG / JPEG 可直接粘贴、拖拽或选择上传；单张 ≤ 3.5 MB，每条消息 ≤ 5 张且合计 ≤ 10 MB。',
                  '图片只随当前回合发送，历史回合保留附件元数据但不重复发送。',
                ]} />

                <H3>更多工具</H3>
                <UL items={[
                  '结构化诊断：固定版本的 ruff / mypy / tsc，结果按文件分组，可点击打开。',
                  '变更影响雷达：改动前先看受影响文件、相关测试与风险等级。',
                  'Git 与轨迹：初始化、提交、diff、回滚、导出 zip；工具轨迹可回放。',
                  '预览部署：把项目复制到临时目录，在隔离容器里启动并做健康检查，超时自动下线。',
                  'MCP 与 SKILL.md：MCP 工具必须显式 allowlist；技能按触发词或 /技能名 注入。',
                ]} />
              </Chapter>

              <Chapter>
                <H2 id="thesis">论文模式</H2>
                <P>
                  论文模式面向本科/研究生的毕业论文与毕业设计。它把导入的 DOCX 当作唯一事实源：
                  解析、检查与修复都在你的环境里完成，原文件始终只读。
                </P>

                <H3>创建项目与导入论文</H3>
                <UL items={[
                  '在顶栏切换到「论文」，新建项目：填写题目、学校、学位与模板。',
                  '仓库内置的三个模板是虚构演示校，用来展示格式；请改为自己学校的模板，或用 NOVA_THESIS_TEMPLATES 指向外部模板目录。',
                  '导入 DOCX 后自动解析节、页面大小、页边距、标题层级、页眉页脚与页码域。',
                  '上传会校验 zip 结构、条目数、解压体积、压缩比与 XML 外部实体，防止压缩炸弹与 XXE。',
                ]} />

                <H3>体检与安全修复</H3>
                <P>
                  问题列表按严重度排序，每条都带规则、位置、当前值、建议值、模板来源与置信度。
                  页面大小、页边距与标题样式可以先预览再应用；修复写入 working.docx，
                  保留版本备份，随时可以撤销。应用后会重新解析并校验段落数与字数，防止内容丢失。
                </P>

                <H3>引用核对</H3>
                <Table
                  head={['层级', '做什么', '是否联网']}
                  rows={[
                    ['L1', '检查 [n] 与作者-年份：缺条目、重复、编号不连续、首次出现顺序', '否'],
                    ['L2', '只把 DOI 发往 Crossref 核验元数据，结果缓存 30 天', '是，仅 DOI'],
                    ['L3（实验）', '用你自带的参考文献 PDF 定位候选页码与原文；支持度由你确认', '否'],
                  ]}
                />
                <P>
                  L3 不做自动判定，也不抓取知网、维普、万方。参考文献只能使用你已经导入的条目。
                </P>

                <H3>关联项目与写作对话</H3>
                <UL items={[
                  '论文项目可以关联一个已有仓库，或桌面端的本机文件夹。',
                  '右侧写作对话复用开发模式的工具、权限与执行器，可以读代码、梳理实现、起草章节草稿。',
                  '草稿里的代码依据使用 文件路径:行号；论文对话按项目独立保存，不会混入开发模式历史。',
                  'AI 生成内容标注「AI 草稿 · 需本人核对」；你可以把这一轮记入 AI 使用声明。',
                ]} />

                <H3>七阶段与作者确认</H3>
                <P>
                  「阶段」页把论文过程分成选题、来源、提纲、研究、起草、修改、定稿七步。
                  每个阶段可以写一段说明，交给写作对话讨论；模型上下文会带上当前阶段、状态和作者说明。
                </P>
                <UL items={[
                  '前进只能到下一阶段，返回可以回到任意更早阶段；返回后，被重做阶段及其下游的确认会标记为失效。',
                  '「确认当前内容」绑定这段说明的 SHA-256，并把状态设为已接受；修改说明会让确认自动失效。',
                  '没有确认的内容只是草稿。阶段状态不会判定内容是否合格，也不会替你署名。',
                ]} />

                <H3>AI 使用声明与定稿包</H3>
                <UL items={[
                  '声明记录工具、环节、用途、提示与输出摘要、是否修改；由你确认后保存。',
                  '定稿包包含：修复版 DOCX、体检报告 DOCX/HTML、引用清单 CSV、AI 使用声明与修改记录。',
                  '报告是本地检查结果，不是学校出具的合规证明；提交前请按学校要求复核。',
                ]} />
                <Callout tone="stop" title="产品边界">
                  Nova 不代写整篇论文、不降重、不做 AIGC 检测、不伪造引用。
                  AI 正文只是草稿，需要你核对、改写并按要求声明。
                </Callout>
              </Chapter>

              <Chapter>
                <H2 id="documents">文档工作区</H2>
                <P>
                  顶栏的「文档」按钮打开文档工作区。它用一个 Markdown 主控源管理报告、论文草稿与简历草稿，
                  再导出 DOCX 或 PDF。文件默认放在 Nova 数据目录；本地模式可以指定任意绝对路径。
                </P>

                <H3>目录结构</H3>
                <Code>{`<工作区>/
  source/         原始材料（只读参考）
  manuscripts/    Markdown 正文（main.md 与分章文件）
  assets/         图片与附件
  exports/        导出的 DOCX / PDF 与保真报告
  .nova/          工作区元数据、写入哈希与版本`}</Code>
                <UL items={[
                  '目标目录不是空的、也不是 Nova 工作区时，创建会被拒绝，不会改动已有文件。',
                  '正文保存使用原子写；每次覆盖前把旧内容存进 .nova/versions，可随时恢复。',
                  '保存时携带读取到的 sha256。若文件在磁盘上被其他程序改过，保存返回冲突，由你决定重新载入或强制覆盖。',
                ]} />

                <H3>从要求起草</H3>
                <P>
                  报告工作区可以只给主题、范围与已知材料，由模型写出一份 Markdown 初稿。
                  缺少的数据、姓名、日期与统计值会写成「待补充」，不会编造；
                  初稿写入 manuscripts/report.md，同名文件不会被覆盖。
                </P>

                <H3>导出与保真报告</H3>
                <Table
                  head={['导出', '工具', '缺失时']}
                  rows={[
                    ['DOCX', 'Pandoc', '明确提示不支持，不改用服务端转换'],
                    ['PDF', 'LibreOffice（soffice）', '明确提示未安装，保留已生成的 DOCX'],
                  ]}
                />
                <UL items={[
                  '每次导出旁边写一份 .fidelity.json：保留了哪些对象、哪些不支持、哪些可能失真。',
                  'HTML 块、脚注、公式块等 Markdown 扩展目前按纯文本保留并标记不支持，不会静默丢弃。',
                  'PDF 是终态导出，不能反向编辑；要修改请改 Markdown 后重新导出。',
                ]} />

                <Callout tone="warn" title="事实与格式边界">
                  文档工作区不核实你写的事实，也不承诺学校或企业的格式合规。
                  导出前请自己核对「待补充」项、引用与数据；格式检查只报告本工具看到的问题。
                </Callout>
              </Chapter>

              <Chapter>
                <H2 id="local">本地模式</H2>
                <P>
                  桌面客户端可以选择「在本机运行」：后端、数据库与数据目录都在这台电脑上，
                  不需要 Docker，也不需要服务器。也可以随时改成「连接服务器」。
                </P>
                <UL items={[
                  '本机运行使用 HostExecutor，工具直接在系统上读写文件、执行命令。',
                  '没有容器隔离：Agent 运行的命令会影响这台电脑，请只对可信项目使用自动/完全权限。',
                  '需要隔离、多人协作或团队共享项目时，连接自托管服务器，让命令进 Docker 沙箱。',
                  '本机文件夹项目原地读写，不复制文件；开发模式与论文模式共用同一套执行器和权限模式。',
                ]} />
                <Callout tone="warn" title="本地模式的安全预期">
                  本地模式不是沙箱。安装依赖、运行脚本与修改文件都发生在你的用户目录下；
                  涉及不可信代码时，优先使用服务器模式，或保持「只读 / 询问」权限。
                </Callout>
              </Chapter>

              <Chapter>
                <H2 id="models">模型与密钥</H2>
                <P>
                  Nova 支持自带 Key（BYOK）。每个账号可以保存多家厂商的凭据并指定默认，
                  对话与后台任务统一走个人配置；管理员也可以选择是否允许使用服务端共享 Key。
                </P>
                <UL items={[
                  '内置 16 家厂商目录：智谱 GLM、百炼、DeepSeek、OpenAI、Anthropic、Gemini、Groq、OpenRouter、Ollama 与自定义兼容端点等。',
                  '密钥加密存储，接口只返回掩码；日志、轨迹与工具输出中的密钥会被脱敏。',
                  '会话级可以切换厂商、模型、推理强度、上下文窗口与温度，刷新后保留。',
                  '预设厂商的 Base URL 固定，不能改成指向其他地址；自定义端点由部署方自行负责。',
                ]} />
                <Callout tone="note" title="不要把 Key 贴在对话里">
                  在设置页填写 Key。对话内容会进入模型上下文，也可能被工具读取；
                  任何需要长期使用的凭据都应该放在设置里，而不是消息中。
                </Callout>
                <P>
                  本地模式可以连接 Ollama 或任意 OpenAI 兼容端点；服务端是否允许共享 Key
                  由 LLM_ALLOW_SERVER_FALLBACK 控制。关闭后，每个用户都必须填写自己的 Key。
                </P>
              </Chapter>

              <Chapter>
                <H2 id="deploy">部署与运维</H2>
                <H3>启动命令</H3>
                <Code>{`cp .env.docker.example .env
# 至少填写：LLM Key、SECRET_KEY、ADMIN_PASSWORD、DEMO_PASSWORD
docker compose up -d --build`}</Code>
                <P>
                  生产环境会拒绝弱 SECRET_KEY 与默认密码。启动时自动执行数据库迁移；
                  /api/v1/status/health 的 schema 组件会报告代码与数据库版本是否一致。
                </P>

                <H3>升级</H3>
                <UL items={[
                  '有已发布镜像时：docker compose pull && docker compose up -d --no-build。',
                  '小内存服务器不要一次重建全部镜像；只构建 app：docker compose build app，再 up -d --no-build app。',
                  '迁移在 app 启动时自动应用；升级前先备份 PostgreSQL 与数据卷。',
                ]} />

                <H3>备份与恢复</H3>
                <Code>{`BACKUP_DIR=/opt/nova-backups ./deploy/backup.sh
# 恢复会覆盖数据库与数据卷，脚本会要求输入 RESTORE 确认
BACKUP_DIR=/opt/nova-backups ./deploy/restore.sh`}</Code>

                <H3>多用户与论文开关</H3>
                <Table
                  head={['变量', '作用', '默认']}
                  rows={[
                    ['REGISTRATION_MODE', 'open 开放注册 / invite 邀请码 / closed 仅管理员建号', 'open'],
                    ['MAX_USERS', '账号数量上限', '50'],
                    ['THESIS_SERVER_ENABLED', '服务端是否开放论文模式', 'true'],
                    ['THESIS_GUEST_ENABLED', '游客能否使用论文模式', 'false'],
                    ['THESIS_MAX_*', '论文项目、DOCX、参考 PDF 与解压体积上限', '见 .env.docker.example'],
                    ['USER_STORAGE_MB', '每个账号的存储配额，论文文件计入其中', '200'],
                  ]}
                />
                <Callout tone="warn" title="公网部署">
                  反代后请设置 TRUSTED_PROXIES；启用 Caddy 时把 APP_BIND 收窄到 127.0.0.1，
                  避免 :8000 成为绕过 HTTPS 的明文旁路。中国大陆服务器的域名需要 ICP 备案。
                </Callout>
              </Chapter>

              <Chapter>
                <H2 id="boundaries">边界与合规</H2>
                <P>
                  Nova 的定位是辅助理解、检查与交付，不是替代作者。以下边界写在产品里，
                  也在提示词与工具权限里执行：
                </P>
                <UL items={[
                  '不代写整篇论文、不降重、不做 AIGC/查重检测、不伪造引用。',
                  '参考文献只使用已导入条目；L2 联网核验只发送 DOI，不发送论文正文。',
                  '不抓取知网、维普、万方等付费文献库。',
                  'AI 生成的正文标注「AI 草稿」，需要本人核对、改写并按要求声明。',
                  '内置模板是虚构演示校，不代表任何学校的官方规定；提交前以学校文件为准。',
                  '体检报告是本地检查结果，不是学校或第三方机构出具的合规证明。',
                ]} />
                <P>
                  数据方面：没有遥测；项目、索引、会话与密钥留在你部署的环境里。
                  使用云端模型时，发送的内容会经过你配置的厂商端点，请按学校与导师的要求处理敏感材料。
                </P>
              </Chapter>

              <Chapter>
                <H2 id="faq">常见问题</H2>

                <H3>游客可以使用论文模式吗？</H3>
                <P>
                  默认不能。论文文件是长期保存的个人材料，访客账号默认被拒绝；
                  部署方可以设置 THESIS_GUEST_ENABLED=true 放开。
                </P>

                <H3>为什么回答里的引用被标红？</H3>
                <P>
                  说明模型给出的 文件:行号 在仓库里不存在或行号越界。展开引用可以看核验结果，
                  让 Agent 重新读取对应文件即可。未验证的结论也会被显式标注。
                </P>

                <H3>论文导入失败怎么办？</H3>
                <P>
                  只支持 DOCX；上传会拒绝损坏的 zip、加密条目、异常压缩比、过多条目或含外部实体的 XML。
                  也可能是项目数量、文档数量或存储配额已满。界面会返回具体原因。
                </P>

                <H3>没有 API Key 能做什么？</H3>
                <P>
                  论文的 DOCX 解析、格式体检与引用 L1 不需要模型；对话、AI 写作、引用 L2 与联网工具需要。
                  服务端开启共享 Key 时可以直接使用，否则请在设置里填写自己的 Key。
                </P>

                <H3>刷新页面会中断任务吗？</H3>
                <P>
                  不会。对话回合在服务端后台执行，SSE 只是观看窗口；重新打开会话会自动回放并接上。
                  同一会话同时只允许一个活动回合，不同会话可以并行。
                </P>

                <H3>本地模式安全吗？</H3>
                <P>
                  本地模式没有容器隔离，命令与文件修改直接影响这台电脑。它适合可信项目与个人使用；
                  处理不可信代码时请连接服务器，让命令进 Docker 沙箱，或保持只读/询问权限。
                </P>

                <H3>如何更新服务器？</H3>
                <P>
                  优先拉取已发布镜像并重启；没有镜像时只重建 app。迁移会随启动自动执行。
                  升级前用 deploy/backup.sh 备份数据库与数据卷。
                </P>
              </Chapter>
            </div>

            <div className="mt-12 flex flex-wrap items-center gap-3 border-t border-edge/60 pt-6">
              <a
                href="/"
                className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2.5 text-base font-semibold text-graphite transition-colors hover:bg-accent/85"
              >
                <Terminal size={14} />
                打开工作台
              </a>
              <a
                href="/downloads"
                className="inline-flex items-center gap-2 rounded-md border border-edge px-4 py-2.5 text-base text-ink transition-colors hover:border-accent/40 hover:text-accent"
              >
                <MonitorDown size={14} />
                下载桌面客户端
              </a>
              <span className="flex items-center gap-1.5 text-2xs text-faint">
                <ShieldCheck size={12} />
                文档随当前部署更新
              </span>
            </div>
          </div>
        </div>
      </main>

      <footer className="relative z-10 border-t border-edge/60">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center gap-x-2 gap-y-1 px-5 py-5 text-2xs text-faint md:px-8">
          <span className="flex items-center gap-1.5">
            <Check size={11} className="text-accent" />
            Apache-2.0
          </span>
          <span aria-hidden="true">·</span>
          <span>无遥测</span>
          <span aria-hidden="true">·</span>
          <a href="/guide" className="transition-colors hover:text-ink">使用文档</a>
          <span className="ml-auto flex items-center gap-1.5 font-mono uppercase tracking-[0.16em]">
            <FileText size={11} />
            Nova Agent / docs
          </span>
        </div>
      </footer>

      <a
        href="#start"
        className="fixed bottom-5 right-5 hidden items-center gap-1.5 rounded-md border border-edge bg-panel px-2.5 py-2 text-2xs text-dim shadow-pop transition-colors hover:text-ink lg:flex"
      >
        <ArrowUpRight size={12} className="-rotate-90" />
        回到顶部
      </a>
    </div>
  )
}
