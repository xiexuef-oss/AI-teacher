import { request } from './client'
import type { components } from './schema'
type S = components['schemas']
const base = '/admin/import-jobs'
export const importOptions = (token: string) => request<S['DocImportOptions']>('GET', '/admin/import-options', { token })
export const listImportJobs = (token: string, cursor?: string | null) => request<S['DocImportJobPage']>('GET', base, { token, query: { cursor } })
export const getImportJob = (token: string, id: string) => request<S['DocImportJobDetail']>('GET', `${base}/${id}`, { token })
export const createImportJob = (token: string, body: S['DocImportJobCreate'], idempotencyKey: string) => request<S['DocImportJobSummary']>('POST', base, { token, body, idempotencyKey })
export const uploadImportFile = (token: string, id: string, body: S['DocImportUpload'], idempotencyKey: string) => request<S['DocImportUploadResult']>('POST', `${base}/${id}/files`, { token, body, idempotencyKey })
export const processImportJob = (token: string, id: string, body: S['DocImportRevision'], idempotencyKey: string) => request<S['DocImportJobSummary']>('POST', `${base}/${id}/process`, { token, body, idempotencyKey })
export const cancelImportJob = (token: string, id: string, body: S['DocImportRevision'], idempotencyKey: string) => request<S['DocImportJobSummary']>('POST', `${base}/${id}/cancel`, { token, body, idempotencyKey })
export const saveImportCandidates = (token: string, id: string, body: S['DocImportCandidatesEdit'], idempotencyKey: string) => request<S['DocImportJobDetail']>('POST', `${base}/${id}/candidates`, { token, body, idempotencyKey })
export const submitImportCandidates = (token: string, id: string, body: S['DocImportSubmit'], idempotencyKey: string) => request<S['DocImportBatchResult']>('POST', `${base}/${id}/submit`, { token, body, idempotencyKey })
export const getImportOriginal = (token: string, id: string, file: string) => request<S['DocImportContent']>('GET', `${base}/${id}/files/${file}/content`, { token })
export const getImportPreview = (token: string, id: string, file: string, page: number, mediaIndex?: number) => request<S['DocImportContent']>('GET', `${base}/${id}/files/${file}/previews/${page}`, { token, query: { media_index: mediaIndex } })
