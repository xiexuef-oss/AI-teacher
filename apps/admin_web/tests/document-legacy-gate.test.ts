import {webcrypto} from 'node:crypto'
import {beforeEach,expect,it,vi} from 'vitest'
import {DocumentImportActions} from '../src/document-import-actions'
import {WriteCommandStore,browserLocks} from '../src/api/write-command-store'
import {captureSessionBinding,setSession} from '../src/session'
import * as api from '../src/api/document-import'
import type {components} from '../src/api/schema'

vi.mock('../src/api/document-import',()=>({createImportJob:vi.fn(),processImportJob:vi.fn()}))
type S=components['schemas']
const prefix='document-import:legacy-owner',rawKey=prefix+':requests'
const defaults:S['DocImportDefaults']={subject:'math',answer_mode:'single_choice',source:{source_type:'self_authored',source_category:'foundation',source_name:'self authored',source_year:null,source_license:'self authored',source_url:null}}
const options:S['DocImportOptions']={server_time:'2030-01-01T00:00:00Z',creation_deadline:'2030-01-01T01:00:00Z',max_file_bytes:1000,max_job_bytes:10000,max_files:10,max_pages:10,max_candidates:50,temporary_ttl_minutes:60,file_kinds:['json'],ocr_mode:'disabled',doc_converter_available:false}
const create:S['DocImportJobCreate']={creation_deadline:options.creation_deadline,title:'new B',defaults}
const oldCreate=()=>JSON.stringify({create:{key:'legacy-create-key',body:{title:'old A',defaults}}})
const actions=()=>new DocumentImportActions(captureSessionBinding()!,()=>true)
const markers=()=>Object.keys(localStorage).filter(k=>k.startsWith('admin-document-legacy-disposition/'))
beforeEach(()=>{
 localStorage.clear();vi.restoreAllMocks();vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto)
 const tails=new Map<string,Promise<unknown>>()
 Object.defineProperty(navigator,'locks',{configurable:true,value:{request:<T>(name:string,_options:unknown,f:()=>Promise<T>)=>{const p=(tails.get(name)??Promise.resolve()).catch(()=>{}).then(f);tails.set(name,p.then(()=>{},()=>{}));return p}}})
 setSession({userId:'legacy-owner',role:'reviewer',token:'memory-only-token'})
 localStorage.setItem(prefix+':expires',String(Date.parse(options.creation_deadline)))
})
it('missing-deadline create blocks ordinary prepare and a fresh window without sending',async()=>{
 const raw=oldCreate();localStorage.setItem(rawKey,raw);const r=actions();await r.restore(options)
 await expect(r.prepare('create',create)).rejects.toThrow(/旧|legacy/)
 await expect(r.fresh(options)).rejects.toThrow(/旧|legacy/)
 expect(api.createImportJob).not.toHaveBeenCalled();expect(localStorage.getItem(rawKey)).toBe(raw)
})
it('quota on the minimal disposition preserves raw and keeps both gates closed',async()=>{
 const raw=oldCreate();localStorage.setItem(rawKey,raw);const r=actions();await r.restore(options)
 const original=Storage.prototype.setItem,spy=vi.spyOn(Storage.prototype,'setItem').mockImplementation(function(this:Storage,k,v){if(k.startsWith('admin-document-legacy-disposition/'))throw Error('quota-marker');original.call(this,k,v)})
 await expect(r.stopLegacyForNewWindow()).rejects.toThrow('quota-marker')
 expect(r.hasUnresolvedLegacy()).toBe(true);await expect(r.prepare('create',create)).rejects.toThrow()
 expect(localStorage.getItem(rawKey)).toBe(raw);expect(markers()).toEqual([]);spy.mockRestore()
})
it('a successful raw-SHA disposition survives reload without copying sensitive raw',async()=>{
 const raw=JSON.stringify({create:{key:'legacy-create-key',body:{title:'PRIVATE_TEXT',token:'PRIVATE_TOKEN',content_base64:'PRIVATE_FILE'}}});localStorage.setItem(rawKey,raw)
 const r=actions();await r.restore(options);await r.stopLegacyForNewWindow();expect(r.hasUnresolvedLegacy()).toBe(false)
 const saved=markers().map(k=>localStorage.getItem(k)).join('');expect(saved).not.toMatch(/PRIVATE_TEXT|PRIVATE_TOKEN|PRIVATE_FILE/)
 expect(markers()).toHaveLength(1);const marker=JSON.parse(localStorage.getItem(markers()[0]!)!);expect(marker.rawSha256).toMatch(/^[a-f0-9]{64}$/)
 const next=actions();await next.restore(options);expect(next.hasUnresolvedLegacy()).toBe(false);await next.fresh(options);const c=await next.prepare('create',create);expect(c.key).not.toBe('legacy-create-key');expect(localStorage.getItem(rawKey)).toBe(raw)
})
it('a changed raw invalidates the old marker immediately and after reload',async()=>{
 localStorage.setItem(rawKey,oldCreate());const r=actions();await r.restore(options);await r.stopLegacyForNewWindow()
 const changed=JSON.stringify({create:{key:'legacy-create-key',body:{title:'changed C',defaults}}});localStorage.setItem(rawKey,changed)
 expect(r.hasUnresolvedLegacy()).toBe(true);expect(()=>r.assertNoUnresolvedLegacy()).toThrow()
 const next=actions();await next.restore(options);await expect(next.prepare('create',create)).rejects.toThrow();expect(localStorage.getItem(rawKey)).toBe(changed)
})
it('unknown raw is kept and requires explicit disposition instead of parse-and-drop',async()=>{
 const raw='{UNKNOWN PRIVATE RAW';localStorage.setItem(rawKey,raw);const r=actions();await r.restore(options)
 expect(r.hasUnresolvedLegacy()).toBe(true);await expect(r.fresh(options)).rejects.toThrow()
 await r.stopLegacyForNewWindow();await r.fresh(options);expect(localStorage.getItem(rawKey)).toBe(raw)
})
it('upload without the original file fingerprint blocks a new window',async()=>{
 localStorage.setItem(rawKey,JSON.stringify({'job-a:upload:file.json':{key:'legacy-upload-key',body:{expected_revision:2,filename:'file.json',size:1,lastModified:123}}}))
 const r=actions();await r.restore(options);await expect(r.prepare('create',create)).rejects.toThrow();expect(r.hasUnresolvedLegacy()).toBe(true)
})
it('an exact validated central ACK stays authoritative without reviving old create',async()=>{
 const body={title:'old A',defaults};localStorage.setItem(rawKey,JSON.stringify({create:{key:'legacy-create-key',body}}))
 const central=new WriteCommandStore(localStorage,browserLocks(),'legacy-owner'),c=await central.prepare({key:'legacy-create-key',method:'POST',path:'/admin/import-jobs',resource:'old-doc-create',body})
 await central.recordResult(c,{id:'job-old'});await central.acknowledgeStoredResult(c)
 const r=actions();await r.restore(options);expect(r.hasUnresolvedLegacy()).toBe(false);r.assertNoUnresolvedLegacy();expect((await central.list())[0]!.phase).toBe('acked');expect(await r.store.history()).toEqual([]);expect(markers()).toEqual([])
})
it('known authority cannot authorize an old raw with a different immutable body',async()=>{
 localStorage.setItem(rawKey,oldCreate());const central=new WriteCommandStore(localStorage,browserLocks(),'legacy-owner'),c=await central.prepare({key:'legacy-create-key',method:'POST',path:'/admin/import-jobs',resource:'new-doc-create',body:{...create,title:'different'}})
 await central.recordResult(c,{id:'job-new'});await central.acknowledgeStoredResult(c)
 const r=actions();await r.restore(options);expect(r.hasUnresolvedLegacy()).toBe(true);await expect(r.prepare('create',create)).rejects.toThrow()
})
it('legal non-file legacy migration preserves its original body/key/expiry',async()=>{
 const body={expected_revision:3,candidate_ids:['candidate-a']};localStorage.setItem(rawKey,JSON.stringify({'job-a:submit':{key:'legal-submit-key',body}}))
 const r=actions();await r.restore(options);await r.selectJob({job:{id:'job-a',expires_at:options.creation_deadline},candidates:[],files:[],defaults} as unknown as S['DocImportJobDetail'])
 expect(r.hasUnresolvedLegacy()).toBe(false);expect(r.active()).toMatchObject({key:'legal-submit-key',body,path:'/admin/import-jobs/job-a/submit'});expect(r.state.expiresAt).toBe(Date.parse(options.creation_deadline));expect(markers()).toEqual([])
})
it('identity replacement while the stop lock waits cannot persist a disposition',async()=>{
 localStorage.setItem(rawKey,oldCreate());const r=actions();await r.restore(options)
 const old=navigator.locks.request.bind(navigator.locks);let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(res=>release=res),started=new Promise<void>(res=>entered=res)
 vi.spyOn(navigator.locks,'request').mockImplementation(((name:string,opt:unknown,f:()=>Promise<unknown>)=>old(name,opt as LockOptions,async()=>{if(name.startsWith('admin-document-legacy-disposition/')){entered();await gate}return f()})) as typeof navigator.locks.request)
 const stopping=r.stopLegacyForNewWindow();await started;setSession({userId:'other-owner',role:'reviewer',token:'other-token'});release();await expect(stopping).rejects.toThrow();expect(markers()).toEqual([])
})
it('legal-looking raw does not authorize a new lane before its original command is migrated',async()=>{
 localStorage.setItem(rawKey,JSON.stringify({'job-a:process':{key:'legal-process-key',body:{expected_revision:3}}}))
 const r=actions();await r.restore(options);await expect(r.prepare('create',create)).rejects.toThrow();await expect(r.fresh(options)).rejects.toThrow()
})
it('a raw replacement while the disposition lock waits cannot reuse the old confirmation',async()=>{
 const raw=oldCreate();localStorage.setItem(rawKey,raw);const r=actions();await r.restore(options)
 const old=navigator.locks.request.bind(navigator.locks);let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(res=>release=res),started=new Promise<void>(res=>entered=res)
 vi.spyOn(navigator.locks,'request').mockImplementation(((name:string,opt:unknown,f:()=>Promise<unknown>)=>old(name,opt as LockOptions,async()=>{if(name.startsWith('admin-document-legacy-disposition/')){entered();await gate}return f()})) as typeof navigator.locks.request)
 const stopping=r.stopLegacyForNewWindow();await started;const changed=raw+' ';localStorage.setItem(rawKey,changed);release();await expect(stopping).rejects.toThrow();expect(markers()).toEqual([]);expect(r.hasUnresolvedLegacy()).toBe(true);expect(localStorage.getItem(rawKey)).toBe(changed)
})
it('a raw arriving while prepare waits cannot yield an authorized new command',async()=>{
 const r=actions();await r.restore(options)
 const original=r.store.prepare.bind(r.store);let release!:()=>void,entered!:()=>void;const gate=new Promise<void>(res=>release=res),started=new Promise<void>(res=>entered=res)
 vi.spyOn(r.store,'prepare').mockImplementation(async(kind,body,jobId,key)=>{entered();await gate;return original(kind,body,jobId,key)})
 const preparing=r.prepare('create',create);await started;localStorage.setItem(rawKey,oldCreate());release();await expect(preparing).rejects.toThrow();expect(api.createImportJob).not.toHaveBeenCalled()
})
it('selecting a job preserves an exact central ACK with its original resource identity',async()=>{
 const body={expected_revision:3};localStorage.setItem(rawKey,JSON.stringify({'job-a:process':{key:'central-acked-process',body}}))
 const central=new WriteCommandStore(localStorage,browserLocks(),'legacy-owner'),c=await central.prepare({key:'central-acked-process',method:'POST',path:'/admin/import-jobs/job-a/process',resource:'original-central-resource',body})
 await central.recordResult(c,{id:'job-a'});await central.acknowledgeStoredResult(c)
 const r=actions();await r.restore(options);await r.selectJob({job:{id:'job-a',expires_at:options.creation_deadline},candidates:[],files:[],defaults} as unknown as S['DocImportJobDetail'])
 expect(r.commands.find(x=>x.key===c.key)).toMatchObject({snapshot:c.snapshot,resource:'original-central-resource',phase:'acked'});expect(localStorage.getItem(r.store.commandKey)).toBeNull()
})
it('a legal prepared central legacy command dispatches by its fixed path with its original body/key',async()=>{
 const body={expected_revision:3};localStorage.setItem(rawKey,JSON.stringify({'job-a:process':{key:'central-pending-process',body}}))
 const central=new WriteCommandStore(localStorage,browserLocks(),'legacy-owner');await central.prepare({key:'central-pending-process',method:'POST',path:'/admin/import-jobs/job-a/process',resource:'original-central-resource',body})
 const r=actions();await r.restore(options);await r.selectJob({job:{id:'job-a',expires_at:options.creation_deadline},candidates:[],files:[],defaults} as unknown as S['DocImportJobDetail'])
 vi.mocked(api.processImportJob).mockResolvedValue({id:'job-a'} as S['DocImportJobSummary']);const c=r.active()!;await r.execute(c)
 expect(api.processImportJob).toHaveBeenCalledWith('memory-only-token','job-a',body,'central-pending-process');expect((await central.list())[0]!.phase).toBe('result_known');expect(localStorage.getItem(r.store.commandKey)).toBeNull()
})
it('an unknown disposition format stays unchanged and cannot authorize a new window',async()=>{
 localStorage.setItem(rawKey,oldCreate());const r=actions();await r.restore(options);await r.stopLegacyForNewWindow();const key=markers()[0]!,unknown='{UNKNOWN MARKER';localStorage.setItem(key,unknown)
 expect(r.hasUnresolvedLegacy()).toBe(true);await expect(r.stopLegacyForNewWindow()).rejects.toThrow();await expect(r.fresh(options)).rejects.toThrow();expect(localStorage.getItem(key)).toBe(unknown)
})
