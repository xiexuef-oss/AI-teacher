import {webcrypto} from 'node:crypto'
import {mount,flushPromises} from '@vue/test-utils'
import {it,expect,vi,beforeEach} from 'vitest'
import MediaAttachments from '../src/components/MediaAttachments.vue'
import * as api from '../src/api/media'
import {setSession} from '../src/session'
vi.mock('../src/api/media',()=>({createMediaUpload:vi.fn(),uploadMediaContent:vi.fn(),confirmMediaUpload:vi.fn(),getMediaContent:vi.fn(),getQuestionMediaContent:vi.fn(),deleteMedia:vi.fn(),confirmQuestionMediaReview:vi.fn()}))
beforeEach(()=>{vi.resetAllMocks();localStorage.clear();sessionStorage.clear();vi.stubGlobal('crypto',webcrypto);Object.defineProperty(navigator,'locks',{configurable:true,value:{request:(_n:string,_o:unknown,fn:()=>unknown)=>fn()}});setSession({token:'t',userId:'owner',role:'reviewer'})})
it('审校附件只经当前题目授权预览，拒绝非图片内容且不缓存跨用户字节',async()=>{
 vi.mocked(api.getQuestionMediaContent).mockResolvedValue({media_id:'m',mime:'image/png',content_base64:'aA=='})
 const w=mount(MediaAttachments,{props:{modelValue:[{kind:'image',media_id:'m',alt:'示意图'}],questionId:'q',readonly:true}})
 await w.get('[data-testid=preview-media]').trigger('click');await flushPromises()
 expect(api.getQuestionMediaContent).toHaveBeenCalledWith('t','q','m')
 expect(api.getMediaContent).not.toHaveBeenCalled()
 expect(w.get('img').attributes('src')).toBe('data:image/png;base64,aA==')
 expect(Object.values(sessionStorage).join('')).not.toContain('aA==')
 w.unmount()
})
it('只有上传并确认后才新增附件，上传字节不存浏览器持久存储',async()=>{
 vi.mocked(api.createMediaUpload).mockResolvedValue({media_id:'m',upload_url:'/api/v1/media/m/content',upload_method:'PUT',expires_at:new Date(Date.now()+60000).toISOString(),max_bytes:100})
 vi.mocked(api.confirmMediaUpload).mockResolvedValue({media_id:'m',mime:'image/png',sha256:'06c604b332b386b6cce8355ccf27fffd3a98b7a7a5b9b3a550c039c6ebae38e4',size_bytes:4,expires_at:new Date(Date.now()+60000).toISOString()})
 vi.mocked(api.uploadMediaContent).mockResolvedValue({media_id:'m',mime:'image/png',sha256:'06c604b332b386b6cce8355ccf27fffd3a98b7a7a5b9b3a550c039c6ebae38e4',size_bytes:4,expires_at:new Date(Date.now()+60000).toISOString()})
 const w=mount(MediaAttachments,{props:{modelValue:[]}})
 const file=new File(['self'], 'test.png',{type:'image/png'})
 Object.defineProperty(w.get('input[type=file]').element,'files',{value:[file]})
 await w.get('input[type=file]').trigger('change')
 await vi.waitFor(()=>expect(w.emitted('update:modelValue')).toBeTruthy())
 expect(api.uploadMediaContent).toHaveBeenCalled()
 expect(api.confirmMediaUpload).toHaveBeenCalled()
 expect(w.emitted('update:modelValue')![0]![0]).toEqual([{kind:'image',media_id:'m',alt:'待人工核对的附件说明'}])
 expect(Object.values(sessionStorage).join('')).not.toContain('c2VsZg==')
 w.unmount();vi.unstubAllGlobals()
})

it('逐图声明必须图片加载完成并明确勾选，不会自动批量声明',async()=>{
 vi.mocked(api.getQuestionMediaContent).mockResolvedValue({media_id:'m',mime:'image/png',content_base64:'aA=='})
 vi.mocked(api.confirmQuestionMediaReview).mockResolvedValue({question_id:'q',version:2,media_id:'m',sha256:'aaa9402664f1a41f40ebbc52c9993eb66aeb366602958fdfaa283b71e64db123',actor_id:'owner',expires_at:new Date(Date.now()+60000).toISOString()})
 const w=mount(MediaAttachments,{props:{modelValue:[{kind:'image',media_id:'m',alt:'题面图'}],questionId:'q',questionVersion:2,authorId:'other',readonly:true}})
 await w.get('[data-testid=preview-media]').trigger('click');await vi.waitFor(()=>expect(w.find('img').exists()).toBe(true))
 expect(w.get('[data-testid=declare-media-review]').attributes('disabled')).toBeDefined()
 await w.get('img').trigger('load')
 await w.get('[data-testid=confirm-viewed-media]').setValue(true)
 await w.get('[data-testid=declare-media-review]').trigger('click');await vi.waitFor(()=>expect(api.confirmQuestionMediaReview).toHaveBeenCalledTimes(1))
 expect(api.confirmQuestionMediaReview).toHaveBeenCalledWith('t','q','m',{expected_version:2,sha256:'aaa9402664f1a41f40ebbc52c9993eb66aeb366602958fdfaa283b71e64db123',confirmed:true},expect.any(String))
 expect(w.text()).toContain('审校声明')
 w.unmount();vi.unstubAllGlobals()
})
