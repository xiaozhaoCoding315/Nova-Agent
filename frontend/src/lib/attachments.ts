import type { FileAttachment } from './types'

const VISION_MIME = new Set(['image/png', 'image/jpeg'])

/** 只有服务端确认过 magic bytes 的 PNG/JPEG 才会带这两个 MIME。 */
export function isVisionImage(file: FileAttachment): boolean {
  return VISION_MIME.has((file.mime || '').toLowerCase())
}
