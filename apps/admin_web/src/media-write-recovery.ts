import type {components} from './api/schema'
import {browserLocks,WriteCommandStore,type Body,type Json,type Command,type Ticket,type StoragePort,type ExclusiveLock} from './api/write-command-store'
import {newIdempotencyKey} from './api/guard'
type S=components['schemas']
export type MediaKind='create'|'content'|'confirm'|'declaration'|'delete'
export interface MediaSource{questionId?:string;version?:number;contextId:string}
export interface MediaAssociation{target:MediaSource;mediaId:string;sha256:string;observedAt:number}
export type MediaAssociationIntent=MediaAssociation&{phase:'intent'}
export interface DeclarationScope{questionId:string;version:number;mediaId:string;sha256:string}
interface WorkspaceRecord{id:string;source?:MediaSource;associations?:MediaAssociationIntent[];metadata?:S['MediaUploadRequest'];declaration?:DeclarationScope;legacyMediaId?:string;legacyKeys?:Partial<Record<MediaKind,string>>;released:Ticket[]}
interface BundleRecord{v:1;owner:string;role:string;activeWorkspaceId:string|null;workspaces:WorkspaceRecord[];legacyRefs:{key:string;hash:string;workspaceId:string}[]}
export interface MediaWorkspace extends WorkspaceRecord{commands:Command[];active?:Command;mediaId?:string;confirmed?:S['MediaAssetInfo']}
export interface MediaBundle{activeWorkspaceId:string|null;workspaces:MediaWorkspace[]}
export type SelectedMedia={body:S['MediaBlobUpload'];bytes:Uint8Array}
const copy=<T>(v:T):T=>JSON.parse(JSON.stringify(v)) as T
function exact(v:object,allowed:string[]){if(Object.keys(v).some(k=>!allowed.includes(k)))throw Error('Unsupported media source preserved')}
function canonical(v:unknown):string{if(v!==null&&typeof v==='object'){if(Array.isArray(v))return `[${v.map(canonical).join(',')}]`;const o=v as Record<string,unknown>;return `{${Object.keys(o).sort().map(k=>`${JSON.stringify(k)}:${canonical(o[k])}`).join(',')}}`}return JSON.stringify(v)}
async function hash(v:unknown){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(v))))].map(b=>b.toString(16).padStart(2,'0')).join('')}
async function byteHash(v:Uint8Array){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new Uint8Array(v)))].map(b=>b.toString(16).padStart(2,'0')).join('')}
const ticket=(c:Ticket):Ticket=>Object.freeze({key:c.key,epoch:c.epoch,snapshot:c.snapshot})
const same=(a:Ticket,b:Ticket)=>a.key===b.key&&a.epoch===b.epoch&&a.snapshot===b.snapshot
function id(v:unknown):asserts v is string{if(typeof v!=='string'||!(/^[A-Za-z0-9._:-]+$/).test(v))throw Error('Invalid media resource ID')}
function sha(v:unknown):asserts v is string{if(typeof v!=='string'||!(/^[a-f0-9]{64}$/).test(v))throw Error('Invalid media SHA256')}
function metadata(v:S['MediaUploadRequest']){exact(v,['purpose','mime','size_bytes','sha256']);if(v.purpose!=='question_attachment'||!['image/png','image/jpeg','image/webp'].includes(v.mime)||!Number.isSafeInteger(v.size_bytes)||v.size_bytes<1)throw Error('Invalid attachment metadata');sha(v.sha256)}
function mediaSource(v:MediaSource){exact(v,['questionId','version','contextId']);id(v.contextId);if(v.questionId!==undefined)id(v.questionId);if(v.version!==undefined&&(!v.questionId||!Number.isSafeInteger(v.version)||v.version<1))throw Error('Unknown media source version')}
function association(v:MediaAssociation,persisted=false){exact(v,['target','mediaId','sha256','observedAt',...(persisted?['phase']:[])]);if(persisted&&(v as MediaAssociationIntent).phase!=='intent')throw Error('Unknown media association intent');mediaSource(v.target);id(v.mediaId);sha(v.sha256);if(!Number.isSafeInteger(v.observedAt)||v.observedAt<0)throw Error('Unknown media observation')}
function declaration(v:DeclarationScope){exact(v,['questionId','version','mediaId','sha256']);id(v.questionId);id(v.mediaId);sha(v.sha256);if(!Number.isSafeInteger(v.version)||v.version<1)throw Error('Unknown declaration source version')}
export function kindOf(c:Command):MediaKind{const k=c.resource.split(':').at(-1);if(!['create','content','confirm','declaration','delete'].includes(k??''))throw Error('Unsupported media command');return k as MediaKind}
export class MediaWriteRecovery{
 readonly commands:WriteCommandStore
 readonly storageKey:string
 constructor(readonly owner:string,readonly role:'reviewer'|'admin',private readonly disk:StoragePort=localStorage,private readonly legacy:Storage=sessionStorage,private readonly locks:ExclusiveLock|undefined=browserLocks()){
  if(!owner||!['reviewer','admin'].includes(role))throw Error('Invalid media owner role')
  this.commands=new WriteCommandStore(disk,locks,owner);this.storageKey=`admin-media/v1/${encodeURIComponent(owner)}/${role}`
 }
 private locked<T>(action:()=>Promise<T>):Promise<T>{if(!this.locks)return Promise.reject(Error('Media recovery needs cross-tab Web Locks; no request sent'));return this.locks.run(this.storageKey,action)}
 private raw():BundleRecord{
  const raw=this.disk.getItem(this.storageKey);if(raw===null)return {v:1,owner:this.owner,role:this.role,activeWorkspaceId:null,workspaces:[],legacyRefs:[]}
  try{const b=JSON.parse(raw) as BundleRecord;exact(b,['v','owner','role','activeWorkspaceId','workspaces','legacyRefs']);if(b.v!==1||b.owner!==this.owner||b.role!==this.role||!Array.isArray(b.workspaces)||!Array.isArray(b.legacyRefs))throw Error()
   const ids=new Set<string>();for(const w of b.workspaces){exact(w,['id','metadata','declaration','legacyMediaId','legacyKeys','released','source','associations']);id(w.id);if(ids.has(w.id)||!Array.isArray(w.released))throw Error();ids.add(w.id);if(w.source)mediaSource(w.source);if(w.associations){if(!Array.isArray(w.associations))throw Error();for(const a of w.associations)association(a,true)}if(w.metadata)metadata(w.metadata);if(w.declaration)declaration(w.declaration);if(!w.metadata&&!w.declaration)throw Error();if(w.legacyMediaId)id(w.legacyMediaId)
    if(w.legacyKeys){exact(w.legacyKeys,['create','content','confirm','declaration']);for(const key of Object.values(w.legacyKeys))if(typeof key!=='string'||!(/^[A-Za-z0-9._:-]{8,128}$/).test(key))throw Error()}
    for(const t of w.released){exact(t,['key','epoch','snapshot']);if(typeof t.key!=='string'||!Number.isSafeInteger(t.epoch)||t.epoch<1||typeof t.snapshot!=='string')throw Error()}
   }
   if(b.activeWorkspaceId!==null&&!ids.has(b.activeWorkspaceId))throw Error();for(const r of b.legacyRefs){exact(r,['key','hash','workspaceId']);if(typeof r.key!=='string'||!ids.has(r.workspaceId))throw Error();sha(r.hash)}return b
  }catch{throw Error('Media recovery source damaged; original raw retained')}
 }
 private change<T>(fn:(b:BundleRecord)=>T|Promise<T>):Promise<T>{return this.locked(async()=>{const b=this.raw(),before=canonical(b),v=await fn(b);if(canonical(b)!==before)this.disk.setItem(this.storageKey,JSON.stringify(b));return copy(v)})}
 private record(b:BundleRecord,wid:string){const w=b.workspaces.find(w=>w.id===wid);if(!w)throw Error('Unknown local media workspace');return w}
 private resource(wid:string,kind:MediaKind){return `media:${this.role}:${wid}:${kind}`}
 private path(w:WorkspaceRecord,kind:MediaKind,mediaId?:string){if(kind==='create')return '/media/uploads';if(kind==='declaration'){if(!w.declaration)throw Error('Missing declaration source');return `/admin/questions/${w.declaration.questionId}/media/${w.declaration.mediaId}/review-confirmations`}if(!mediaId)throw Error('Missing media receipt');return `/media/${mediaId}/${kind}`}
 private validateResult(w:WorkspaceRecord,c:Command,result:Json){
  if(!result||typeof result!=='object'||Array.isArray(result))throw Error('Invalid media receipt')
  const r=result as Body,k=kindOf(c)
  if(k==='create'){exact(r,['media_id','upload_url','upload_method','expires_at','max_bytes']);id(r.media_id);if(r.upload_url!==`/api/v1/media/${r.media_id}/content`||r.upload_method!=='PUT'||typeof r.max_bytes!=='number'||r.max_bytes<1||(w.legacyMediaId&&w.legacyMediaId!==r.media_id))throw Error('Create receipt source mismatch')}
  else if(k==='declaration'){const d=w.declaration!;exact(r,['question_id','version','media_id','sha256','actor_id','expires_at']);if(r.question_id!==d.questionId||r.version!==d.version||r.media_id!==d.mediaId||r.sha256!==d.sha256||r.actor_id!==this.owner)throw Error('Declaration receipt source mismatch')}
  else if(k==='delete'){exact(r,['media_id','deleted']);if(r.media_id!==c.path.split('/')[2]||r.deleted!==true)throw Error('Delete receipt mismatch');return}
  else{exact(r,['media_id','mime','size_bytes','sha256','expires_at']);if(r.media_id!==c.path.split('/')[2]||r.mime!==w.metadata?.mime||r.size_bytes!==w.metadata?.size_bytes||r.sha256!==w.metadata?.sha256)throw Error('Media receipt metadata mismatch')}
  if(typeof r.expires_at!=='string'||!Number.isFinite(Date.parse(r.expires_at)))throw Error('Unknown media receipt expiry')
 }
 private build(w:WorkspaceRecord,all:Command[]):MediaWorkspace{
  const commands=all.filter(c=>c.owner===this.owner&&(['create','content','confirm','declaration','delete'] as MediaKind[]).some(k=>c.resource===this.resource(w.id,k)))
  const create=commands.find(c=>kindOf(c)==='create'&&c.result),mediaId=create?.result?(create.result as Body).media_id as string:undefined
  for(const c of commands){const k=kindOf(c),target=k==='delete'?mediaId??w.declaration?.mediaId:mediaId
   if(c.method!==(k==='content'?'PUT':'POST')||c.path!==this.path(w,k,target))throw Error('Media command path/method/source mismatch')
   const expected=k==='create'?w.metadata:k==='content'?{}:k==='confirm'?{sha256:w.metadata?.sha256}:k==='declaration'?{expected_version:w.declaration?.version,sha256:w.declaration?.sha256,confirmed:true}:{}
   if(canonical(c.body)!==canonical(expected))throw Error('Media command body differs from fixed source')
   if(k==='content'&&(!c.file||c.file.sha256!==w.metadata?.sha256||c.file.size!==w.metadata?.size_bytes))throw Error('Wrong content source fingerprint')
   if(c.result!==undefined)this.validateResult(w,c,c.result)
  }
  const active=commands.find(c=>!w.released.some(t=>same(t,c))&&['prepared','result_known','unavailable'].includes(c.phase))
  const confirmed=commands.find(c=>kindOf(c)==='confirm'&&c.result)?.result as S['MediaAssetInfo']|undefined
  return {...copy(w),commands,active,mediaId,confirmed}
 }
 async read():Promise<MediaBundle>{const b=await this.locked(async()=>copy(this.raw())),all=await this.commands.list();return {activeWorkspaceId:b.activeWorkspaceId,workspaces:b.workspaces.map(w=>this.build(w,all))}}
 async workspace(wid:string):Promise<MediaWorkspace>{const w=(await this.read()).workspaces.find(w=>w.id===wid);if(!w)throw Error('Unknown media workspace');return w}
 createWorkspace(wid:string,input:S['MediaUploadRequest'],source?:MediaSource):Promise<MediaWorkspace>{metadata(input);if(source)mediaSource(source);const m=copy(input),capturedSource=source?copy(source):undefined;return this.change(b=>{id(wid);if(b.workspaces.some(w=>w.id===wid))throw Error('Reuse existing workspace explicitly');b.workspaces.push({id:wid,metadata:m,released:[],...(capturedSource?{source:capturedSource}:{})});b.activeWorkspaceId=wid;return wid}).then(id=>this.workspace(id))}
 private prepare(wid:string,kind:MediaKind,body:Body,key?:string,file?:Command['file']):Promise<Command>{
  const capturedBody=copy(body),capturedFile=file?copy(file):undefined
  return this.locked(async()=>{
   const record=this.record(this.raw(),wid),all=await this.commands.list(),w=this.build(record,all),old=w.commands.find(c=>kindOf(c)===kind)
   if(old){if(key&&key!==old.key||canonical(old.body)!==canonical(capturedBody)||canonical(old.file??null)!==canonical(capturedFile??null))throw Error('Fixed media command cannot be replaced');return old}
   if(w.active)throw Error('Recover or explicitly release the original media command')
   const target=kind==='delete'?w.mediaId??w.declaration?.mediaId:w.mediaId
   return this.commands.prepare({key:key??w.legacyKeys?.[kind]??newIdempotencyKey(),method:kind==='content'?'PUT':'POST',path:this.path(w,kind,target),resource:this.resource(wid,kind),body:capturedBody,...(capturedFile?{file:capturedFile}:{})})
  })
 } async prepareCreate(wid:string,key?:string){const w=await this.workspace(wid);if(!w.metadata)throw Error('Upload metadata required');return this.prepare(wid,'create',w.metadata,key)}
 prepareContent(wid:string,input:SelectedMedia,key?:string):Promise<Command>{const selected={body:copy(input.body),bytes:new Uint8Array(input.bytes)};return (async()=>{
  exact(selected.body,['content_base64']);const w=await this.workspace(wid);if(!w.mediaId||!w.metadata)throw Error('Reconstruct original create receipt first')
  const encoded=btoa(Array.from(selected.bytes,b=>String.fromCharCode(b)).join(''));if(encoded!==selected.body.content_base64||await byteHash(selected.bytes)!==w.metadata.sha256||selected.bytes.length!==w.metadata.size_bytes)throw Error('Reselect original media bytes')
  return this.prepare(wid,'content',{},key,{sha256:w.metadata.sha256,size:w.metadata.size_bytes,wireFingerprint:await hash(selected.body)})
 })()}
 async prepareConfirm(wid:string,key?:string){const w=await this.workspace(wid);if(!w.mediaId||!w.metadata||!w.commands.some(c=>kindOf(c)==='content'&&c.result))throw Error('Known content receipt required');return this.prepare(wid,'confirm',{sha256:w.metadata.sha256},key)}
 prepareDeclaration(wid:string,input:DeclarationScope,key?:string):Promise<Command>{return this.prepareDeclarationLane(wid,input,key).then(value=>value.command)}
 prepareDeclarationLane(wid:string,input:DeclarationScope,key?:string):Promise<{workspaceId:string;command:Command;reused:boolean}>{
  declaration(input);id(wid);const scope=copy(input)
  return this.locked(async()=>{
   const b=this.raw(),all=await this.commands.list(),requested=b.workspaces.find(w=>w.id===wid)
   if(requested&&canonical(requested.declaration??null)!==canonical(scope))throw Error('Declaration source immutable')
   // Ordinary ensure is not a fresh intent: even an ACK that appeared after a
   // caller read must reuse history. A new UUID cannot authorize another POST.
   for(const record of b.workspaces){
    if(canonical(record.declaration??null)!==canonical(scope))continue
    const w=this.build(record,all),pending=w.commands.find(c=>kindOf(c)==='declaration'&&!w.released.some(t=>same(t,c))&&['prepared','unavailable','result_known','acked'].includes(c.phase))
    if(pending){if(key&&key!==pending.key)throw Error('Existing declaration lane requires original key');return {workspaceId:w.id,command:pending,reused:true}}
   }
   if(requested){
    const w=this.build(requested,all),existing=w.commands.find(c=>kindOf(c)==='declaration')
    if(existing){if(w.released.some(t=>same(t,existing)))throw Error('Explicit new declaration needs a new workspace');if(key&&key!==existing.key)throw Error('Fixed media command cannot be replaced');return {workspaceId:w.id,command:existing,reused:true}}
    if(w.active)throw Error('Unresolved media command')
   }else{
    b.workspaces.push({id:wid,declaration:scope,released:[]});b.activeWorkspaceId=wid
    // Workspace metadata precedes the shared command. A failed prepare leaves
    // recoverable local metadata; HTTP is never attempted before prepare.
    this.disk.setItem(this.storageKey,JSON.stringify(b))
   }
   const record=this.record(b,wid),body:S['MediaReviewConfirmation']={expected_version:scope.version,sha256:scope.sha256,confirmed:true}
   const command=await this.commands.prepare({key:key??record.legacyKeys?.declaration??newIdempotencyKey(),method:'POST',path:this.path(record,'declaration'),resource:this.resource(wid,'declaration'),body})
   return {workspaceId:wid,command,reused:false}
  })
 } async prepareDelete(wid:string,mediaId:string,key?:string){const w=await this.workspace(wid);if(mediaId!==(w.mediaId??w.declaration?.mediaId))throw Error('Unbound delete target');return this.prepare(wid,'delete',{},key)}
 private async bound(t:Ticket){const captured=ticket(t),b=await this.read();for(const w of b.workspaces){const c=w.commands.find(c=>same(c,captured));if(c)return {w,c}}throw Error('Unknown media command scope/ticket')}
 send(t:Ticket,callback:(c:Command,body:Body)=>Promise<Json>):Promise<Command>{const captured=ticket(t);return (async()=>{const {w,c}=await this.bound(captured);if(w.released.some(r=>same(r,c)))throw Error('Original unknown command was explicitly released');return this.commands.send(c,async fixed=>{const result=await callback(fixed,fixed.body);this.validateResult(w,fixed,result);return result})})()}
 sendContent(t:Ticket,input:SelectedMedia|undefined,callback:(c:Command,body:Body)=>Promise<Json>):Promise<Command>{const captured=ticket(t),selected=input?{body:copy(input.body),bytes:new Uint8Array(input.bytes)}:undefined;return (async()=>{const {w,c}=await this.bound(captured);if(kindOf(c)!=='content'||w.released.some(r=>same(r,c)))throw Error('Unknown or released content command');return this.commands.sendFile(c,selected,async(fixed,body)=>{const result=await callback(fixed,body);this.validateResult(w,fixed,result);return result})})()}
 async ack(t:Ticket):Promise<void>{const captured=ticket(t);await this.bound(captured);await this.commands.acknowledgeStoredResult(captured)}
 async markUnavailable(t:Ticket):Promise<void>{const captured=ticket(t),{c}=await this.bound(captured);if(c.result!==undefined)return;await this.commands.mark(c,'unavailable','media_unavailable')}
 releaseUnknown(t:Ticket):Promise<void>{const captured=ticket(t);return (async()=>{const {w,c}=await this.bound(captured);if(!['prepared','unavailable'].includes(c.phase)||c.result!==undefined)throw Error('Known success must be locally acknowledged');await this.change(b=>{const target=this.record(b,w.id);if(!target.released.some(r=>same(r,c)))target.released.push(captured);return null})})()}
 /** Records only an explicit association INTENT after readable ownership/byte/lease
  * checks. Parent draft persistence is authoritative for the actual reference; this entry is never proof that the reference was saved. */
 recordAssociation(wid:string,input:MediaAssociation):Promise<void>{
  association(input);const captured=copy(input)
  return this.change(async b=>{
   const record=this.record(b,wid),w=this.build(record,await this.commands.list())
   const confirmed=w.commands.find(c=>kindOf(c)==='confirm'&&c.phase==='acked'&&c.result)?.result as S['MediaAssetInfo']|undefined
   if(!confirmed||confirmed.media_id!==captured.mediaId||confirmed.sha256!==captured.sha256||Date.parse(confirmed.expires_at)<=Date.now()||captured.observedAt>Date.now()+60000)throw Error('Current readable confirmed media is required')
   const intent:MediaAssociationIntent={...captured,phase:'intent'},values=record.associations??=[];if(!values.some(a=>canonical(a)===canonical(intent)))values.push(intent)
   return null
  }).then(()=>{})
 }
 private legacyUpload(raw:string){const v=JSON.parse(raw) as {fingerprint:string;id?:string;createKey:string;putKey:string;confirmKey:string;expires:number};exact(v,['fingerprint','id','createKey','putKey','confirmKey','expires']);const m=/^(image\/(?:png|jpeg|webp)):(\d+):([a-f0-9]{64})$/.exec(v.fingerprint);if(!m||!Number.isFinite(v.expires))throw Error('Unknown legacy upload source');const value:S['MediaUploadRequest']={purpose:'question_attachment',mime:m[1] as S['MediaUploadRequest']['mime'],size_bytes:Number(m[2]),sha256:m[3]!};metadata(value);for(const k of [v.createKey,v.putKey,v.confirmKey])if(typeof k!=='string'||!(/^[A-Za-z0-9._:-]{8,128}$/).test(k))throw Error('Unknown legacy command key');if(new Set([v.createKey,v.putKey,v.confirmKey]).size!==3)throw Error('Duplicate legacy keys');if(v.id)id(v.id);return {v,value}}
 async migrateLegacyUpload():Promise<MediaWorkspace|undefined>{const key=`media-upload:${this.owner}`,raw=this.legacy.getItem(key);if(raw===null)return undefined;const {v,value}=this.legacyUpload(raw),digest=await hash(raw);const wid=await this.change(b=>{const consumed=b.legacyRefs.find(r=>r.key===key&&r.hash===digest);if(consumed)return consumed.workspaceId;const wid=`legacy-upload-${digest.slice(0,24)}`;b.workspaces.push({id:wid,metadata:value,legacyMediaId:v.id,legacyKeys:{create:v.createKey,content:v.putKey,confirm:v.confirmKey},released:[]});b.legacyRefs.push({key,hash:digest,workspaceId:wid});if(b.activeWorkspaceId===null)b.activeWorkspaceId=wid;return wid});return this.workspace(wid)}
 async migrateLegacyDeclaration(input:DeclarationScope):Promise<MediaWorkspace|undefined>{declaration(input);const d=copy(input),key=`media-review:${this.owner}:${d.questionId}:${d.version}:${d.mediaId}:${d.sha256}`,raw=this.legacy.getItem(key);if(raw===null)return undefined;const value=JSON.parse(raw) as {key:string;expires:number};exact(value,['key','expires']);if(typeof value.key!=='string'||!(/^[A-Za-z0-9._:-]{8,128}$/).test(value.key)||!Number.isFinite(value.expires))throw Error('Invalid legacy declaration source');const digest=await hash(raw),scopeHash=await hash({key,raw}),wid=await this.change(b=>{const old=b.legacyRefs.find(r=>r.key===key&&r.hash===digest);if(old)return old.workspaceId;const wid=`legacy-declaration-${scopeHash.slice(0,24)}`;b.workspaces.push({id:wid,declaration:d,legacyKeys:{declaration:value.key},released:[]});b.legacyRefs.push({key,hash:digest,workspaceId:wid});return wid});return this.workspace(wid)}
 async migrateLegacyDeclarations(questionId?:string,version?:number):Promise<MediaWorkspace[]>{
  const prefix=`media-review:${this.owner}:`,scopes:DeclarationScope[]=[]
  for(let n=0;n<this.legacy.length;n++){
   const key=this.legacy.key(n);if(!key?.startsWith(prefix))continue
   const parts=key.slice(prefix.length).split(':');if(parts.length!==4||!(/^[1-9][0-9]*$/).test(parts[1]!))throw Error('Unknown legacy declaration key preserved')
   const scope={questionId:parts[0]!,version:Number(parts[1]),mediaId:parts[2]!,sha256:parts[3]!};declaration(scope)
   if((questionId===undefined||scope.questionId===questionId)&&(version===undefined||scope.version===version))scopes.push(scope)
  }
  const workspaces:MediaWorkspace[]=[];for(const scope of scopes){const w=await this.migrateLegacyDeclaration(scope);if(w)workspaces.push(w)}return workspaces
 }}





