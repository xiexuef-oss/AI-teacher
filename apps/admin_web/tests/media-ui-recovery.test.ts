import {webcrypto} from 'node:crypto'
import {mount,flushPromises} from '@vue/test-utils'
import {beforeEach,it,expect,vi} from 'vitest'
import MediaAttachments from '../src/components/MediaAttachments.vue'
import {setSession} from '../src/session'
import * as api from '../src/api/media'
vi.mock('../src/api/media',()=>({createMediaUpload:vi.fn(),uploadMediaContent:vi.fn(),confirmMediaUpload:vi.fn(),getMediaContent:vi.fn(),getQuestionMediaContent:vi.fn(),confirmQuestionMediaReview:vi.fn()}))
beforeEach(()=>{localStorage.clear();sessionStorage.clear();vi.resetAllMocks();vi.stubGlobal('crypto',webcrypto);Object.defineProperty(navigator,'locks',{configurable:true,value:{request:(_n:string,_o:unknown,fn:()=>unknown)=>fn()}});setSession({token:'t',userId:'owner',role:'reviewer'})})
it('metadata未知重挂载公开历史且不自动重发或保存原图',async()=>{
 vi.mocked(api.createMediaUpload).mockRejectedValue(new Error('offline'))
 const w=mount(MediaAttachments,{props:{modelValue:[]}})
 Object.defineProperty(w.get('input[type=file]').element,'files',{value:[new File(['self'],'x.png',{type:'image/png'})]})
 await w.get('input[type=file]').trigger('change')
 await vi.waitFor(()=>expect(api.createMediaUpload).toHaveBeenCalledTimes(1))
 await vi.waitFor(()=>expect(w.text()).toContain('结果未知'))
 const raw=Object.values(localStorage).join('');expect(raw).not.toContain('c2VsZg==');expect(raw).toContain('question_attachment')
 w.unmount();const next=mount(MediaAttachments,{props:{modelValue:[]}})
 await vi.waitFor(()=>expect(next.find('[data-testid=media-history]').exists()).toBe(true))
 expect(api.createMediaUpload).toHaveBeenCalledTimes(1);next.unmount()
})
it('换题后旧metadata成功仅留历史，不继续content或追加附件',async()=>{
 let resolve!:(value:Awaited<ReturnType<typeof api.createMediaUpload>>)=>void
 vi.mocked(api.createMediaUpload).mockImplementation(()=>new Promise(r=>{resolve=r}))
 const w=mount(MediaAttachments,{props:{modelValue:[],questionId:'A',questionVersion:1}})
 Object.defineProperty(w.get('input[type=file]').element,'files',{value:[new File(['self'],'x.png',{type:'image/png'})]})
 await w.get('input[type=file]').trigger('change')
 await vi.waitFor(()=>expect(api.createMediaUpload).toHaveBeenCalledTimes(1))
 await w.setProps({questionId:'B'})
 resolve({media_id:'old',upload_url:'/api/v1/media/old/content',upload_method:'PUT',max_bytes:100,expires_at:new Date(Date.now()+60000).toISOString()})
 await vi.waitFor(()=>expect(Object.values(localStorage).join('')).toContain('result_known'))
 expect(api.uploadMediaContent).not.toHaveBeenCalled();expect(w.emitted('update:modelValue')).toBeUndefined();w.unmount()
})
it('原声明恢复固定版本和key，不GET重基且不标当前版本已审',async()=>{
 const {MediaWriteRecovery}=await import('../src/media-write-recovery')
 const r=new MediaWriteRecovery('owner','reviewer')
 const c=await r.prepareDeclaration('historical-declaration',{questionId:'q',version:1,mediaId:'m',sha256:'a'.repeat(64)})
 vi.mocked(api.confirmQuestionMediaReview).mockResolvedValue({question_id:'q',version:1,media_id:'m',sha256:'a'.repeat(64),actor_id:'owner',expires_at:new Date(Date.now()+60000).toISOString()})
 const w=mount(MediaAttachments,{props:{modelValue:[{kind:'image',media_id:'m',alt:'图'}],questionId:'q',questionVersion:2,readonly:true}})
 await vi.waitFor(()=>expect(w.find('[data-testid=media-history]').exists()).toBe(true))
 const button=w.findAll('button').find(b=>b.text()==='恢复原命令')!;await button.trigger('click')
 await vi.waitFor(()=>expect(api.confirmQuestionMediaReview).toHaveBeenCalledTimes(1))
 expect(api.confirmQuestionMediaReview).toHaveBeenCalledWith('t','q','m',{expected_version:1,sha256:'a'.repeat(64),confirmed:true},c.key)
 expect(api.getQuestionMediaContent).not.toHaveBeenCalled();expect(api.getMediaContent).not.toHaveBeenCalled()
 expect(w.text()).not.toContain('已记录本人对本图当前版本');w.unmount()
})
it('known本机ACK无原图也不发HTTP',async()=>{
 const {MediaWriteRecovery}=await import('../src/media-write-recovery')
 const r=new MediaWriteRecovery('owner','reviewer');const c=await r.prepareDeclaration('known-declaration',{questionId:'q',version:1,mediaId:'m',sha256:'a'.repeat(64)})
 await r.send(c,async()=>({question_id:'q',version:1,media_id:'m',sha256:'a'.repeat(64),actor_id:'owner',expires_at:new Date(Date.now()+60000).toISOString()}))
 const w=mount(MediaAttachments,{props:{modelValue:[]}})
 await vi.waitFor(()=>expect(w.findAll('button').some(b=>b.text()==='仅确认本机历史')).toBe(true))
 await w.findAll('button').find(b=>b.text()==='仅确认本机历史')!.trigger('click')
 await vi.waitFor(()=>expect(w.text()).toContain('acked'))
 expect(api.confirmQuestionMediaReview).not.toHaveBeenCalled();expect(api.createMediaUpload).not.toHaveBeenCalled();w.unmount()
})
async function confirmedHistory(){
 const {MediaWriteRecovery}=await import('../src/media-write-recovery');const r=new MediaWriteRecovery('owner','reviewer')
 const sha='06c604b332b386b6cce8355ccf27fffd3a98b7a7a5b9b3a550c039c6ebae38e4',expires_at=new Date(Date.now()+60000).toISOString()
 await r.createWorkspace('restored-image',{purpose:'question_attachment',mime:'image/png',size_bytes:4,sha256:sha})
 const create=await r.prepareCreate('restored-image');await r.send(create,async()=>({media_id:'restored',upload_url:'/api/v1/media/restored/content',upload_method:'PUT',max_bytes:100,expires_at}));await r.ack(create)
 const body={content_base64:'c2VsZg=='},bytes=new TextEncoder().encode('self'),info={media_id:'restored',mime:'image/png',size_bytes:4,sha256:sha,expires_at}
 const content=await r.prepareContent('restored-image',{body,bytes});await r.sendContent(content,{body,bytes},async()=>info);await r.ack(content)
 const confirm=await r.prepareConfirm('restored-image');await r.send(confirm,async()=>info);await r.ack(confirm)
 return r
}
it('历史图片须明确选择当前目标、实时读取核SHA并先交父草稿保存才能关联',async()=>{
 await confirmedHistory();vi.mocked(api.getMediaContent).mockResolvedValue({media_id:'restored',mime:'image/png',content_base64:'c2VsZg=='})
 const save=vi.fn(async(_next:unknown,_context:unknown)=>{})
 const w=mount(MediaAttachments,{props:{modelValue:[],questionId:'B',questionVersion:3,persistAttachments:save}})
 await vi.waitFor(()=>expect(w.find('[data-testid=associate-media]').exists()).toBe(true))
 expect(w.get('[data-testid=associate-media]').attributes('disabled')).toBeDefined()
 await w.get('[data-testid=choose-association-target]').setValue(true)
 await w.get('[data-testid=associate-media]').trigger('click')
 await vi.waitFor(()=>expect(save).toHaveBeenCalledTimes(1))
 expect(api.getMediaContent).toHaveBeenCalledWith('t','restored');expect(save.mock.calls[0]![0]).toEqual([{kind:'image',media_id:'restored',alt:'待人工核对的附件说明'}])
 await vi.waitFor(()=>expect(w.emitted('update:modelValue')).toBeTruthy());w.unmount()
})
it('关联读取中换题或更新父草稿代际，旧A结果不调用保存也不追加',async()=>{
 await confirmedHistory();let resolve!:(v:Awaited<ReturnType<typeof api.getMediaContent>>)=>void
 vi.mocked(api.getMediaContent).mockImplementation(()=>new Promise(r=>{resolve=r}));const save=vi.fn(async()=>{})
 const w=mount(MediaAttachments,{props:{modelValue:[],questionId:'A',questionVersion:1,draftRevision:1,persistAttachments:save}})
 await vi.waitFor(()=>expect(w.find('[data-testid=associate-media]').exists()).toBe(true));await w.get('[data-testid=choose-association-target]').setValue(true);await w.get('[data-testid=associate-media]').trigger('click')
 await vi.waitFor(()=>expect(api.getMediaContent).toHaveBeenCalledTimes(1));await w.setProps({questionId:'B',draftRevision:2})
 resolve({media_id:'restored',mime:'image/png',content_base64:'c2VsZg=='})
 await flushPromises();expect(save).not.toHaveBeenCalled();expect(w.emitted('update:modelValue')).toBeUndefined();w.unmount()
})
it('当前读取字节不匹配不关联，原known回执保持成功历史',async()=>{
 const r=await confirmedHistory();vi.mocked(api.getMediaContent).mockResolvedValue({media_id:'restored',mime:'image/png',content_base64:'YmFk'});const save=vi.fn(async()=>{})
 const w=mount(MediaAttachments,{props:{modelValue:[],questionId:'B',persistAttachments:save}})
 await vi.waitFor(()=>expect(w.find('[data-testid=associate-media]').exists()).toBe(true));await w.get('[data-testid=choose-association-target]').setValue(true);await w.get('[data-testid=associate-media]').trigger('click')
 await vi.waitFor(()=>expect(w.text()).toContain('当前媒体字节与历史来源不匹配'))
 expect(save).not.toHaveBeenCalled();expect(w.emitted('update:modelValue')).toBeUndefined();expect((await r.workspace('restored-image')).commands.find(c=>c.path.endsWith('/confirm'))?.phase).toBe('acked');w.unmount()
})
it('父草稿保存失败不追加引用，已知历史无需重发上传',async()=>{
 await confirmedHistory();vi.mocked(api.getMediaContent).mockResolvedValue({media_id:'restored',mime:'image/png',content_base64:'c2VsZg=='});const save=vi.fn(async()=>{throw Error('draft disk failed')})
 const w=mount(MediaAttachments,{props:{modelValue:[],questionId:'B',persistAttachments:save}})
 await vi.waitFor(()=>expect(w.find('[data-testid=associate-media]').exists()).toBe(true));await w.get('[data-testid=choose-association-target]').setValue(true);await w.get('[data-testid=associate-media]').trigger('click')
 await vi.waitFor(()=>expect(w.text()).toContain('draft disk failed'));expect(w.emitted('update:modelValue')).toBeUndefined();expect(api.confirmMediaUpload).not.toHaveBeenCalled();w.unmount()
})
it('声明已执行但丢响应后普通按钮不另建key，历史重试沿原body/key',async()=>{
 vi.mocked(api.getQuestionMediaContent).mockResolvedValue({media_id:'m',mime:'image/png',content_base64:'aA=='})
 vi.mocked(api.confirmQuestionMediaReview).mockRejectedValue(new Error('response lost'))
 const w=mount(MediaAttachments,{props:{modelValue:[{kind:'image',media_id:'m',alt:'图'}],questionId:'q',questionVersion:2,readonly:true,authorId:'other'}})
 await w.get('[data-testid=preview-media]').trigger('click');await vi.waitFor(()=>expect(w.find('img').exists()).toBe(true));await w.get('img').trigger('load');await w.get('[data-testid=confirm-viewed-media]').setValue(true)
 await w.get('[data-testid=declare-media-review]').trigger('click');await vi.waitFor(()=>expect(api.confirmQuestionMediaReview).toHaveBeenCalledTimes(1));await vi.waitFor(()=>expect(w.get('[data-testid=declare-media-review]').attributes('disabled')).toBeUndefined())
 const original=vi.mocked(api.confirmQuestionMediaReview).mock.calls[0]!
 await w.get('[data-testid=declare-media-review]').trigger('click');await vi.waitFor(()=>expect(w.text()).toContain('已有原声明待恢复'))
 expect(api.confirmQuestionMediaReview).toHaveBeenCalledTimes(1)
 await w.findAll('button').find(b=>b.text()==='恢复原命令')!.trigger('click');await vi.waitFor(()=>expect(api.confirmQuestionMediaReview).toHaveBeenCalledTimes(2))
 expect(vi.mocked(api.confirmQuestionMediaReview).mock.calls[1]).toEqual(original);w.unmount()
})
it('并发原子lane返回复用历史时普通入口不发送也不确认新声明',async()=>{
 const {MediaWriteRecovery}=await import('../src/media-write-recovery')
 const original=MediaWriteRecovery.prototype.prepareDeclarationLane
 const spy=vi.spyOn(MediaWriteRecovery.prototype,'prepareDeclarationLane').mockImplementation(async function(this:InstanceType<typeof MediaWriteRecovery>,wid,scope,key){await original.call(this,'concurrent-original-workspace',scope,key);return original.call(this,wid,scope,key)})
 vi.mocked(api.getQuestionMediaContent).mockResolvedValue({media_id:'m',mime:'image/png',content_base64:'aA=='})
 const w=mount(MediaAttachments,{props:{modelValue:[{kind:'image',media_id:'m',alt:'图'}],questionId:'q',questionVersion:2,readonly:true,authorId:'other'}})
 await w.get('[data-testid=preview-media]').trigger('click');await vi.waitFor(()=>expect(w.find('img').exists()).toBe(true));await w.get('img').trigger('load');await w.get('[data-testid=confirm-viewed-media]').setValue(true);await w.get('[data-testid=declare-media-review]').trigger('click')
 await vi.waitFor(()=>expect(w.text()).toContain('原工作区 concurrent-original-workspace'))
 expect(api.confirmQuestionMediaReview).not.toHaveBeenCalled();expect(w.text()).not.toContain('已记录本人对本图当前版本');w.unmount();spy.mockRestore()
})
it('真实两组件B旧read后A发送并ACK，B进原子lane复用ACK历史无第二POST',async()=>{
 const {MediaWriteRecovery}=await import('../src/media-write-recovery')
 const original=MediaWriteRecovery.prototype.prepareDeclarationLane
 let entered!:()=>void,release!:()=>void,first=true
 const enteredGate=new Promise<void>(r=>{entered=r}),releaseGate=new Promise<void>(r=>{release=r})
 const spy=vi.spyOn(MediaWriteRecovery.prototype,'prepareDeclarationLane').mockImplementation(async function(this:InstanceType<typeof MediaWriteRecovery>,...args:Parameters<typeof original>){if(first){first=false;entered();await releaseGate}return original.apply(this,args)})
 const sha='aaa9402664f1a41f40ebbc52c9993eb66aeb366602958fdfaa283b71e64db123'
 vi.mocked(api.getQuestionMediaContent).mockResolvedValue({media_id:'m',mime:'image/png',content_base64:'aA=='})
 vi.mocked(api.confirmQuestionMediaReview).mockResolvedValue({question_id:'q',version:2,media_id:'m',sha256:sha,actor_id:'owner',expires_at:new Date(Date.now()+60000).toISOString()})
 const props={modelValue:[{kind:'image' as const,media_id:'m',alt:'图'}],questionId:'q',questionVersion:2,readonly:true,authorId:'other'}
 const b=mount(MediaAttachments,{props}),a=mount(MediaAttachments,{props})
 for(const w of [b,a]){await w.get('[data-testid=preview-media]').trigger('click');await vi.waitFor(()=>expect(w.find('img').exists()).toBe(true));await w.get('img').trigger('load');await w.get('[data-testid=confirm-viewed-media]').setValue(true)}
 await b.get('[data-testid=declare-media-review]').trigger('click');await enteredGate
 await a.get('[data-testid=declare-media-review]').trigger('click')
 await vi.waitFor(()=>expect(a.text()).toContain('已记录本人对本图当前版本'))
 const r=new MediaWriteRecovery('owner','reviewer'),before=await r.read(),existing=before.workspaces.flatMap(w=>w.commands).filter(c=>c.path.endsWith('/review-confirmations'))
 expect(existing).toHaveLength(1);expect(existing[0]!.phase).toBe('acked');expect(api.confirmQuestionMediaReview).toHaveBeenCalledTimes(1)
 release();await vi.waitFor(()=>expect(b.text()).toContain('已有原声明待恢复或确认本机历史'))
 expect(api.confirmQuestionMediaReview).toHaveBeenCalledTimes(1);expect(b.text()).not.toContain('已记录本人对本图当前版本')
 const after=await r.read();expect(after.workspaces.flatMap(w=>w.commands).filter(c=>c.path.endsWith('/review-confirmations')).map(c=>c.key)).toEqual([existing[0]!.key])
 a.unmount();b.unmount();spy.mockRestore()
})
