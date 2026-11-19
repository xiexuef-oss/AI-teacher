// @vitest-environment node
import { expect, test } from 'vitest'
import { WriteCommandStore } from '../src/api/write-command-store';
class Memory {
 data = new Map<string,string>(); fail = false;
 getItem(k:string) {return this.data.get(k) ?? null;}
 setItem(k:string,v:string) {if(this.fail) throw Error('quota');this.data.set(k,v);}
}
class Locks {
 private tails = new Map<string,Promise<unknown>>();
 async run<T>(name:string, action:()=>Promise<T>):Promise<T> {
  const previous=this.tails.get(name)??Promise.resolve();
  const next=previous.catch(()=>{}).then(action);this.tails.set(name,next);return next;
 }
}
const spec=(key='intent-a', body={title:'A'})=>({key,method:'POST' as const,path:'/admin/question-imports',resource:'import',body});
test('quota rejects prepare before a caller could send',async()=>{
 const disk=new Memory();disk.fail=true;const s=new WriteCommandStore(disk,new Locks(),'alice');
 await expect(s.prepare(spec())).rejects.toThrow('quota');
});
test('missing cross-tab coordinator fails closed',async()=>{
 const s=new WriteCommandStore(new Memory(),undefined,'alice');
 await expect(s.prepare(spec())).rejects.toThrow();
});
test('prepared snapshot survives restart and cannot reuse key with B',async()=>{
 const disk=new Memory(),locks=new Locks();const s=new WriteCommandStore(disk,locks,'alice');
 const a=await s.prepare(spec());const restored=new WriteCommandStore(disk,locks,'alice');
 await expect(restored.prepare(spec('intent-a',{title:'B'}))).rejects.toThrow();
 expect((await restored.list())[0]!.body).toEqual(a.body);
});
test('two tabs serialize RMW and send one persisted successful result',async()=>{
 const disk=new Memory(),locks=new Locks();const a=new WriteCommandStore(disk,locks,'alice'),b=new WriteCommandStore(disk,locks,'alice');
 const [ca,cb]=await Promise.all([a.prepare(spec()),b.prepare(spec('intent-b',{title:'B'}))]);
 expect((await a.list()).map(c=>c.epoch)).toEqual([1,2]);let calls=0;
 const send=async()=>{calls++;await Promise.resolve();return {id:'result-a'};};
 await Promise.all([a.send(ca,send),b.send(ca,send)]);
 expect(calls).toBe(1);const rows=await a.list();expect(rows[0]!.phase).toBe('result_known');expect(rows[1]!.body).toEqual(cb.body);
});
test('late A result ACK does not alter B or require HTTP',async()=>{
 const disk=new Memory(),locks=new Locks(),s=new WriteCommandStore(disk,locks,'alice');
 const input=spec();const aPromise=s.prepare(input);input.body.title='mutated';const a=await aPromise;
 expect(a.body.title).toBe('A');const b=await s.prepare(spec('intent-b',{title:'B'}));
 await s.recordResult(a,{id:'saved-a'});const reopened=new WriteCommandStore(disk,locks,'alice');
 await reopened.acknowledgeStoredResult(a);const rows=await reopened.list();expect(rows[0]!.phase).toBe('acked');expect(rows[1]).toEqual(b);
 await expect(s.recordResult({...a,epoch:b.epoch},{id:'bad'})).rejects.toThrow('Stale');
});
test('damaged bytes are preserved and every write fails closed',async()=>{
 const disk=new Memory(),s=new WriteCommandStore(disk,new Locks(),'alice');
 disk.data.set(s.storageKey,'{"v":99,"precious":"unknown"}');const before=disk.data.get(s.storageKey);
 await expect(s.prepare(spec())).rejects.toThrow('preserved');expect(disk.data.get(s.storageKey)).toBe(before);
});
test('token and raw file data never persist',async()=>{
 const disk=new Memory(),s=new WriteCommandStore(disk,new Locks(),'alice');
 expect(()=>s.prepare({...spec(),body:{nested:{access_token:'secret'}}})).toThrow('Sensitive');
 expect(()=>s.prepare({...spec(),body:{content_base64:'AQID'}})).toThrow('Sensitive');expect(disk.data.size).toBe(0);
 const c=await s.prepare(spec());expect(()=>s.recordResult(c,{token:'secret'})).toThrow('Sensitive');
});
test('result and ACK quota failures keep original evidence; GET is not ACK',async()=>{
 const disk=new Memory(),s=new WriteCommandStore(disk,new Locks(),'alice'),c=await s.prepare(spec());
 await expect(s.acknowledgeStoredResult(c)).rejects.toThrow('No persisted');const before=disk.data.get(s.storageKey);
 disk.fail=true;await expect(s.recordResult(c,{id:'a'})).rejects.toThrow('quota');expect(disk.data.get(s.storageKey)).toBe(before);
 disk.fail=false;await s.recordResult(c,{id:'a'});const known=disk.data.get(s.storageKey);disk.fail=true;
 await expect(s.acknowledgeStoredResult(c)).rejects.toThrow('quota');expect(disk.data.get(s.storageKey)).toBe(known);
});
test('timeout preserves immutable command for explicit same-key retry',async()=>{
 const s=new WriteCommandStore(new Memory(),new Locks(),'alice'),c=await s.prepare(spec());
 await expect(s.send(c,async()=>{throw Error('network');})).rejects.toThrow('network');
 expect((await s.list())[0]!.phase).toBe('prepared');
 const result=await s.send(c,async command=>{expect(command.body).toEqual(c.body);expect(command.key).toBe(c.key);return {id:'a'};});
 expect(result.phase).toBe('result_known');
});
test('file reconstructed body must match complete canonical fingerprint',async()=>{
 const wire={filename:'sample.png',content_base64:'AQID',expected_revision:2};
 const hash=async(v:unknown)=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(v,Object.keys(v as object).sort()))))].map(b=>b.toString(16).padStart(2,'0')).join('');
 const disk=new Memory(),s=new WriteCommandStore(disk,new Locks(),'alice');
 const c=await s.prepare({...spec(),file:{sha256:'a'.repeat(64),size:3,wireFingerprint:await hash(wire)}});
 expect(JSON.stringify([...disk.data.values()])).not.toContain('AQID');
 expect(await s.verifyFileBody(c,wire,'a'.repeat(64),3)).toEqual(wire);
 await expect(s.verifyFileBody(c,{...wire,content_base64:'BA=='},'a'.repeat(64),3)).rejects.toThrow('original');
});
class GateLocks extends Locks {
 entered!:()=>void;release!:()=>void;
 readonly enteredPromise=new Promise<void>(resolve=>this.entered=resolve);
 private gate=new Promise<void>(resolve=>this.release=resolve);
 blockNext=false;
 override async run<T>(name:string,action:()=>Promise<T>):Promise<T>{
  return super.run(name,async()=>{if(this.blockNext){this.blockNext=false;this.entered();await this.gate;}return action();});
 }
}
test('queued result captures ticket before external mutation A to B',async()=>{
 const disk=new Memory(),locks=new GateLocks(),s=new WriteCommandStore(disk,locks,'alice');
 const a=await s.prepare(spec()),b=await s.prepare(spec('intent-b',{title:'B'}));
 const mutable={key:a.key,epoch:a.epoch,snapshot:a.snapshot};locks.blockNext=true;
 const result=s.recordResult(mutable,{id:'result-a'});await locks.enteredPromise;
 Object.assign(mutable,{key:b.key,epoch:b.epoch,snapshot:b.snapshot});locks.release();await result;
 const rows=await s.list();expect(rows[0]!.result).toEqual({id:'result-a'});expect(rows[1]!.result).toBeUndefined();
});
test('queued ACK captures ticket before external mutation A to B',async()=>{
 const disk=new Memory(),locks=new GateLocks(),s=new WriteCommandStore(disk,locks,'alice');
 const a=await s.prepare(spec()),b=await s.prepare(spec('intent-b',{title:'B'}));
 await s.recordResult(a,{id:'a'});await s.recordResult(b,{id:'b'});
 const mutable={key:a.key,epoch:a.epoch,snapshot:a.snapshot};locks.blockNext=true;
 const ack=s.acknowledgeStoredResult(mutable);await locks.enteredPromise;Object.assign(mutable,b);locks.release();await ack;
 const rows=await s.list();expect(rows[0]!.phase).toBe('acked');expect(rows[1]!.phase).toBe('result_known');
});
test('queued send captures ticket before external mutation A to B',async()=>{
 const disk=new Memory(),locks=new GateLocks(),s=new WriteCommandStore(disk,locks,'alice');
 const a=await s.prepare(spec()),b=await s.prepare(spec('intent-b',{title:'B'}));
 const mutable={key:a.key,epoch:a.epoch,snapshot:a.snapshot};locks.blockNext=true;let sent='';
 const pending=s.send(mutable,async c=>{sent=c.key;return {id:'saved'};});await locks.enteredPromise;Object.assign(mutable,b);locks.release();await pending;
 expect(sent).toBe(a.key);expect((await s.list())[1]!.phase).toBe('prepared');
});
test('file send requires original bytes and metadata before any HTTP',async()=>{
 const disk=new Memory(),s=new WriteCommandStore(disk,new Locks(),'alice');
 const wire={filename:'sample.png',content_base64:'AQID'};
 const hash=async(v:Uint8Array)=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new Uint8Array(v)))].map(b=>b.toString(16).padStart(2,'0')).join('');
 const bytes=new Uint8Array([1,2,3]);
 const c=await s.prepare({...spec(),file:{sha256:await hash(bytes),size:3,wireFingerprint:await hash(new TextEncoder().encode(JSON.stringify(wire,Object.keys(wire).sort())))}});
 let calls=0;const callback=async()=>{calls++;return {id:'uploaded'};};
 // Dynamic invocation lets a missing production interface fail at runtime.
 const dynamicStore=s as any;
 await expect(dynamicStore.sendFile(c,undefined,callback)).rejects.toThrow();
 await expect(dynamicStore.sendFile(c,{body:wire,bytes:new Uint8Array([9,2,3])},callback)).rejects.toThrow();
 await expect(dynamicStore.sendFile(c,{body:{...wire,filename:'other.png'},bytes},callback)).rejects.toThrow();
 expect(calls).toBe(0);
 await dynamicStore.sendFile(c,{body:wire,bytes},async(command:any,body:any)=>{
  calls++;expect(command.key).toBe(c.key);expect(body).toEqual(wire);
  expect((await s.list())[0]!.phase).toBe('prepared');return {id:'uploaded'};
 });
 expect(calls).toBe(1);expect(JSON.stringify([...disk.data.values()])).not.toContain('AQID');
 await new WriteCommandStore(disk,new Locks(),'alice').sendFile(c,undefined,callback);
 expect(calls).toBe(1);await s.acknowledgeStoredResult(c);
});
test('queued mark captures ticket rather than mutable caller identity',async()=>{
 const locks=new GateLocks(),s=new WriteCommandStore(new Memory(),locks,'alice');
 const a=await s.prepare(spec()),b=await s.prepare(spec('intent-b',{title:'B'})),t={key:a.key,epoch:a.epoch,snapshot:a.snapshot};
 locks.blockNext=true;const pending=s.mark(t,'unavailable','timeout');await locks.enteredPromise;Object.assign(t,b);locks.release();await pending;
 const rows=await s.list();expect(rows[0]!.phase).toBe('unavailable');expect(rows[1]!.phase).toBe('prepared');
});
test('queued file verification captures ticket before lock is granted',async()=>{
 const locks=new GateLocks(),s=new WriteCommandStore(new Memory(),locks,'alice');const wire={content_base64:'AQID'};
 const fp=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(wire))))].map(b=>b.toString(16).padStart(2,'0')).join('');
 const a=await s.prepare({...spec(),file:{sha256:'a'.repeat(64),size:3,wireFingerprint:fp}}),b=await s.prepare(spec('intent-b',{title:'B'}));
 const t={key:a.key,epoch:a.epoch,snapshot:a.snapshot};locks.blockNext=true;
 const pending=s.verifyFileBody(t,wire,'a'.repeat(64),3);await locks.enteredPromise;Object.assign(t,b);locks.release();expect(await pending).toEqual(wire);
});
test('file send snapshots ticket bytes and body before queued work; quota blocks network',async()=>{
 const locks=new GateLocks(),disk=new Memory(),s=new WriteCommandStore(disk,locks,'alice');const wire={content_base64:'AQID'},bytes=new Uint8Array([1,2,3]);
 const hash=async(v:Uint8Array)=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new Uint8Array(v)))].map(b=>b.toString(16).padStart(2,'0')).join('');
 const descriptor={sha256:await hash(bytes),size:3,wireFingerprint:await hash(new TextEncoder().encode(JSON.stringify(wire)))};
 let calls=0;disk.fail=true;
 await expect((async()=>{const c=await s.prepare({...spec(),file:descriptor});await s.sendFile(c,{body:wire,bytes},async()=>{calls++;return {id:'a'};});})()).rejects.toThrow('quota');expect(calls).toBe(0);disk.fail=false;
 const a=await s.prepare({...spec(),file:descriptor}),b=await s.prepare(spec('intent-b',{title:'B'}));const t={key:a.key,epoch:a.epoch,snapshot:a.snapshot};locks.blockNext=true;
 const pending=s.sendFile(t,{body:wire,bytes},async(c,body)=>{calls++;expect(c.key).toBe(a.key);expect(body.content_base64).toBe('AQID');return {id:'a'};});
 await locks.enteredPromise;Object.assign(t,b);wire.content_base64='BA==';bytes[0]=9;locks.release();await pending;expect(calls).toBe(1);expect((await s.list())[1]!.phase).toBe('prepared');
});


