import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiBase, request } from '../src/api/client'

function respond(status: number, body: unknown): Response {
  return new Response(body === null ? '' : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('request', () => {
  it('带上 token 与查询参数，取出信封里的 data', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(respond(200, { data: { ok: 1 } }))

    const data = await request<{ ok: number }>('GET', '/admin/questions', {
      token: 'tok',
      query: { status: 'draft', subject: undefined, cursor: null, limit: 20 },
    })

    expect(data).toEqual({ ok: 1 })
    const [url, init] = spy.mock.calls[0] as [URL, RequestInit]
    expect(url.pathname).toBe('/api/v1/admin/questions')
    expect(url.searchParams.get('status')).toBe('draft')
    expect(url.searchParams.get('limit')).toBe('20')
    expect(url.searchParams.has('subject')).toBe(false)
    expect(url.searchParams.has('cursor')).toBe(false)
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok')
  })

  it('POST 带 JSON 请求体和幂等键', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(respond(200, { data: {} }))

    await request('POST', '/admin/questions/x/review', {
      token: 'tok',
      body: { decision: 'approve' },
      idempotencyKey: 'key-0001-abcd',
    })

    const [, init] = spy.mock.calls[0] as [URL, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['Idempotency-Key']).toBe('key-0001-abcd')
    expect(headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ decision: 'approve' }))
  })

  it('错误信封变成 ApiError，保留错误码、说明、details 与请求 ID', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      respond(422, {
        error: {
          code: 'content_checks_failed',
          message: '程序校验没通过',
          details: { problems: ['a', 'b'] },
          request_id: 'req-1',
        },
      }),
    )

    const failure = await request('POST', '/x').catch((error: unknown) => error)

    expect(failure).toBeInstanceOf(ApiError)
    const error = failure as ApiError
    expect([error.status, error.code, error.message, error.requestId]).toEqual([
      422,
      'content_checks_failed',
      '程序校验没通过',
      'req-1',
    ])
    expect(error.details.problems).toEqual(['a', 'b'])
  })

  it('不是 JSON 的错误响应也有说明', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('<html>bad gateway</html>', { status: 502 }))

    const error = (await request('GET', '/x').catch((e: unknown) => e)) as ApiError

    expect([error.status, error.code]).toEqual([502, 'http_error'])
    expect(error.message).toContain('502')
  })

  it('连不上服务器：status 为 0，说明里告诉人去看后端有没有启动', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))

    const error = (await request('GET', '/x').catch((e: unknown) => e)) as ApiError

    expect([error.status, error.code]).toEqual([0, 'network_error'])
    expect(error.message).toContain('后端')
  })

  it('缺省连本机开发服务器', () => {
    expect(apiBase()).toBe('http://127.0.0.1:8000/api/v1')
  })
})
