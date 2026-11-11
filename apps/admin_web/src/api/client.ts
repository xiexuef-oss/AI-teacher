import type { ErrorBody } from './types'

/** 服务端返回的错误信封（{"error": {...}}），或者根本连不上（status 为 0）。 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Record<string, unknown> = {},
    readonly requestId = '',
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** 后端地址：VITE_API_BASE，缺省为本机开发服务器。 */
export function apiBase(): string {
  const configured = import.meta.env.VITE_API_BASE
  return (configured && configured.length > 0 ? configured : 'http://127.0.0.1:8000/api/v1').replace(
    /\/$/,
    '',
  )
}

export interface RequestOptions {
  token?: string | null
  query?: Record<string, string | number | null | undefined>
  body?: unknown
  /** 非幂等动作的幂等键：同一个用户动作固定一个，重试时复用。 */
  idempotencyKey?: string
}

export async function request<T>(
  method: 'GET' | 'POST',
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const url = new URL(apiBase() + path, window.location.href)
  for (const [name, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(name, String(value))
  }
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (options.token) headers.Authorization = `Bearer ${options.token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    })
  } catch {
    throw new ApiError(0, 'network_error', '连不上服务器，请确认后端已经启动')
  }

  const text = await response.text()
  let payload: { data?: unknown; error?: ErrorBody } | null = null
  if (text) {
    try {
      payload = JSON.parse(text) as { data?: unknown; error?: ErrorBody }
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    const error = payload?.error
    throw new ApiError(
      response.status,
      error?.code ?? 'http_error',
      error?.message ?? `请求失败（${response.status}）`,
      (error?.details as Record<string, unknown> | undefined) ?? {},
      error?.request_id ?? '',
    )
  }
  return payload?.data as T
}
