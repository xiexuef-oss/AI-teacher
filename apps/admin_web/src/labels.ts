import type { AdminQuestionSummary, Subject } from './api/types'

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
