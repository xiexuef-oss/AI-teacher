import type {components} from './api/schema'
import {WriteCommandStore,browserLocks,type Body,type Command,type Json} from './api/write-command-store'
import {DocumentWriteRecovery,type DocumentKind,type DocumentState,type DocumentBodies} from './document-write-recovery'
import * as api from './api/document-import'
import type {SessionBinding} from './session'
import {isCurrentSessionBinding} from './session'
type S=components['schemas']
const canonical=(value:unknown):string=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([a],[b])=>a.localeCompare(b))):item)
const rawDigest=async(raw:string)=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(raw)))].map(n=>n.toString(16).padStart(2,'0')).join('')
interface LegacyDisposition{v:1;owner:string;role:string;rawSha256:string;disposition:'stopped_unknown'}
export class DocumentImportActions {
 store!:DocumentWriteRecovery
 state!:DocumentState
 commands:Command[]=[]
 legacyNotice=''
 private legacyRaw:string|null|undefined
 private legacySha=''
 private legacyRisk=true
 constructor(readonly binding:SessionBinding,private readonly guard:()=>boolean){}
 current(){return this.guard()&&isCurrentSessionBinding(this.binding)}
 private legacyKey(){return `document-import:${this.binding.userId}:requests`}
 private dispositionKey(sha:string){return `admin-document-legacy-disposition/v1/${encodeURIComponent(this.binding.userId)}/${this.binding.role}/${sha}`}
 private disposition(sha:string):LegacyDisposition|undefined{
  const raw=localStorage.getItem(this.dispositionKey(sha));if(raw===null)return
  const value=JSON.parse(raw) as LegacyDisposition
  if(!value||Object.keys(value).sort().join(',')!=='disposition,owner,rawSha256,role,v'||value.v!==1||value.owner!==this.binding.userId||value.role!==this.binding.role||value.rawSha256!==sha||value.disposition!=='stopped_unknown')throw Error('旧操作停止记录格式未知，保留原记录。')
  return value
 }
 hasUnresolvedLegacy():boolean{
  const raw=localStorage.getItem(this.legacyKey());if(raw===null)return false
  if(raw!==this.legacyRaw||!this.legacySha)return true
  try{if(this.disposition(this.legacySha))return false}catch{return true}
  return this.legacyRisk
 }
 assertNoUnresolvedLegacy(){if(!this.current())throw Error('身份或页面已变化');if(this.hasUnresolvedLegacy())throw Error('旧操作结果未知，请先明确保留未知并停止本机重试，再建立新窗口。')}
 private async refreshLegacyGate(){
  const raw=localStorage.getItem(this.legacyKey())
  if(raw===null){this.legacyRaw=null;this.legacySha='';this.legacyRisk=false;return}
  const sha=await rawDigest(raw)
  let risk=true
  try{if(this.disposition(sha)){this.legacyRaw=raw;this.legacySha=sha;this.legacyRisk=true;return}}catch{/* Unknown markers never authorize a new lane. */}
  let entries:Record<string,unknown>|undefined
  try{const parsed:unknown=JSON.parse(raw);if(parsed&&typeof parsed==='object'&&!Array.isArray(parsed))entries=parsed as Record<string,unknown>}catch{/* Keep unknown raw unchanged. */}
  if(entries){
   const locks=browserLocks(),authorities=await new WriteCommandStore(localStorage,locks,this.binding.userId).list(),released=new Set<string>()
   const prefix=`admin-document-state/v1/${encodeURIComponent(this.binding.userId)}/`
   for(const key of Object.keys(localStorage).filter(k=>k.startsWith(prefix))){
    const s=JSON.parse(localStorage.getItem(key)!) as DocumentState
    if(s.owner!==this.binding.userId||s.role!==this.binding.role)continue
    const commands=await new DocumentWriteRecovery(this.binding.userId,this.binding.role,s.workspace).commands.list()
    authorities.push(...commands)
    for(const t of s.released??[])released.add(`${t.key}:${t.epoch}:${t.snapshot}`)
   }
   const expiry=Number(localStorage.getItem(`document-import:${this.binding.userId}:expires`))
   risk=Object.entries(entries).some(([action,unknownRecord])=>{
    if(!unknownRecord||typeof unknownRecord!=='object'||Array.isArray(unknownRecord))return true
    const record=unknownRecord as {key?:unknown;body?:unknown}
    if(Object.keys(record).some(k=>!['key','body'].includes(k))||typeof record.key!=='string'||!record.body||typeof record.body!=='object'||Array.isArray(record.body))return true
    const body=record.body as Body,match=/^([^:]+):(process|cancel|save|candidates|submit)$/.exec(action),upload=/^([^:]+):upload(?::.*)?$/.exec(action)
    const kind=match?.[2]==='save'?'candidates':match?.[2]
    const path=action==='create'?'/admin/import-jobs':match?`/admin/import-jobs/${match[1]}/${kind}`:upload?`/admin/import-jobs/${upload[1]}/files`:undefined
    if(path&&authorities.some(c=>c.key===record.key&&c.method==='POST'&&c.path===path&&canonical(c.body)===canonical(body)&&(['result_known','acked','rejected'].includes(c.phase)||released.has(`${c.key}:${c.epoch}:${c.snapshot}`))))return false
    if(!match||!Number.isFinite(expiry)||expiry<=Date.now()||!Number.isSafeInteger(body.expected_revision)||Number(body.expected_revision)<1)return true
    const allowed=kind==='candidates'?['expected_revision','items']:kind==='submit'?['expected_revision','candidate_ids']:['expected_revision']
    if(Object.keys(body).some(k=>!allowed.includes(k))||allowed.some(k=>!(k in body)))return true
    if(kind==='candidates'&&!Array.isArray(body.items))return true
    if(kind==='submit'&&(!Array.isArray(body.candidate_ids)||!body.candidate_ids.every(id=>typeof id==='string')))return true
    // A recoverable record must first enter this workspace's original command lane.
    // Its shape alone cannot authorize a new window while the old intent is pending.
    return !this.commands.some(c=>c.key===record.key&&c.method==='POST'&&c.path===path&&canonical(c.body)===canonical(body))
   })
  }
  if(localStorage.getItem(this.legacyKey())!==raw)throw Error('旧记录在检查期间变化，未放行新操作。')
  this.legacyRaw=raw;this.legacySha=sha;this.legacyRisk=risk
  if(risk)this.legacyNotice='旧操作结果未知且不能精确恢复；原文保留，请明确停止本机重试后再建立新窗口。'
 }
 async stopLegacyForNewWindow(){
  if(!this.current())throw Error('身份或页面已变化')
  const raw=localStorage.getItem(this.legacyKey());if(raw===null)return
  const sha=await rawDigest(raw),locks=browserLocks();if(!locks)throw Error('缺少跨页锁，旧操作仍保持未知。')
  await locks.run(`admin-document-legacy-disposition/v1/${encodeURIComponent(this.binding.userId)}`,async()=>{
   if(!this.current()||localStorage.getItem(this.legacyKey())!==raw)throw Error('身份或旧记录已变化，未停止旧操作。')
   if(!this.disposition(sha))localStorage.setItem(this.dispositionKey(sha),JSON.stringify({v:1,owner:this.binding.userId,role:this.binding.role,rawSha256:sha,disposition:'stopped_unknown'} satisfies LegacyDisposition))
   this.legacyRaw=raw;this.legacySha=sha;this.legacyRisk=true
  })
 }
 async restore(options:S['DocImportOptions'],jobId?:string){
  const prefix=`admin-document-state/v1/${encodeURIComponent(this.binding.userId)}/`,states:DocumentState[]=[]
  for(const key of Object.keys(localStorage).filter(k=>k.startsWith(prefix))){try{const state=JSON.parse(localStorage.getItem(key)!) as DocumentState;if(state.owner!==this.binding.userId||state.role!==this.binding.role)continue;states.push(state)}catch{throw Error('文档恢复原文格式未知，保留原文。')}}
  const saved=states.filter(s=>!jobId||s.jobId===jobId).at(-1)
  if(saved){this.store=new DocumentWriteRecovery(this.binding.userId,this.binding.role,saved.workspace);this.state=await this.store.load()}
  else{const expiresAt=Date.parse(options.creation_deadline);this.store=new DocumentWriteRecovery(this.binding.userId,this.binding.role,crypto.randomUUID());this.state=await this.store.initialize(expiresAt)}
  this.commands=await this.store.history()
  const legacy=localStorage.getItem(`document-import:${this.binding.userId}:requests`)
  if(legacy)this.legacyNotice='旧请求原文保留；无原deadline或文件指纹的旧操作不能自动补字段重发。'
  await this.refreshLegacyGate()
 }
 async choose(workspace:string){const store=new DocumentWriteRecovery(this.binding.userId,this.binding.role,workspace),state=await store.load(),commands=await store.history();if(!this.current())return;this.store=store;this.state=state;this.commands=commands}
 async fresh(options:S['DocImportOptions']){await this.refreshLegacyGate();this.assertNoUnresolvedLegacy();this.store=new DocumentWriteRecovery(this.binding.userId,this.binding.role,crypto.randomUUID());this.state=await this.store.initialize(Date.parse(options.creation_deadline));this.commands=[];this.assertNoUnresolvedLegacy()}
 async selectJob(detail:S['DocImportJobDetail']){
  const prefix=`admin-document-state/v1/${encodeURIComponent(this.binding.userId)}/`;let selected:DocumentState|undefined
  for(const key of Object.keys(localStorage).filter(k=>k.startsWith(prefix))){const value=JSON.parse(localStorage.getItem(key)!) as DocumentState;if(value.owner===this.binding.userId&&value.role===this.binding.role&&value.jobId===detail.job.id)selected=value}
  if(selected){this.store=new DocumentWriteRecovery(this.binding.userId,this.binding.role,selected.workspace);this.state=await this.store.load()}
  else{this.store=new DocumentWriteRecovery(this.binding.userId,this.binding.role,crypto.randomUUID());this.state=await this.store.initialize(Date.parse(detail.job.expires_at),detail.job.id)}
  if(!this.state.expired){await this.store.tightenExpiry(Date.parse(detail.job.expires_at));this.state=await this.store.load()}
  await this.migrateLegacy(detail.job.id)
  this.commands=await this.store.history()
  await this.refreshLegacyGate()
 }
 async migrateLegacy(jobId:string){
  const prefix=`document-import:${this.binding.userId}`,expiry=Number(localStorage.getItem(prefix+':expires'))
  const raw=localStorage.getItem(prefix+':requests'),draft=localStorage.getItem(prefix+':edits:'+jobId)
  if(!raw&&!draft)return
  if(!Number.isFinite(expiry)||expiry<=Date.now()){this.legacyNotice='旧记录缺有效留存来源，原文保留，不重建命令。';return}
  await this.store.tightenExpiry(expiry)
  if(draft&&!this.state.draft){try{const d=JSON.parse(draft);if(!Array.isArray(d.items)||!Number.isSafeInteger(d.revision)||Object.keys(d).some(k=>!['revision','items','backups'].includes(k)))throw Error();this.state=await this.store.saveDraft({phase:'candidates',items:d.items},d.revision,this.state.generation,()=>this.current())}catch{throw Error('旧候选草稿格式或落盘未知，原文保留，未覆盖。')}}
  if(raw){let entries:Record<string,{key:string;body:Body}>;try{entries=JSON.parse(raw);if(!entries||Array.isArray(entries))throw Error()}catch{throw Error('旧命令原文损坏，保留原文并停止。')}
   for(const [action,record] of Object.entries(entries)){
    if(!action.startsWith(jobId+':'))continue
    const tail=action.slice(jobId.length+1),kind=tail==='save'?'candidates':tail
    const allowed=kind==='candidates'?['expected_revision','items']:kind==='submit'?['expected_revision','candidate_ids']:['expected_revision']
    if(!['process','cancel','candidates','submit'].includes(kind)||!record||typeof record.key!=='string'||!record.body||Object.keys(record.body).some(k=>!allowed.includes(k))||allowed.some(k=>!(k in record.body))||!Number.isSafeInteger(record.body.expected_revision)){this.legacyNotice='旧上传缺原字节指纹或旧动作格式未知，原文保留且不能自动重发。';continue}
    const original=(await new WriteCommandStore(localStorage,browserLocks(),this.binding.userId).list()).find(c=>c.key===record.key)
    await this.store.importLegacy({key:record.key,method:'POST',path:`/admin/import-jobs/${jobId}/${kind}`,resource:original?.resource??`document:${this.binding.role}:${this.store.workspace}:${kind}`,body:record.body})
   }
  }
  this.state=await this.store.load()
 }
 async refresh(){const store=this.store,state=await store.load(),commands=await store.history();if(this.store===store&&this.current()){this.state=state;this.commands=commands}}
 active(){return this.commands.find(c=>!this.state.released.some(t=>t.key===c.key&&t.snapshot===c.snapshot&&t.epoch===c.epoch)&&['prepared','unavailable','result_known'].includes(c.phase))}
 async saveDraft(value:Body,baseRevision:number|undefined,generation:number,guard:()=>boolean){const store=this.store,result=await store.saveDraft(value,baseRevision,generation,guard);if(store===this.store&&this.current())this.state=result;return result}
 async prepare<K extends Exclude<DocumentKind,'upload'>>(kind:K,body:DocumentBodies[K]){await this.refreshLegacyGate();this.assertNoUnresolvedLegacy();const c=await this.store.prepare(kind,body,this.state.jobId);this.assertNoUnresolvedLegacy();await this.refresh();this.assertNoUnresolvedLegacy();return c}
 async execute(c:Command,file?:{body:S['DocImportUpload'];bytes:Uint8Array}){
  const originalStore=this.store
  const send=async(fixed:Command,body:Body=fixed.body):Promise<Json>=>{
   await this.refreshLegacyGate();this.assertNoUnresolvedLegacy()
   if(!this.current()||this.store!==originalStore)throw Error('原身份/工作区已变化，未发送请求。')
   const token=this.binding.token,jobId=fixed.path.split('/')[3]!,action=fixed.path.split('/')[4],kind=fixed.path==='/admin/import-jobs'?'create':action==='files'?'upload':action
   switch(kind){
    case 'create':return await api.createImportJob(token,body as S['DocImportJobCreate'],fixed.key) as unknown as Json
    case 'upload':return await api.uploadImportFile(token,jobId,body as S['DocImportUpload'],fixed.key) as unknown as Json
    case 'process':return await api.processImportJob(token,jobId,body as S['DocImportRevision'],fixed.key) as unknown as Json
    case 'cancel':return await api.cancelImportJob(token,jobId,body as S['DocImportRevision'],fixed.key) as unknown as Json
    case 'candidates':return await api.saveImportCandidates(token,jobId,body as S['DocImportCandidatesEdit'],fixed.key) as unknown as Json
    case 'submit':return await api.submitImportCandidates(token,jobId,body as S['DocImportSubmit'],fixed.key) as unknown as Json
    default:throw Error('未知文档命令，保留原文')
   }
  }
  const result=c.file?await originalStore.sendUpload(c,file,send):await originalStore.send(c,send)
  if(!this.current()||this.store!==originalStore)return null
  await this.refresh();return result
 }
}
