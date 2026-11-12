import { describe, expect, it } from 'vitest'
import { diffList, diffSequences, diffText, listChanged, tokenize } from '../src/diff'

const text = (segs: { text: string }[]) => segs.map((seg) => seg.text).join('')

describe('tokenize', () => {
  it('汉字一个字一块，英文数字连成词，空白一块，符号一个一块', () => {
    expect(tokenize('求 f(x)=x2 的值')).toEqual(['求', ' ', 'f', '(', 'x', ')', '=', 'x2', ' ', '的', '值'])
    expect(tokenize('')).toEqual([])
    expect(tokenize('a  b')).toEqual(['a', '  ', 'b'])
  })

  it('不会把 LaTeX 的反斜杠和花括号弄丢', () => {
    expect(tokenize('$\\dfrac{a}{b}$').join('')).toBe('$\\dfrac{a}{b}$')
  })
})

describe('diffText', () => {
  it('相同的文本没有差异', () => {
    const diff = diffText('二次函数的图像', '二次函数的图像')
    expect(diff.changed).toBe(false)
    expect(diff.left).toEqual([{ text: '二次函数的图像', kind: 'same' }])
    expect(diff.right).toEqual(diff.left)
  })

  it('改了几个字：左边标出删掉的，右边标出新加的，其余是相同的', () => {
    const diff = diffText('函数 f(x)=|x-1| 的递减区间', '函数 f(x)=|x+1| 的递减区间')

    expect(diff.changed).toBe(true)
    expect(text(diff.left)).toBe('函数 f(x)=|x-1| 的递减区间')
    expect(text(diff.right)).toBe('函数 f(x)=|x+1| 的递减区间')
    expect(diff.left.filter((seg) => seg.kind === 'del').map((seg) => seg.text)).toEqual(['-'])
    expect(diff.right.filter((seg) => seg.kind === 'add').map((seg) => seg.text)).toEqual(['+'])
  })

  it('末尾补了一句：只有右边有"新加的"', () => {
    const diff = diffText('木箱做匀速运动。', '木箱做匀速运动。（按国际单位制作答）')

    expect(diff.left.every((seg) => seg.kind === 'same')).toBe(true)
    expect(diff.right.filter((seg) => seg.kind === 'add').map((seg) => seg.text)).toEqual(['（按国际单位制作答）'])
  })

  it('一边是空的：整段是删掉的或者新加的', () => {
    expect(diffText('', '新内容').right).toEqual([{ text: '新内容', kind: 'add' }])
    expect(diffText('旧内容', '').left).toEqual([{ text: '旧内容', kind: 'del' }])
  })

  it('拼起来总是还原两边的原文（不丢字、不多字）', () => {
    const pairs: [string, string][] = [
      ['abc', 'axc'],
      ['质量为 $5\\ \\text{kg}$ 的木箱', '质量为 $5\\ \\text{kg}$ 的重木箱，放在地面上'],
      ['完全不同', 'totally different'],
      ['重复重复重复', '重复重复'],
    ]
    for (const [a, b] of pairs) {
      const diff = diffText(a, b)
      expect(text(diff.left)).toBe(a)
      expect(text(diff.right)).toBe(b)
    }
  })

  it('特别长的文本不会卡死：超过规模上限就整段当作换掉了', () => {
    const a = '甲乙丙丁'.repeat(2000)
    const b = '戊己庚辛'.repeat(2000)

    const started = Date.now()
    const diff = diffText(a, b)

    expect(Date.now() - started).toBeLessThan(2000)
    expect(text(diff.left)).toBe(a)
    expect(text(diff.right)).toBe(b)
    expect(diff.changed).toBe(true)
  })
})

describe('diffSequences', () => {
  it('两头相同的部分被直接跳过，只对中间做比较', () => {
    const ops = diffSequences([1, 2, 3, 4, 5], [1, 2, 9, 4, 5])
    expect(ops.map((op) => `${op.kind}:${op.value}`)).toEqual(['same:1', 'same:2', 'del:3', 'add:9', 'same:4', 'same:5'])
  })

  it('得到的是最长公共子序列（不是随便配对）', () => {
    const ops = diffSequences(['A', 'B', 'C', 'D'], ['B', 'D', 'E'])
    expect(ops.filter((op) => op.kind === 'same').map((op) => op.value)).toEqual(['B', 'D'])
  })
})

describe('diffList', () => {
  it('没改的项是 same，列表整体没有改动', () => {
    const rows = diffList(['第一层', '第二层'], ['第一层', '第二层'])
    expect(rows.map((row) => row.kind)).toEqual(['same', 'same'])
    expect(listChanged(rows)).toBe(false)
  })

  it('改了其中一项：配成 changed，带文本级差异', () => {
    const rows = diffList(['先画受力图', '列方程', '求解'], ['先画受力图', '沿斜面方向列方程', '求解'])

    expect(rows.map((row) => row.kind)).toEqual(['same', 'changed', 'same'])
    const changed = rows[1]!
    expect([changed.left, changed.right]).toEqual(['列方程', '沿斜面方向列方程'])
    expect(changed.rightSegs!.filter((seg) => seg.kind === 'add').map((seg) => seg.text).join('')).toBe('沿斜面方向')
    expect(listChanged(rows)).toBe(true)
  })

  it('多了一项、少了一项', () => {
    const added = diffList(['甲'], ['甲', '乙'])
    expect(added.map((row) => [row.kind, row.left, row.right])).toEqual([
      ['same', '甲', '甲'],
      ['added', null, '乙'],
    ])
    const removed = diffList(['甲', '乙'], ['乙'])
    expect(removed.map((row) => [row.kind, row.left, row.right])).toEqual([
      ['removed', '甲', null],
      ['same', '乙', '乙'],
    ])
  })

  it('删掉两项、加上一项：先配一对 changed，剩下的是 removed', () => {
    const rows = diffList(['甲', '乙', '丙'], ['丙', '丁'])
    expect(rows.map((row) => row.kind)).toEqual(['removed', 'removed', 'same', 'added'])
    const swapped = diffList(['甲', '乙'], ['丙'])
    expect(swapped.map((row) => row.kind)).toEqual(['changed', 'removed'])
  })

  it('顺序变了也看得出来：同一项换了位置不算"没变"', () => {
    const rows = diffList(['甲', '乙'], ['乙', '甲'])
    expect(listChanged(rows)).toBe(true)
  })

  it('两边都是空：没有行', () => {
    expect(diffList([], [])).toEqual([])
  })
})
