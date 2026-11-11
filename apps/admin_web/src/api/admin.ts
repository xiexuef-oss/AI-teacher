import { request } from './client'
import type {
  AdminQuestionDetail,
  AdminQuestionEdit,
  AdminQuestionPage,
  Health,
  LocalIdentity,
  LocalRole,
  QuestionReviewState,
  QuestionStatus,
  ReviewDecision,
  Subject,
} from './types'

export const getHealth = () => request<Health>('GET', '/health')

/** 仅本地身份 Mock 开启时可用（回环地址）。真实登录方式冻结前，审核后台只能这样进。 */
export const createLocalIdentity = (role: LocalRole) =>
  request<LocalIdentity>('POST', '/dev/local-identities', { query: { role } })

export interface QueueFilter {
  status?: QuestionStatus
  subject?: Subject
  cursor?: string | null
  limit?: number
}

export const listQuestions = (token: string, filter: QueueFilter) =>
  request<AdminQuestionPage>('GET', '/admin/questions', { token, query: { ...filter } })

export const getQuestion = (token: string, id: string) =>
  request<AdminQuestionDetail>('GET', `/admin/questions/${id}`, { token })

export const reviewQuestion = (
  token: string,
  id: string,
  body: ReviewDecision,
  idempotencyKey: string,
) =>
  request<QuestionReviewState>('POST', `/admin/questions/${id}/review`, {
    token,
    body,
    idempotencyKey,
  })

/** 修改题目：整体替换可编辑的内容，产生新版本（旧版本留痕）。已上线的题要先下线。 */
export const createQuestionVersion = (
  token: string,
  id: string,
  body: AdminQuestionEdit,
  idempotencyKey: string,
) =>
  request<AdminQuestionDetail>('POST', `/admin/questions/${id}/versions`, {
    token,
    body,
    idempotencyKey,
  })
