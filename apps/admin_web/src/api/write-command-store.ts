export type Json = null|boolean|number|string|Json[]|{[k:string]:Json};
export type Body = {[k:string]:Json};
export interface StoragePort {getItem(k:string):string|null;setItem(k:string,v:string):void}
export interface ExclusiveLock {run<T>(name:string,action:()=>Promise<T>):Promise<T>}
export function browserLocks():ExclusiveLock|undefined {
 if(!globalThis.navigator?.locks)return undefined;
 return {async run<T>(name:string,action:()=>Promise<T>):Promise<T>{return await navigator.locks.request(name,{mode:'exclusive'},action);}};
}
export interface FileReference {sha256:string;size:number;wireFingerprint:string}
export interface Spec<B extends Body=Body> {key:string;method:'POST'|'PUT'|'PATCH'|'DELETE';path:string;resource:string;body:B;file?:FileReference}
export interface Ticket {key:string;epoch:number;snapshot:string}
export interface Command<B extends Body=Body> extends Spec<B>,Ticket {owner:string;phase:'prepared'|'result_known'|'acked'|'unavailable'|'rejected';createdAt:number;result?:Json;error?:string}
function capture(t:Ticket):Ticket {return Object.freeze({key:t.key,epoch:t.epoch,snapshot:t.snapshot});}
interface Bundle {v:1;owner:string;epoch:number;commands:Command[]}
const forbidden=/^(authorization|access_token|refresh_token|token|content_base64|base64|bytes|file_path|filepath)$/i;
function json(v:unknown):asserts v is Json {
 if(v===null||typeof v==='string'||typeof v==='boolean')return;
 if(typeof v==='number'&&Number.isFinite(v))return;
 if(Array.isArray(v)){v.forEach(json);return;}
 if(typeof v!=='object'||Object.getPrototypeOf(v)!==Object.prototype)throw Error('Plain JSON required');
 for(const [k,child]of Object.entries(v)){if(forbidden.test(k))throw Error('Sensitive material must stay in memory');json(child);}
}
function canonical(v:Json):string {
 if(v!==null&&typeof v==='object'){
  if(Array.isArray(v))return `[${v.map(canonical).join(',')}]`;
  return `{${Object.keys(v).sort().map(k=>`${JSON.stringify(k)}:${canonical(v[k]!)}`).join(',')}}`;
 }
 return JSON.stringify(v);
}
function clone<T>(v:T):T{return JSON.parse(JSON.stringify(v)) as T;}
function keys(v:object,allowed:string[]){if(Object.keys(v).some(k=>!allowed.includes(k)))throw Error('Unknown fields preserved');}
async function hash(v:Json):Promise<string>{return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(canonical(v))))].map(b=>b.toString(16).padStart(2,'0')).join('');}
function identity(c:Spec,owner:string):Body{return {owner,key:c.key,method:c.method,path:c.path,resource:c.resource,body:c.body,...(c.file?{file:{...c.file}}:{})};}
function validate(c:Spec){
 if(!/^[A-Za-z0-9._:-]{8,128}$/.test(c.key)||!['POST','PUT','PATCH','DELETE'].includes(c.method)||!/^\/[A-Za-z0-9/_:.%-]+$/.test(c.path)||/\/{2}|(?:^|\/)\.{1,2}(?:\/|$)/.test(c.path)||!c.resource)throw Error('Invalid command identity');
 json(c.body);if(!c.body||Array.isArray(c.body)||typeof c.body!=='object')throw Error('Object body required');
 if(c.file){keys(c.file,['sha256','size','wireFingerprint']);if(!/^[a-f0-9]{64}$/.test(c.file.sha256)||!/^[a-f0-9]{64}$/.test(c.file.wireFingerprint)||!Number.isSafeInteger(c.file.size)||c.file.size<0)throw Error('Invalid file reference');}
}
/** Owner bundle contains historical commands only, never current GET projections.
 * Durable epoch identifies a command, not a login. Controller owns token/UI guards. */
export class WriteCommandStore {
 readonly storageKey:string;
 constructor(private readonly disk:StoragePort,private readonly locks:ExclusiveLock|undefined,readonly owner:string){
  if(!owner||owner.length>256)throw Error('Invalid owner');this.storageKey=`admin-write/v1/${encodeURIComponent(owner)}`;
 }
 private locked<T>(suffix:string,action:()=>Promise<T>):Promise<T>{
  if(!this.locks)return Promise.reject(Error('Cross-tab coordination unavailable; fail closed'));
  return this.locks.run(this.storageKey+suffix,action);
 }
 private async read():Promise<Bundle>{
  const raw=this.disk.getItem(this.storageKey);if(raw===null)return {v:1,owner:this.owner,epoch:0,commands:[]};
  try{
   const b=JSON.parse(raw) as Bundle;keys(b,['v','owner','epoch','commands']);
   if(b.v!==1||b.owner!==this.owner||!Number.isSafeInteger(b.epoch)||b.epoch<0||!Array.isArray(b.commands))throw Error('Unknown bundle');
   const used=new Set<string>(),epochs=new Set<number>();
   for(const c of b.commands){
    keys(c,['key','method','path','resource','body','file','owner','epoch','snapshot','phase','createdAt','result','error']);validate(c);
    if(c.owner!==this.owner||used.has(c.key)||epochs.has(c.epoch)||!Number.isSafeInteger(c.epoch)||c.epoch<1||c.epoch>b.epoch||!Number.isSafeInteger(c.createdAt)||!['prepared','result_known','acked','unavailable','rejected'].includes(c.phase)||c.snapshot!==await hash(identity(c,this.owner)))throw Error('Damaged command');
    used.add(c.key);epochs.add(c.epoch);if('result'in c)json(c.result);
    if(['result_known','acked'].includes(c.phase)&&!('result'in c))throw Error('Missing result');
    if(c.error!==undefined&&!/^[a-z_]{1,64}$/.test(c.error))throw Error('Unknown error');
   }
   return b;
  }catch{throw Error('Recovery data damaged or unsupported; original bytes preserved');}
 }
 private change<T>(action:(b:Bundle)=>Promise<T>):Promise<T>{return this.locked('',async()=>{const b=await this.read();const value=await action(b);this.disk.setItem(this.storageKey,JSON.stringify(b));return clone(value);});}
 list():Promise<Command[]>{return this.locked('',async()=>clone((await this.read()).commands));}
 /** Retention cleanup only: caller persists its non-content expiry tombstone first.
  * This forgets local payloads, never cancels HTTP or changes a server outcome.
  * Missing tickets are idempotent; any conflicting existing identity aborts all. */
 discardValidated(tickets:readonly Ticket[]):Promise<void>{
  const selected=tickets.map(capture);
  return this.locked('',async()=>{
   const b=await this.read(),remove=new Set<string>();
   for(const t of selected){
    if(!/^[A-Za-z0-9._:-]{8,128}$/.test(t.key)||!Number.isSafeInteger(t.epoch)||t.epoch<1||!/^[a-f0-9]{64}$/.test(t.snapshot))throw Error('Invalid retention ticket');
    const c=b.commands.find(c=>c.key===t.key);
    if(c){if(c.epoch!==t.epoch||c.snapshot!==t.snapshot)throw Error('Stale command snapshot');remove.add(c.key);}
   }
   if(remove.size){b.commands=b.commands.filter(c=>!remove.has(c.key));this.disk.setItem(this.storageKey,JSON.stringify(b));}
  });
 }
 prepare<B extends Body>(spec:Spec<B>):Promise<Command<B>>{
  validate(spec);const captured=clone(spec);
  return this.change(async b=>{
   const snapshot=await hash(identity(captured,this.owner)),old=b.commands.find(c=>c.key===captured.key);
   if(old){if(old.snapshot!==snapshot)throw Error('Key belongs to a different immutable request');return old as Command<B>;}
   const c:Command<B>={...captured,owner:this.owner,epoch:++b.epoch,snapshot,phase:'prepared',createdAt:Date.now()};b.commands.push(c);return c;
  });
 }
 private command(b:Bundle,t:Ticket):Command{
  const c=b.commands.find(c=>c.key===t.key);if(!c||c.epoch!==t.epoch||c.snapshot!==t.snapshot)throw Error('Stale command snapshot');return c;
 }
 recordResult(ticket:Ticket,result:Json):Promise<Command>{
  const t=capture(ticket);
  json(result);const captured=clone(result);
  return this.change(async b=>{const c=this.command(b,t);if(c.phase==='rejected')throw Error('Already rejected');if('result'in c&&canonical(c.result!)!==canonical(captured))throw Error('Conflicting historical result');c.result=captured;if(c.phase!=='acked')c.phase='result_known';return c;});
 }
 /** Only validated persisted success; needs neither HTTP nor file nor a current GET. */
 acknowledgeStoredResult(ticket:Ticket):Promise<Command>{const t=capture(ticket);return this.change(async b=>{const c=this.command(b,t);if(!['result_known','acked'].includes(c.phase)||!('result'in c))throw Error('No persisted successful result');c.phase='acked';return c;});}
 mark(ticket:Ticket,phase:'rejected'|'unavailable',error:string):Promise<Command>{
  const t=capture(ticket);
  if(!/^[a-z_]{1,64}$/.test(error))return Promise.reject(Error('Symbolic error only'));
  return this.change(async b=>{const c=this.command(b,t);if('result'in c)throw Error('Cannot downgrade known history');c.phase=phase;c.error=error;return c;});
 }
 /** Full generated file body remains in memory only. Caller computes actual byte digest. */
 async verifyFileBody(ticket:Ticket,completeBody:unknown,sha256:string,size:number):Promise<Body>{
  const t=capture(ticket);
  const body=JSON.parse(JSON.stringify(completeBody)) as Body;
  return this.locked('',async()=>{const c=this.command(await this.read(),t);if(!c.file||c.file.sha256!==sha256||c.file.size!==size||c.file.wireFingerprint!==await hash(body))throw Error('Reselect original file and exact metadata');return clone(body);});
 }
 /** File body/bytes and ticket are captured synchronously before waiting for locks.
  * A stored success returns without a file. Raw bytes and base64 never enter disk. */
 sendFile<R extends Json>(ticket:Ticket,file:{body:Body;bytes:Uint8Array}|undefined,
   send:(command:Command,body:Body)=>Promise<R>):Promise<Command>{
  const t=capture(ticket);
  const selected=file?{body:clone(file.body),bytes:new Uint8Array(file.bytes)}:undefined;
  return this.locked(`/send/${encodeURIComponent(t.key)}`,async()=>{
   const c=await this.locked('',async()=>clone(this.command(await this.read(),t)));
   if(['result_known','acked'].includes(c.phase))return c;
   if(c.phase==='rejected'||!c.file||!selected)throw Error('Reselect original file before sending');
   const byteDigest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',selected.bytes))]
     .map(b=>b.toString(16).padStart(2,'0')).join('');
   if(c.file.sha256!==byteDigest||c.file.size!==selected.bytes.length||
      c.file.wireFingerprint!==await hash(selected.body))throw Error('Reselect original bytes and exact wire body');
   const result=await send(c,clone(selected.body));
   return this.recordResult(t,result);
  });
 }
 /** Command Web Lock spans send. Bundle lock covers only short storage mutations.
  * Each tab rechecks persisted result after obtaining the command lock. */
 send<R extends Json>(ticket:Ticket,send:(c:Command)=>Promise<R>):Promise<Command>{
  const t=capture(ticket);
  return this.locked(`/send/${encodeURIComponent(t.key)}`,async()=>{
   const c=await this.locked('',async()=>clone(this.command(await this.read(),t)));
   if(['result_known','acked'].includes(c.phase))return c;
   if(c.phase==='rejected'||c.file)throw Error('Explicit reconciliation or file reconstruction required');
   const result=await send(c);return this.recordResult(t,result);
  });
 }
}


