import type { AdminQuestionSummary, ProofStage, Subject } from './api/types'

export const SUBJECT_LABEL: Record<Subject, string> = {
  math: '数学',
  physics: '物理',
  chemistry: '化学',
}

export const MODE_LABEL: Record<AdminQuestionSummary['answer_mode'], string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  fill: '填空题',
  written: '解答题',
  experiment: '实验题',
  proof: '证明题',
}

/** 证明阶段，按证明的先后排好（docs/06：拆解前提、构造、关键变形、结论）。 */
export const PROOF_STAGES: ProofStage[] = ['premise', 'construction', 'reasoning', 'conclusion']

export const STAGE_LABEL: Record<ProofStage, string> = {
  premise: '前提',
  construction: '构造',
  reasoning: '推理',
  conclusion: '结论',
}

export const SOLUTION_LABEL = { standard: '标准解法', fast: '快速解法' } as const

export function shortId(id: string | null): string {
  return id ? id.slice(0, 8) : '—'
}

export function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('zh-CN', { hour12: false })
}
