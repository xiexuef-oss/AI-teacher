import type {
  AdminHistoryAction,
  AdminQuestionDetail,
  QuestionStatus,
  ReviewDecisionType,
} from './api/types'

export const STATUS_LABEL: Record<QuestionStatus, string> = {
  draft: '待审（草稿）',
  reviewed: '已二审',
  published: '已上线',
  withdrawn: '已下线',
}

/** 审核历史里的动作名：四种审核决策，加上"修改"（产生新版本）。 */
export const HISTORY_LABEL: Record<AdminHistoryAction, string> = {
  approve: '二审通过',
  reject: '退回修改',
  publish: '上线',
  withdraw: '下线（撤回）',
  edit: '修改（新版本）',
  import: '导入草稿',
}

/** 一次修改里"改动了哪些部分"的中文名。 */
export const PART_LABEL: Record<string, string> = {
  title: '标题',
  difficulty: '难度',
  grade: '年级',
  content: '题面',
  answer: '答案',
  teaching: '教学辅助',
  solutions: '解法',
  knowledge: '知识点',
  rubric: '评分细则',
}

/** 已上线的题要先下线才能改；其余状态都可以改（改完是新版本，回到待审）。 */
export function canEdit(status: QuestionStatus): boolean {
  return status !== 'published'
}

export const DECISION_LABEL: Record<ReviewDecisionType, string> = {
  approve: '二审通过',
  reject: '退回修改',
  publish: '上线',
  withdraw: '下线（撤回）',
}

export const DECISION_HELP: Record<ReviewDecisionType, string> = {
  approve: '确认题目、答案和你勾选的解法没有问题，进入"已二审"。提交者本人不能做这一步。',
  reject: '退回给提交者修改，之前的审核确认全部作废。必须写明原因。',
  publish: '让学生看到这道题。上线前服务端会再做一次程序校验。',
  withdraw: '发现问题，立刻让学生看不到这道题。下线之后不能再恢复，必须写明原因。',
}

/** 每种状态下可以做的决策，与服务端的状态流转一致（docs/07 §4）。 */
const FROM_STATUS: Record<QuestionStatus, ReviewDecisionType[]> = {
  draft: ['approve', 'reject'],
  reviewed: ['publish', 'reject'],
  published: ['withdraw'],
  withdrawn: [],
}

export function availableDecisions(status: QuestionStatus): ReviewDecisionType[] {
  return FROM_STATUS[status]
}

export function commentRequired(decision: ReviewDecisionType): boolean {
  return decision === 'reject' || decision === 'withdraw'
}

/**
 * 这个决策现在为什么做不了；可以做返回 null。
 * 这只是提前给审核人一个说明，真正的限制在服务端，这里不是授权依据。
 */
export function blockedReason(
  detail: AdminQuestionDetail,
  decision: ReviewDecisionType,
  userId: string,
): string | null {
  const gate = decision === 'approve' || decision === 'publish'
  if (gate && detail.created_by !== null && detail.created_by === userId) {
    return '你是这道题的提交者，不能审核或上线自己的题，请换另一位审校员。'
  }
  if (gate && detail.check_problems.length > 0) {
    return `程序校验发现 ${detail.check_problems.length} 个问题，修改后才能${DECISION_LABEL[decision]}。`
  }
  if (decision === 'publish') {
    const standard = detail.solutions.find((solution) => solution.kind === 'standard')
    if (!standard || !standard.reviewed) return '标准解法还没有经过审核确认。'
  }
  return null
}

/** 把服务端的错误码翻成审核人看得懂的话；认不出的原样显示服务端的说明。 */
export function explainError(code: string, message: string): string {
  switch (code) {
    case 'self_review_forbidden':
      return '提交内容的人不能审核或上线自己的题，请换另一位审校员。'
    case 'version_conflict':
      return '这道题的版本已经变了，你看到的不是最新的。请刷新后再审。'
    case 'invalid_transition':
      return '题目的状态已经变了（可能别人刚处理过），现在不能执行这个操作。请刷新后再看。'
    case 'comment_required':
      return '这个操作必须写明原因。'
    case 'no_changes':
      return '没有任何改动，不会产生新版本。'
    case 'solution_not_confirmed':
      return message
    case 'content_checks_failed':
      return '程序校验没有通过，问题见下面的列表。'
    case 'forbidden':
      return '当前账号没有审核权限。'
    case 'network_error':
      return message
    default:
      return message
  }
}
