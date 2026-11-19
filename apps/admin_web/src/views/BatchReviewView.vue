<script setup lang="ts">
import {ref,shallowRef,watch,onBeforeUnmount} from 'vue'
import {useRoute} from 'vue-router'
import {getQuestion,reviewQuestionBatch} from '../api/admin'
import {ApiError} from '../api/client'
import type {components} from '../api/schema'
import type {Command,Body,Json} from '../api/write-command-store'
import {handleUnauthorized,newIdempotencyKey} from '../api/guard'
import {availableDecisions,blockedReason,DECISION_LABEL} from '../decisions'
import {useSession,captureSessionBinding,isCurrentSessionBinding} from '../session'
import {BatchWriteRecovery,legacyBatchFingerprint,type BatchDraftBranch} from '../batch-write-recovery'
import MathText from '../components/MathText.vue'
import MediaAttachments from '../components/MediaAttachments.vue'
type S=components['schemas']
type Choice={id:string;version:number;reviewRevision:number|null;decision:S['ReviewDecisionType'];comment:string;fast:boolean;confirmed:boolean}
type Row=Choice&{detail:S['AdminQuestionDetail'];ticket:number}
const session=useSession(),route=useRoute(),rows=ref<Row[]>([]),busy=ref(false),error=ref(''),result=ref<S['ReviewBatchResult']>()
const pending=shallowRef<Command|null>(null),legacyUnknown=ref(false),branches=ref<BatchDraftBranch[]>([]),selectedBranch=ref<string|null>(null),unsaved=ref(false),historical=ref(false)
let adapter:BatchWriteRecovery|null=null,epoch=0,alive=true,serial=0,actionGeneration=0,cursor=0,branchGeneration=0,queue:Promise<void>=Promise.resolve(),failure:unknown=null,ready:Promise<void>=Promise.resolve()
const blocked=ref<string[]>([]),refreshNeeded=new Set<string>()
function current(binding:ReturnType<typeof captureSessionBinding>,ticket:number){return alive&&ticket===epoch&&isCurrentSessionBinding(binding)}
function choices():Choice[]{return rows.value.map(({id,version,reviewRevision,decision,comment,fast,confirmed})=>({id,version,reviewRevision,decision,comment,fast,confirmed}))}
function decode(raw:string):Choice[]{const value=JSON.parse(raw) as Choice[];if(!Array.isArray(value)||value.some(v=>!v||typeof v.id!=='string'||!Number.isSafeInteger(v.version)||v.version<1||!(v.reviewRevision===null||Number.isSafeInteger(v.reviewRevision)&&v.reviewRevision>=1)||!['approve','reject','publish','withdraw'].includes(v.decision)||typeof v.comment!=='string'||typeof v.fast!=='boolean'||typeof v.confirmed!=='boolean'||Object.keys(v).some(k=>!['id','version','reviewRevision','decision','comment','fast','confirmed'].includes(k))))throw Error('批量草稿格式未知，原文保留');return value}
function validBatch(value:unknown):value is S['ReviewBatch']{
 if(!value||typeof value!=='object'||Object.keys(value).some(k=>k!=='items')||!('items' in value)||!Array.isArray(value.items)||value.items.length<1||value.items.length>50)return false
 return value.items.every((item:unknown)=>{
  if(!item||typeof item!=='object')return false
  const i=item as Record<string,unknown>
  return !Object.keys(i).some(k=>!['question_id','expected_version','expected_review_revision','decision','comment','solution_kinds','confirmed'].includes(k))&&typeof i.question_id==='string'&&/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(i.question_id)&&Number.isSafeInteger(i.expected_version)&&Number(i.expected_version)>=1&&Number.isSafeInteger(i.expected_review_revision)&&Number(i.expected_review_revision)>=1&&i.confirmed===true&&['approve','reject','publish','withdraw'].includes(String(i.decision))&&(i.comment==null||typeof i.comment==='string'&&i.comment.length<=2000)&&(i.solution_kinds==null||Array.isArray(i.solution_kinds)&&i.solution_kinds.every(k=>['standard','fast'].includes(k)))
 })
}
const succeeded=(id:string)=>blocked.value.includes(id)||refreshNeeded.has(id)
const sourceChanged=(row:Row)=>row.version!==row.detail.version||row.reviewRevision!==row.detail.review_revision
async function persist(){const text=JSON.stringify(choices()),binding=captureSessionBinding(),ticket=epoch,store=adapter,edit=serial;if(!binding||!store)return;unsaved.value=true;queue=queue.catch(()=>{}).then(async()=>{try{const d=await store.save(text,cursor);if(!d.conflict)cursor=d.generation;if(current(binding,ticket)){branches.value=d.branches;if(edit===serial)unsaved.value=false;if(d.conflict){selectedBranch.value=d.conflict.id;branchGeneration=d.generation;failure=Error('跨标签批量草稿冲突已保存，请明确选择来源');error.value=String(failure)}else{failure=null;selectedBranch.value=null}}}catch(e){if(current(binding,ticket)){failure=e;error.value='本机保存失败，输入仅在页面内存，请勿退出；未发送新请求。'+String(e)}}});await queue}
function edit(row:Row,reset=true){serial++;if(reset)row.confirmed=false;blocked.value=blocked.value.filter(id=>id!==row.id);historical.value=false;void persist()}
async function initialize(){const ticket=++epoch,binding=captureSessionBinding();rows.value=[];result.value=undefined;pending.value=null;legacyUnknown.value=false;branches.value=[];selectedBranch.value=null;blocked.value=[];busy.value=false;error.value='';cursor=0;failure=null;queue=Promise.resolve();if(!binding)return;const ids=Array.from(new Set(String(route.query.ids||'').split(',').filter(Boolean)));const store=new BatchWriteRecovery(binding.userId,undefined,ids);adapter=store
 try{const draft=await store.load();if(!current(binding,ticket))return;cursor=draft.generation;branches.value=draft.branches;const saved=draft.raw?decode(draft.raw):[];if(ids.length<1||ids.length>50)throw Error('请从队列选择1至50道题目。');if(saved.length&&JSON.stringify(saved.map(v=>v.id))!==JSON.stringify(ids))throw Error('已有另一组题目的本机草稿，原文保留，请返回原批次处理。')
 for(const id of ids){const detail=await getQuestion(binding.token,id);if(!current(binding,ticket))return;const prior=saved.find(v=>v.id===id);rows.value.push({...prior,id,version:prior?.version??detail.version,reviewRevision:prior?prior.reviewRevision:detail.review_revision??null,decision:prior?.decision??availableDecisions(detail.status)[0]??'approve',comment:prior?.comment??'',fast:prior?.fast??false,confirmed:prior?.confirmed??false,detail,ticket:0})}
 pending.value=(await store.pending())??null;if(!current(binding,ticket))return
 const history=await store.history();if(!current(binding,ticket))return;if(history){result.value=history.result as unknown as S['ReviewBatchResult'];historical.value=true;for(const item of result.value.items)if(item.status==='succeeded')refreshNeeded.add(item.question_id)}
 const raw=sessionStorage.getItem('batch-review:'+binding.userId);const stopped=localStorage.getItem('admin-batch-legacy-stop/v1/'+encodeURIComponent(binding.userId));
 const fingerprint=raw?await legacyBatchFingerprint(raw):null;if(!current(binding,ticket))return;
 if(raw&&fingerprint!==stopped&&!pending.value){try{const old=JSON.parse(raw) as {body:unknown;key:string};const oldIds=old.body&&typeof old.body==='object'&&'items'in old.body&&Array.isArray(old.body.items)?old.body.items.map(i=>i?.question_id):null;const related=oldIds===null||JSON.stringify(oldIds)===JSON.stringify(ids);if(!related){/* Preserve unrelated legacy raw without importing it into this group. */}else if(validBatch(old.body)&&typeof old.key==='string'){const c=await store.recoverLegacy(old.key,old.body as unknown as Body);if(current(binding,ticket)&&['prepared','result_known','unavailable'].includes(c.phase)&&c.error!=='abandoned_unknown')pending.value=c}else legacyUnknown.value=true}catch{legacyUnknown.value=true}}
 const oldResult=sessionStorage.getItem('batch-review:'+binding.userId+':result');if(oldResult&&!history){try{const v=JSON.parse(oldResult) as {value:S['ReviewBatchResult']};if(Array.isArray(v.value?.items)){result.value=v.value;blocked.value=v.value.items.filter(i=>i.status==='succeeded').map(i=>i.question_id)}}catch{/* legacy raw preserved */}}
 }catch(e){if(current(binding,ticket)){failure=e;if(!handleUnauthorized(e,binding))error.value=String(e)}}}
watch(()=>session.session,()=>{ready=initialize()},{immediate:true});watch(()=>route.fullPath,()=>{ready=initialize()});onBeforeUnmount(()=>{alive=false;epoch++})
async function refresh(row:Row){const binding=captureSessionBinding(),ticket=epoch,request=++row.ticket,edit=serial;if(!binding)return;try{const detail=await getQuestion(binding.token,row.id);if(!current(binding,ticket)||request!==row.ticket||edit!==serial)return;row.detail=detail;row.version=detail.version;row.reviewRevision=detail.review_revision??null;row.confirmed=false;row.decision=availableDecisions(detail.status)[0]||'approve';refreshNeeded.delete(row.id);editRow(row)}catch(e){if(current(binding,ticket)&&request===row.ticket&&edit===serial&&!handleUnauthorized(e,binding))error.value=String(e)}}
function editRow(row:Row){edit(row,false)}
async function apply(command:Command,store:BatchWriteRecovery,binding:NonNullable<ReturnType<typeof captureSessionBinding>>,ticket:number){const edit=serial;let saved:Command
 try{saved=await store.commands.send(command,async c=>{if(!current(binding,ticket))throw Error('身份或页面已变化，未发送请求');if(!validBatch(c.body))throw Error('原批次缺少来源，不能精确恢复');return await reviewQuestionBatch(binding.token,c.body,c.key) as unknown as Json})}
 catch(e){const persisted=(await store.commands.list()).find(c=>c.key===command.key);if(persisted?.error==='abandoned_unknown')throw e;if(e instanceof ApiError&&e.status===422&&e.code==='validation_error'){await store.commands.mark(command,'rejected','validation_error');if(current(binding,ticket))pending.value=null}throw e}
 if(!current(binding,ticket)||saved.error==='abandoned_unknown')return;pending.value=saved;await store.commands.acknowledgeStoredResult(saved);if(!current(binding,ticket))return
 // An abandoned late receipt remains historical and cannot revive the active lane.
 const all=await store.commands.list();if(!current(binding,ticket))return;pending.value=(await store.pending())??null;if(!current(binding,ticket))return
 if(all.find(c=>c.key===command.key)?.error==='abandoned_unknown')return
 const latest=all.filter(c=>store.matches(c)&&c.result!==undefined).sort((a,b)=>a.epoch-b.epoch).at(-1);if(latest?.key!==saved.key)return;result.value=saved.result as unknown as S['ReviewBatchResult'];historical.value=true;for(const item of result.value.items)if(item.status==='succeeded')refreshNeeded.add(item.question_id)
 if(edit===serial&&!unsaved.value){blocked.value=result.value.items.filter(i=>i.status==='succeeded').map(i=>i.question_id);for(const row of rows.value)row.confirmed=false;serial++;await persist()}}
async function submit(){const binding=captureSessionBinding(),ticket=epoch,store=adapter;if(!binding||!store||busy.value)return;const action=++actionGeneration,edit=serial;busy.value=true;error.value='';try{await ready;await queue;if(!current(binding,ticket))return;if(edit!==serial)throw Error('编辑已变化，请等待本机保存后再次明确提交');if(failure)throw failure;if(legacyUnknown.value)throw Error('旧批次缺少来源，不能发送；请明确保留未知记录后重新确认');if(pending.value){await apply(pending.value,store,binding,ticket);return}
 const selected=rows.value.filter(r=>r.confirmed&&!succeeded(r.id));if(!selected.length)throw Error('请逐题核对并明确确认。');const body:S['ReviewBatch']={items:selected.map(row=>{if(refreshNeeded.has(row.id))throw Error('历史成功项请先刷新来源并重新明确确认');if(row.reviewRevision===null)throw Error('缺少审核修订号，请刷新并重新确认');return {question_id:row.id,expected_version:row.version,expected_review_revision:row.reviewRevision,decision:row.decision,comment:row.comment||null,solution_kinds:row.decision==='approve'?(row.fast?['standard','fast']:['standard']):null,confirmed:true}})}
 const command=await store.commands.prepare({key:newIdempotencyKey(),body:body as unknown as Body,method:'POST',path:'/admin/question-reviews/batch',resource:store.resource});if(!current(binding,ticket))return;pending.value=command;await apply(command,store,binding,ticket)
 }catch(e){if(current(binding,ticket)&&action===actionGeneration&&!handleUnauthorized(e,binding))error.value=String(e)}finally{if(current(binding,ticket)&&action===actionGeneration)busy.value=false}}
async function acknowledge(){const binding=captureSessionBinding(),ticket=epoch,command=pending.value,store=adapter;if(!binding||!store||!command)return;try{await store.commands.acknowledgeStoredResult(command);if(current(binding,ticket)){pending.value=null;result.value=command.result as unknown as S['ReviewBatchResult'];historical.value=true}}catch(e){if(current(binding,ticket))error.value=String(e)}}
async function abandon(){const binding=captureSessionBinding(),ticket=epoch,store=adapter,command=pending.value;if(!binding||!store)return;if(!window.confirm('原批次可能已经逐题完成或稍后完成。停止本机重试不会取消服务端操作。保留未知记录并重新逐题确认？'))return;try{if(command)await store.commands.mark(command,'unavailable','abandoned_unknown');else{const raw=sessionStorage.getItem('batch-review:'+binding.userId);if(raw){const hash=await legacyBatchFingerprint(raw);if(!current(binding,ticket))return;localStorage.setItem('admin-batch-legacy-stop/v1/'+encodeURIComponent(binding.userId),hash)}}if(current(binding,ticket)){actionGeneration++;busy.value=false;pending.value=null;legacyUnknown.value=false;for(const row of rows.value)row.confirmed=false;serial++;await persist()}}catch(e){if(current(binding,ticket))error.value=String(e)}}
async function loadBranch(id:string){const binding=captureSessionBinding(),ticket=epoch,store=adapter,edit=serial;if(!binding||!store)return;try{await queue;if(!current(binding,ticket)||unsaved.value||edit!==serial)return;const d=await store.load();if(!current(binding,ticket)||edit!==serial)return;const branch=d.branches.find(v=>v.id===id);if(!branch)return;const saved=decode(branch.raw);if(JSON.stringify(saved.map(v=>v.id))!==JSON.stringify(rows.value.map(v=>v.id)))throw Error('其他题目分支不能替换当前批次');for(const row of rows.value)Object.assign(row,saved.find(v=>v.id===row.id));serial++;selectedBranch.value=id;branchGeneration=d.generation;failure=Error('请明确采用来源分支后再提交')}catch(e){if(current(binding,ticket))error.value=String(e)}}
async function promoteBranch(){const store=adapter,binding=captureSessionBinding(),ticket=epoch,id=selectedBranch.value,edit=serial;if(!store||!binding||!id)return;await queue;if(!current(binding,ticket)||unsaved.value||edit!==serial||id!==selectedBranch.value)return;try{const d=await store.promoteBranch(id,branchGeneration);if(!current(binding,ticket)||edit!==serial)return;cursor=d.generation;branches.value=d.branches;selectedBranch.value=null;failure=null;error.value=''}catch(e){if(current(binding,ticket))error.value=String(e)}}
</script>
<template>
 <main class="page"><RouterLink to="/">返回审核队列</RouterLink><h1>逐题确认批量审核</h1>
 <p>每题核对内容、版本和解法后单独确认。二审与发布是分别确认的动作；不会自动发布。</p>
 <p>普通校验失败按每题保存点处理，其他成功项与整批回执在同一个外层事务提交；意外进程或数据库故障会回滚整批未提交改动。网络中断请明确恢复原批次，不以当前GET推定原请求成功。成功项不自动再审，失败项刷新后重新核对确认。</p>
 <p v-if="error" role="alert">{{error}}</p>
 <section v-if="pending"><h2>待恢复的原批次</h2><p>原完整请求与幂等键先保存在本机，刷新不会自动重发；续改内容单独保留，不修改原请求。</p><pre>{{JSON.stringify(pending.body,null,2)}}</pre></section>
 <p v-if="rows.length" role="status" data-testid="batch-draft-state">{{unsaved?'尚未安全保存，请勿退出':selectedBranch?'冲突分支已保存，请明确选择':'本机批量草稿已保存'}}</p>
 <p v-if="historical" role="status">以下仅为原批次历史逐题结果，续改内容保留，不代表当前题目状态。</p>
 <p v-if="legacyUnknown" role="alert">旧批次缺少双来源，原raw/body/key保留为未知证据；不能以新body重用旧key。</p>
 <button v-if="pending?.phase==='result_known'" data-testid="batch-ack" @click="acknowledge">仅本机确认已保存的历史结果</button>
 <button v-if="pending||legacyUnknown" data-testid="batch-abandon" @click="abandon">保留未知记录，停止本机重试后另起新批次</button>
 <section v-if="branches.length" aria-label="批量冲突草稿"><button v-for="branch in branches" :key="branch.id" :data-testid="'batch-branch-'+branch.id" @click="loadBranch(branch.id).catch(e=>error=String(e))">载入冲突分支</button><button v-if="selectedBranch" data-testid="batch-promote" @click="promoteBranch">明确采用当前分支，保留主草稿备份</button></section>
 <article v-for="row in rows" :key="row.detail.id">
  <h2>{{row.detail.title}} · v{{row.detail.version}}</h2><RouterLink :to="{name:'question',params:{id:row.detail.id}}" target="_blank">打开完整题目、答案与解法核对</RouterLink><MathText :text="row.detail.content.stem"/><MediaAttachments v-if="row.detail.content.attachments.length" :model-value="row.detail.content.attachments" :question-id="row.detail.id" :question-version="row.detail.version" :author-id="row.detail.created_by" readonly />
  <p>来源：{{row.detail.source.source_name}}；使用依据：{{row.detail.source.source_license}}</p><p>本机决策来源：v{{row.version}} / 审核修订{{row.reviewRevision??'未知'}}。当前读取不会自动更新决策来源。</p><p v-if="sourceChanged(row)" role="alert">本机决策来源已变化或未知，请逐题刷新并重新核对；续改内容仍保留。</p>
  <details><summary>答案与解法、自查要点及程序校验</summary><pre>{{JSON.stringify({answer:row.detail.answer,solutions:row.detail.solutions,rubric:row.detail.rubric,check_problems:row.detail.check_problems},null,2)}}</pre></details>
  <fieldset :disabled="succeeded(row.detail.id)">
   <label>本题决策 <select v-model="row.decision" @change="edit(row)"><option v-for="decision in availableDecisions(row.detail.status)" :key="decision" :value="decision">{{DECISION_LABEL[decision]}}</option></select></label>
   <label>原因 / 备注 <textarea v-model="row.comment" maxlength="2000" @input="edit(row)"/></label>
   <label v-if="row.decision==='approve'&&row.detail.solutions.some(s=>s.kind==='fast')"><input v-model="row.fast" type="checkbox" @change="edit(row)"/>已核对快速解法的条件与边界（标准解法必须确认）</label>
   <p v-if="blockedReason(row.detail,row.decision,session.session?.userId||'')" role="alert">{{blockedReason(row.detail,row.decision,session.session?.userId||'')}}</p>
   <label><input v-model="row.confirmed" data-testid="batch-confirm" type="checkbox" @change="edit(row,false)" :disabled="sourceChanged(row)||!!blockedReason(row.detail,row.decision,session.session?.userId||'')||(['reject','withdraw'].includes(row.decision)&&!row.comment.trim())"/>我已逐题核对v{{row.version}}的题目、答案、解法与来源，并明确确认本题{{DECISION_LABEL[row.decision]}}</label>
  </fieldset>
  <button @click="refresh(row)">刷新本题版本并重新核对</button>
  <p v-for="item in result?.items.filter(i=>i.question_id===row.detail.id)" :key="item.question_id" role="status">{{item.status==='succeeded'?'已成功':'本题失败'}} {{item.state?.status}} {{item.error?.code}} {{item.error?.message}}</p>
 </article>
 <button data-testid="batch-submit" :disabled="busy||!!selectedBranch" @click="submit">{{pending?'恢复原批次 / 网络失败重试':'提交已逐题确认的决策 / 仅重试失败项'}}</button>
 </main>
</template>
<style scoped>article{margin:1.5rem 0;padding:1rem;border:1px solid #bbb}label{display:block;margin:.5rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}textarea{display:block;width:100%;box-sizing:border-box}</style>
