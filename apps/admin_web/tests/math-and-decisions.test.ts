import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MathText from '../src/components/MathText.vue'
import {
  availableDecisions,
  blockedReason,
  commentRequired,
  explainError,
} from '../src/decisions'
import { splitMath } from '../src/math'
import { AUTHOR, detail, FAST, ME, solution } from './fixtures'

describe('splitMath', () => {
  it('普通文字和行内公式交替', () => {
    expect(splitMath('已知 $x>0$，则 $x+\\dfrac{4}{x}$ 的最小值为')).toEqual([
      { text: '已知 ', math: false },
      { text: 'x>0', math: true },
      { text: '，则 ', math: false },
      { text: 'x+\\dfrac{4}{x}', math: true },
      { text: ' 的最小值为', math: false },
    ])
  })

  it('没有公式、空字符串、不配对的 $', () => {
    expect(splitMath('只有文字')).toEqual([{ text: '只有文字', math: false }])
    expect(splitMath('')).toEqual([])
    const unpaired = splitMath('价格是 $5 元')
    expect(unpaired.every((part) => !part.math)).toBe(true)
    expect(unpaired.map((part) => part.text).join('')).toBe('价格是 $5 元')
  })
})

describe('MathText', () => {
  it('公式交给 KaTeX 渲染，文字原样显示', () => {
    const wrapper = mount(MathText, { props: { text: '函数 $x^2$ 的图像' } })
    expect(wrapper.find('.katex').exists()).toBe(true)
    expect(wrapper.text()).toContain('函数')
    expect(wrapper.text()).toContain('的图像')
    expect(wrapper.html()).not.toContain('$x^2$')
  })

  it('文字里的尖括号不会被当成 HTML', () => {
    const wrapper = mount(MathText, { props: { text: '<img src=x onerror=alert(1)> 和 $a<b$' } })
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('<img src=x onerror=alert(1)>')
  })

  it('解析不了的公式不抛异常，按源码显示', () => {
    const wrapper = mount(MathText, { props: { text: '坏公式 $\\notacommand{x}$ 后面' } })
    expect(wrapper.text()).toContain('后面')
    expect(wrapper.html()).toContain('notacommand')
  })
})

describe('决策规则（与服务端的状态流转一致）', () => {
  it('每种状态下能做的决策', () => {
    expect(availableDecisions('draft')).toEqual(['approve', 'reject'])
    expect(availableDecisions('reviewed')).toEqual(['publish', 'reject'])
    expect(availableDecisions('published')).toEqual(['withdraw'])
    expect(availableDecisions('withdrawn')).toEqual([])
  })

  it('退回和下线必须写原因，其余不用', () => {
    expect(commentRequired('reject')).toBe(true)
    expect(commentRequired('withdraw')).toBe(true)
    expect(commentRequired('approve')).toBe(false)
    expect(commentRequired('publish')).toBe(false)
  })

  it('提交者不能审核或上线自己的题，但可以退回或下线', () => {
    const own = detail({ created_by: ME, status: 'draft' })
    expect(blockedReason(own, 'approve', ME)).toContain('提交者')
    expect(blockedReason(own, 'reject', ME)).toBeNull()
    expect(blockedReason(detail({ created_by: ME, status: 'reviewed', solutions: [solution({ reviewed: true })] }), 'publish', ME)).toContain('提交者')
    expect(blockedReason(detail({ created_by: ME, status: 'published' }), 'withdraw', ME)).toBeNull()
    expect(blockedReason(detail({ created_by: AUTHOR }), 'approve', ME)).toBeNull()
    expect(blockedReason(detail({ created_by: null }), 'approve', ME)).toBeNull()
  })

  it('程序校验有问题时不能二审或上线', () => {
    const broken = detail({ check_problems: ['answer.value 含有不存在的选项'] })
    expect(blockedReason(broken, 'approve', ME)).toContain('1 个问题')
    expect(blockedReason(broken, 'reject', ME)).toBeNull()
  })

  it('标准解法没有审核确认时不能上线', () => {
    const reviewed = detail({ status: 'reviewed', solutions: [solution({ reviewed: false }), FAST] })
    expect(blockedReason(reviewed, 'publish', ME)).toContain('标准解法')
    const ready = detail({ status: 'reviewed', solutions: [solution({ reviewed: true })] })
    expect(blockedReason(ready, 'publish', ME)).toBeNull()
  })

  it('把错误码翻成审核人看得懂的话', () => {
    expect(explainError('self_review_forbidden', 'x')).toContain('不能审核')
    expect(explainError('version_conflict', 'x')).toContain('刷新')
    expect(explainError('invalid_transition', 'x')).toContain('刷新')
    expect(explainError('something_new', '服务端的说明')).toBe('服务端的说明')
  })
})
