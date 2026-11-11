// 编辑表单与"修改"请求之间的转换。全部是纯函数，好测：
//   formFromDetail   题目详情 → 表单（文本框里的字符串）
//   requestFromForm  表单 → AdminQuestionEdit 请求（或者一组错误）
//   bodyFromDetail   题目详情原样还原成请求；表单没改动时 requestFromForm 的结果必须与它一致
import type {
  AdminQuestionDetail,
  AdminQuestionEdit,
  AdminSolutionInput,
  Grade,
  SolutionKind,
} from './api/types'

export interface OptionRow {
  key: string
  text: string
  analysis: string
  correct: boolean
}

export interface BlankRow {
  key: string
  label: string
  unitHint: string
  placeholder: string
  answer: string
}

export interface SolutionForm {
  on: boolean
  steps: string[]
  finalAnswer: string
  keyPoints: string[]
  conditions: string[]
  boundary: string
}

export interface EditorForm {
  title: string
  difficulty: number
  grade: Grade | ''
  stem: string
  options: OptionRow[]
  blanks: BlankRow[]
  rulesJson: string
  unitsJson: string
  concept: string
  hints: string[]
  conceptRephrase: string
  visualOn: boolean
  visualTemplate: string
  visualParamsJson: string
  visualCaption: string
  leakMarkers: string[]
  standard: SolutionForm
  fast: SolutionForm
  knowledge: string
  rubricJson: string
  comment: string
}

export type Built = { ok: true; body: AdminQuestionEdit } | { ok: false; errors: string[] }

const CHOICE_MODES = new Set(['single_choice', 'multiple_choice'])
const FILL_MODES = new Set(['fill'])

const pretty = (value: unknown): string => JSON.stringify(value ?? {}, null, 2)
const orNull = (text: string): string | null => (text === '' ? null : text)

/** 对象键排序后的 JSON，用来比较"内容有没有变"（文本框里解析出来的对象键顺序可能变）。 */
export function canonical(value: unknown): string {
  const sort = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(sort)
    if (node && typeof node === 'object') {
      return Object.fromEntries(
        Object.entries(node as Record<string, unknown>)
          .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
          .map(([key, inner]) => [key, sort(inner)]),
      )
    }
    return node
  }
  return JSON.stringify(sort(value))
}

function solutionForm(detail: AdminQuestionDetail, kind: SolutionKind): SolutionForm {
  const found = detail.solutions.find((solution) => solution.kind === kind)
  return {
    on: found !== undefined,
    steps: [...(found?.steps ?? [])],
    finalAnswer: found?.final_answer ?? '',
    keyPoints: [...(found?.key_points ?? [])],
    conditions: [...(found?.conditions ?? [])],
    boundary: found?.boundary ?? '',
  }
}

export function formFromDetail(detail: AdminQuestionDetail): EditorForm {
  const correct = new Set(Array.isArray(detail.answer.value) ? detail.answer.value.map(String) : [])
  const answers =
    detail.answer.value && !Array.isArray(detail.answer.value) && typeof detail.answer.value === 'object'
      ? (detail.answer.value as Record<string, unknown>)
      : {}
  const visual = detail.teaching.visual
  return {
    title: detail.title,
    difficulty: detail.difficulty,
    grade: detail.grade ?? '',
    stem: detail.content.stem,
    options: detail.content.options.map((option) => ({
      key: option.key,
      text: option.text,
      analysis: detail.teaching.option_analysis[option.key] ?? '',
      correct: correct.has(option.key),
    })),
    blanks: detail.content.blanks.map((blank) => ({
      key: blank.key,
      label: blank.label ?? '',
      unitHint: blank.unit_hint ?? '',
      placeholder: blank.placeholder ?? '',
      answer: answers[blank.key] === undefined ? '' : String(answers[blank.key]),
    })),
    rulesJson: pretty(detail.answer.equivalence_rules),
    unitsJson: pretty(detail.answer.units),
    concept: detail.teaching.concept ?? '',
    hints: [...detail.teaching.hints],
    conceptRephrase: detail.teaching.concept_rephrase ?? '',
    visualOn: visual !== null,
    visualTemplate: visual?.template_id ?? '',
    visualParamsJson: pretty(visual?.params),
    visualCaption: visual?.caption ?? '',
    leakMarkers: [...detail.teaching.leak_markers],
    standard: solutionForm(detail, 'standard'),
    fast: solutionForm(detail, 'fast'),
    knowledge: detail.knowledge.map((node) => node.code).join(', '),
    rubricJson: pretty(detail.rubric),
    comment: '',
  }
}

function solutionInput(kind: SolutionKind, form: SolutionForm): AdminSolutionInput {
  const keep = (items: string[]) => items.filter((item) => item.trim() !== '')
  const fast = kind === 'fast'
  return {
    kind,
    steps: keep(form.steps),
    final_answer: form.finalAnswer,
    key_points: keep(form.keyPoints),
    conditions: fast ? keep(form.conditions) : null,
    boundary: fast ? orNull(form.boundary) : null,
  }
}

/** 题目详情原样还原成一次"修改"请求（不含修改说明）。 */
export function bodyFromDetail(detail: AdminQuestionDetail): AdminQuestionEdit {
  return {
    expected_version: detail.version,
    title: detail.title,
    difficulty: detail.difficulty,
    grade: detail.grade,
    content: detail.content,
    answer: detail.answer,
    teaching: detail.teaching,
    solutions: detail.solutions.map((solution) => ({
      kind: solution.kind,
      steps: solution.steps,
      final_answer: solution.final_answer,
      key_points: solution.key_points,
      conditions: solution.conditions,
      boundary: solution.boundary,
    })),
    knowledge: detail.knowledge.map((node) => node.code),
    rubric: detail.rubric,
  }
}

/** 契约里 type: object 且没有 properties 的字段，生成出来是 Record<string, never>。 */
type Obj = Record<string, never>

function parseObject(label: string, text: string, errors: string[]): Obj {
  if (text.trim() === '') return {}
  try {
    const parsed: unknown = JSON.parse(text)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Obj
    }
    errors.push(`${label}必须是 JSON 对象（花括号包起来的）`)
  } catch {
    errors.push(`${label}不是合法的 JSON`)
  }
  return {}
}

export function requestFromForm(form: EditorForm, detail: AdminQuestionDetail): Built {
  const errors: string[] = []
  const keep = (items: string[]) => items.filter((item) => item.trim() !== '')

  if (form.title.trim() === '') errors.push('标题不能为空')
  if (form.stem.trim() === '') errors.push('题干不能为空')

  const rules = parseObject('判定规则', form.rulesJson, errors)
  const units = parseObject('单位规则', form.unitsJson, errors)
  const rubric = parseObject('评分细则', form.rubricJson, errors)

  let visual: AdminQuestionEdit['teaching']['visual'] = null
  if (form.visualOn) {
    const params = parseObject('图解参数', form.visualParamsJson, errors)
    const numbers: Record<string, number> = {}
    for (const [name, value] of Object.entries(params as Record<string, unknown>)) {
      if (typeof value === 'number' && Number.isFinite(value)) numbers[name] = value
      else errors.push(`图解参数 ${name} 必须是数字`)
    }
    if (form.visualTemplate.trim() === '') errors.push('图解要选一个模板')
    visual = {
      template_id: form.visualTemplate.trim(),
      params: numbers,
      caption: form.visualCaption,
    }
  }

  // 答案：选择题是勾选的选项键（选中的集合没变就沿用原来的顺序），填空题是每个空位的值
  let value: unknown = detail.answer.value
  if (CHOICE_MODES.has(detail.answer_mode)) {
    const selected = new Set(form.options.filter((row) => row.correct).map((row) => row.key))
    const original = Array.isArray(detail.answer.value) ? detail.answer.value.map(String) : []
    const sameSet = original.length === selected.size && original.every((key) => selected.has(key))
    value = sameSet ? original : form.options.filter((row) => row.correct).map((row) => row.key)
  } else if (FILL_MODES.has(detail.answer_mode)) {
    value = Object.fromEntries(form.blanks.map((row) => [row.key, row.answer]))
  }

  const optionAnalysis = Object.fromEntries(
    form.options.filter((row) => row.analysis.trim() !== '').map((row) => [row.key, row.analysis]),
  )

  const solutions: AdminSolutionInput[] = []
  if (form.standard.on) solutions.push(solutionInput('standard', form.standard))
  if (form.fast.on) solutions.push(solutionInput('fast', form.fast))

  if (errors.length > 0) return { ok: false, errors }
  return {
    ok: true,
    body: {
      expected_version: detail.version,
      title: form.title,
      difficulty: form.difficulty,
      grade: form.grade === '' ? null : form.grade,
      content: {
        stem: form.stem,
        options: form.options.map((row) => ({ key: row.key, text: row.text })),
        blanks: form.blanks.map((row) => ({
          key: row.key,
          label: orNull(row.label),
          unit_hint: orNull(row.unitHint),
          placeholder: orNull(row.placeholder),
        })),
        subquestions: detail.content.subquestions,
        attachments: detail.content.attachments,
      },
      answer: { value, equivalence_rules: rules, units },
      teaching: {
        concept: orNull(form.concept),
        hints: keep(form.hints),
        concept_rephrase: orNull(form.conceptRephrase),
        option_analysis: optionAnalysis,
        visual,
        leak_markers: keep(form.leakMarkers),
      },
      solutions,
      knowledge: form.knowledge
        .split(/[\s,，、]+/)
        .map((code) => code.trim())
        .filter((code) => code !== ''),
      rubric: rubric,
      ...(form.comment.trim() === '' ? {} : { comment: form.comment.trim() }),
    },
  }
}

/** 表单现在的内容与题目详情相比有没有改动（不看修改说明）。 */
export function isUnchanged(body: AdminQuestionEdit, detail: AdminQuestionDetail): boolean {
  const { comment: _comment, ...rest } = body
  return canonical(rest) === canonical(bodyFromDetail(detail))
}
