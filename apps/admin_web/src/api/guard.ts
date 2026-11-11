import { clearSession } from '../session'
import { ApiError } from './client'

let handler: () => void = () => {}

/** 登录失效（401）时要做的事（回到登录页）；由 main.ts 在路由创建之后设置，避免循环引用。 */
export function setUnauthorizedHandler(fn: () => void): void {
  handler = fn
}

/** 是 401 就清掉会话并回到登录页，返回 true；其他错误原样交给调用方。 */
export function handleUnauthorized(error: unknown): boolean {
  if (error instanceof ApiError && error.status === 401) {
    clearSession()
    handler()
    return true
  }
  return false
}

export function newIdempotencyKey(): string {
  const c = globalThis.crypto
  return c && 'randomUUID' in c
    ? c.randomUUID()
    : `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
