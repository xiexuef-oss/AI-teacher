<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch, shallowRef, computed } from 'vue'
import * as api from '../api/document-import'
import {onBeforeRouteLeave} from 'vue-router'
import { handleUnauthorized } from '../api/guard'
import type { components } from '../api/schema'
import { useSession,captureSessionBinding,isCurrentSessionBinding } from '../session'
import {type Body,type Command} from '../api/write-command-store'
import {DocumentImportActions} from '../document-import-actions'
import type {DocumentState,DocumentBodies,DocumentKind} from '../document-write-recovery'
import {ApiError} from '../api/client'
import MathText from '../components/MathText.vue'
import QuestionEditor from '../components/QuestionEditor.vue'
import type { EditorDetail, EditorForm } from '../editing'
import { formFromDetail } from '../editing'
import { expireImportRecovery } from '../import-recovery'
type S = components['schemas']
const session = useSession()
const options = ref<S['DocImportOptions']>()
const jobs = ref<S['DocImportJobSummary'][]>([])
const detailOwner=ref<string|null>(null)
const detail = ref<S['DocImportJobDetail']>()
const busy = ref(false), error = ref(''), notice = ref(''), preview = ref('')
const title = ref(''), sourceName = ref(''), license = ref('')
const subject = ref<S['Subject']>('math'), mode = ref<S['AnswerMode']>('single_choice')
const sourceType = ref<S['AdminImportSource']['source_type']>('self_authored')
const category = ref<S['SourceCategory']>('foundation')
const sourceYear = ref<number | null>(null), sourceUrl = ref('')
const editors = ref<Array<S['DocImportCandidateInput'] & { json: string; question_id: string | null; warnings: string[]; error: S['DocImportItemError'] | null; structuredDraft?: EditorForm; structuredValid?: boolean; editorOpen?: boolean; editorEpoch?: number }>>([])
const editorInputSerial=ref(0),documentSourceConflict=ref(false)
let draftHydrating=false,documentMounted=true,draftQueue:Promise<void>=Promise.resolve()
const workspaces=shallowRef<Array<{workspace:string;jobId?:string;expired?:boolean}>>([])
const recovery=shallowRef<DocumentImportActions>(),localState=shallowRef<DocumentState>(),history=shallowRef<Command[]>([])
let draftGeneration=0,editBaseRevision:number|undefined
const branchConflict=ref(false),durableSerial=ref(0),draftState=computed(()=>editorInputSerial.value>durableSerial.value?'仅内存未保存':branchConflict.value?'独立分支已保存，待明确选择':localState.value?.draft?'本机草稿已保存':'尚未编辑')
const branchPreview=ref(''),headPreview=ref('')
function syncRecovery(){const r=recovery.value;if(!r?.current())return;workspaces.value=Object.keys(localStorage).filter(k=>k.startsWith(`admin-document-state/v1/${encodeURIComponent(r.binding.userId)}/`)).map(k=>JSON.parse(localStorage.getItem(k)!) as DocumentState).filter(s=>s.owner===r.binding.userId&&s.role===r.binding.role).map(s=>({workspace:s.workspace,jobId:s.jobId,expired:s.expired}));localState.value=r.state;history.value=[...r.commands];documentSourceConflict.value=!!detail.value&&(r.state.draft?.value.phase==='candidates'||editorInputSerial.value>0)&&editBaseRevision!==detail.value.job.revision}

const batch = ref<S['DocImportBatchResult']>()
const answerLocations = ref<Record<number, string>>({})
const storage = () => `document-import:${session.session?.userId}`
async function run(action: () => Promise<void>) {
  if (busy.value) return
  const binding=captureSessionBinding()
  busy.value = true; error.value = ''
  try { await action() } catch (e) {
    if (isCurrentSessionBinding(binding)&&!handleUnauthorized(e,binding)) error.value = e instanceof Error ? e.message : String(e)
  } finally { busy.value = false }
}
async function show(value:S['DocImportJobDetail'],binding:ReturnType<typeof captureSessionBinding>,switchJob=false){
 if(!isCurrentSessionBinding(binding)||!recovery.value?.current())return
 const r=recovery.value
 if(switchJob||r.state.jobId!==value.job.id){await r.selectJob(value);if(!r.current())return}
 else if(!r.state.expired){await r.store.tightenExpiry(Date.parse(value.job.expires_at));await r.refresh()}
 if(!r.current())return
 if(detail.value?.job.id===value.job.id&&detail.value.job.revision>value.job.revision)return
 const changing=detail.value?.job.id!==value.job.id
 detailOwner.value=binding.userId;detail.value=value
 if(changing){draftGeneration=r.state.generation;editBaseRevision=r.state.draft?.value.phase==='candidates'?r.state.draft.baseRevision:value.job.revision}
 if(changing||!editorInputSerial.value){draftHydrating=true;const draft=r.state.draft?.value;editors.value=draft?.phase==='candidates'&&Array.isArray(draft.items)?JSON.parse(JSON.stringify(draft.items)):value.candidates.map(c=>({...c,json:c.payload?JSON.stringify(c.payload,null,2):''}));draftHydrating=false}
 syncRecovery()
}
async function loadOwnedJob(id:string,switchJob=false){const binding=captureSessionBinding(),r=recovery.value;if(!binding||!r)throw Error('缺少身份');const value=await api.getImportJob(binding.token,id);if(r!==recovery.value||!r.current())return;await show(value,binding,switchJob)}
async function refresh(){if(detail.value)await loadOwnedJob(detail.value.job.id)}
async function open(id:string){await run(async()=>{await draftQueue;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入仅在内存，请先保存后切换任务。');const binding=captureSessionBinding(),old=recovery.value,serial=editorInputSerial.value;if(!binding)throw Error('缺少身份');const guard=()=>documentMounted&&old===recovery.value&&isCurrentSessionBinding(binding)&&editorInputSerial.value===serial;const value=await api.getImportJob(binding.token,id);if(!guard())throw Error('等待期间输入或身份变化，未切换任务。');const next=new DocumentImportActions(binding,()=>documentMounted);await next.selectJob(value);if(!guard())throw Error('等待期间输入变化，未切换任务。');recovery.value=next;editorInputSerial.value=0;durableSerial.value=0;await show(value,binding);hydrate()})}
async function sendCommand(c:Command,file?:{body:S['DocImportUpload'];bytes:Uint8Array}){
 const r=recovery.value!;let known:Command|null
 try{known=await r.execute(c,file)}catch(e){if(r.current()&&r===recovery.value){if(e instanceof ApiError&&e.status===422&&e.code==='validation_error'&&!c.path.endsWith('/submit'))await r.store.mark(c,'rejected',e.code);else if(e instanceof ApiError&&e.status===404)await r.store.mark(c,'unavailable',e.code);await r.refresh();syncRecovery()}throw e}
 if(!known||r!==recovery.value||!r.current())return
 // Receipt is historical. Current job is obtained separately; newer local inputs are untouched.
 try{await r.store.ack(known)}finally{if(r===recovery.value&&r.current()){await r.refresh();if(r===recovery.value&&r.current())syncRecovery()}}
 if(r!==recovery.value||!r.current())return
 if(known.path.endsWith('/submit')&&known.result)batch.value=known.result as unknown as S['DocImportBatchResult']
 if(r.state.jobId)await loadOwnedJob(r.state.jobId)
}
async function intent<K extends Exclude<DocumentKind,'upload'>>(kind:K,body:DocumentBodies[K]){const r=recovery.value;if(!r?.current())throw Error('本机恢复尚未初始化');await draftQueue;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入未落盘，未发送。');if(branchConflict.value)throw Error('请先比较并明确采用独立分支');if(r.active())throw Error('请明确恢复、确认或停止原操作，原body/key保持不变。');const c=await r.prepare(kind,body);syncRecovery();await sendCommand(c)}
async function create(){if(!title.value.trim()||!sourceName.value.trim()||!license.value.trim()){error.value='请填写任务名称、来源和使用依据。';return}await run(async()=>{
 const r=recovery.value;if(!r?.state)throw Error('本机恢复尚未安全初始化，未发送。');r.assertNoUnresolvedLegacy();if(r.state.jobId)throw Error('原工作区已绑定任务，请明确建立新创建窗口。');const body:S['DocImportJobCreate']={creation_deadline:new Date(r.state.initialDeadline!).toISOString(),title:title.value,defaults:{subject:subject.value,answer_mode:mode.value,source:{source_type:sourceType.value,source_category:category.value,source_name:sourceName.value,source_year:sourceYear.value||null,source_license:license.value,source_url:sourceUrl.value||null}}}
 // Preserve original wire spelling supplied by the server for a new creation window.
 if(options.value&&Date.parse(options.value.creation_deadline)===r.state.initialDeadline)body.creation_deadline=options.value.creation_deadline
 await intent('create',body)
})}
async function chooseWorkspace(id:string){await run(async()=>{await draftQueue;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入未落盘，请勿离开。');const old=recovery.value!,serial=editorInputSerial.value,next=new DocumentImportActions(old.binding,()=>documentMounted);await next.choose(id);if(old!==recovery.value||!next.current()||editorInputSerial.value!==serial)throw Error('输入或身份已变化，未切换工作区。');recovery.value=next;detail.value=undefined;draftHydrating=true;editors.value=[];draftHydrating=false;editorInputSerial.value=0;durableSerial.value=0;hydrate();syncRecovery();if(next.state.jobId&&!next.state.expired)await loadOwnedJob(next.state.jobId)})}
async function retryLocalDraft(){const r=recovery.value;if(!r)return;const serial=editorInputSerial.value,guard=()=>r===recovery.value&&r.current()&&editorInputSerial.value===serial;try{await draftQueue;if(detail.value)await writeCandidateDraft(JSON.parse(JSON.stringify(editors.value)),guard);else{const value:Body={phase:'creation',title:title.value,sourceName:sourceName.value,license:license.value,sourceYear:sourceYear.value,sourceUrl:sourceUrl.value,subject:subject.value,mode:mode.value,sourceType:sourceType.value,category:category.value};const result=await r.saveDraft(value,undefined,draftGeneration,guard);if('conflict'in result)branchConflict.value=true;else draftGeneration=result.generation;syncRecovery()}if(guard()){durableSerial.value=serial;clearDurableIsolated(r)}}catch(e){if(guard())error.value='最新输入仅在内存保留。'+String(e)}}
async function newWorkspace(){await run(async()=>{await draftQueue;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入仅在内存，请勿离开。');if(recovery.value?.active())throw Error('请先明确确认已知结果或停止原未知操作。');const binding=captureSessionBinding(),old=recovery.value,serial=editorInputSerial.value;if(!binding)throw Error('缺少身份');const guard=()=>documentMounted&&old===recovery.value&&isCurrentSessionBinding(binding)&&editorInputSerial.value===serial;const o=await api.importOptions(binding.token);if(!guard())throw Error('输入或身份已变化，未切换创建窗口。');await old?.stopLegacyForNewWindow();if(!guard())throw Error('输入或身份已变化，未切换创建窗口。');const r=new DocumentImportActions(binding,()=>documentMounted);await r.fresh(o);if(!guard())throw Error('输入或身份已变化，未切换创建窗口。');recovery.value=r;options.value=o;detail.value=undefined;editors.value=[];editorInputSerial.value=0;durableSerial.value=0;draftGeneration=0;editBaseRevision=undefined;syncRecovery();notice.value='已明确开启新创建窗口；旧命令历史保持原key/body。'})}
async function retry(c:Command){await run(async()=>{if(c.file)throw Error('请在原操作下重选同字节原文件。');await sendCommand(c)})}
async function acknowledge(c:Pick<Command,'key'|'snapshot'|'epoch'>){await run(async()=>{const r=recovery.value!;await r.store.ack(c);if(r!==recovery.value||!r.current())return;await r.refresh();if(r!==recovery.value||!r.current())return;syncRecovery();notice.value='已确认本机历史回执；不代表当前任务状态。'})}
async function stop(c:Command){await run(async()=>{const r=recovery.value!;await r.store.release(c);if(r!==recovery.value||!r.current())return;await r.refresh();if(r!==recovery.value||!r.current())return;syncRecovery();notice.value='已保留未知记录并停止本机重试；未取消服务端操作。'})}
async function retryFile(c:Command,event:Event){const file=(event.target as HTMLInputElement).files?.[0];if(!file)return;await run(async()=>{const bytes=await fileBytes(file);await sendCommand(c,{body:{...c.body,content_base64:await base64(file)} as S['DocImportUpload'],bytes})})}
function fileBytes(file:File):Promise<Uint8Array>{return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(new Uint8Array(reader.result as ArrayBuffer));reader.onerror=()=>reject(Error('读取文件失败'));reader.readAsArrayBuffer(file)})}
function base64(file: File): Promise<string> {
  return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]!); reader.onerror = () => reject(new Error('读取文件失败')); reader.readAsDataURL(file) })
}
async function upload(event:Event){const files=Array.from((event.target as HTMLInputElement).files||[]);if(!detail.value||!options.value||!files.length)return;const limits=options.value;if(files.length+detail.value.files.length>limits.max_files||files.some(f=>f.size>limits.max_file_bytes)||files.reduce((n,f)=>n+f.size,detail.value.files.reduce((n,f)=>n+f.size_bytes,0))>limits.max_job_bytes){error.value='所选文件数量或大小超过任务限额。';return}
 await run(async()=>{const r=recovery.value!;for(const file of files){if(!r.current()||r!==recovery.value)throw Error('上下文已变化');if(r.active())throw Error('请先处理原未决操作');const body:S['DocImportUpload']={expected_revision:detail.value!.job.revision,filename:file.name,content_base64:await base64(file)},bytes=await fileBytes(file);if(!r.current())return;const c=await r.store.prepareUpload(body,bytes);await r.refresh();syncRecovery();await sendCommand(c,{body,bytes})}})
}
async function change(action:'process'|'cancel'){await run(async()=>{await intent(action,{expected_revision:detail.value!.job.revision})})}
function pairAnswer(index: number) {
  const selection = answerLocations.value[index]
  if (!selection) return
  const [file_id, page] = selection.split(':')
  const item = editors.value[index]!
  if (!file_id || !page || !detail.value?.files.some(f => f.id === file_id && f.pages.some(p => p.number === Number(page)))) return
  if (!item.locations.some(l => l.file_id === file_id && l.page === Number(page))) item.locations.push({ file_id, page: Number(page), block: null })
  item.confirmed = false
  notice.value = '已记录人工配对的答案原文位置；请自行校对答案 JSON，系统未填入答案。'
}
function canEditStructured(index: number): boolean {
  if (!candidateBody(index)) return false
  try { formFromDetail(editorDetail(index)); return true } catch { return false }
}
function editorDetail(index: number): EditorDetail {
  const body = candidateBody(index)!
  return { ...body.question, id: '', version: 0, answer_mode: body.answer_mode,
    knowledge: body.question.knowledge.map(code => ({code})) }
}
function editStructured(index: number, form: EditorForm, body: import('../editing').EditorBody | null) {
  const item = editors.value[index]!
  item.structuredDraft = form; item.structuredValid = body !== null; item.confirmed = false
  const original = candidateBody(index)
  if (body && original) {
    const { expected_version: _version, ...question } = body
    const value: S['AdminQuestionImport'] = { ...original, question }
    item.json = JSON.stringify(value, null, 2); item.payload = value; item.title = question.title; item.text = question.content.stem
  }
}
function syncCandidateText(index: number) {
  const item = editors.value[index]!
  const body = candidateBody(index)
  if (body) {
    body.question.title = item.title; body.question.content.stem = item.text
    item.json = JSON.stringify(body, null, 2)
  }
  resetStructured(index)
}
function resetStructured(index: number) {
  const item = editors.value[index]!
  item.confirmed = false; item.structuredValid = undefined; item.structuredDraft = undefined; item.editorEpoch = (item.editorEpoch || 0) + 1
}
function candidateBody(index: number): S['AdminQuestionImport'] | null {
  try {
    const body = JSON.parse(editors.value[index]!.json)
    return body && typeof body === 'object' && body.source && body.question ? body as S['AdminQuestionImport'] : null
  } catch { return null }
}
function metadata(index: number, field: 'subject' | 'answer_mode' | keyof S['AdminImportSource'], event: Event) {
  const body = candidateBody(index)
  if (!body) return
  const value = (event.target as HTMLInputElement).value
  if (field === 'subject') body.subject = value as S['Subject']
  else if (field === 'answer_mode') body.answer_mode = value as S['AnswerMode']
  else Object.assign(body.source, { [field]: field === 'source_year' ? (value ? Number(value) : null) : field === 'source_url' ? (value || null) : value })
  const item = editors.value[index]!
  item.json = JSON.stringify(body, null, 2); item.payload = body; resetStructured(index)
}
function skeleton(index: number) {
  const item = editors.value[index]!
  const defaults = detail.value!.defaults
  const payload: S['AdminQuestionImport'] = { ...defaults, source: { ...defaults.source }, question: {
    title: item.title, difficulty: 1, grade: null,
    content: { stem: item.text, options: [], blanks: [], subquestions: [], attachments: [], data_tables: [], safety: null, proof: null },
    answer: { value: null, equivalence_rules: {}, units: {} },
    teaching: { concept: null, hints: [], concept_rephrase: null, option_analysis: {}, visual: null, leak_markers: [] },
    solutions: [], knowledge: [], rubric: {},
  } }
  item.json = JSON.stringify(payload, null, 2); resetStructured(index)
}
async function download(file:S['DocImportFile']){await run(async()=>{const r=recovery.value,value=detail.value,binding=captureSessionBinding();if(!r||!value||!binding)return;const current=()=>documentMounted&&r===recovery.value&&r.current()&&isCurrentSessionBinding(binding)&&detail.value===value;const content=await api.getImportOriginal(binding.token,value.job.id,file.id);if(!current())return;const bytes=Uint8Array.from(atob(content.content_base64),c=>c.charCodeAt(0)),url=URL.createObjectURL(new Blob([bytes],{type:content.media_type})),link=document.createElement('a');try{if(!current())return;link.href=url;link.download=content.filename;document.body.appendChild(link);link.click()}finally{link.remove();URL.revokeObjectURL(url)}})}
function split(index: number) {
  const item = editors.value[index]!
  const at = item.text.indexOf('\n')
  if (at < 0) { error.value = '请在切分位置插入换行；按首个换行拆分。'; return }
  editors.value.splice(index + 1, 0, { ...item, id: null, title: item.title + '（拆分）', text: item.text.slice(at + 1), payload: null, json: '', confirmed: false })
  item.text = item.text.slice(0, at); item.payload = null; item.json = ''; item.confirmed = false
}
function merge(index: number) {
  const item = editors.value[index]!, next = editors.value[index + 1]
  if (!next || qualification(item) || qualification(next)) return
  item.text += '\n' + next.text; item.locations.push(...next.locations); item.confirmed = false; item.payload = null; item.json = ''
  editors.value.splice(index + 1, 1)
}
function move(index: number, delta: number) {
  const to = index + delta
  if (to < 0 || to >= editors.value.length) return
  const item = editors.value.splice(index, 1)[0]!
  editors.value.splice(to, 0, item)
}
function qualification(item:typeof editors.value[number]){return detail.value?.candidates.find(c=>c.id===item.id)?.question_id??item.question_id}
function candidateRequestItems():S['DocImportCandidateInput'][] {const imported=detail.value!.candidates.filter(c=>c.question_id),ids=new Set(imported.map(c=>c.id));const items:S['DocImportCandidateInput'][]=editors.value.filter(c=>!ids.has(c.id!)).map(c=>({id:c.id,title:c.title,text:c.text,locations:c.locations,payload:c.json.trim()?JSON.parse(c.json) as S['AdminQuestionImport']:null,confirmed:c.confirmed}));for(const c of imported){const index=detail.value!.candidates.indexOf(c);items.splice(Math.min(index,items.length),0,{id:c.id,title:c.title,text:c.text,locations:c.locations,payload:c.payload,confirmed:c.confirmed})}return items}
async function save(){await run(async()=>{const r=recovery.value!,job=detail.value!.job;await draftQueue;if(documentSourceConflict.value)throw Error('草稿来源不同，请比较后明确采用当前来源。');if(editors.value.some(c=>!qualification(c)&&c.structuredValid===false))throw Error('请先补完整可视化表单中的输入，再保存校对。');const items=candidateRequestItems();if(items.some(c=>c.confirmed&&!c.payload))throw Error('确认前须填写完整题目 JSON（包含题面、答案、教学与来源）。');await intent('candidates',{expected_revision:editBaseRevision??job.revision,items});if(r!==recovery.value||!r.current())return;notice.value='校对历史结果已确认；后续编辑继续保留。'})}
async function submit(failedOnly=false){await run(async()=>{const job=detail.value!.job;const failed=new Set(batch.value?.items.filter(i=>i.status==='failed').map(i=>i.candidate_id)||detail.value!.candidates.filter(c=>c.error).map(c=>c.id));const body:S['DocImportSubmit']={expected_revision:job.revision,candidate_ids:detail.value!.candidates.filter(c=>c.confirmed&&!c.question_id&&(!failedOnly||failed.has(c.id))).map(c=>c.id).slice(0,50)};if(!body.candidate_ids.length)throw Error('请先保存已确认的候选题。');await intent('submit',body)})}
async function image(file:string,page:number,mediaIndex?:number){await run(async()=>{const r=recovery.value,value=detail.value,binding=captureSessionBinding();if(!r||!value||!binding)return;const result=await api.getImportPreview(binding.token,value.job.id,file,page,mediaIndex);if(!documentMounted||r!==recovery.value||!r.current()||!isCurrentSessionBinding(binding)||detail.value!==value)return;if(result.media_type!=='image/png')throw Error('仅允许安全 PNG 预览');preview.value=`data:image/png;base64,${result.content_base64}`})}
let timer: ReturnType<typeof setInterval> | undefined
type CandidateEditors=typeof editors.value
function draftBody(rows:CandidateEditors):Body{return {phase:'candidates',items:JSON.parse(JSON.stringify(rows))}}
async function writeCandidateDraft(snapshot:CandidateEditors,guard:()=>boolean,adopt=false,rejectConflict=false):Promise<void>{
 const r=recovery.value!,source=detail.value,generation=adopt?r.state.generation:draftGeneration,old=r.state.draft
 const base=editBaseRevision??(old?.value.phase==='candidates'?old.baseRevision:source?.job.revision),adoptedRevision=source?.job.revision
 const current=()=>guard()&&r===recovery.value&&r.current()&&(!adopt||detail.value===source&&detail.value?.job.revision===adoptedRevision)
 if(!current())throw Error('候选上下文已变化')
 const value=draftBody(snapshot),result=adopt||(old&&old.value.phase!=='candidates')?await r.store.adoptDraft(value,adopt?adoptedRevision:base,generation,current):await r.saveDraft(value,base,generation,current)
 if(!('conflict'in result)&&r===recovery.value&&r.current()&&detail.value?.job.id===source?.job.id){
  draftGeneration=result.generation
  editBaseRevision=adopt?adoptedRevision:base
 }
 if(!current())throw Error('保存后候选来源或输入已变化，未应用旧选择。')
 await r.refresh();if(!current())throw Error('读取后候选来源或输入已变化，未应用旧选择。')
 syncRecovery()
 if('conflict'in result){branchConflict.value=true;if(rejectConflict)throw Error('双方草稿已保存为独立分支，请明确比较；当前输入未覆盖主草稿。');return}
 branchConflict.value=false;syncRecovery()
}
watch(editors,()=>{
 if(draftHydrating||!detail.value)return
 const serial=++editorInputSerial.value,binding=captureSessionBinding(),id=detail.value.job.id,rows=editors.value,snapshot:CandidateEditors=JSON.parse(JSON.stringify(rows)),r=recovery.value
 if(!binding||!r)return
 const guard=()=>documentMounted&&r===recovery.value&&r.current()&&detailOwner.value===binding.userId&&detail.value?.job.id===id&&editors.value===rows&&editorInputSerial.value===serial&&!r.state.expired
 draftQueue=draftQueue.catch(()=>{}).then(async()=>{if(!guard())return;try{await writeCandidateDraft(snapshot,guard);if(guard()){durableSerial.value=serial;clearDurableIsolated(r)}}catch(e){if(guard())error.value='候选输入仅在页面内存保留，请勿退出。'+String(e)}})
},{deep:true,flush:'sync'})
// The attachment callback uses the same authoritative document draft; no secondary cache can ACK it.
async function persistCandidateDraft(index:number,form:EditorForm,body:import('../editing').EditorBody|null,context:{isCurrent:()=>boolean}):Promise<void>{
 const binding=captureSessionBinding(),id=detail.value?.job.id,item=editors.value[index],rows=editors.value,serial=editorInputSerial.value,r=recovery.value
 if(!binding||!id||!item?.id||!r)throw Error('缺少真实任务与候选来源。')
 if(r.state.draft?.value.phase==='candidates'&&r.state.draft.baseRevision!==detail.value!.job.revision)throw Error('候选草稿来源不同，请明确采用当前来源后关联附件。')
 const guard=()=>documentMounted&&context.isCurrent()&&r===recovery.value&&r.current()&&detailOwner.value===binding.userId&&detail.value?.job.id===id&&editors.value===rows&&editors.value[index]===item&&editorInputSerial.value===serial&&!r.state.expired
 if(!guard())throw Error('候选、输入或任务留存来源已变化，附件未关联。')
 const snapshot:CandidateEditors=JSON.parse(JSON.stringify(rows)),target=snapshot[index]!
 target.structuredDraft=JSON.parse(JSON.stringify(form));target.structuredValid=body!==null;target.confirmed=false
 const original=candidateBody(index)
 if(body&&original){const {expected_version:_version,...question}=body;const value:S['AdminQuestionImport']={...original,question};target.json=JSON.stringify(value,null,2);target.payload=value;target.title=question.title;target.text=question.content.stem}
 await draftQueue;if(!guard())throw Error('候选输入在等待中变化，附件未关联。')
 await writeCandidateDraft(snapshot,guard,false,true)
}
function selectionLease(){const r=recovery.value!,serial=editorInputSerial.value,rows=editors.value,source=detail.value,revision=source?.job.revision;return {r,source,rows,serial,guard:()=>documentMounted&&r===recovery.value&&r.current()&&editorInputSerial.value===serial&&editors.value===rows&&detail.value===source&&detail.value?.job.revision===revision}}
async function adoptDocumentSource(){const {r,rows,serial,guard}=selectionLease();if(!r||!detail.value)return;try{await draftQueue;if(!guard())return;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入尚未落盘，请勿覆盖。');await writeCandidateDraft(JSON.parse(JSON.stringify(rows)),guard,true);if(!guard())return;durableSerial.value=serial;clearDurableIsolated(r);syncRecovery();headPreview.value=JSON.stringify(r.state.draft,null,2);notice.value='已备份原来源并明确采用当前任务来源。'}catch(e){if(guard())error.value=String(e)}}
async function useCurrentCandidates(){await run(async()=>{const {r,source,guard}=selectionLease();await draftQueue;if(!guard()||!source)return;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入尚未落盘');const rows=source.candidates.map(c=>({...c,json:c.payload?JSON.stringify(c.payload,null,2):''})),state=await r.store.adoptDraft(draftBody(rows),source.job.revision,r.state.generation,guard);if(!guard())return;r.state=state;await r.refresh();if(!guard())return;syncRecovery();hydrate();headPreview.value=JSON.stringify(state.draft,null,2)})}
async function loadBranch(id:string){await run(async()=>{const {r,guard}=selectionLease();await draftQueue;if(!guard())return;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入仅在内存，未载入分支。');await r.refresh();if(!guard())return;syncRecovery();const b=r.state.branches.find(b=>b.id===id);if(!b)throw Error('分支不存在');headPreview.value=JSON.stringify(r.state.draft,null,2);branchPreview.value=JSON.stringify(b,null,2)})}
async function adoptBranch(id:string){await run(async()=>{const {r,guard}=selectionLease();await draftQueue;if(!guard())return;if(editorInputSerial.value>durableSerial.value)throw Error('最新输入尚未落盘');const state=await r.store.adoptBranch(id,r.state.generation,guard);if(!guard())return;r.state=state;await r.refresh();if(!guard())return;syncRecovery();hydrate();headPreview.value=JSON.stringify(r.state.draft,null,2);notice.value='已明确载入独立分支，原主草稿已备份。'})}
function hydrate(){branchConflict.value=false;draftGeneration=recovery.value?.state.generation??0;editBaseRevision=recovery.value?.state.draft?.baseRevision;const value=recovery.value?.state.draft?.value;if(!value)return;draftHydrating=true;try{if(value.phase==='candidates'&&Array.isArray(value.items))editors.value=JSON.parse(JSON.stringify(value.items));else if(value.phase==='creation'){title.value=String(value.title??'');sourceName.value=String(value.sourceName??'');license.value=String(value.license??'');sourceYear.value=typeof value.sourceYear==='number'?value.sourceYear:null;sourceUrl.value=String(value.sourceUrl??'');subject.value=value.subject as S['Subject'];mode.value=value.mode as S['AnswerMode'];sourceType.value=value.sourceType as S['AdminImportSource']['source_type'];category.value=value.category as S['SourceCategory']}}finally{draftHydrating=false}}
watch([title,sourceName,license,sourceYear,sourceUrl,subject,mode,sourceType,category],()=>{const r=recovery.value;if(draftHydrating||!r||detail.value)return;const serial=++editorInputSerial.value;const value:Body={phase:'creation',title:title.value,sourceName:sourceName.value,license:license.value,sourceYear:sourceYear.value,sourceUrl:sourceUrl.value,subject:subject.value,mode:mode.value,sourceType:sourceType.value,category:category.value};const guard=()=>r===recovery.value&&r.current()&&editorInputSerial.value===serial;draftQueue=draftQueue.catch(()=>{}).then(async()=>{if(!guard())return;try{const result=await r.saveDraft(value,undefined,draftGeneration,guard);syncRecovery();if('conflict'in result){branchConflict.value=true;if(guard()){durableSerial.value=serial;clearDurableIsolated(r)};return}draftGeneration=result.generation;if(guard()){durableSerial.value=serial;clearDurableIsolated(r)}}catch(e){if(guard())error.value='创建输入仅在内存保留，请勿退出。'+String(e)}})},{flush:'sync'})
// Identity replacement removes the old projection; unpersisted text stays in private owner/role/workspace memory entries.
interface IsolatedDraft{expiresAt:number;owner:string;role:'reviewer'|'admin';workspace?:string;rows:CandidateEditors;source?:S['DocImportJobDetail'];creation:Body;generation:number;base?:number;serial:number;durable:number}
const isolatedDrafts=shallowRef<Record<string,IsolatedDraft>>({}),isolatedNotice=computed(()=>Object.keys(isolatedDrafts.value).length>0),restorableIsolated=computed(()=>Object.entries(isolatedDrafts.value).filter(([,draft])=>draft.owner===session.session?.userId&&draft.role===session.session?.role))
const isolatedKey=(owner:string,role:string,workspace:string|undefined)=>JSON.stringify([owner,role,workspace??null])
function removeIsolated(key:string){const next={...isolatedDrafts.value};delete next[key];isolatedDrafts.value=next}
function clearDurableIsolated(r:DocumentImportActions){if(r===recovery.value&&r.current()&&editorInputSerial.value===durableSerial.value)removeIsolated(isolatedKey(r.binding.userId,r.binding.role,r.state.workspace))}
watch(()=>session.session,()=>{
 const r=recovery.value;if(r?.current())return
 if(r&&editorInputSerial.value>durableSerial.value){const saved:IsolatedDraft={expiresAt:r.state?.expiresAt??Date.now(),owner:r.binding.userId,role:r.binding.role,workspace:r.state?.workspace,rows:JSON.parse(JSON.stringify(editors.value)),source:detail.value?JSON.parse(JSON.stringify(detail.value)):undefined,creation:{title:title.value,sourceName:sourceName.value,license:license.value,sourceYear:sourceYear.value,sourceUrl:sourceUrl.value,subject:subject.value,mode:mode.value,sourceType:sourceType.value,category:category.value},generation:draftGeneration,base:editBaseRevision,serial:editorInputSerial.value,durable:durableSerial.value};isolatedDrafts.value={...isolatedDrafts.value,[isolatedKey(saved.owner,saved.role,saved.workspace)]:saved}}
 draftHydrating=true;recovery.value=undefined;detail.value=undefined;detailOwner.value=null;editors.value=[];preview.value='';batch.value=undefined;jobs.value=[];options.value=undefined;history.value=[];localState.value=undefined;workspaces.value=[];title.value='';sourceName.value='';license.value='';sourceUrl.value='';sourceYear.value=null;branchPreview.value='';headPreview.value='';error.value='';notice.value='身份已变化，请重新载入当前身份工作区；原身份草稿和命令保留。';editorInputSerial.value=0;durableSerial.value=0;branchConflict.value=false;draftHydrating=false
},{flush:'sync'})
async function restoreIsolated(key:string){await run(async()=>{const saved=isolatedDrafts.value[key],binding=captureSessionBinding();if(!saved||!binding||binding.userId!==saved.owner||binding.role!==saved.role||!saved.workspace)throw Error('仅原身份可明确恢复隔离内存输入。');const next=new DocumentImportActions(binding,()=>documentMounted);await next.choose(saved.workspace);if(next.state.expired||Date.now()>=saved.expiresAt){removeIsolated(key);throw Error('原固定留存期限已到，不恢复过期隔离正文。')}if(!isCurrentSessionBinding(binding)||isolatedDrafts.value[key]!==saved||!documentMounted)return;recovery.value=next;detail.value=saved.source;detailOwner.value=binding.userId;draftHydrating=true;editors.value=JSON.parse(JSON.stringify(saved.rows));const c=saved.creation;title.value=String(c.title??'');sourceName.value=String(c.sourceName??'');license.value=String(c.license??'');sourceUrl.value=String(c.sourceUrl??'');sourceYear.value=typeof c.sourceYear==='number'?c.sourceYear:null;subject.value=c.subject as S['Subject'];mode.value=c.mode as S['AnswerMode'];sourceType.value=c.sourceType as S['AdminImportSource']['source_type'];category.value=c.category as S['SourceCategory'];editorInputSerial.value=saved.serial;durableSerial.value=saved.durable;draftGeneration=saved.generation;editBaseRevision=saved.base;draftHydrating=false;syncRecovery();notice.value='已明确恢复原身份隔离输入；未落盘内容仍须本机保存。'})}
onMounted(()=>run(async()=>{
 const binding=captureSessionBinding();if(!binding)throw Error('缺少身份')
 const value=await api.importOptions(binding.token);if(!isCurrentSessionBinding(binding)||!documentMounted)return;options.value=value
 const r=new DocumentImportActions(binding,()=>documentMounted);recovery.value=r
 // Legacy expiry is handled only for its original namespace. New scoped text has its own fixed TTL.
 expireImportRecovery(binding.userId)
 await r.restore(value);if(!r.current())return;syncRecovery();hydrate()
 const listed=await api.listImportJobs(binding.token);if(!r.current()||r!==recovery.value)return;jobs.value=listed.items
 const id=r.state.jobId??localStorage.getItem(storage()+':job');if(id)await loadOwnedJob(id)
 timer=setInterval(()=>{for(const [key,draft]of Object.entries(isolatedDrafts.value))if(Date.now()>=draft.expiresAt)removeIsolated(key);const r=recovery.value;if(!r?.current())return;void r.refresh().then(()=>{if(r!==recovery.value||!r.current())return;syncRecovery();if(r.state.expired){detail.value=undefined;draftHydrating=true;editors.value=[];draftHydrating=false;batch.value=undefined;preview.value='';notice.value='原固定留存期已到；原结果状态保留为最小记录。'}}).catch(e=>{if(r===recovery.value&&r.current())error.value=String(e)});if(!busy.value&&['queued','processing'].includes(detail.value?.job.status||''))void run(refresh)},2500)
}))
onBeforeRouteLeave(async()=>{await draftQueue;if(editorInputSerial.value>durableSerial.value){error.value='最新输入仅在内存，未离开当前工作区。';return false}return true})
onUnmounted(() => { documentMounted=false; if (timer) clearInterval(timer) })
</script>

<template>
  <main class="page">
    <RouterLink to="/">返回审核队列</RouterLink> · <RouterLink to="/import">单题 JSON 导入</RouterLink>
    <h1>文档导入工作台</h1><p v-if="isolatedNotice" role="alert">原身份最新输入尚未落盘，仅在隔离内存保留；不要关闭页面，可切回原身份明确恢复。</p><button v-for="[key,draft] in restorableIsolated" :key="key" data-testid="doc-restore-isolated" @click="restoreIsolated(key)">明确恢复原身份隔离内存输入 · {{ draft.workspace }}</button><p v-if="documentSourceConflict" role="alert">旧本机草稿与当前任务来源不同，原文保留；请比较后明确选择。</p><details v-if="documentSourceConflict"><summary>比较本机来源 {{ editBaseRevision??'未知' }} 与当前任务来源 {{ detail?.job.revision }}</summary><h3>本机输入</h3><pre>{{ JSON.stringify(editors,null,2) }}</pre><h3>当前服务端候选（只读观察）</h3><pre>{{ JSON.stringify(detail?.candidates,null,2) }}</pre><button data-testid="document-use-current" @click="useCurrentCandidates">备份本机并明确载入当前服务端候选</button></details><button v-if="documentSourceConflict" data-testid="document-adopt-source" @click="adoptDocumentSource">备份旧来源并明确采用当前任务草稿</button>
    <p>仅使用自编或明确授权材料；保存为待审草稿后，须由另一位审校员审核，不能自动发布。</p>
    <p v-if="options?.ocr_mode === 'disabled'">OCR 当前禁用，扫描件和图片需要人工录入。</p>
    <p v-else-if="options?.ocr_mode === 'mock'">OCR 当前为 Mock，仅测试流程，不代表真实识别。</p>
    <p v-if="options && !options.doc_converter_available">DOC 转换器不可用，请另存为 DOCX。</p>
    <p v-if="options">最多 {{ options.max_files }} 文件；单文件 {{ options.max_file_bytes }} 字节；任务 {{ options.max_job_bytes }} 字节；{{ options.max_pages }} 页；临时保存 {{ options.temporary_ttl_minutes }} 分钟。</p>
    <fieldset :disabled="!recovery"><legend>新建导入任务</legend>
      <label>任务名称 <input v-model="title" /></label>
      <label>来源 <input v-model="sourceName" /></label>
      <label>使用依据 / 授权编号 <input v-model="license" /></label>
      <label>来源类型 <select v-model="sourceType"><option value="self_authored">自编</option><option value="textbook_licensed">教材授权</option><option value="public_license">公开许可</option><option value="gaokao_licensed">试题授权</option></select></label>
      <label>分类 <select v-model="category"><option value="foundation">基础母题</option><option value="mock_exam">模拟题</option><option value="gaokao_real">高考真题（须授权核验）</option></select></label>
      <label>年份 <input v-model.number="sourceYear" type="number" /></label><label>来源网址 <input v-model="sourceUrl" /></label>
      <label>学科 <select v-model="subject"><option value="math">数学</option><option value="physics">物理</option><option value="chemistry">化学</option></select></label>
      <label>作答方式 <select v-model="mode"><option v-for="m in ['single_choice','multiple_choice','fill','written','experiment','proof']" :key="m" :value="m">{{ m }}</option></select></label>
      <button :disabled="busy" data-testid="create-job" @click="create">建立任务</button>
    </fieldset>
    <p data-testid="doc-draft-state">{{ draftState }}</p><button v-if="editorInputSerial>durableSerial" data-testid="doc-save-local" @click="retryLocalDraft">重试本机保存最新输入</button><p v-if="localState">原固定留存截止 {{ new Date(localState.expiresAt).toISOString() }}</p><button v-for="w in workspaces" :key="w.workspace" :disabled="busy" data-testid="doc-workspace" @click="chooseWorkspace(w.workspace)">查看原工作区 {{ w.jobId??w.workspace }} {{ w.expired?'已过期':'' }}</button>
    <p v-if="recovery?.legacyNotice" role="alert">{{ recovery.legacyNotice }}</p>
    <section aria-label="本机操作历史"><h2>本机操作历史</h2><p>刷新不会自动发送；当前任务观察与历史回执分开。停止重试不表示服务端取消。</p>
      <article v-for="c in history" :key="c.key"><pre>{{ c.method }} {{ c.path }} · {{ c.phase }} · {{ c.key }}
{{ JSON.stringify(c.body) }}</pre>
       <template v-if="!localState?.released.some(t=>t.snapshot===c.snapshot)">
        <button v-if="['prepared','unavailable'].includes(c.phase)&&!c.file" data-testid="doc-retry" :disabled="busy" @click="retry(c)">恢复原操作（原body/key）</button>
        <label v-if="['prepared','unavailable'].includes(c.phase)&&c.file">重选原字节文件<input data-testid="doc-reselect" type="file" :disabled="busy" @change="retryFile(c,$event)" /></label>
        <button v-if="c.phase==='result_known'" data-testid="doc-ack" :disabled="busy" @click="acknowledge(c)">确认已保存的历史结果（仅本机）</button>
        <button v-if="['prepared','unavailable'].includes(c.phase)" data-testid="doc-stop" :disabled="busy" @click="stop(c)">保留未知记录并停止本机重试</button>
       </template>
      </article><p v-for="t in localState?.tombstones" :key="t.key">已过期：{{ t.path }} · {{ t.phase }} · {{ t.key }}<button v-if="t.phase==='result_known'" @click="acknowledge(t)">确认过期历史结果（仅本机）</button></p>
      <details v-for="branch in localState?.branches" :key="branch.id"><summary>独立分支 {{ branch.id }} · 来源 {{ branch.baseRevision??'未知' }}</summary><button data-testid="doc-branch-load" @click="loadBranch(branch.id)">比较分支与当前主草稿</button><button data-testid="doc-branch-adopt" @click="adoptBranch(branch.id)">备份主草稿并明确采用此分支</button></details><pre data-testid="doc-head-preview">{{ headPreview }}</pre><pre data-testid="doc-branch-preview">{{ branchPreview }}</pre>
    </section>
    <button data-testid="doc-new-workspace" :disabled="busy" @click="newWorkspace">保留历史并明确建立新创建窗口</button><h2>恢复任务</h2><button v-for="job in jobs" :key="job.id" :disabled="busy" @click="open(job.id)">{{ job.title }} · {{ job.status }}</button>
    <p v-if="error" role="alert" class="notice error">{{ error }}</p><p role="status">{{ notice }}</p>
    <section v-if="detail">
      <h2>{{ detail.job.title }} · {{ detail.job.status }}</h2>
      <p>文件 {{ detail.job.processed_files }}/{{ detail.job.file_count }}；候选 {{ detail.job.candidate_count }}；确认 {{ detail.job.confirmed_count }}；草稿 {{ detail.job.imported_count }}；失败 {{ detail.job.failed_count }}。{{ detail.job.message }}</p>
      <p>每次最多50题，完成后请继续创建剩余已确认草稿。</p><p>刷新可恢复任务、校对内容及未完成提交。并发冲突时请刷新任务后重新核对。</p>
      <input aria-label="上传多个文件" type="file" multiple accept=".pdf,.docx,.doc,.png,.jpg,.jpeg,.json" :disabled="busy || detail.job.status !== 'uploading'" @change="upload" />
      <button :disabled="busy" @click="change('process')">开始提取 / 重试处理</button><button :disabled="busy" @click="change('cancel')">取消未开始的工作</button><button :disabled="busy" @click="run(refresh)">刷新任务</button>
      <h3>原文对照</h3><p>公式、图表、双栏与跨页切分可能不完整，请核对原文；DOCX 序号是片段，不是物理页码。</p>
      <details v-for="file in detail.files" :key="file.id"><summary>{{ file.filename }} · {{ file.status }}</summary>
        <button v-if="file.original_available" :disabled="busy" @click="download(file)">下载原文件 {{ file.filename }}</button><p v-if="file.kind === 'docx' || file.kind === 'doc'">Word 片段预览不保留完整公式与版式；纯文字片段请下载原文件回看。</p>
        <p v-for="problem in file.problems" :key="problem">{{ problem }}</p>
        <article v-for="page in file.pages" :key="page.number"><h4>页 / 片段 {{ page.number }} · {{ page.method }}</h4><pre>{{ page.text }}</pre><p>{{ page.warnings.join('；') }}</p><button v-for="(media, mediaIndex) in page.media_refs" :key="mediaIndex" :disabled="busy" @click="image(file.id, page.number, mediaIndex)">图片 {{ mediaIndex + 1 }} · {{ media }}</button><button v-if="!page.media_refs.length && file.kind !== 'docx' && file.kind !== 'doc'" :disabled="busy" @click="image(file.id, page.number)">查看 PNG 原文</button></article>
      </details><img v-if="preview" :src="preview" alt="原文 PNG 预览" />
      <h3>候选题校对</h3><p>按首个换行拆分；合并会清除结构化内容，须重新核对答案配对。完整题目 JSON 与单题导入格式一致。</p>
      <article v-for="(item, index) in editors" :key="item.id || index" class="candidate">
        <fieldset :disabled="!!qualification(item)"><legend>候选 {{ index + 1 }}</legend>
          <label>标题 <input v-model="item.title" @input="syncCandidateText(index)" /></label>
          <label>提取文字 <textarea v-model="item.text" rows="6" @input="syncCandidateText(index)" /></label>
          <button @click="skeleton(index)">按任务默认值生成可编辑题目骨架</button><p>骨架须补齐答案、选项、教学和解析；不会自动确认。可展开可视化表单编辑答案、提示与解析；原始 JSON 仍可编辑。</p>
          <p>原始位置：{{ item.locations.map(l => `${l.file_id} / ${l.page}`).join('；') }}</p><p>{{ item.warnings.join('；') }}</p>
          <section v-if="candidateBody(index)" data-testid="candidate-metadata" aria-label="逐题学科题型与来源">
            <h4>逐题学科、题型与来源</h4>
            <label>学科 <select data-testid="candidate-subject" :value="candidateBody(index)?.subject" @change="metadata(index, 'subject', $event)"><option value="math">数学</option><option value="physics">物理</option><option value="chemistry">化学</option></select></label>
            <label>题型 / 作答方式 <select data-testid="candidate-mode" :value="candidateBody(index)?.answer_mode" @change="metadata(index, 'answer_mode', $event)"><option value="single_choice">单选题</option><option value="multiple_choice">多选题</option><option value="fill">填空题</option><option value="written">解答题</option><option value="experiment">实验题</option><option value="proof">证明题</option></select></label>
            <label>来源类型 <select data-testid="candidate-source-type" :value="candidateBody(index)?.source.source_type" @change="metadata(index, 'source_type', $event)"><option value="self_authored">自编</option><option value="textbook_licensed">教材授权</option><option value="public_license">公开许可</option><option value="gaokao_licensed">高考授权</option></select></label>
            <label>来源分类 <select data-testid="candidate-category" :value="candidateBody(index)?.source.source_category" @change="metadata(index, 'source_category', $event)"><option value="foundation">基础母题</option><option value="mock_exam">模拟题</option><option value="gaokao_real">高考真题</option><option value="ai_variant">AI变式</option></select></label>
            <label>来源名称 <input data-testid="candidate-source-name" :value="candidateBody(index)?.source.source_name" @input="metadata(index, 'source_name', $event)" /></label>
            <label>来源年份 <input data-testid="candidate-year" type="number" :value="candidateBody(index)?.source.source_year" @input="metadata(index, 'source_year', $event)" /></label>
            <label>授权依据 <input data-testid="candidate-license" :value="candidateBody(index)?.source.source_license" @input="metadata(index, 'source_license', $event)" /></label>
            <label>来源 URL <input data-testid="candidate-url" type="url" :value="candidateBody(index)?.source.source_url" @input="metadata(index, 'source_url', $event)" /></label>
          </section>
          <h4>题面预览</h4><MathText :text="item.text" />
          <label>人工配对答案原文（文件 / 页或片段）<select v-model="answerLocations[index]" data-testid="answer-location"><option value="">请选择人工核对的答案位置</option><optgroup v-for="file in detail.files" :key="file.id" :label="file.filename"><option v-for="page in file.pages" :key="page.number" :value="`${file.id}:${page.number}`">{{ file.filename }} / {{ page.number }}</option></optgroup></select></label>
          <button data-testid="pair-answer" @click="pairAnswer(index)">记录人工答案配对位置</button><p>此操作仅保留原文位置，不改变题干或自动填写结构化答案；配对后须重新确认。</p>
          <label>题面、答案、题型、来源与教学 JSON <textarea v-model="item.json" data-testid="candidate-json" rows="12" spellcheck="false" @input="resetStructured(index)" /></label>
          <button v-if="canEditStructured(index)" data-testid="open-structured-editor" @click="item.editorOpen = !item.editorOpen">{{ item.editorOpen ? '收起可视化校对' : '展开可视化校对' }}</button>
          <QuestionEditor v-if="item.editorOpen && canEditStructured(index)" :key="`${detail.job.id}:${item.id}:${item.editorEpoch||0}`" :detail="editorDetail(index)" :initial-form="item.structuredDraft" :draft-revision="`${detail.job.id}:${item.id}:${detail.job.revision}:${editorInputSerial}`" :persist-draft="(form,body,ctx)=>persistCandidateDraft(index,form,body,ctx)" local-only @draft="(form, body) => editStructured(index, form, body)" />
          <label><input v-model="item.confirmed" type="checkbox" :disabled="item.structuredValid === false" />我已人工核对题面、答案配对、来源和使用依据</label>
          <button @click="split(index)">拆分</button><button :disabled="!editors[index + 1] || !!qualification(editors[index + 1]!)" @click="merge(index)">合并下一题</button>
          <button @click="move(index, -1)">上移</button><button @click="move(index, 1)">下移</button><button @click="editors.splice(index, 1)">删除候选</button>
        </fieldset>
        <p v-if="qualification(item)">此项已导入；当前只读文字是保留的本机历史输入，不代表已入库草稿内容。请打开服务端草稿核对。</p><p v-if="item.error" role="alert">{{ item.error.code }}：{{ item.error.message }}</p>
        <RouterLink v-if="qualification(item)" :to="{name:'question',params:{id:qualification(item)!}}">打开待审草稿</RouterLink>
      </article>
      <button :disabled="busy" @click="save">保存校对与确认</button><button :disabled="busy" @click="submit()">批量创建已保存的确认草稿 / 重试未完成批次</button>
      <section v-if="batch"><h3>批次结果</h3><p v-for="item in batch.items" :key="item.candidate_id">{{ item.candidate_id }}：{{ item.status }} {{ item.error?.message }}</p><button :disabled="busy" @click="submit(true)">仅重试失败项</button></section>
    </section>
  </main>
</template>
<style scoped>
label { display: block; margin: .6rem 0; } textarea { display: block; width: 100%; box-sizing: border-box; font-family: monospace; } pre { white-space: pre-wrap; overflow-wrap: anywhere; } img { max-width: 100%; } .candidate { margin: 1rem 0; } .candidate input:not([type=checkbox]) { width: 100%; box-sizing: border-box; } button { margin: .3rem; }
</style>



