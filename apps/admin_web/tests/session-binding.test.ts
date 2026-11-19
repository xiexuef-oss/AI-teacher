import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import * as session from '../src/session'
import { handleUnauthorized } from '../src/api/guard'
import { ApiError } from '../src/api/client'
import { createHash } from 'node:crypto'

const A = { token: 'synthetic-A', userId: 'A', role: 'reviewer' as const }
const B = { token: 'synthetic-B', userId: 'B', role: 'reviewer' as const }
afterEach(() => vi.restoreAllMocks())
beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  session.setSession(A)
})
it('old request 401 cannot clear a later signed-in account', () => {
  const binding = session.captureSessionBinding()
  session.setSession(B)
  expect(handleUnauthorized(new ApiError(401, 'unauthorized', 'expired'), binding)).toBe(true)
  expect(session.useSession().session?.userId).toBe('B')
})
it('same identity signing out and in invalidates an old binding', () => {
  const old = session.captureSessionBinding()
  session.clearSession()
  session.setSession(A)
  expect(session.isCurrentSessionBinding(old)).toBe(false)
  expect(session.isCurrentSessionBinding(session.captureSessionBinding())).toBe(true)
})
it('another tab session replacement prevents sending before storage event delivery', () => {
  const old = session.captureSessionBinding()
  localStorage.setItem('tutor_admin_session', JSON.stringify(B))
  expect(session.isCurrentSessionBinding(old)).toBe(false)
})
it('current request 401 still logs out the current identity', () => {
  const current = session.captureSessionBinding()
  expect(handleUnauthorized(new ApiError(401, 'unauthorized', 'expired'), current)).toBe(true)
  expect(session.useSession().session).toBeNull()
})
it('received storage event updates identity and invalidates in-flight bindings', () => {
  const old = session.captureSessionBinding()
  localStorage.setItem('tutor_admin_session', JSON.stringify(B))
  window.dispatchEvent(new StorageEvent('storage', { key: 'tutor_admin_session', newValue: JSON.stringify(B) }))
  expect(session.useSession().session?.userId).toBe('B')
  expect(session.isCurrentSessionBinding(old)).toBe(false)
})
it('failed login persistence is explicit and cannot leave an unusable signed-in identity', () => {
  session.clearSession()
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('quota', 'QuotaExceededError') })
  expect(() => session.setSession(A)).toThrow('无法保存登录状态')
  expect(session.useSession().session).toBeNull()
  expect(session.captureSessionBinding()).toBeNull()
})

it('legacy full sessions load without rewriting raw data and logout preserves owner recovery', () => {
  const raw = JSON.stringify(A, null, 2)
  localStorage.setItem('tutor_admin_session', raw)
  window.dispatchEvent(new StorageEvent('storage', { key: 'tutor_admin_session' }))
  const binding = session.captureSessionBinding()
  expect(session.isCurrentSessionBinding(binding)).toBe(true)
  expect(localStorage.getItem('tutor_admin_session')).toBe(raw)
  localStorage.setItem('document-import:A:pending', 'original-A-command')
  sessionStorage.setItem('batch-review:A', 'original-A-batch')
  session.clearSession()
  expect(session.useSession().session).toBeNull()
  expect(session.isCurrentSessionBinding(binding)).toBe(false)
  expect(localStorage.getItem('tutor_admin_session')).toBe(raw)
  expect(localStorage.getItem('document-import:A:pending')).toBe('original-A-command')
  expect(sessionStorage.getItem('batch-review:A')).toBe('original-A-batch')
  window.dispatchEvent(new StorageEvent('storage', { key: 'tutor_admin_session' }))
  expect(session.useSession().session).toBeNull()
})

it('a fresh same-credential login in another tab invalidates the old record before events', () => {
  const binding = session.captureSessionBinding()
  localStorage.setItem('tutor_admin_auth_record:fresh-same-owner', JSON.stringify(A))
  localStorage.setItem('tutor_admin_session', JSON.stringify({ version: 2, recordId: 'fresh-same-owner', userId: A.userId, role: A.role }))
  expect(session.isCurrentSessionBinding(binding)).toBe(false)
  window.dispatchEvent(new StorageEvent('storage', { key: 'tutor_admin_session' }))
  expect(session.useSession().session?.userId).toBe(A.userId)
  expect(session.isCurrentSessionBinding(session.captureSessionBinding())).toBe(true)
})

it('failed pointer persistence preserves the previous owner and its usable binding', () => {
  const binding = session.captureSessionBinding()
  const nativeSet = Storage.prototype.setItem
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(function (this: Storage, key: string, value: string) {
    if (key === 'tutor_admin_session') throw new DOMException('quota', 'QuotaExceededError')
    nativeSet.call(this, key, value)
  })
  expect(() => session.setSession(B)).toThrow('无法保存登录状态')
  expect(session.useSession().session?.userId).toBe(A.userId)
  expect(session.isCurrentSessionBinding(binding)).toBe(true)
})

it('legacy identity uses standard SHA256 with canonical UTF8 credentials and preserves original raw on explicit login', () => {
  const legacy = { token: 'synthetic-' + '长凭据'.repeat(40), userId: '旧账号', role: 'admin' as const }
  const raw = JSON.stringify(legacy, null, 2)
  localStorage.setItem('tutor_admin_session', raw)
  window.dispatchEvent(new StorageEvent('storage', { key: 'tutor_admin_session' }))
  const binding = session.captureSessionBinding()
  const digest = createHash('sha256').update(JSON.stringify(legacy), 'utf8').digest('hex')
  expect(binding?.recordId).toBe('legacy:' + digest)
  session.setSession(B)
  expect(localStorage.getItem('tutor_admin_auth_legacy:legacy:' + digest)).toBe(raw)
  expect(session.useSession().session?.userId).toBe(B.userId)
})

it('unreadable legacy backup cannot cause the only original credential record to be overwritten', () => {
  const raw = JSON.stringify(A, null, 2)
  localStorage.setItem('tutor_admin_session', raw)
  window.dispatchEvent(new StorageEvent('storage', { key: 'tutor_admin_session' }))
  const key = 'tutor_admin_auth_legacy:' + session.captureSessionBinding()!.recordId
  localStorage.setItem(key, 'unknown-preserved-format')
  expect(() => session.setSession(B)).toThrow('无法保存登录状态')
  expect(localStorage.getItem('tutor_admin_session')).toBe(raw)
  expect(localStorage.getItem(key)).toBe('unknown-preserved-format')
  expect(session.useSession().session?.userId).toBe(A.userId)
})
