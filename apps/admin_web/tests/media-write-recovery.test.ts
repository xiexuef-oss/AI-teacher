import {webcrypto} from 'node:crypto'
import {beforeEach,expect,it,vi} from 'vitest'
import {MediaWriteRecovery} from '../src/media-write-recovery'
import type {components} from '../src/api/schema'
import {ApiError} from '../src/api/client'
type S=components['schemas']
const bytes=new Uint8Array([1,2,3])
const sha='039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81'
const metadata:S['MediaUploadRequest']={purpose:'question_attachment',mime:'image/png',size_bytes:3,sha256:sha}
it.each([[409, 'storage_conflict'], [503, 'storage_unavailable']] as const)(
 'storage %s retains original media command across reconstruction', async (status, code) => {
  const first = new MediaWriteRecovery('owner-a', 'reviewer')
  await first.createWorkspace('storage-retry', metadata)
  const command = await first.prepareCreate('storage-retry')
  await expect(first.send(command, async () => {
   throw new ApiError(status, code, 'Storage temporarily unavailable')
  })).rejects.toThrow(ApiError)
  const restored = new MediaWriteRecovery('owner-a', 'reviewer')
  const original = (await restored.workspace('storage-retry')).active!
  expect(original.key).toBe(command.key)
  expect(original.body).toEqual(command.body)
  expect(original.phase).toBe('prepared')
  await restored.send(original, async sent => {
   expect(sent.key).toBe(command.key)
   expect(sent.body).toEqual(metadata)
   return upload()
  })
  await restored.ack(original)
  expect((await restored.workspace('storage-retry')).active).toBeUndefined()
 })
beforeEach(()=>{vi.restoreAllMocks();localStorage.clear();sessionStorage.clear();vi.stubGlobal('crypto',webcrypto);const tails=new Map<string,Promise<unknown>>();Object.defineProperty(navigator,'locks',{configurable:true,value:{request:<T>(name:string,_opts:unknown,action:()=>Promise<T>)=>{const p=(tails.get(name)??Promise.resolve()).catch(()=>{}).then(action);tails.set(name,p.then(()=>{},()=>{}));return p}}})})
it('workspace prepare quota fails before any network can be sent',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer');const original=Storage.prototype.setItem;const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(()=>{throw Error('quota')})
 await expect(s.createWorkspace('workspace-a',metadata)).rejects.toThrow('quota');spy.mockRestore();expect(original).toBeDefined()
})
it('fixed generated create body/key restore after rebuilding instance',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer');await s.createWorkspace('workspace-a',metadata);const a=await s.prepareCreate('workspace-a')
 const restored=new MediaWriteRecovery('owner-a','reviewer');const again=await restored.prepareCreate('workspace-a');expect(again.key).toBe(a.key);expect(again.body).toEqual(metadata)
})
it('legacy original raw kept and create body exactly reconstructed with old key',async()=>{
 const raw=JSON.stringify({fingerprint:`image/png:3:${sha}`,id:'legacy-id',createKey:'legacy-create',putKey:'legacy-content',confirmKey:'legacy-confirm',expires:Date.now()+60000});sessionStorage.setItem('media-upload:owner-a',raw)
 const s=new MediaWriteRecovery('owner-a','reviewer');const w=await s.migrateLegacyUpload();expect(w).toBeDefined();const c=await s.prepareCreate(w!.id);expect(c.key).toBe('legacy-create');expect(c.body).toEqual(metadata);expect(sessionStorage.getItem('media-upload:owner-a')).toBe(raw)
})

const expiry='2030-01-01T00:00:00Z'
const upload=(media='media-a')=>({media_id:media,upload_url:`/api/v1/media/${media}/content`,upload_method:'PUT' as const,expires_at:expiry,max_bytes:1024})
const info=(media='media-a')=>({media_id:media,mime:'image/png' as const,size_bytes:3,sha256:sha,expires_at:expiry})
async function created(s:MediaWriteRecovery,wid='workspace-a',media='media-a'){
 await s.createWorkspace(wid,metadata);const c=await s.prepareCreate(wid);await s.send(c,async()=>upload(media));await s.ack(c);return c
}
it('content same bytes only; no base64 persisted; known result can ACK without original file',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer');await created(s)
 const c=await s.prepareContent('workspace-a',{body:{content_base64:'AQID'},bytes});let calls=0
 await expect(s.sendContent(c,{body:{content_base64:'CQID'},bytes:new Uint8Array([9,2,3])},async()=>{calls++;return info()})).rejects.toThrow('original')
 expect(calls).toBe(0);await s.sendContent(c,{body:{content_base64:'AQID'},bytes},async()=>{calls++;return info()})
 const restored=new MediaWriteRecovery('owner-a','reviewer');await restored.sendContent(c,undefined,async()=>{calls++;return info()});expect(calls).toBe(1);await restored.ack(c)
 expect((await restored.workspace('workspace-a')).active).toBeUndefined();expect(localStorage.getItem(s.storageKey)).not.toContain('AQID');expect(localStorage.getItem(s.commands.storageKey)).not.toContain('AQID')
})
it('confirm declaration and delete are exact object bodies, all known results pure local ACK',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer');await created(s);const content=await s.prepareContent('workspace-a',{body:{content_base64:'AQID'},bytes});await s.sendContent(content,{body:{content_base64:'AQID'},bytes},async()=>info());await s.ack(content)
 const confirm=await s.prepareConfirm('workspace-a');expect(confirm.body).toEqual({sha256:sha});await s.send(confirm,async()=>info());await s.ack(confirm)
 const scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha};const declared=await s.prepareDeclaration('declaration-a',scope);expect(declared.body).toEqual({expected_version:2,sha256:sha,confirmed:true});await s.send(declared,async()=>({question_id:scope.questionId,version:2,media_id:'media-a',sha256:sha,actor_id:'owner-a',expires_at:expiry}));await s.ack(declared)
 const remove=await s.prepareDelete('workspace-a','media-a');expect(remove.body).toEqual({});await s.send(remove,async()=>({media_id:'media-a',deleted:true}));await s.ack(remove)
 expect((await s.workspace('workspace-a')).commands.map(c=>c.phase)).toEqual(['acked','acked','acked','acked'])
})
it('legacy three original keys recover then ACK cannot revive via retained raw',async()=>{
 const raw=JSON.stringify({fingerprint:`image/png:3:${sha}`,id:'legacy-id',createKey:'legacy-create',putKey:'legacy-content',confirmKey:'legacy-confirm',expires:Date.now()+60000});sessionStorage.setItem('media-upload:owner-a',raw)
 const s=new MediaWriteRecovery('owner-a','reviewer'),w=(await s.migrateLegacyUpload())!;expect(w.mediaId).toBeUndefined();expect(w.legacyMediaId).toBe('legacy-id')
 await expect(s.prepareContent(w.id,{body:{content_base64:'AQID'},bytes})).rejects.toThrow('create receipt')
 const c=await s.prepareCreate(w.id);await s.send(c,async()=>upload('legacy-id'));await s.ack(c)
 const put=await s.prepareContent(w.id,{body:{content_base64:'AQID'},bytes});expect(put.key).toBe('legacy-content');await s.sendContent(put,{body:{content_base64:'AQID'},bytes},async()=>info('legacy-id'));await s.ack(put)
 const confirm=await s.prepareConfirm(w.id);expect(confirm.key).toBe('legacy-confirm');await s.send(confirm,async()=>info('legacy-id'));await s.ack(confirm)
 const reopened=new MediaWriteRecovery('owner-a','reviewer');const again=(await reopened.migrateLegacyUpload())!;expect(again.id).toBe(w.id);expect(again.active).toBeUndefined();let calls=0;await reopened.send(await reopened.prepareCreate(w.id),async()=>{calls++;return upload('legacy-id')});expect(calls).toBe(0);expect(sessionStorage.getItem('media-upload:owner-a')).toBe(raw)
})
it('legacy declaration enum reconstructs only original source and consumes retained key',async()=>{
 const scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha},key=`media-review:owner-a:question-a:2:media-a:${sha}`,raw=JSON.stringify({key:'declaration-key',expires:Date.now()+60000});sessionStorage.setItem(key,raw)
 const s=new MediaWriteRecovery('owner-a','reviewer'),all=await s.migrateLegacyDeclarations();expect(all).toHaveLength(1);const c=await s.prepareDeclaration(all[0]!.id,scope);expect(c.key).toBe('declaration-key');expect(c.body).toEqual({expected_version:2,sha256:sha,confirmed:true})
 await s.send(c,async()=>({question_id:'question-a',version:2,media_id:'media-a',sha256:sha,actor_id:'owner-a',expires_at:expiry}));await s.ack(c);const restored=(await new MediaWriteRecovery('owner-a','reviewer').migrateLegacyDeclarations())[0]!;expect(restored.active).toBeUndefined();expect(sessionStorage.getItem(key)).toBe(raw)
 await expect(s.prepareDeclaration(all[0]!.id,{...scope,version:3})).rejects.toThrow('immutable')
})
it('legacy migration quota/unknown fields preserve raw without prepared HTTP',async()=>{
 const key='media-upload:owner-a',raw=JSON.stringify({fingerprint:`image/png:3:${sha}`,createKey:'legacy-create',putKey:'legacy-content',confirmKey:'legacy-confirm',expires:0});sessionStorage.setItem(key,raw);const s=new MediaWriteRecovery('owner-a','reviewer')
 const original=Storage.prototype.setItem,spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k===s.storageKey)throw Error('quota');original.call(this,k,v)})
 await expect(s.migrateLegacyUpload()).rejects.toThrow('quota');spy.mockRestore();expect(sessionStorage.getItem(key)).toBe(raw);expect(localStorage.getItem(s.storageKey)).toBeNull();expect(await s.commands.list()).toHaveLength(0)
 sessionStorage.setItem(key,JSON.stringify({...JSON.parse(raw),bytes:'potential-private-image'}));await expect(s.migrateLegacyUpload()).rejects.toThrow('preserved');expect(localStorage.getItem(s.storageKey)).toBeNull()
})
it('TTL unknown released old workspace and late success cannot claim new active workspace',async()=>{
 const a=new MediaWriteRecovery('owner-a','reviewer'),b=new MediaWriteRecovery('owner-a','reviewer');await a.createWorkspace('old-a',metadata);const old=await a.prepareCreate('old-a');await a.markUnavailable(old);await a.releaseUnknown(old)
 await b.createWorkspace('new-b',metadata);const current=await b.prepareCreate('new-b');await a.commands.recordResult(old,upload() as never)
 const read=await a.read();expect(read.activeWorkspaceId).toBe('new-b');expect(read.workspaces.find(w=>w.id==='old-a')?.active).toBeUndefined();expect(read.workspaces.find(w=>w.id==='new-b')?.active?.key).toBe(current.key)
 expect((await new MediaWriteRecovery('owner-a','admin').read()).workspaces).toHaveLength(0);expect((await new MediaWriteRecovery('owner-b','reviewer').read()).workspaces).toHaveLength(0)
})
it('wrong receipt media/source rejected without binding; raw quota at ACK keeps known result',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer');await s.createWorkspace('workspace-a',metadata);const c=await s.prepareCreate('workspace-a');await s.send(c,async()=>upload());const original=Storage.prototype.setItem,spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k===s.commands.storageKey&&v.includes('"phase":"acked"'))throw Error('quota');original.call(this,k,v)})
 await expect(s.ack(c)).rejects.toThrow('quota');expect((await s.workspace('workspace-a')).active?.phase).toBe('result_known');spy.mockRestore();await s.ack(c)
 const put=await s.prepareContent('workspace-a',{body:{content_base64:'AQID'},bytes});await expect(s.sendContent(put,{body:{content_base64:'AQID'},bytes},async()=>info('wrong-id'))).rejects.toThrow('mismatch');expect((await s.workspace('workspace-a')).active?.phase).toBe('prepared')
})
it('two coordinated tabs prepare one immutable create intent for the same workspace',async()=>{
 const a=new MediaWriteRecovery('owner-a','reviewer'),b=new MediaWriteRecovery('owner-a','reviewer');await a.createWorkspace('shared-workspace',metadata)
 const [first,second]=await Promise.all([a.prepareCreate('shared-workspace'),b.prepareCreate('shared-workspace')]);expect(first.key).toBe(second.key);expect((await a.workspace('shared-workspace')).commands).toHaveLength(1)
})
it('slow legacy migration must not steal active workspace created meanwhile',async()=>{
 const raw=JSON.stringify({fingerprint:`image/png:3:${sha}`,createKey:'legacy-create',putKey:'legacy-content',confirmKey:'legacy-confirm',expires:0});sessionStorage.setItem('media-upload:owner-a',raw)
 let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(r=>release=r),started=new Promise<void>(r=>entered=r),original=crypto.subtle.digest.bind(crypto.subtle)
 const spy=vi.spyOn(crypto.subtle,'digest').mockImplementationOnce(async(algorithm,data)=>{entered();await gate;return original(algorithm,data)})
 const s=new MediaWriteRecovery('owner-a','reviewer'),migration=s.migrateLegacyUpload();await started;await s.createWorkspace('new-b',metadata);release();await migration;expect((await s.read()).activeWorkspaceId).toBe('new-b');spy.mockRestore()
})
it('source context is durable and immutable across recovery',async()=>{
 const source={questionId:'question-a',version:2,contextId:'component-a'},s=new MediaWriteRecovery('owner-a','reviewer')
 await s.createWorkspace('source-workspace',metadata,source);source.questionId='mutated-caller'
 const restored=await new MediaWriteRecovery('owner-a','reviewer').workspace('source-workspace');expect(restored.source).toEqual({questionId:'question-a',version:2,contextId:'component-a'})
})
async function confirmedWorkspace(s:MediaWriteRecovery,wid='workspace-a',expires=expiry){
 await created(s,wid);const put=await s.prepareContent(wid,{body:{content_base64:'AQID'},bytes});await s.sendContent(put,{body:{content_base64:'AQID'},bytes},async()=>info());await s.ack(put);const confirm=await s.prepareConfirm(wid);await s.send(confirm,async()=>({...info(),expires_at:expires}));await s.ack(confirm)
}
it('explicit association preserves original source and captures target without automatic retargeting',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer'),source={questionId:'question-a',version:2,contextId:'old-component'};await s.createWorkspace('source-a',metadata,source)
 const create=await s.prepareCreate('source-a');await s.send(create,async()=>upload());await s.ack(create);const put=await s.prepareContent('source-a',{body:{content_base64:'AQID'},bytes});await s.sendContent(put,{body:{content_base64:'AQID'},bytes},async()=>info());await s.ack(put);const confirm=await s.prepareConfirm('source-a');await s.send(confirm,async()=>info());await s.ack(confirm)
 const target={questionId:'question-b',version:3,contextId:'new-component'},evidence={target,mediaId:'media-a',sha256:sha,observedAt:Date.now()};const storing=s.recordAssociation('source-a',evidence);target.questionId='mutated-after-call';await storing
 const restored=await new MediaWriteRecovery('owner-a','reviewer').workspace('source-a');expect(restored.source).toEqual(source);expect(restored.associations?.[0]?.target.questionId).toBe('question-b');expect(restored.associations).toHaveLength(1);expect(restored.associations?.[0]?.phase).toBe('intent')
})
it('association needs acknowledged nonexpired confirm and quota failure records no association',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer'),input={target:{questionId:'question-b',version:3,contextId:'current-component'},mediaId:'media-a',sha256:sha,observedAt:Date.now()};await created(s)
 await expect(s.recordAssociation('workspace-a',input)).rejects.toThrow('confirmed media');const put=await s.prepareContent('workspace-a',{body:{content_base64:'AQID'},bytes});await s.sendContent(put,{body:{content_base64:'AQID'},bytes},async()=>info());await s.ack(put);const confirm=await s.prepareConfirm('workspace-a');await s.send(confirm,async()=>info())
 await expect(s.recordAssociation('workspace-a',input)).rejects.toThrow('confirmed media');await s.ack(confirm)
 const original=Storage.prototype.setItem,spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k===s.storageKey)throw Error('quota');original.call(this,k,v)});await expect(s.recordAssociation('workspace-a',input)).rejects.toThrow('quota');spy.mockRestore();expect((await s.workspace('workspace-a')).associations).toBeUndefined()
 await expect(s.recordAssociation('workspace-a',{...input,mediaId:'other-media'})).rejects.toThrow('confirmed media')
})
it('expired historical success can ACK but is never proof of current association',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer');await confirmedWorkspace(s,'expired','2000-01-01T00:00:00Z');await expect(s.recordAssociation('expired',{target:{contextId:'new-component'},mediaId:'media-a',sha256:sha,observedAt:Date.now()})).rejects.toThrow('confirmed media');expect((await s.workspace('expired')).commands.every(c=>c.phase==='acked')).toBe(true)
})

it('two tabs different declaration workspace UUIDs same source must share one fixed command lane',async()=>{
 const a=new MediaWriteRecovery('owner-a','reviewer'),b=new MediaWriteRecovery('owner-a','reviewer'),scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha}
 const [first,second]=await Promise.all([a.prepareDeclaration('tab-a-uuid',scope),b.prepareDeclaration('tab-b-uuid',{sha256:sha,mediaId:'media-a',version:2,questionId:'question-a'})]);expect(first.key).toBe(second.key);expect(first.resource).toBe(second.resource);expect((await a.read()).workspaces).toHaveLength(1)
})
it('declaration lane returns actual workspace and reused status, known history needs local ACK',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer'),other=new MediaWriteRecovery('owner-a','reviewer'),scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha}
 const [a,b]=await Promise.all([s.prepareDeclarationLane('uuid-a',scope),other.prepareDeclarationLane('uuid-b',scope)])
 expect(a.workspaceId).toBe(b.workspaceId);expect([a.reused,b.reused].sort()).toEqual([false,true]);expect(a.command.key).toBe(b.command.key)
 await s.send(a.command,async()=>({question_id:'question-a',version:2,media_id:'media-a',sha256:sha,actor_id:'owner-a',expires_at:expiry}))
 const known=await other.prepareDeclarationLane('uuid-c',scope);expect(known.reused).toBe(true);expect(known.command.phase).toBe('result_known');await expect(s.releaseUnknown(known.command)).rejects.toThrow('Known success')
 await s.ack(known.command);const ordinary=await other.prepareDeclarationLane('uuid-new-after-ack',scope);expect(ordinary.reused).toBe(true);expect(ordinary.command.key).toBe(a.command.key);expect(ordinary.workspaceId).toBe(a.workspaceId);expect(ordinary.command.phase).toBe('acked');expect((await s.read()).workspaces).toHaveLength(1)
})
it('released declaration allows new intent while late old known result cannot reclaim lane',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer'),scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha},a=await s.prepareDeclarationLane('old-a',scope)
 await s.markUnavailable(a.command);await s.releaseUnknown(a.command);const b=await s.prepareDeclarationLane('new-b',scope);expect(b.command.key).not.toBe(a.command.key)
 await s.commands.recordResult(a.command,{question_id:'question-a',version:2,media_id:'media-a',sha256:sha,actor_id:'owner-a',expires_at:expiry})
 const replay=await s.prepareDeclarationLane('third-c',scope);expect(replay.workspaceId).toBe(b.workspaceId);expect(replay.command.key).toBe(b.command.key);expect((await s.workspace(a.workspaceId)).active).toBeUndefined()
})
it('different declaration source or role uses independent lane, not a global media slot',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer'),scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha},a=await s.prepareDeclarationLane('scope-a',scope)
 for(const [id,delta] of [['scope-b',{questionId:'question-b'}],['scope-c',{version:3}],['scope-d',{mediaId:'media-b'}],['scope-e',{sha256:'a'.repeat(64)}]] as const){const next=await s.prepareDeclarationLane(id,{...scope,...delta});expect(next.command.key).not.toBe(a.command.key);expect(next.reused).toBe(false)}
 const admin=await new MediaWriteRecovery('owner-a','admin').prepareDeclarationLane('admin-a',scope);expect(admin.command.key).not.toBe(a.command.key);expect(admin.command.resource).toContain('media:admin:')
})
it('declaration release quota retains old lane and prepare storage quota sends nothing',async()=>{
 const s=new MediaWriteRecovery('owner-a','reviewer'),scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha},a=await s.prepareDeclarationLane('original-a',scope),original=Storage.prototype.setItem
 const spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k===s.storageKey)throw Error('quota');original.call(this,k,v)})
 await expect(s.releaseUnknown(a.command)).rejects.toThrow('quota');spy.mockRestore();const retained=await s.prepareDeclarationLane('attempt-b',scope);expect(retained.command.key).toBe(a.command.key);expect(retained.reused).toBe(true)
 const other=new MediaWriteRecovery('owner-b','reviewer'),quota=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k===other.commands.storageKey)throw Error('quota-prepare');original.call(this,k,v)})
 await expect(other.prepareDeclarationLane('new-owner',scope)).rejects.toThrow('quota-prepare');quota.mockRestore();expect(await other.commands.list()).toHaveLength(0)
})
it('stale tab read before A finishes cannot create a second POST after A ACK',async()=>{
 const a=new MediaWriteRecovery('owner-a','reviewer'),b=new MediaWriteRecovery('owner-a','reviewer'),scope={questionId:'question-a',version:2,mediaId:'media-a',sha256:sha}
 // B ordinary entry sees no history, then pauses before its atomic prepare.
 expect((await b.read()).workspaces).toHaveLength(0)
 let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(r=>release=r),ready=new Promise<void>(r=>entered=r);let posts=0
 const waiting=(async()=>{entered();await gate;const lane=await b.prepareDeclarationLane('stale-tab-b',scope);if(!lane.reused)await b.send(lane.command,async()=>{posts++;return {question_id:'question-a',version:2,media_id:'media-a',sha256:sha,actor_id:'owner-a',expires_at:expiry}});return lane})()
 await ready
 const first=await a.prepareDeclarationLane('first-tab-a',scope)
 await a.send(first.command,async()=>{posts++;return {question_id:'question-a',version:2,media_id:'media-a',sha256:sha,actor_id:'owner-a',expires_at:expiry}});await a.ack(first.command)
 release();const resumed=await waiting
 expect(resumed.reused).toBe(true);expect(resumed.command.phase).toBe('acked');expect(resumed.command.key).toBe(first.command.key);expect(resumed.workspaceId).toBe(first.workspaceId);expect(posts).toBe(1)
})
