import { reactive } from 'vue'

export interface Session { token: string; userId: string; role: 'reviewer' | 'admin' }
export class SessionPersistenceError extends Error {
  constructor() { super('无法保存登录状态，请允许本站使用本机存储后重试。'); this.name = 'SessionPersistenceError' }
}
const STORAGE_KEY = 'tutor_admin_session'
const RECORD_PREFIX = 'tutor_admin_auth_record:'
const REVOKED_PREFIX = 'tutor_admin_auth_revoked:'
const LEGACY_PREFIX = 'tutor_admin_auth_legacy:'

// Synchronous SHA-256 only names a legacy identity; it is not encryption.
// Credentials belong to authentication storage, never to command journals.
function legacyDigest(value: string): string {
  const k = [
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
  ]
  const bytes = new TextEncoder().encode(value)
  const data = new Uint8Array(Math.ceil((bytes.length + 9) / 64) * 64)
  data.set(bytes); data[bytes.length] = 0x80
  const view = new DataView(data.buffer)
  view.setUint32(data.length - 8, Math.floor(bytes.length * 8 / 0x100000000))
  view.setUint32(data.length - 4, bytes.length * 8)
  const h = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19]
  const r = (n: number, c: number) => (n >>> c) | (n << (32 - c))
  const w = new Uint32Array(64)
  for (let offset = 0; offset < data.length; offset += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(offset + i * 4)
    for (let i = 16; i < 64; i++) {
      const x = w[i - 15]!, y = w[i - 2]!
      w[i] = (w[i - 16]! + (r(x,7) ^ r(x,18) ^ (x >>> 3)) + w[i - 7]! + (r(y,17) ^ r(y,19) ^ (y >>> 10))) >>> 0
    }
    let [a,b,c,d,e,f,g,z] = h as [number,number,number,number,number,number,number,number]
    for (let i = 0; i < 64; i++) {
      const t1 = (z + (r(e,6) ^ r(e,11) ^ r(e,25)) + ((e & f) ^ (~e & g)) + k[i]! + w[i]!) >>> 0
      const t2 = ((r(a,2) ^ r(a,13) ^ r(a,22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0
      z=g; g=f; f=e; e=(d+t1)>>>0; d=c; c=b; b=a; a=(t1+t2)>>>0
    }
    const next = [a,b,c,d,e,f,g,z]
    for (let i = 0; i < 8; i++) h[i] = (h[i]! + next[i]!) >>> 0
  }
  return h.map(n => n.toString(16).padStart(8,'0')).join('')
}
function parseSession(value: unknown): Session | null {
  if (!value || typeof value !== 'object') return null
  const v = value as Partial<Session>
  return typeof v.token === 'string' && v.token !== '' && typeof v.userId === 'string' && v.userId !== '' &&
    (v.role === 'reviewer' || v.role === 'admin') ? { token: v.token, userId: v.userId, role: v.role } : null
}
interface Identity { session: Session; recordId: string; legacyRaw?: string }
function legacyIdentity(raw: string): Identity | null {
  const value = JSON.parse(raw)
  if (value?.version !== undefined) return null
  const session = parseSession(value)
  return session ? { session, recordId: 'legacy:' + legacyDigest(JSON.stringify(session)), legacyRaw: raw } : null
}
function load(): Identity | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw)
    if (value?.version === 2) {
      if (typeof value.recordId !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value.recordId)) return null
      const rawRecord = window.localStorage.getItem(RECORD_PREFIX + value.recordId)
      const session = rawRecord ? parseSession(JSON.parse(rawRecord)) : null
      return session && session.userId === value.userId && session.role === value.role ? { session, recordId: value.recordId } : null
    }
    // No read-time migration writes: a different tab may already have installed B.
    const identity = legacyIdentity(raw)
    return identity && window.localStorage.getItem(REVOKED_PREFIX + identity.recordId) === null ? identity : null
  } catch { return null } // Preserve unreadable/unknown bytes.
}
const initial = load()
const state = reactive<{ session: Session | null }>({ session: initial?.session ?? null })
let recordId = initial?.recordId ?? null
let legacyRaw = initial?.legacyRaw
let identityEpoch = 0
function adopt(identity: Identity | null): void {
  const next = identity?.session ?? null
  if (recordId === (identity?.recordId ?? null) && state.session?.token === next?.token &&
      state.session?.userId === next?.userId && state.session?.role === next?.role) return
  identityEpoch += 1
  recordId = identity?.recordId ?? null
  legacyRaw = identity?.legacyRaw
  state.session = next
}
/** In-memory context. Never persist this entire object or its token in a command. */
export interface SessionBinding {
  readonly epoch: number
  readonly token: string
  readonly userId: string
  readonly role: Session['role']
  readonly recordId: string
}
export function captureSessionBinding(): SessionBinding | null {
  return state.session && recordId ? Object.freeze({ ...state.session, recordId, epoch: identityEpoch }) : null
}
export function isCurrentSessionBinding(binding: SessionBinding | null): binding is SessionBinding {
  if (!binding || binding.epoch !== identityEpoch || binding.recordId !== recordId) return false
  const current = state.session
  if (!current || current.userId !== binding.userId || current.token !== binding.token || current.role !== binding.role) return false
  const persisted = load()
  return persisted !== null && persisted.recordId === binding.recordId && persisted.session.userId === binding.userId &&
    persisted.session.token === binding.token && persisted.session.role === binding.role
}
window.addEventListener('storage', event => {
  if (event.key === null || event.key === STORAGE_KEY || event.key.startsWith(RECORD_PREFIX) || event.key.startsWith(REVOKED_PREFIX)) adopt(load())
})
export function useSession() { return state }
function preserveLegacy(identity: Identity): void {
  if (identity.legacyRaw === undefined) return
  const key = LEGACY_PREFIX + identity.recordId
  const existing = window.localStorage.getItem(key)
  if (existing === null) window.localStorage.setItem(key, identity.legacyRaw)
  else if (legacyIdentity(existing)?.recordId !== identity.recordId) throw new Error('Unknown legacy backup preserved')
}
export function setSession(session: Session): void {
  const id = crypto.randomUUID()
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw) {
      let old: Identity | null
      try { old = legacyIdentity(raw) } catch { old = null }
      if (old) preserveLegacy(old)
    }
    window.localStorage.setItem(RECORD_PREFIX + id, JSON.stringify(session))
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, recordId: id, userId: session.userId, role: session.role }))
  } catch {
    try { window.localStorage.removeItem(RECORD_PREFIX + id) } catch { /* only our uncommitted record */ }
    throw new SessionPersistenceError()
  }
  adopt({ session: { ...session }, recordId: id })
}
export function clearSession(): void {
  // Only invalidate OUR immutable record. Never remove or rewrite the shared
  // pointer, even if another tab switches accounts between a guard and this call.
  const target = recordId
  const session = state.session
  if (target && session) {
    try {
      if (legacyRaw !== undefined) {
        preserveLegacy({ session, recordId: target, legacyRaw })
        window.localStorage.setItem(REVOKED_PREFIX + target, '1')
      } else {
        window.localStorage.removeItem(RECORD_PREFIX + target)
      }
    } catch { throw new SessionPersistenceError() }
  }
  // Keep owner recovery journals; a dangling v2 pointer never falls back to legacy.
  adopt(load())
}
