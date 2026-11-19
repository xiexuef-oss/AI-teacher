import {request} from './client'
import type {components} from './schema'
type S=components['schemas']
export const createMediaUpload=(token:string,body:S['MediaUploadRequest'],idempotencyKey:string)=>request<S['MediaUpload']>('POST','/media/uploads',{token,body,idempotencyKey})
export const uploadMediaContent=(token:string,id:string,body:S['MediaBlobUpload'],idempotencyKey:string)=>request<S['MediaAssetInfo']>('PUT',`/media/${id}/content`,{token,body,idempotencyKey})
export const confirmMediaUpload=(token:string,id:string,body:S['MediaConfirm'],idempotencyKey:string)=>request<S['MediaAssetInfo']>('POST',`/media/${id}/confirm`,{token,body,idempotencyKey})
export const getMediaContent=(token:string,id:string)=>request<S['MediaContent']>('GET',`/media/${id}/content`,{token})
export const getQuestionMediaContent=(token:string,q:string,id:string)=>request<S['MediaContent']>('GET',`/admin/questions/${q}/media/${id}/content`,{token})
export const deleteMedia=(token:string,id:string,idempotencyKey:string)=>request<S['MediaDeleted']>('POST',`/media/${id}/delete`,{token,body:{},idempotencyKey})

export const confirmQuestionMediaReview=(token:string,q:string,id:string,body:S['MediaReviewConfirmation'],idempotencyKey:string)=>request<S['MediaReviewDeclaration']>('POST',`/admin/questions/${q}/media/${id}/review-confirmations`,{token,body,idempotencyKey})
