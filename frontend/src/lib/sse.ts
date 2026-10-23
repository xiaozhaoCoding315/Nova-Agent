import { ApiError } from './api'

export type SSEPayload = Record<string, any>
export type SSEHandler = (event: string, data: SSEPayload) => void

export type ChatStreamBody = {
  session_id?: string
  content: string
  repo_ids: string[]
  permission_mode?: 'readonly' | 'ask' | 'auto'
}

/**
 * POST-based SSE reader (fetch + ReadableStream) with AbortController support.
 * Any non-2xx response or network failure throws — callers must render an
 * error state; previously a silent failure left the UI stuck forever.
 */
export async function streamChat(
  body: ChatStreamBody,
  onEvent: SSEHandler,
  signal: AbortSignal,
): Promise<void> {
  let res: Response
  try {
    res = await fetch('/api/v1/chat/message', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (err) {
    if ((err as Error).name === 'AbortError') return
    throw new ApiError(0, '网络连接失败，请检查服务是否可用')
  }

  if (!res.ok) {
    let detail = `请求失败（${res.status}）`
    try {
      const parsed = await res.json()
      if (typeof parsed?.detail === 'string') detail = parsed.detail
    } catch {
      /* keep default */
    }
    throw new ApiError(res.status, detail)
  }
  if (!res.body) throw new ApiError(0, '浏览器不支持流式响应')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        let event = 'message'
        const dataLines: string[] = []
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) event = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
        }
        if (dataLines.length === 0) continue
        try {
          onEvent(event, JSON.parse(dataLines.join('\n')))
        } catch {
          /* skip malformed frame */
        }
      }
    }
  } catch (err) {
    if ((err as Error).name === 'AbortError') return
    throw err
  } finally {
    reader.releaseLock()
  }
}