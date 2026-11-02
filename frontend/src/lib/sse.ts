import { ApiError, friendlyHttpError } from './api'
import type { LlmOverrides } from './types'

export type SSEPayload = Record<string, any>
export type SSEHandler = (event: string, data: SSEPayload) => void
export type TurnOpenInfo = { turnId: string | null; sessionId: string | null }

export type ChatStreamBody = {
  session_id?: string
  content: string
  repo_ids: string[]
  permission_mode?: 'readonly' | 'ask' | 'auto' | 'full'
  model?: string
  llm_overrides?: LlmOverrides
  file_ids?: string[]
}

async function readSSE(
  res: Response,
  onEvent: SSEHandler,
): Promise<void> {
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
          if (line.startsWith(':')) continue
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
  } finally {
    reader.releaseLock()
  }
}

async function openSSE(url: string, init: RequestInit, signal: AbortSignal): Promise<Response> {
  let res: Response
  try {
    res = await fetch(url, { credentials: 'include', signal, ...init })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new ApiError(0, '网络连接失败，请检查服务是否可用')
  }
  if (!res.ok) {
    let detail: string | undefined
    try {
      const parsed = await res.json()
      if (typeof parsed?.detail === 'string') detail = parsed.detail
    } catch {
      /* 非 JSON 错误体，用状态码兜底文案 */
    }
    throw friendlyHttpError(res.status, detail)
  }
  return res
}

export async function streamChat(
  body: ChatStreamBody,
  onEvent: SSEHandler,
  signal: AbortSignal,
  onOpen?: (info: TurnOpenInfo) => void,
): Promise<void> {
  let res: Response
  try {
    res = await openSSE('/api/v1/chat/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }, signal)
  } catch (err) {
    if ((err as Error).name === 'AbortError') return
    throw err
  }
  onOpen?.({
    turnId: res.headers.get('X-Turn-Id'),
    sessionId: res.headers.get('X-Session-Id'),
  })
  try {
    await readSSE(res, onEvent)
  } catch (err) {
    if ((err as Error).name === 'AbortError') return
    throw new ApiError(
      0,
      '连接中断：网络不稳定或服务刚重启。任务仍在后台执行，可在会话里重新连接。',
    )
  }
}

export async function streamTurn(
  turnId: string,
  onEvent: SSEHandler,
  signal: AbortSignal,
  afterSeq = 0,
): Promise<void> {
  let res: Response
  try {
    res = await openSSE(
      `/api/v1/chat/turns/${encodeURIComponent(turnId)}/stream?after_seq=${afterSeq}`,
      { method: 'GET' },
      signal,
    )
  } catch (err) {
    if ((err as Error).name === 'AbortError') return
    throw err
  }
  try {
    await readSSE(res, onEvent)
  } catch (err) {
    if ((err as Error).name === 'AbortError') return
    throw new ApiError(0, '重新连接中断，请稍后再试')
  }
}
