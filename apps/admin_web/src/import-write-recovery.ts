import { browserLocks, WriteCommandStore, type Command, type ExclusiveLock } from './api/write-command-store'
export interface ImportDraftBranch { id:string;raw:string;sourceGeneration:number }
interface Draft {v:1;owner:string;raw:string;generation:number;branches:ImportDraftBranch[]}
interface DraftSave extends Draft {conflict?:ImportDraftBranch}
export class ImportWriteRecovery {
 readonly commands:WriteCommandStore
 private readonly draftKey:string
 constructor(readonly owner:string,private readonly locks:ExclusiveLock|undefined=browserLocks()) {
  this.commands=new WriteCommandStore(localStorage,locks,owner)
  this.draftKey=`admin-import-draft/v1/${encodeURIComponent(owner)}`
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
  }catch{throw Error('本机导入草稿损坏，已保留原文，请勿覆盖。')}
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
 async pending():Promise<Command|undefined>{return (await this.commands.list()).filter(c=>c.resource==='single-question-import'&&c.method==='POST'&&c.path==='/admin/question-imports'&&['prepared','unavailable','result_known'].includes(c.phase)).at(-1)}
}

