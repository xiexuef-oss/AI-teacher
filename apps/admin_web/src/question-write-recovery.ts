import { browserLocks, WriteCommandStore, type Command, type ExclusiveLock, type Ticket } from './api/write-command-store'
export interface QuestionDraftBranch { id:string;raw:string;sourceGeneration:number }
interface Draft {v:1;owner:string;raw:string;generation:number;branches:QuestionDraftBranch[];released:Ticket[]}
interface DraftSave extends Draft {conflict?:QuestionDraftBranch}
export class QuestionWriteRecovery {
 readonly commands:WriteCommandStore
 private readonly draftKey:string
 constructor(readonly owner:string,readonly questionId:string,readonly kind:'edit'|'review',private readonly locks:ExclusiveLock|undefined=browserLocks()) {
  this.commands=new WriteCommandStore(localStorage,locks,owner)
  this.draftKey=`admin-question-draft/v1/${encodeURIComponent(owner)}/${encodeURIComponent(questionId)}/${kind}`
 }
 private run<T>(action:()=>Promise<T>):Promise<T> {
  if(!this.locks)return Promise.reject(Error('浏览器不支持跨标签页安全恢复，未发送请求。'))
  return this.locks.run(this.draftKey,action)
 }
 private read():Draft {
  const raw=localStorage.getItem(this.draftKey)
  if(raw===null)return {v:1,owner:this.owner,raw:'',generation:0,branches:[],released:[]}
  try {
   const d=JSON.parse(raw) as Draft
   if(d.v!==1||d.owner!==this.owner||typeof d.raw!=='string'||!Number.isSafeInteger(d.generation)||d.generation<0||Object.keys(d).some(k=>!['v','owner','raw','generation','branches','released'].includes(k)))throw Error()
   if((d as Partial<Draft>).branches===undefined)d.branches=[]
   if((d as Partial<Draft>).released===undefined)d.released=[]
   if(!Array.isArray(d.released)||d.released.some(t=>typeof t.key!=='string'||!Number.isSafeInteger(t.epoch)||t.epoch<1||typeof t.snapshot!=='string'||Object.keys(t).some(k=>!['key','epoch','snapshot'].includes(k))))throw Error()
   if(!Array.isArray(d.branches)||d.branches.some(b=>typeof b.id!=='string'||typeof b.raw!=='string'||!Number.isSafeInteger(b.sourceGeneration)||b.sourceGeneration<0||Object.keys(b).some(k=>!['id','raw','sourceGeneration'].includes(k)))||new Set(d.branches.map(b=>b.id)).size!==d.branches.length)throw Error()
   return d
  }catch{throw Error('本机导入草稿损坏，已保留原文，请勿覆盖。')}
 }
 load():Promise<Draft>{return this.run(async()=>this.read())}
 save(raw:string,expectedGeneration:number):Promise<DraftSave>{
  return this.run(async()=>{
   const old=this.read()
   if(old.generation!==expectedGeneration){
    const existing=old.branches.find(b=>b.raw===raw&&b.sourceGeneration===expectedGeneration)
    if(existing)return {...old,conflict:existing}
    const branch={id:crypto.randomUUID(),raw,sourceGeneration:expectedGeneration}
    const next={...old,branches:[...old.branches,branch]}
    localStorage.setItem(this.draftKey,JSON.stringify(next))
    return {...next,conflict:branch}
   }
   if(old.raw===raw)return old
   const next:Draft={...old,raw,generation:old.generation+1}
   localStorage.setItem(this.draftKey,JSON.stringify(next));return next
  })
 }
 /** Guarded snapshots are not ordinary edits: CAS or lease failure never applies
  * the proposed parent form. Network and original write commands are untouched. */
 saveGuarded(raw:string,expectedGeneration:number,isCurrent:()=>boolean):Promise<Draft>{
  if(!isCurrent())return Promise.reject(Error('附件关联上下文已变化，未保存。'))
  return this.run(async()=>{
   if(!isCurrent())throw Error('附件关联上下文已变化，未保存。')
   const old=this.read();if(old.generation!==expectedGeneration)throw Error('草稿来源已变化，附件未关联，请比较双方。')
   if(!isCurrent())throw Error('附件关联上下文已变化，未保存。')
   if(old.raw===raw)return old
   const next={...old,raw,generation:old.generation+1}
   localStorage.setItem(this.draftKey,JSON.stringify(next));return next
  })
 }
 /** Explicit source resolution; selection alone never rebases or submits. */
 promoteBranch(id:string,expectedHeadGeneration:number):Promise<Draft>{
  return this.run(async()=>{
   const old=this.read(),branch=old.branches.find(b=>b.id===id)
   if(!branch||old.generation!==expectedHeadGeneration)throw Error('当前草稿已变化，请重新查看双方后选择。')
   const previous={id:crypto.randomUUID(),raw:old.raw,sourceGeneration:old.generation}
   const next={...old,raw:branch.raw,generation:old.generation+1,branches:[...old.branches,previous]}
   localStorage.setItem(this.draftKey,JSON.stringify(next));return next
  })
 }
 get path(){return `/admin/questions/${encodeURIComponent(this.questionId)}/${this.kind==='edit'?'versions':'review'}`}
 get resource(){return `question:${this.questionId}:${this.kind}`}
 async pending():Promise<Command|undefined>{const d=await this.load();return (await this.commands.list()).filter(c=>!d.released.some(t=>t.key===c.key&&t.epoch===c.epoch&&t.snapshot===c.snapshot)&&c.owner===this.owner&&c.resource===this.resource&&c.method==='POST'&&c.path===this.path&&['prepared','unavailable','result_known'].includes(c.phase)).at(-1)}
 async isReleased(ticket:Ticket):Promise<boolean>{const t={key:ticket.key,epoch:ticket.epoch,snapshot:ticket.snapshot};return (await this.load()).released.some(r=>r.key===t.key&&r.epoch===t.epoch&&r.snapshot===t.snapshot)}
 releaseUnknown(ticket:Ticket):Promise<void>{
  const t={key:ticket.key,epoch:ticket.epoch,snapshot:ticket.snapshot}
  return this.run(async()=>{
   const d=this.read(),c=(await this.commands.list()).find(c=>c.key===t.key&&c.epoch===t.epoch&&c.snapshot===t.snapshot&&c.owner===this.owner&&c.resource===this.resource&&c.method==='POST'&&c.path===this.path)
   if(!c||!['prepared','unavailable'].includes(c.phase))throw Error('只有未知原命令可以停止重试；已知成功请本机确认。')
   if(d.released.some(r=>r.key===t.key&&r.epoch===t.epoch&&r.snapshot===t.snapshot))return
   localStorage.setItem(this.draftKey,JSON.stringify({...d,released:[...d.released,t]}))
  })
 }
 adopt(raw:string,expectedGeneration:number):Promise<Draft>{return this.run(async()=>{const old=this.read();if(old.generation!==expectedGeneration)throw Error('草稿已变化，请重新比较来源。');const next={...old,raw,generation:old.generation+1,branches:[...old.branches,{id:crypto.randomUUID(),raw:old.raw,sourceGeneration:old.generation}]};localStorage.setItem(this.draftKey,JSON.stringify(next));return next})}}


import { onBeforeUnmount, onMounted, ref, shallowRef, nextTick, computed } from 'vue'
import { captureSessionBinding,isCurrentSessionBinding } from './session'
import { ApiError } from './api/client'
import { handleUnauthorized,newIdempotencyKey } from './api/guard'
import type { Body,Json } from './api/write-command-store'
interface Source {id:string;version:number;reviewRevision:number|null}
export function useQuestionCommands(kind:'edit'|'review',source:Source,getForm:()=>unknown,setForm:(v:unknown)=>void,localOnly=false,project?:()=>Body|null){
 const headRaw=ref(''),pending=shallowRef<Command|null>(null),message=ref(''),blocked=ref(false),loaded=ref(localOnly),branches=ref<QuestionDraftBranch[]>([])
 let applying=false,live=true,store:QuestionWriteRecovery|null=null,generation=0,queue:Promise<void>=Promise.resolve(),lastQueuedRaw:string|null=null
 const editSerial=ref(0),durableSerial=ref(0)
 let branchId:string|null=null,selectedHead=0,initializing:Promise<void>=Promise.resolve()
 let draftSource=source
 const payload=()=>JSON.stringify({source:draftSource,form:getForm()})
 const hasUnsaved=()=>durableSerial.value<editSerial.value
 const draftState=computed(()=>!loaded.value?'正在读取本机草稿…':hasUnsaved()?(message.value.includes('内存')?'尚未保存到本机，请勿退出。':'正在保存到本机…'):!headRaw.value?'尚未编辑。':blocked.value?'本机草稿已保存，来源待确认。':'本机草稿已保存。')
 const current=(binding:ReturnType<typeof captureSessionBinding>)=>live&&isCurrentSessionBinding(binding)&&(!store||store.owner===binding.userId)
 async function applyForm(value:unknown){applying=true;try{setForm(value);await nextTick()}finally{applying=false}}
 function decode(raw:string){const p=JSON.parse(raw) as {source:Source;form:unknown};if(!p||Object.keys(p).some(k=>!['source','form'].includes(k))||p.source?.id!==source.id||Object.keys(p.source).some(k=>!['id','version','reviewRevision'].includes(k))||!Number.isInteger(p.source.version)||p.source.version<1||(p.source.reviewRevision!==null&&(!Number.isInteger(p.source.reviewRevision)||p.source.reviewRevision<1))||!p.form||typeof p.form!=='object'||Array.isArray(p.form)||Object.keys(p.form).some(k=>!Object.keys(getForm() as object).includes(k)))throw Error('草稿格式未知，保留原文。');return p}
 async function initialize(){
  if(localOnly)return
  const binding=captureSessionBinding();if(!binding)return
  const s=new QuestionWriteRecovery(binding.userId,source.id,kind);store=s
  try{const d=await s.load();generation=d.generation;const command=await s.pending();if(!current(binding))return
   if(d.raw){const p=decode(d.raw);draftSource=p.source;await applyForm(p.form);blocked.value=JSON.stringify(p.source)!==JSON.stringify(source)}
   headRaw.value=d.raw;branches.value=d.branches;pending.value=command??null;lastQueuedRaw=payload();loaded.value=true
  }catch(e){if(current(binding)){blocked.value=true;message.value=String(e)}}
 }
 onMounted(()=>{initializing=initialize()});onBeforeUnmount(()=>{live=false})
 function changed(){
  if(localOnly||applying||!loaded.value)return
  const binding=captureSessionBinding(),s=store,raw=payload();if(!s||!binding||raw===lastQueuedRaw)return
  lastQueuedRaw=raw;const serial=++editSerial.value
  queue=queue.catch(()=>{}).then(async()=>{
   await initializing
   try{const d=await s.save(raw,generation);if(!d.conflict)generation=d.generation;durableSerial.value=Math.max(durableSerial.value,serial);if(!current(binding))return
    headRaw.value=d.raw;branches.value=d.branches
    if(d.conflict){blocked.value=true;branchId=d.conflict.id;selectedHead=d.generation;if(serial===editSerial.value)message.value='冲突分支已独立保存，请明确选择来源。'}
    else if(serial===editSerial.value){blocked.value=branchId!==null||JSON.stringify(draftSource)!==JSON.stringify(source);if(message.value.includes('仅在当前页面内存'))message.value='最新输入已安全保存在本机。'}
   }catch(e){if(serial===editSerial.value)lastQueuedRaw=null;if(current(binding)&&serial===editSerial.value){blocked.value=true;message.value='输入仅在当前页面内存保留，请勿退出。'+String(e)}}
  })
 } function persistSnapshot(snapshot:unknown,context:{isCurrent:()=>boolean}):Promise<void>{
  const leaseCurrent=context.isCurrent
  const captured=JSON.parse(JSON.stringify(snapshot)) as unknown,binding=captureSessionBinding(),s=store,serial=editSerial.value
  const guard=()=>current(binding)&&leaseCurrent()&&serial===editSerial.value&&!hasUnsaved()&&!blocked.value
  const operation=queue.catch(()=>{}).then(async()=>{
   await initializing
   if(!s||!guard()||!loaded.value)throw Error('最新输入、身份或来源已变化，附件未关联。')
   const raw=JSON.stringify({source:draftSource,form:captured})
   const d=await s.saveGuarded(raw,generation,guard)
   if(!guard())throw Error('保存后上下文变化，附件未应用到当前表单。')
   generation=d.generation;headRaw.value=d.raw;lastQueuedRaw=raw;durableSerial.value=Math.max(durableSerial.value,serial)
   await applyForm(captured)
  })
  queue=operation.catch(e=>{if(current(binding))message.value='附件关联未应用，输入仍保留。'+String(e)})
  return operation
 }
 async function run(body:Body,send:(token:string,body:Body,key:string)=>Promise<Json>){
  const binding=captureSessionBinding(),s=store;if(!s||!binding||!current(binding))return null
  await queue;if(!current(binding))return null
  if(hasUnsaved()||blocked.value||!loaded.value)throw Error('草稿未安全保存或来源冲突，未发送请求。')
  if(pending.value)throw Error('请先明确恢复原命令，不会把续改内容作为旧请求发送。')
  // Persist a complete initial snapshot even if no form watch has fired.
  const d=await s.save(payload(),generation);if(!d.conflict)generation=d.generation
  if(d.conflict){blocked.value=true;branches.value=d.branches;branchId=d.conflict.id;selectedHead=d.generation;throw Error('冲突分支已保存，未发送请求。')}
  const c=await s.commands.prepare({key:newIdempotencyKey(),method:'POST',path:s.path,resource:s.resource,body})
  if(!current(binding))return null;pending.value=c
  return deliver(c,send)
 }
 async function deliver(c:Command,send:(token:string,body:Body,key:string)=>Promise<Json>){
  const binding=captureSessionBinding(),s=store;if(!s||!binding||!current(binding))return null
  const before=payload(),matches=project?JSON.stringify(project())===JSON.stringify(c.body):true
  try{const result=await s.commands.send(c,async fixed=>{if(!current(binding))throw Error('身份或页面已失效');return send(binding.token,fixed.body,fixed.key)})
   if(!current(binding)||await s.isReleased(c))return null;pending.value=result
   if(hasUnsaved())return null
   await s.commands.acknowledgeStoredResult(result);if(!current(binding))return null;pending.value=null
   if(hasUnsaved())return null
   message.value='历史写入结果已保留；当前题目状态以重新读取为准。'
   return matches&&before===payload()?result:null
  }catch(e){if(e instanceof ApiError&&e.status===422&&e.code==='validation_error'){
    await s.commands.mark(c,'rejected','validation_error');if(current(binding))pending.value=null
   }
   if(current(binding)&&!handleUnauthorized(e,binding))message.value=String(e instanceof ApiError?e.message:e)
   throw e
  }
 }
 async function retry(send:(token:string,body:Body,key:string)=>Promise<Json>){if(!pending.value)return null;return deliver(pending.value,send)}
 async function release(){
  await queue;if(hasUnsaved())throw Error('最新输入仅在内存，请先保存，不会释放原命令。')
  const binding=captureSessionBinding(),s=store,c=pending.value;if(!s||!c||!current(binding))return
  await s.releaseUnknown(c)
  if(current(binding)&&pending.value?.key===c.key){pending.value=null;message.value='原命令仍是未知历史，仅停止本机重试；未撤销或取消服务器操作。新来源须另行明确采用。'}
 }
 async function ack(){await queue;if(hasUnsaved())throw Error('最新输入仅在内存，请勿退出或确认覆盖。');const serial=editSerial.value;const binding=captureSessionBinding(),s=store,c=pending.value;if(!s||!c||!current(binding))return
  try{await s.commands.acknowledgeStoredResult(c);if(current(binding)&&serial===editSerial.value&&!hasUnsaved()){pending.value=null;message.value='已确认本机保存的历史成功结果，无需网络。'}}catch(e){if(current(binding))message.value='本机确认未成功，历史记录仍保留。'+String(e)}
 }
 async function loadBranch(id:string){await queue;if(hasUnsaved())throw Error('输入仅在内存，请勿退出。');const serial=editSerial.value;const binding=captureSessionBinding(),s=store;if(!s)return;const d=await s.load();if(!current(binding))return;if(serial!==editSerial.value||hasUnsaved())throw Error('最新输入尚未落盘，请勿载入覆盖。')
  const branch=d.branches.find(b=>b.id===id);if(!branch)return;const selected=decode(branch.raw);headRaw.value=d.raw;branches.value=d.branches;draftSource=selected.source;await applyForm(selected.form);branchId=id;selectedHead=d.generation;generation=branch.sourceGeneration;lastQueuedRaw=payload();blocked.value=true
 }
 async function adopt(){await queue;if(hasUnsaved())throw Error('输入尚未落盘');const serial=editSerial.value;const binding=captureSessionBinding(),s=store;if(!s)return
  const d=await s.adopt(JSON.stringify({source,form:getForm()}),branchId?selectedHead:generation)
  if(serial!==editSerial.value||hasUnsaved()){if(current(binding))message.value='采用期间出现新输入，请先保存并重新比较。';return}
  generation=d.generation;draftSource=source;lastQueuedRaw=payload()
  if(current(binding)){headRaw.value=d.raw;branches.value=d.branches;blocked.value=false;branchId=null;message.value='已保留旧来源并采用当前来源，请重新核对后提交新命令。'}
 }
 return {pending,message,blocked,loaded,branches,headRaw,draftState,changed,persistSnapshot,run,retry,release:()=>release().catch(e=>{message.value='停止重试未成功，原记录与输入保留。'+String(e)}),ack:()=>ack().catch(e=>{message.value='确认未成功，记录保留。'+String(e)}),loadBranch:(id:string)=>loadBranch(id).catch(e=>{message.value='载入未成功，输入保留。'+String(e)}),adopt:()=>adopt().catch(e=>{message.value='来源选择未成功，输入与旧记录保留。'+String(e)})}
}














