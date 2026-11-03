/**
 * ICP 备案号。大陆服务器对外提供网站必须展示，且要链接到工信部备案系统。
 *
 * 备案号随部署不同而不同（自己的域名 vs 别人的），所以走构建期环境变量
 * `VITE_ICP_BEIAN`：留空就整块不渲染，本地开发、桌面端和自托管海外部署
 * 都不会凭空多出一行。填法见 .env.docker.example 的 ICP_BEIAN。
 */
export function IcpNotice({ className = '' }: { className?: string }) {
  const number = (import.meta.env.VITE_ICP_BEIAN ?? '').trim()
  if (!number) return null
  return (
    <a
      href="https://beian.miit.gov.cn/"
      target="_blank"
      rel="noreferrer"
      className={className}
    >
      {number}
    </a>
  )
}
