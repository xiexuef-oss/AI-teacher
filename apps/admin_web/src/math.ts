export interface MathSegment {
  text: string
  math: boolean
}

/** 把 `普通文字 $公式$ 普通文字` 拆成片段；没有配对的 `$` 按普通文字保留（与学生端同一规则）。 */
export function splitMath(text: string): MathSegment[] {
  const segments: MathSegment[] = []
  const pattern = /\$([^$]+)\$/g
  let cursor = 0
  for (const match of text.matchAll(pattern)) {
    const start = match.index ?? 0
    if (start > cursor) segments.push({ text: text.slice(cursor, start), math: false })
    segments.push({ text: match[1] ?? '', math: true })
    cursor = start + match[0].length
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), math: false })
  return segments
}
