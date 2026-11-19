import { describe, expect, it } from 'vitest'
import { bodyFromDetail, formFromDetail, isUnchanged, requestFromForm } from '../src/editing'
import { detail } from './fixtures'

const link = {
  target_block_id: 'hint:1',
  source_span: { block_id: 'stem', block_sha256: 'a'.repeat(64), start: 0, end: 2 },
  independent_safe: true,
}

describe('审核引用注记编辑', () => {
  it('普通编辑和本机草稿恢复保留原来的审核范围，不重算摘要', () => {
    const source = detail()
    source.teaching.reference_links = [structuredClone(link)]
    const form = formFromDetail(source)
    const restored = JSON.parse(JSON.stringify(form))
    const built = requestFromForm(restored, source)
    expect(built.ok).toBe(true)
    if (!built.ok) return
    expect(built.body.teaching.reference_links).toEqual([link])
    expect(built.body).toEqual(bodyFromDetail(source))
    expect(isUnchanged(built.body, source)).toBe(true)
    restored.title += '（修订）'
    const edited = requestFromForm(restored, source)
    expect(edited.ok && edited.body.teaching.reference_links).toEqual([link])
    expect(source.teaching.reference_links).toEqual([link])
  })

  it('旧本机表单没有新增字段时仍保留当前版本注记', () => {
    const source = detail()
    source.teaching.reference_links = [structuredClone(link)]
    const form = formFromDetail(source)
    delete (form as unknown as Record<string, unknown>).referenceLinksJson
    const built = requestFromForm(form, source)
    expect(built.ok && built.body.teaching.reference_links).toEqual([link])
  })

  it('明确清空注记才删除，不能静默清除', () => {
    const source = detail()
    source.teaching.reference_links = [structuredClone(link)]
    const form = { ...formFromDetail(source), referenceLinksJson: '[]' }
    const built = requestFromForm(form, source)
    expect(built.ok && built.body.teaching.reference_links).toEqual([])
  })

  it.each([
    '{}', 'null', '{',
    JSON.stringify([{ ...link, url: 'https://example.test' }]),
    JSON.stringify([{ ...link, independent_safe: 'true' }]),
    JSON.stringify([{ ...link, source_span: { ...link.source_span, start: 0.5 } }]),
    JSON.stringify([{ ...link, source_span: { ...link.source_span, end: 0 } }]),
    JSON.stringify([{ ...link, source_span: { ...link.source_span, block_id: 'https://example.test' } }]),
    JSON.stringify([{ ...link, source_span: { ...link.source_span, block_id: 'stem\n' } }]),
    JSON.stringify([{ ...link, source_span: { ...link.source_span, block_sha256: 'a'.repeat(64) + '\n' } }]),
    JSON.stringify([{ ...link, source_span: { ...link.source_span, url: 'https://example.test' } }]),
    JSON.stringify(Array.from({ length: 9 }, (_, start) => ({ ...link, source_span: { ...link.source_span, start, end: start + 1 } }))),
    JSON.stringify(Array.from({ length: 65 }, (_, start) => ({ ...link, target_block_id: `hint:${start + 1}` }))),
    JSON.stringify([link, link]),
  ])('错误注记不能变成空数组后提交：%s', text => {
    const source = detail()
    const form = { ...formFromDetail(source), referenceLinksJson: text }
    const built = requestFromForm(form, source)
    expect(built.ok).toBe(false)
    if (!built.ok) expect(built.errors.join(' ')).toContain('引用')
  })
})
