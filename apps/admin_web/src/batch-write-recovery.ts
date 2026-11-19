import { browserLocks, WriteCommandStore, type Command, type ExclusiveLock, type Body, type Json } from './api/write-command-store'
function canonicalBatchBody(value:Json):string {
 if(value!==null&&typeof value==='object'){
  if(Array.isArray(value))return '['+value.map(canonicalBatchBody).join(',')+']'
  return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonicalBatchBody(value[key]!)).join(',')+'}'
 }
 return JSON.stringify(value)
}
export interface BatchDraftBranch { id:string;raw:string;sourceGeneration:number }
interface Draft {v:1;owner:string;raw:string;generation:number;branches:BatchDraftBranch[]}
interface DraftSave extends Draft {conflict?:BatchDraftBranch}
export class BatchWriteRecovery {
 readonly commands:WriteCommandStore
 readonly resource:string
 private readonly draftKey:string
 constructor(readonly owner:string,private readonly locks:ExclusiveLock|undefined=browserLocks(),readonly group:readonly string[]=[]) {
  this.commands=new WriteCommandStore(localStorage,locks,owner)
  const scope=group.length?'/group/'+encodeURIComponent(JSON.stringify(group)):''
  this.draftKey=`admin-batch-draft/v1/${encodeURIComponent(owner)}${scope}`
  this.resource='batch-question-review'+scope
 }
 private run<T>(action:()=>Promise<T>):Promise<T> {
  if(!this.locks)return Promise.reject(Error('浏览器不支持跨标签页安全恢复，未发送请求。'))
  return this.locks.run(this.draftKey,action)
 }
 private read():Draft {
  const raw=localStorage.getItem(this.draftKey)
  if(raw===null)return {v:1,owner:this.owner,raw:'',generation:0,branches:[]}
  try {
   const d=JSON.parse(raw) as Draft
   if(d.v!==1||d.owner!==this.owner||typeof d.raw!=='string'||!Number.isSafeInteger(d.generation)||d.generation<0||Object.keys(d).some(k=>!['v','owner','raw','generation','branches'].includes(k)))throw Error()
   if((d as Partial<Draft>).branches===undefined)d.branches=[]
   if(!Array.isArray(d.branches)||d.branches.some(b=>typeof b.id!=='string'||typeof b.raw!=='string'||!Number.isSafeInteger(b.sourceGeneration)||b.sourceGeneration<0||Object.keys(b).some(k=>!['id','raw','sourceGeneration'].includes(k)))||new Set(d.branches.map(b=>b.id)).size!==d.branches.length)throw Error()
   return d
  }catch{throw Error('本机批量草稿损坏，已保留原文，请勿覆盖。')}
 }
 load():Promise<Draft>{return this.run(async()=>this.read())}
 save(raw:string,expectedGeneration:number):Promise<DraftSave>{
  return this.run(async()=>{
   const old=this.read()
   if(old.generation!==expectedGeneration){
    const existing=old.branches.find(branch=>branch.raw===raw&&branch.sourceGeneration===expectedGeneration)
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
 matches(c:Command):boolean{
  if(c.method!=='POST'||c.path!=='/admin/question-reviews/batch')return false
  if(c.resource===this.resource)return true
  // Existing complete owner-only command may be recovered only for its exact item group.
  return this.group.length>0&&c.resource==='batch-question-review'&&Array.isArray(c.body.items)&&JSON.stringify(c.body.items.map(i=>i&&typeof i==='object'&&!Array.isArray(i)?i.question_id:null))===JSON.stringify(this.group)
 }
 /** An existing key keeps its original resource identity and terminal phase.
  * Never prepare a scoped replacement for an already persisted owner-only key. */
 async recoverLegacy(key:string,body:Body):Promise<Command>{
  const existing=(await this.commands.list()).find(command=>command.key===key)
  if(existing){
   if(existing.owner!==this.owner||!this.matches(existing)||canonicalBatchBody(existing.body)!==canonicalBatchBody(body))throw Error('旧键对应的完整请求身份不一致，原记录保留，未发送请求。')
   return existing
  }
  return this.commands.prepare({key,body,method:'POST',path:'/admin/question-reviews/batch',resource:this.resource})
 }
 async history():Promise<Command|undefined>{return (await this.commands.list()).filter(c=>this.matches(c)&&c.result!==undefined).sort((a,b)=>a.epoch-b.epoch).at(-1)}
 async pending():Promise<Command|undefined>{return (await this.commands.list()).filter(c=>this.matches(c)&&c.error!=='abandoned_unknown'&&['prepared','unavailable','result_known'].includes(c.phase)).at(-1)}

}



export async function legacyBatchFingerprint(raw:string):Promise<string>{return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)))].map(v=>v.toString(16).padStart(2,'0')).join('')}
