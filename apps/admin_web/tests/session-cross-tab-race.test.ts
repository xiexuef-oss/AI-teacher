import { afterEach, expect, it, vi } from 'vitest'
import { captureSessionBinding, setSession, useSession } from '../src/session'
import { handleUnauthorized } from '../src/api/guard'
import { ApiError } from '../src/api/client'

const STORAGE_KEY = 'tutor_admin_session'
const A = { token: 'synthetic-race-A', userId: 'race-A', role: 'reviewer' as const }
const B = { token: 'synthetic-race-B', userId: 'race-B', role: 'reviewer' as const }

afterEach(() => vi.restoreAllMocks())

it('A 401 cannot remove B persisted after the final binding read but before logout', () => {
  localStorage.clear()
  sessionStorage.clear()
  setSession(A)
  const binding = captureSessionBinding()
  const nativeGet = Storage.prototype.getItem
  const nativeSet = Storage.prototype.setItem
  const initialPointer = JSON.parse(nativeGet.call(localStorage, STORAGE_KEY)!)
  let injected = false
  let gateReturned: string | null = null

  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key: string) {
    const value = nativeGet.call(this, key)
    if (this === localStorage && key === STORAGE_KEY && !injected) {
      injected = true
      gateReturned = value
      // Another tab writes B after this read has obtained A. Its storage event
      // has not reached this tab, so do not mutate the application's A state.
      nativeSet.call(localStorage, STORAGE_KEY, JSON.stringify(B))
      expect(useSession().session?.userId).toBe(A.userId)
    }
    return value
  })

  expect(handleUnauthorized(new ApiError(401, 'unauthorized', 'A expired'), binding)).toBe(true)
  expect(injected).toBe(true)
  expect(JSON.parse(gateReturned!)).toEqual(initialPointer)
  expect(JSON.parse(nativeGet.call(localStorage, STORAGE_KEY) ?? 'null')).toEqual(B)
})

it('A logout does not remove a different immutable auth record and active pointer', () => {
  localStorage.clear()
  setSession(A)
  const binding = captureSessionBinding()
  const nativeGet = Storage.prototype.getItem
  const nativeSet = Storage.prototype.setItem
  const pointerB = { version: 2, recordId: 'other-tab-B', userId: B.userId, role: B.role }
  let injected = false
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(function (this: Storage, key: string) {
    const value = nativeGet.call(this, key)
    if (this === localStorage && key === STORAGE_KEY && !injected) {
      injected = true
      nativeSet.call(localStorage, 'tutor_admin_auth_record:other-tab-B', JSON.stringify(B))
      nativeSet.call(localStorage, STORAGE_KEY, JSON.stringify(pointerB))
    }
    return value
  })
  handleUnauthorized(new ApiError(401, 'unauthorized', 'A expired'), binding)
  expect(JSON.parse(nativeGet.call(localStorage, STORAGE_KEY) ?? 'null')).toEqual(pointerB)
  expect(JSON.parse(nativeGet.call(localStorage, 'tutor_admin_auth_record:other-tab-B')!)).toEqual(B)
  expect(useSession().session?.userId).toBe(B.userId)
})
