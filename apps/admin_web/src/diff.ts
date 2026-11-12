// 文本、列表的差异计算：纯函数，不依赖界面。
// 对比的单位：文本按"字/词"拆开做最长公共子序列；列表按"项"做最长公共子序列，
// 相邻的"删掉一项、加上一项"配成"改了一项"，再对这一对做文本对比。

export type SegKind = 'same' | 'del' | 'add'

export interface Seg {
  text: string
  kind: SegKind
}

export interface TextDiff {
  left: Seg[]
  right: Seg[]
  changed: boolean
}

export type RowKind = 'same' | 'changed' | 'removed' | 'added'

export interface ListRow {
  kind: RowKind
  left: string | null
  right: string | null
  leftSegs: Seg[] | null
  rightSegs: Seg[] | null
}

type Op<T> = { kind: 'same' | 'del' | 'add'; value: T }

/** 做 LCS 的最大规模（元素个数之积）。再大就放弃细分，整段当作"换掉了"，免得页面卡死。 */
const MAX_CELLS = 2_000_000

/** 汉字一个字一块，英文、数字、下划线、小数点连成一个词，空白连成一块，其余符号一个一块。 */
export function tokenize(text: string): string[] {
  return text.match(/\s+|[㐀-鿿]|[A-Za-z0-9_.]+|[\s\S]/gu) ?? []
}

/** 最长公共子序列意义上的差异。先去掉两头相同的部分，只对中间做动态规划。 */
export function diffSequences<T>(a: T[], b: T[], same: (x: T, y: T) => boolean = (x, y) => x === y): Op<T>[] {
  let start = 0
  while (start < a.length && start < b.length && same(a[start] as T, b[start] as T)) start++
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && same(a[endA - 1] as T, b[endB - 1] as T)) {
    endA--
    endB--
  }

  const head: Op<T>[] = a.slice(0, start).map((value) => ({ kind: 'same', value }))
  const tail: Op<T>[] = a.slice(endA).map((value) => ({ kind: 'same', value }))
  const midA = a.slice(start, endA)
  const midB = b.slice(start, endB)
  return [...head, ...diffMiddle(midA, midB, same), ...tail]
}

function diffMiddle<T>(a: T[], b: T[], same: (x: T, y: T) => boolean): Op<T>[] {
  if (a.length === 0) return b.map((value) => ({ kind: 'add', value }))
  if (b.length === 0) return a.map((value) => ({ kind: 'del', value }))
  if (a.length * b.length > MAX_CELLS) {
    return [
      ...a.map((value): Op<T> => ({ kind: 'del', value })),
      ...b.map((value): Op<T> => ({ kind: 'add', value })),
    ]
  }

  // lcs[i][j]：a 的后 i.. 与 b 的后 j.. 的最长公共子序列长度
  const width = b.length + 1
  const lcs = new Uint32Array((a.length + 1) * width)
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i * width + j] = same(a[i] as T, b[j] as T)
        ? (lcs[(i + 1) * width + j + 1] as number) + 1
        : Math.max(lcs[(i + 1) * width + j] as number, lcs[i * width + j + 1] as number)
    }
  }

  const ops: Op<T>[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (same(a[i] as T, b[j] as T)) {
      ops.push({ kind: 'same', value: a[i] as T })
      i++
      j++
    } else if ((lcs[(i + 1) * width + j] as number) >= (lcs[i * width + j + 1] as number)) {
      ops.push({ kind: 'del', value: a[i] as T })
      i++
    } else {
      ops.push({ kind: 'add', value: b[j] as T })
      j++
    }
  }
  while (i < a.length) ops.push({ kind: 'del', value: a[i++] as T })
  while (j < b.length) ops.push({ kind: 'add', value: b[j++] as T })
  return ops
}

function pushSeg(segs: Seg[], text: string, kind: SegKind): void {
  const last = segs[segs.length - 1]
  if (last && last.kind === kind) last.text += text
  else segs.push({ text, kind })
}

/** 两段文本的差异：左边带"删掉的"，右边带"新加的"，相邻同类的片段合并。 */
export function diffText(a: string, b: string): TextDiff {
  if (a === b) {
    const segs: Seg[] = a === '' ? [] : [{ text: a, kind: 'same' }]
    return { left: segs, right: segs.map((seg) => ({ ...seg })), changed: false }
  }
  const left: Seg[] = []
  const right: Seg[] = []
  for (const op of diffSequences(tokenize(a), tokenize(b))) {
    if (op.kind === 'same') {
      pushSeg(left, op.value, 'same')
      pushSeg(right, op.value, 'same')
    } else if (op.kind === 'del') {
      pushSeg(left, op.value, 'del')
    } else {
      pushSeg(right, op.value, 'add')
    }
  }
  return { left, right, changed: true }
}

/**
 * 两个列表的差异，按顺序给出每一行。
 * 完全相同的项是 same；相邻的"删一项、加一项"配成 changed（带文本级的差异）；剩下的是 removed / added。
 */
export function diffList(a: string[], b: string[]): ListRow[] {
  const rows: ListRow[] = []
  const ops = diffSequences(a, b)
  let index = 0
  while (index < ops.length) {
    const op = ops[index] as Op<string>
    if (op.kind === 'same') {
      rows.push({ kind: 'same', left: op.value, right: op.value, leftSegs: null, rightSegs: null })
      index++
      continue
    }
    const removed: string[] = []
    const added: string[] = []
    while (index < ops.length && (ops[index] as Op<string>).kind !== 'same') {
      const run = ops[index] as Op<string>
      if (run.kind === 'del') removed.push(run.value)
      else added.push(run.value)
      index++
    }
    const pairs = Math.min(removed.length, added.length)
    for (let k = 0; k < pairs; k++) {
      const inline = diffText(removed[k] as string, added[k] as string)
      rows.push({
        kind: 'changed',
        left: removed[k] as string,
        right: added[k] as string,
        leftSegs: inline.left,
        rightSegs: inline.right,
      })
    }
    for (const value of removed.slice(pairs)) {
      rows.push({ kind: 'removed', left: value, right: null, leftSegs: null, rightSegs: null })
    }
    for (const value of added.slice(pairs)) {
      rows.push({ kind: 'added', left: null, right: value, leftSegs: null, rightSegs: null })
    }
  }
  return rows
}

/** 列表有没有任何改动。 */
export function listChanged(rows: ListRow[]): boolean {
  return rows.some((row) => row.kind !== 'same')
}
