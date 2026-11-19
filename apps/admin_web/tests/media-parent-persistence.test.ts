import * as mediaApi from '../src/api/media'
import {readFileSync} from 'node:fs'
import {createRouter,createMemoryHistory} from 'vue-router'
import DocumentImportView from '../src/views/DocumentImportView.vue'
import * as docApi from '../src/api/document-import'
import type {components} from '../src/api/schema'
import {webcrypto} from 'node:crypto'
import {mount,flushPromises,enableAutoUnmount} from '@vue/test-utils'
import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import QuestionEditor from '../src/components/QuestionEditor.vue'
import MediaAttachments from '../src/components/MediaAttachments.vue'
import {setSession} from '../src/session'
import {detail,ME} from './fixtures'
vi.mock('../src/api/media',()=>({createMediaUpload:vi.fn(),uploadMediaContent:vi.fn(),confirmMediaUpload:vi.fn(),getMediaContent:vi.fn(),getQuestionMediaContent:vi.fn(),confirmQuestionMediaReview:vi.fn()}))
vi.mock('../src/api/document-import',()=>({importOptions:vi.fn(),listImportJobs:vi.fn(),getImportJob:vi.fn(),createImportJob:vi.fn(),uploadImportFile:vi.fn(),processImportJob:vi.fn(),cancelImportJob:vi.fn(),saveImportCandidates:vi.fn(),submitImportCandidates:vi.fn(),getImportPreview:vi.fn(),getImportOriginal:vi.fn()}))
enableAutoUnmount(afterEach)
beforeEach(()=>{localStorage.clear();sessionStorage.clear();vi.restoreAllMocks();vi.stubGlobal('crypto',webcrypto);const tails=new Map<string,Promise<unknown>>();Object.defineProperty(navigator,'locks',{configurable:true,value:{request:<T>(name:string,_options:unknown,action:()=>Promise<T>)=>{const next=(tails.get(name)??Promise.resolve()).catch(()=>{}).then(action);tails.set(name,next.then(()=>{},()=>{}));return next}}});setSession({token:'parent-token',userId:ME,role:'reviewer'})})
const next=[{kind:'image' as const,media_id:'media-a',alt:'engineered example'}]
it('真实Question父必须提供持久ACK回调，附件先落草稿再apply',async()=>{
 const d=detail(),w=mount(QuestionEditor,{props:{detail:d}});await flushPromises()
 const child=w.getComponent(MediaAttachments),persist=child.props('persistAttachments');expect(typeof persist).toBe('function')
 await persist!(next,{isCurrent:()=>true})
 expect(child.props('modelValue')).toEqual(next)
 const raw=JSON.parse(localStorage.getItem(`admin-question-draft/v1/${encodeURIComponent(ME)}/${encodeURIComponent(d.id)}/edit`)!)
 expect(JSON.parse(raw.raw).form.attachments).toEqual(next)
})
it('真实Question父配额失败不得apply附件',async()=>{
 const w=mount(QuestionEditor,{props:{detail:detail()}});await flushPromises();const child=w.getComponent(MediaAttachments),persist=child.props('persistAttachments');expect(typeof persist).toBe('function')
 const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('quota')})
 await expect(persist!(next,{isCurrent:()=>true})).rejects.toThrow();expect(child.props('modelValue')).toEqual([]);spy.mockRestore()
})
function documentRaw(){const key=Object.keys(localStorage).find(k=>k.startsWith('admin-document-state/v1/')&&JSON.parse(localStorage.getItem(k)!).jobId==='job-a');return key?localStorage.getItem(key):null}
async function candidatePage(){
 type S=components['schemas'];const payload=JSON.parse(readFileSync('public/examples/question-import.json','utf-8')) as S['AdminQuestionImport']
 const expires=new Date(Date.now()+120000).toISOString(),job:S['DocImportJobSummary']={id:'job-a',title:'工程候选',status:'needs_review',revision:1,file_count:0,processed_files:0,candidate_count:2,confirmed_count:0,imported_count:0,failed_count:0,message:null,created_at:'',updated_at:'',expires_at:expires}
 vi.mocked(docApi.importOptions).mockResolvedValue({server_time:new Date().toISOString(),creation_deadline:new Date(Date.now()+7200000).toISOString(),max_file_bytes:1000,max_job_bytes:10000,max_files:10,max_pages:80,max_candidates:200,temporary_ttl_minutes:120,file_kinds:['json'],ocr_mode:'disabled',doc_converter_available:false})
 vi.mocked(docApi.listImportJobs).mockResolvedValue({items:[job],next_cursor:null})
 vi.mocked(docApi.getImportJob).mockResolvedValue({job,files:[],defaults:{subject:payload.subject,answer_mode:payload.answer_mode,source:payload.source},candidates:['candidate-a','candidate-b'].map(id=>({id,title:id,text:'工程题干',locations:[],warnings:[],payload,confirmed:false,confirmed_by:null,question_id:null,error:null}))})
 localStorage.setItem(`document-import:${ME}:expires`,String(Date.now()+120000));localStorage.setItem(`document-import:${ME}:job`,job.id)
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:DocumentImportView}]});await router.push('/');await router.isReady();const w=mount(DocumentImportView,{global:{plugins:[router]}});await flushPromises();await w.findAll('[data-testid=open-structured-editor]')[0]!.trigger('click');await flushPromises();return w
}
it('localOnly候选真实父持久成功后才应用附件，不伪造题目id/version',async()=>{
 const w=await candidatePage(),editor=w.getComponent(QuestionEditor),child=editor.getComponent(MediaAttachments),persist=child.props('persistAttachments');expect(typeof editor.props('persistDraft')).toBe('function')
 expect(child.props('questionId')).toBeUndefined();expect(child.props('questionVersion')).toBeUndefined()
 await persist!(next,{isCurrent:()=>true});expect(child.props('modelValue')).toEqual(next)
 const raw=JSON.parse(documentRaw()!).draft.value
 expect(raw.items[0].structuredDraft.attachments).toEqual(next);expect(raw.items[1].structuredDraft).toBeUndefined()
})

function gateNext(prefix:string){
 const previous=navigator.locks.request.bind(navigator.locks);let release!:()=>void,entered!:()=>void,held=false
 const gate=new Promise<void>(r=>release=r),started=new Promise<void>(r=>entered=r)
 Object.defineProperty(navigator,'locks',{configurable:true,value:{request:(name:string,opts:unknown,action:()=>Promise<unknown>)=>previous(name,opts as LockOptions,async()=>{if(!held&&name.startsWith(prefix)){held=true;entered();await gate}return action()})}})
 return {started,release:()=>release()}
}
it('Question父排队期间B输入或子lease变化均不apply旧附件',async()=>{
 for(const change of ['input','lease','account'] as const){
  const w=mount(QuestionEditor,{props:{detail:detail()}});await flushPromises();const child=w.getComponent(MediaAttachments),persist=child.props('persistAttachments')!;let lease=true
  const gate=gateNext('admin-question-draft/'),operation=persist(next,{isCurrent:()=>lease});await gate.started
  if(change==='input')await w.get('[data-testid=title]').setValue('最新B')
  else if(change==='lease')lease=false
  else setSession({token:'replacement',userId:'other-owner',role:'reviewer'})
  gate.release();await expect(operation).rejects.toThrow();expect(child.props('modelValue')).toEqual([])
  if(change==='input')expect((w.get('[data-testid=title]').element as HTMLInputElement).value).toBe('最新B')
  w.unmount();setSession({token:'parent-token',userId:ME,role:'reviewer'});await flushPromises()
 }
})
it('Question guarded来源CAS失败不覆盖另一tab当前草稿或apply附件',async()=>{
 const d=detail(),w=mount(QuestionEditor,{props:{detail:d}});await flushPromises();const {QuestionWriteRecovery}=await import('../src/question-write-recovery'),{formFromDetail}=await import('../src/editing');const other=new QuestionWriteRecovery(ME,d.id,'edit'),form=formFromDetail(d);form.title='另一标签页B'
 await other.save(JSON.stringify({source:{id:d.id,version:d.version,reviewRevision:d.review_revision??null},form}),0)
 await expect(w.getComponent(MediaAttachments).props('persistAttachments')!(next,{isCurrent:()=>true})).rejects.toThrow('来源');expect(w.getComponent(MediaAttachments).props('modelValue')).toEqual([]);expect(JSON.parse((await other.load()).raw).form.title).toBe('另一标签页B')
})
it('整个Question表单输入都推进子组件draftRevision',async()=>{
 const w=mount(QuestionEditor,{props:{detail:detail()}});await flushPromises();const child=w.getComponent(MediaAttachments)
 for(const [selector,value] of [['title','新标题'],['difficulty','3'],['option-text-0','新选项'],['standard-final','新答案'],['knowledge','math.engineering.changed'],['comment','新修改说明']]){const before=child.props('draftRevision');await w.get(`[data-testid=${selector}]`).setValue(value);expect(child.props('draftRevision')).not.toBe(before)}
})
it('localOnly父写失败或候选输入代际变化不apply附件',async()=>{
 const w=await candidatePage(),editor=w.getComponent(QuestionEditor),child=editor.getComponent(MediaAttachments),persist=child.props('persistAttachments')!
 const original=Storage.prototype.setItem,spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k.startsWith('admin-document-state/v1/'))throw Error('quota');original.call(this,k,v)})
 await expect(persist(next,{isCurrent:()=>true})).rejects.toThrow('quota');expect(child.props('modelValue')).toEqual([]);spy.mockRestore()
 const gate=gateNext('admin-document-state/v1/'),operation=persist(next,{isCurrent:()=>true});await gate.started
 await editor.get('[data-testid=title]').setValue('候选最新B');gate.release();await expect(operation).rejects.toThrow();expect(child.props('modelValue')).toEqual([]);expect((editor.get('[data-testid=title]').element as HTMLInputElement).value).toBe('候选最新B')
})
it('localOnly换candidate期间旧附件不得写入新candidate，留存期限不延长',async()=>{
 const w=await candidatePage(),editor=w.getComponent(QuestionEditor),child=editor.getComponent(MediaAttachments),retention=localStorage.getItem(`document-import:${ME}:expires`),gate=gateNext('admin-document-state/v1/'),operation=child.props('persistAttachments')!(next,{isCurrent:()=>true});await gate.started
 const down=w.findAll('button').find(b=>b.text()==='下移')!;await down.trigger('click');gate.release();await expect(operation).rejects.toThrow();expect(localStorage.getItem(`document-import:${ME}:expires`)).toBe(retention)
 for(const component of w.findAllComponents(MediaAttachments))expect(component.props('modelValue')).toEqual([])
})

it('正常新上传真实子事件经父持久回调后仍可关联且busy恢复',async()=>{
 const expiry=new Date(Date.now()+120000).toISOString(),sha='039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81'
 vi.mocked(mediaApi.createMediaUpload).mockResolvedValue({media_id:'media-a',upload_url:'/api/v1/media/media-a/content',upload_method:'PUT',expires_at:expiry,max_bytes:1024})
 vi.mocked(mediaApi.uploadMediaContent).mockResolvedValue({media_id:'media-a',mime:'image/png',size_bytes:3,sha256:sha,expires_at:expiry})
 vi.mocked(mediaApi.confirmMediaUpload).mockResolvedValue({media_id:'media-a',mime:'image/png',size_bytes:3,sha256:sha,expires_at:expiry})
 const d=detail(),w=mount(QuestionEditor,{props:{detail:d}});await flushPromises();const child=w.getComponent(MediaAttachments),input=child.get('input[type=file]')
 Object.defineProperty(input.element,'files',{configurable:true,value:[new File([new Uint8Array([1,2,3])],'engineering.png',{type:'image/png'})]})
 await input.trigger('change');await vi.waitFor(()=>expect(child.props('modelValue')).toHaveLength(1))
 const raw=JSON.parse(localStorage.getItem(`admin-question-draft/v1/${encodeURIComponent(ME)}/${encodeURIComponent(d.id)}/edit`)!)
 expect(JSON.parse(raw.raw).form.attachments[0].media_id).toBe('media-a');await vi.waitFor(()=>expect(input.attributes('disabled')).toBeUndefined());expect(mediaApi.confirmMediaUpload).toHaveBeenCalledTimes(1)
})
it('localOnly旧任务来源先保留并明确采用，不能自动重基关联附件',async()=>{
 const key=`document-import:${ME}:edits:job-a`,old={revision:9,items:[{id:'candidate-a',title:'旧输入',text:'工程题干',locations:[],warnings:[],payload:JSON.parse(readFileSync('public/examples/question-import.json','utf-8')),json:readFileSync('public/examples/question-import.json','utf-8'),confirmed:false,question_id:null,error:null}]};localStorage.setItem(key,JSON.stringify(old))
 const w=await candidatePage(),editor=w.getComponent(QuestionEditor),child=editor.getComponent(MediaAttachments),persist=child.props('persistAttachments')!,retention=localStorage.getItem(`document-import:${ME}:expires`)
 await expect(persist(next,{isCurrent:()=>true})).rejects.toThrow('来源');expect(child.props('modelValue')).toEqual([]);expect(JSON.parse(localStorage.getItem(key)!).revision).toBe(9)
 await w.get('[data-testid=document-adopt-source]').trigger('click');await vi.waitFor(()=>expect(w.find('[data-testid=document-adopt-source]').exists()).toBe(false))
 const adopted=JSON.parse(documentRaw()!);expect(adopted.branches).toEqual(expect.arrayContaining([expect.objectContaining({baseRevision:9,value:{phase:'candidates',items:old.items.map(i=>({...i,editorOpen:true}))}})]));expect(JSON.parse(localStorage.getItem(key)!)).toEqual(old)
 await persist(next,{isCurrent:()=>true});expect(child.props('modelValue')).toEqual(next);expect(localStorage.getItem(`document-import:${ME}:expires`)).toBe(retention)
})
it('父持久接口拒绝附件中的原图字段，不写入候选或Question草稿',async()=>{
 const w=mount(QuestionEditor,{props:{detail:detail()}});await flushPromises();const child=w.getComponent(MediaAttachments),before=localStorage.getItem(`admin-question-draft/v1/${encodeURIComponent(ME)}/${encodeURIComponent(detail().id)}/edit`)
 await expect(child.props('persistAttachments')!([{...next[0]!,content_base64:'private-image'}] as never,{isCurrent:()=>true})).rejects.toThrow('图片原文');expect(child.props('modelValue')).toEqual([]);expect(localStorage.getItem(`admin-question-draft/v1/${encodeURIComponent(ME)}/${encodeURIComponent(detail().id)}/edit`)).toBe(before)
})
