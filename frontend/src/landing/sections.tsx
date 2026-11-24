import {
  ArrowUpRight, Bell, Check, FileText, Package, Smartphone, Terminal, User,
} from 'lucide-react'
import {
  CAPABILITY_GROUPS, DELIVERY_CARDS, DEV_POINTS, REMOTE_POINTS,
  THESIS_POINTS, THESIS_STEPS, TRUST,
} from './content'

function SectionHeading({
  title,
  aside,
  children,
}: {
  title: string
  aside: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h2 className="text-2xl font-semibold tracking-tight text-ink md:text-3xl">{title}</h2>
        {children && <div className="mt-3 max-w-2xl">{children}</div>}
      </div>
      <span className="font-mono text-2xs uppercase tracking-[0.16em] text-faint">{aside}</span>
    </div>
  )
}

export function ModeSplit() {
  return (
    <section id="modes" className="border-t border-edge/60 py-16 md:py-20">
      <SectionHeading title="一个 Agent，两种工作方式。" aside="开发 / 论文">
        <p className="text-sm leading-6 text-dim">
          开发模式面向代码仓库，论文模式面向毕业论文与毕业设计。两者共用同一套模型配置、
          权限模式与执行器，但会话历史、工作区和产物完全分开。
        </p>
      </SectionHeading>

      <div className="mt-9 grid border-y border-edge/60 md:grid-cols-2 md:divide-x md:divide-edge/60">
        <div className="py-7 md:pr-9">
          <div className="flex items-center gap-2 font-mono text-2xs uppercase tracking-[0.16em] text-accent">
            <Terminal size={13} />
            开发模式
          </div>
          <h3 className="mt-3 text-xl font-semibold text-ink">把结论落到文件、命令和退出码上</h3>
          <p className="mt-2 max-w-md text-sm leading-6 text-dim">
            导入项目后直接提问、改代码、跑测试。回答里的每个文件和行号都会核验，
            写入前先给出 diff，运行结果保留真实退出码。
          </p>
          <ul className="mt-5 space-y-2 text-xs leading-5 text-dim">
            {DEV_POINTS.map((point) => (
              <li key={point} className="flex gap-2">
                <Check size={12} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
          <a
            href="/guide#dev"
            className="mt-6 inline-flex items-center gap-1.5 text-xs text-accent underline decoration-accent/40 underline-offset-4 hover:decoration-accent"
          >
            开发模式使用文档
            <ArrowUpRight size={12} />
          </a>
        </div>

        <div className="border-t border-edge/60 py-7 md:border-t-0 md:pl-9">
          <div className="flex items-center gap-2 font-mono text-2xs uppercase tracking-[0.16em] text-warn">
            <FileText size={13} />
            论文模式
          </div>
          <h3 className="mt-3 text-xl font-semibold text-ink">从选题到定稿，每一步都留下记录</h3>
          <p className="mt-2 max-w-md text-sm leading-6 text-dim">
            从题目、要求到提纲与章节，按阶段推进；阶段稿可直接导出 MD / DOCX / PDF。
            需要模板合规时再导入学校 DOCX 体检，原文件只读，修复写入工作副本。
            AI 只起草草稿，正文需要你核对。
          </p>
          <ul className="mt-5 space-y-2 text-xs leading-5 text-dim">
            {THESIS_POINTS.map((point) => (
              <li key={point} className="flex gap-2">
                <Check size={12} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
                <span>{point}</span>
              </li>
            ))}
          </ul>
          <a
            href="/guide#thesis"
            className="mt-6 inline-flex items-center gap-1.5 text-xs text-warn underline decoration-warn/40 underline-offset-4 hover:decoration-warn"
          >
            论文模式使用文档
            <ArrowUpRight size={12} />
          </a>
        </div>
      </div>
    </section>
  )
}

export function CapabilityLedger() {
  return (
    <section id="capabilities" className="py-16 md:py-20">
      <SectionHeading title="能力清单" aside="能力与验证">
        <p className="text-sm leading-6 text-dim">
          不靠“更聪明”这类形容词。下面每一项都对应一个可以自己验证的行为：
          一条引用、一次真实执行、一份可撤销的改动。
        </p>
      </SectionHeading>

      <div className="mt-9 border-t border-edge/60">
        {CAPABILITY_GROUPS.map((group) => (
          <div
            key={group.title}
            className="grid gap-4 border-b border-edge/60 py-6 lg:grid-cols-[170px_minmax(0,1fr)] lg:gap-10"
          >
            <div>
              <h3 className="text-base font-semibold text-ink">{group.title}</h3>
              <p className="mt-1.5 text-2xs leading-5 text-faint">{group.note}</p>
            </div>
            <div>
              {group.rows.map((row) => (
                <div
                  key={row.name}
                  className="grid gap-1 border-b border-edge/40 py-2.5 last:border-b-0 last:pb-0 sm:grid-cols-[168px_minmax(0,1fr)] sm:gap-6"
                >
                  <span className="text-xs font-medium text-ink/90">{row.name}</span>
                  <span className="text-xs leading-5 text-dim">{row.detail}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-3">
        <a href="/guide" className="text-xs text-accent underline decoration-accent/40 underline-offset-4 hover:decoration-accent">
          查看完整功能与操作步骤
        </a>
        <span className="text-2xs text-faint">包含权限模式、引用核对、部署与常见问题。</span>
      </div>
    </section>
  )
}

export function ThesisWorkflow() {
  return (
    <section id="thesis-flow" className="border-t border-edge/60 py-16 md:py-20">
      <SectionHeading title="论文模式的四个步骤" aside="论文流程">
        <p className="text-sm leading-6 text-dim">
          从导入到定稿包，每一步都留下可回看的记录。模板不符时只提示，不替你判断学校规定。
        </p>
      </SectionHeading>

      <ol className="mt-9 grid gap-0 border-y border-edge/60 md:grid-cols-4 md:divide-x md:divide-edge/60">
        {THESIS_STEPS.map((step) => (
          <li key={step.no} className="relative py-6 md:px-5 md:first:pl-0 md:last:pr-0">
            <span className="font-mono text-2xs text-warn">{step.no}</span>
            <h3 className="mt-2 text-base font-medium text-ink">{step.title}</h3>
            <p className="mt-1.5 text-xs leading-5 text-dim">{step.text}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}

const DELIVERY_ICONS = [FileText, User, Package]

export function DeliveryWorkflows() {
  return (
    <section id="delivery" className="border-t border-edge/60 py-16 md:py-20">
      <SectionHeading title="不止代码。" aside="文档 / 简历 / 证据">
        <p className="text-sm leading-6 text-dim">
          报告、简历与交付证据共用同一个项目、模型与文件权限；
          每份产物都能回到它的来源，而不是散落在另一个聊天窗口里。
        </p>
      </SectionHeading>

      <div className="mt-9 grid gap-4 md:grid-cols-3">
        {DELIVERY_CARDS.map((card, index) => {
          const Icon = DELIVERY_ICONS[index] ?? FileText
          return (
            <div
              key={card.title}
              className="flex min-w-0 flex-col rounded-lg border border-edge bg-panel/45 p-5"
            >
              <div className="flex items-center gap-2 font-mono text-2xs uppercase tracking-[0.16em] text-faint">
                <Icon size={13} className="text-accent" />
                {card.kicker}
              </div>
              <h3 className="mt-3 text-lg font-semibold text-ink">{card.title}</h3>
              <p className="mt-1.5 text-sm leading-6 text-dim">{card.text}</p>
              <ul className="mt-4 space-y-2 text-xs leading-5 text-dim">
                {card.points.map((point) => (
                  <li key={point} className="flex gap-2">
                    <span className="text-accent" aria-hidden="true">─</span>
                    <span className="min-w-0">{point}</span>
                  </li>
                ))}
              </ul>
              <a
                href={card.href}
                className="mt-auto inline-flex items-center gap-1.5 pt-5 text-xs text-accent underline decoration-accent/40 underline-offset-4 hover:decoration-accent"
              >
                使用文档
                <ArrowUpRight size={12} />
              </a>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function PhoneMock() {
  return (
    <div className="overflow-hidden rounded-[20px] border border-edge bg-panel shadow-pop">
      <div className="flex items-center justify-between border-b border-edge/80 px-3 py-2.5">
        <span className="flex items-center gap-1.5 font-mono text-2xs text-dim">
          <Smartphone size={11} />
          nova / m
        </span>
        <span className="flex items-center gap-1.5 font-mono text-2xs text-accent">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
          运行中
        </span>
      </div>

      <div className="space-y-2 px-3 py-3">
        <div className="ml-auto max-w-[92%] rounded-lg rounded-br-sm bg-accentSoft px-2.5 py-2 text-xs leading-5 text-ink">
          把导出失败的日志整理一下，修完跑测试
        </div>
        <p className="text-right font-mono text-2xs text-faint">已签名 · 待电脑确认</p>

        <div className="rounded-md border border-edge bg-base/60 p-2.5">
          <div className="flex items-center justify-between font-mono text-2xs">
            <span className="text-faint">当前任务</span>
            <span className="text-accent">3 个工具调用</span>
          </div>
          <p className="mt-1 text-xs leading-5 text-ink/90">修复导出目录并发清理</p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-edge">
            <div className="h-full w-2/3 rounded-full bg-accent" />
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          <span className="rounded-sm border border-edge px-1.5 py-0.5 font-mono text-2xs text-dim">
            停止运行
          </span>
          <span className="rounded-sm border border-edge px-1.5 py-0.5 font-mono text-2xs text-dim">
            完成通知
          </span>
        </div>
      </div>
    </div>
  )
}

function DesktopConfirmMock() {
  return (
    <div className="rounded-lg border border-warn/30 bg-panel p-3 shadow-pop">
      <div className="flex items-center gap-1.5 font-mono text-2xs text-warn">
        <Bell size={11} />
        手机发来的指令
      </div>
      <p className="mt-2 text-xs leading-5 text-ink/90">
        把导出失败的日志整理一下，修完跑测试
      </p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">
        <span className="rounded-sm bg-accent px-2 py-1 text-2xs font-medium text-graphite">
          确认并发送
        </span>
        <span className="rounded-sm border border-edge px-2 py-1 text-2xs text-dim">
          拒绝
        </span>
      </div>
      <p className="mt-2 border-t border-edge/60 pt-2 font-mono text-2xs leading-5 text-faint">
        确认后才进入当前对话
        <br />
        高风险操作仍需本地审批
      </p>
    </div>
  )
}

export function RemoteControl() {
  return (
    <section id="remote" className="border-t border-edge/60 py-16 md:py-20">
      <SectionHeading title="手机发指令，电脑做决定。" aside="遥控 / 移动工作台">
        <p className="text-sm leading-6 text-dim">
          电脑上生成一次性配对链接，手机扫码并核对 6 位验证串。手机发来的自然语言
          先进入待确认队列，电脑点确认后才作为普通消息进入当前对话；
          高风险操作始终留在电脑上。
        </p>
      </SectionHeading>

      <div className="mt-9 grid gap-8 lg:grid-cols-[0.85fr_1.15fr] lg:items-center lg:gap-14">
        <ul className="space-y-4">
          {REMOTE_POINTS.map((point) => (
            <li key={point.title} className="border-l border-edge pl-4">
              <h3 className="text-sm font-medium text-ink">{point.title}</h3>
              <p className="mt-1 text-xs leading-5 text-dim">{point.text}</p>
            </li>
          ))}
        </ul>

        <div className="min-w-0">
          <div className="mx-auto grid max-w-lg gap-3 sm:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] sm:items-center">
            <PhoneMock />
            <DesktopConfirmMock />
          </div>
          <p className="mt-3 text-center font-mono text-2xs text-faint">
            界面示意 · 指令原文保留在桌面待确认队列
          </p>
        </div>
      </div>
    </section>
  )
}

export function TrustSection() {
  return (
    <section id="trust" className="py-16 md:py-20">
      <SectionHeading title="你的环境，你的数据。" aside="隐私与边界">
        <p className="text-sm leading-6 text-dim">
          Nova 是 Apache-2.0 开源项目。桌面端可以在本机运行，服务器端用 docker compose 自托管；
          没有云端账号，也没有数据托管。
        </p>
      </SectionHeading>

      <div className="mt-9 grid gap-6 border-t border-edge/60 pt-7 md:grid-cols-3 md:gap-10">
        {TRUST.map((item) => (
          <div key={item.title} className="border-l border-edge pl-4">
            <h3 className="text-sm font-medium text-ink">{item.title}</h3>
            <p className="mt-1.5 text-xs leading-5 text-dim">{item.text}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
