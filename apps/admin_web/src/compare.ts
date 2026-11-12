// 两个版本的对比：把两份版本快照拆成"部分 → 字段"，每个字段给出有没有改动和具体差异。
// 纯函数，界面只管把结果画出来。
import type { AdminSolution, AdminVersionSnapshot } from './api/types'
import { diffList, diffText, listChanged, type ListRow, type Seg } from './diff'

export interface FieldDiff {
  key: string
  label: string
  /** 内容里带 $公式$：界面上除了原文，再渲染一份公式。 */
  math: boolean
  /** text：一段文本；rows：多行（列表、键值对、JSON 的每一行）。 */
  mode: 'text' | 'rows'
  changed: boolean
  left: string | null
  right: string | null
  leftSegs: Seg[] | null
  rightSegs: Seg[] | null
  rows: ListRow[]
}

export interface SectionDiff {
  key: string
  title: string
  changed: boolean
  fields: FieldDiff[]
}

export interface Comparison {
  sections: SectionDiff[]
  changed: boolean
  /** 有改动的部分的名字，按顺序。 */
  changedTitles: string[]
}

const GRADE_LABEL: Record<string, string> = { G10: '高一', G11: '高二', G12: '高三' }
const SOLUTION_NAME = { standard: '标准解法', fast: '快速解法' } as const

const hasMath = (...texts: (string | null | undefined)[]): boolean =>
  texts.some((text) => !!text && /\$[^$]+\$/.test(text))

function textField(key: string, label: string, left: string, right: string, math = false): FieldDiff {
  const diff = diffText(left, right)
  return {
    key,
    label,
    math: math && hasMath(left, right),
    mode: 'text',
    changed: diff.changed,
    left,
    right,
    leftSegs: diff.left,
    rightSegs: diff.right,
    rows: [],
  }
}

function rowsField(key: string, label: string, left: string[], right: string[], math = false): FieldDiff {
  const rows = diffList(left, right)
  return {
    key,
    label,
    math: math && hasMath(...left, ...right),
    mode: 'rows',
    changed: listChanged(rows),
    left: null,
    right: null,
    leftSegs: null,
    rightSegs: null,
    rows,
  }
}

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, inner]) => [key, sortKeys(inner)]),
    )
  }
  return value
}

/** 把结构化的值摊成缩进的 JSON 的每一行（键排好序）；空对象、空数组没有行。 */
export function jsonLines(value: unknown): string[] {
  if (value === null || value === undefined) return []
  if (Array.isArray(value) && value.length === 0) return []
  if (typeof value === 'object' && !Array.isArray(value) && Object.keys(value as object).length === 0) return []
  return JSON.stringify(sortKeys(value), null, 2).split('\n')
}

function answerLines(value: unknown): string[] {
  if (Array.isArray(value)) return [value.map(String).join('、')]
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).map(([key, answer]) => `${key} = ${String(answer)}`)
  }
  return value === undefined || value === null ? [] : [String(value)]
}

function optionLines(options: { key: string; text: string }[]): string[] {
  return options.map((option) => `${option.key}. ${option.text}`)
}

function analysisLines(analysis: Record<string, string>): string[] {
  return Object.entries(analysis)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([key, text]) => `${key}. ${text}`)
}

function reviewText(solution: AdminSolution | undefined): string {
  if (!solution) return '没有这种解法'
  return solution.reviewed ? '已审核' : '未审核'
}

function solutionFields(
  kind: 'standard' | 'fast',
  left: AdminSolution | undefined,
  right: AdminSolution | undefined,
): FieldDiff[] {
  const name = SOLUTION_NAME[kind]
  const fields = [
    textField(`${kind}.review`, `${name} · 审核标记`, reviewText(left), reviewText(right)),
    rowsField(`${kind}.steps`, `${name} · 步骤`, left?.steps ?? [], right?.steps ?? [], true),
    textField(`${kind}.final`, `${name} · 答案`, left?.final_answer ?? '', right?.final_answer ?? '', true),
    rowsField(`${kind}.points`, `${name} · 方法要点`, left?.key_points ?? [], right?.key_points ?? []),
  ]
  if (kind === 'fast') {
    fields.push(
      rowsField('fast.conditions', `${name} · 适用条件`, left?.conditions ?? [], right?.conditions ?? [], true),
      textField('fast.boundary', `${name} · 不适用的情形`, left?.boundary ?? '', right?.boundary ?? '', true),
    )
  }
  return fields
}

function section(key: string, title: string, fields: FieldDiff[]): SectionDiff {
  return { key, title, changed: fields.some((field) => field.changed), fields }
}

export function compareSnapshots(left: AdminVersionSnapshot, right: AdminVersionSnapshot): Comparison {
  const gradeText = (grade: string | null) => (grade === null ? '不限' : (GRADE_LABEL[grade] ?? grade))
  const standardOf = (shot: AdminVersionSnapshot) => shot.solutions.find((item) => item.kind === 'standard')
  const fastOf = (shot: AdminVersionSnapshot) => shot.solutions.find((item) => item.kind === 'fast')
  const blankLines = (shot: AdminVersionSnapshot) =>
    shot.content.blanks.map(
      (blank) => `${blank.key}｜${blank.label ?? ''}｜${blank.unit_hint ?? ''}｜${blank.placeholder ?? ''}`,
    )
  const extraContent = (shot: AdminVersionSnapshot) =>
    shot.content.subquestions.length === 0 && shot.content.attachments.length === 0
      ? []
      : jsonLines({ attachments: shot.content.attachments, subquestions: shot.content.subquestions })

  const sections: SectionDiff[] = [
    section('basic', '基本信息', [
      textField('title', '标题', left.title, right.title),
      textField('difficulty', '难度', String(left.difficulty), String(right.difficulty)),
      textField('grade', '年级', gradeText(left.grade), gradeText(right.grade)),
    ]),
    section('content', '题面', [
      textField('stem', '题干', left.content.stem, right.content.stem, true),
      rowsField('options', '选项', optionLines(left.content.options), optionLines(right.content.options), true),
      rowsField('blanks', '空位（键｜标签｜单位提示｜占位文字）', blankLines(left), blankLines(right)),
      rowsField('extra', '小问与附件', extraContent(left), extraContent(right)),
    ]),
    section('answer', '答案', [
      rowsField('answer', '标准答案', answerLines(left.answer.value), answerLines(right.answer.value)),
      rowsField('rules', '判定规则', jsonLines(left.answer.equivalence_rules), jsonLines(right.answer.equivalence_rules)),
      rowsField('units', '单位规则', jsonLines(left.answer.units), jsonLines(right.answer.units)),
    ]),
    section('solutions', '解法', [
      ...solutionFields('standard', standardOf(left), standardOf(right)),
      ...solutionFields('fast', fastOf(left), fastOf(right)),
    ]),
    section('teaching', '教学辅助', [
      textField('concept', '知识点讲解', left.teaching.concept ?? '', right.teaching.concept ?? ''),
      rowsField('hints', '分层提示', left.teaching.hints, right.teaching.hints, true),
      textField(
        'rephrase',
        '换种讲法',
        left.teaching.concept_rephrase ?? '',
        right.teaching.concept_rephrase ?? '',
        true,
      ),
      rowsField(
        'analysis',
        '选项分析',
        analysisLines(left.teaching.option_analysis),
        analysisLines(right.teaching.option_analysis),
        true,
      ),
      rowsField('visual', '图解', jsonLines(left.teaching.visual), jsonLines(right.teaching.visual)),
      rowsField('markers', '额外的泄题标记', left.teaching.leak_markers, right.teaching.leak_markers),
    ]),
    section('knowledge', '知识点', [rowsField('knowledge', '知识点', left.knowledge, right.knowledge)]),
    section('rubric', '评分细则', [rowsField('rubric', '评分细则', jsonLines(left.rubric), jsonLines(right.rubric))]),
  ]

  const changedTitles = sections.filter((item) => item.changed).map((item) => item.title)
  return { sections, changed: changedTitles.length > 0, changedTitles }
}
