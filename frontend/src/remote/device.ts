import type { RemoteCommandEnvelope } from '../lib/types'

const DB_NAME = 'nova-remote'
const DB_VERSION = 1
const STORE = 'device'

export type StoredDevice = {
  deviceId: string
  pairId: string
  name: string
  privateKey: CryptoKey
  createdAt: string
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('无法打开本机存储'))
  })
}

async function withStore<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await openDb()
  return new Promise<T>((resolve, reject) => {
    const transaction = db.transaction(STORE, mode)
    const request = run(transaction.objectStore(STORE))
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error ?? new Error('本机存储操作失败'))
    transaction.oncomplete = () => db.close()
  })
}

export async function loadStoredDevice(): Promise<StoredDevice | null> {
  try {
    const value = await withStore<StoredDevice | undefined>('readonly', (store) => store.get('current'))
    if (!value || !value.deviceId || !value.privateKey) return null
    return value
  } catch {
    return null
  }
}

export async function saveStoredDevice(device: StoredDevice): Promise<void> {
  await withStore('readwrite', (store) => store.put(device, 'current'))
}

export async function clearStoredDevice(): Promise<void> {
  try {
    await withStore('readwrite', (store) => store.delete('current'))
  } catch {
    /* 清不掉时至少让当前页忘记设备 */
  }
}

export function pairingParams(): { pairId: string; token: string } | null {
  const hash = window.location.hash.replace(/^#/, '')
  if (!hash) return null
  const params = new URLSearchParams(hash)
  const pairId = params.get('pair_id') ?? ''
  const token = params.get('token') ?? ''
  if (!pairId || !token) return null
  return { pairId, token }
}

export function removePairingHash(): void {
  try {
    window.history.replaceState(null, '', window.location.pathname)
  } catch {
    /* 地址栏清理失败不影响已完成的配对 */
  }
}

export function cryptoAvailable(): boolean {
  return typeof crypto !== 'undefined' && !!crypto.subtle
}

export function base64url(value: ArrayBuffer | Uint8Array): string {
  const bytes = value instanceof Uint8Array ? value : new Uint8Array(value)
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

/** Must match Python's json.dumps(sort_keys=True, separators=(",", ":"))。 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`
  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(',')}}`
}

export async function createDeviceKeys(): Promise<{
  privateKey: CryptoKey
  publicKey: Record<string, string>
}> {
  const pair = await crypto.subtle.generateKey(
    { name: 'ECDSA', namedCurve: 'P-256' },
    false,
    ['sign', 'verify'],
  )
  const publicJwk = await crypto.subtle.exportKey('jwk', pair.publicKey)
  return {
    privateKey: pair.privateKey,
    publicKey: {
      kty: 'EC',
      crv: 'P-256',
      x: String(publicJwk.x ?? ''),
      y: String(publicJwk.y ?? ''),
    },
  }
}

function randomHex(bytes: number): string {
  const data = new Uint8Array(bytes)
  crypto.getRandomValues(data)
  return Array.from(data, (value) => value.toString(16).padStart(2, '0')).join('')
}

export async function signCommand(
  device: StoredDevice,
  type: 'status.get' | 'run.stop' | 'approval.list' | 'approval.decide',
  options: {
    ttlSeconds?: number
    approvalId?: string
    actionHash?: string
    decision?: 'approve' | 'reject'
  } = {},
): Promise<RemoteCommandEnvelope> {
  const now = Date.now()
  const unsigned = {
    v: 1,
    command_id: `cmd_${randomHex(8)}`,
    device_id: device.deviceId,
    type,
    action_hash: options.actionHash ?? '',
    args_ciphertext: '',
    approval_id: options.approvalId ?? '',
    decision: options.decision ?? '',
    issued_at: new Date(now).toISOString(),
    expires_at: new Date(now + (options.ttlSeconds ?? 45) * 1000).toISOString(),
    nonce: randomHex(12),
  }
  const signature = await crypto.subtle.sign(
    { name: 'ECDSA', hash: 'SHA-256' },
    device.privateKey,
    new TextEncoder().encode(canonicalJson(unsigned)),
  )
  return {
    ...unsigned,
    type,
    signature: base64url(signature),
  } as RemoteCommandEnvelope
}
