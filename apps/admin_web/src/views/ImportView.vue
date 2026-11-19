<script setup lang="ts">
import { computed, ref, shallowRef, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { importQuestion } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized, newIdempotencyKey } from '../api/guard'
import type { AdminQuestionDetail, AdminQuestionImport } from '../api/types'
import type { Command, Body, Json } from '../api/write-command-store'
import MathText from '../components/MathText.vue'
import { captureSessionBinding, isCurrentSessionBinding, useSession } from '../session'
import { ImportWriteRecovery, type ImportDraftBranch } from '../import-write-recovery'

const raw=ref(''),confirmed=ref(false),busy=ref(false),error=ref('')
const result=ref<AdminQuestionDetail|null>(null),pending=shallowRef<Command|null>(null),historical=ref(false)
const unsavedInput=ref(false),headDraft=ref('')
const branches=ref<ImportDraftBranch[]>([]),selectedBranch=ref<string|null>(null)
const session=useSession(),route=useRoute()
let adapter:ImportWriteRecovery|null=null,selection=0,viewEpoch=0,alive=true,draftCursor={generation:0}
let branchHeadGeneration=0
let editSerial=0
let ready:Promise<void>=Promise.resolve()
let draftQueue:Promise<void>=Promise.resolve(),draftFailure:unknown=null
const parsed=computed(()=>{
 if(!raw.value.trim())return {value:null,error:''}
 try {
  const v=JSON.parse(raw.value)
  if(!v||typeof v!=='object'||Array.isArray(v)||typeof v.subject!=='string'||typeof v.answer_mode!=='string'||typeof v.source?.source_name!=='string'||typeof v.source?.source_license!=='string'||typeof v.question?.title!=='string'||typeof v.question?.content?.stem!=='string')throw Error('文件须含 subject、answer_mode、source 和 question，请参照示例文件。')
  return {value:v as AdminQuestionImport,error:''}
 }catch(e){return {value:null,error:e instanceof SyntaxError?'JSON 格式错误，请检查文件。':String(e)}}
})
function reset(){confirmed.value=false;error.value='';result.value=null;historical.value=false}
function current(binding:ReturnType<typeof captureSessionBinding>,epoch:number){return alive&&epoch===viewEpoch&&isCurrentSessionBinding(binding)}
async function initialize(){
 const initialEdit=editSerial,epoch=++viewEpoch,binding=captureSessionBinding();selection++;raw.value='';pending.value=null;branches.value=[];headDraft.value='';unsavedInput.value=false;selectedBranch.value=null;busy.value=false;reset();draftCursor={generation:0};draftFailure=null;draftQueue=Promise.resolve()
 if(!binding)return
 const store=new ImportWriteRecovery(binding.userId),cursor=draftCursor;adapter=store
 try{const d=await store.load();cursor.generation=d.generation;const command=await store.pending();if(!current(binding,epoch))return;if(editSerial===initialEdit)raw.value=d.raw;cursor.generation=d.generation;pending.value=command??null;branches.value=d.branches;headDraft.value=d.raw}
 catch(e){if(current(binding,epoch))error.value=String(e)}
}
watch(()=>session.session,()=>{ready=initialize()},{immediate:true})
watch(()=>route.fullPath,()=>{ready=initialize()})
onBeforeUnmount(()=>{alive=false;viewEpoch++;selection++})
function edit(){
 const serial=++editSerial;selection++;unsavedInput.value=true;reset();const binding=captureSessionBinding(),epoch=viewEpoch,store=adapter,text=raw.value,cursor=draftCursor,initialization=ready
 if(!binding||!store)return
 draftQueue=draftQueue.catch(()=>{}).then(async()=>{
  await initialization
  try{const d=await store.save(text,cursor.generation);if(!d.conflict)cursor.generation=d.generation;if(current(binding,epoch)){branches.value=d.branches;headDraft.value=d.raw;if(serial===editSerial)unsavedInput.value=false;if(d.conflict){selectedBranch.value=d.conflict.id;branchHeadGeneration=d.generation;draftFailure=Error('跨标签页冲突分支已保存，请明确选择来源。');error.value=String(draftFailure)}else{draftFailure=null;selectedBranch.value=null}}}
  catch(e){if(current(binding,epoch)){draftFailure=e;error.value='无法保存本机草稿，输入目前仅在此页面内存保留，请勿退出；未发送请求。'+String(e)}}
 })
}
async function selectFile(event:Event){
 const binding=captureSessionBinding(),epoch=viewEpoch,pick=++selection
 const file=(event.target as HTMLInputElement).files?.[0];if(!file)return
 reset();if(file.size>1024*1024){raw.value='';error.value='请选择不超过 1 MB 的单题 JSON 文件。';return}
 try{const text=await file.text();if(current(binding,epoch)&&pick===selection){raw.value=text.replace(/^\uFEFF/,'');edit()}}
 catch{if(current(binding,epoch)&&pick===selection)error.value='读取文件失败，请重新选择。'}
}
async function apply(command:Command,store:ImportWriteRecovery,binding:NonNullable<ReturnType<typeof captureSessionBinding>>,epoch:number){
 let saved:Command
 try{saved=await store.commands.send(command,async c=>{
  if(!current(binding,epoch))throw Error('原页面或身份已失效，未发送请求。')
  return await importQuestion(binding.token,c.body as unknown as AdminQuestionImport,c.key) as unknown as Json
 })}catch(e){
  if(e instanceof ApiError && e.status===422 && e.code==='validation_error'){
   try{await store.commands.mark(command,'rejected','validation_error')}
   catch(storageFailure){throw storageFailure}
   if(current(binding,epoch))pending.value=null
  }
  throw e
 }
 if(!current(binding,epoch))return
 pending.value=saved
 if(saved.phase==='result_known'||saved.phase==='acked'){
  await store.commands.acknowledgeStoredResult(saved)
  if(!current(binding,epoch))return
  pending.value=null
  if(JSON.stringify(parsed.value.value)===JSON.stringify(saved.body))result.value=saved.result as unknown as AdminQuestionDetail
  else historical.value=true
 }
}
async function submit(){
 const binding=captureSessionBinding(),epoch=viewEpoch,store=adapter,body=parsed.value.value
 if(!binding||!store||!body||!confirmed.value||busy.value||result.value||!current(binding,epoch))return
 if(pending.value)return
 busy.value=true;error.value=''
 try{
  await draftQueue;if(!current(binding,epoch))return;if(draftFailure)throw draftFailure
  const command=await store.commands.prepare({key:newIdempotencyKey(),method:'POST',path:'/admin/question-imports',resource:'single-question-import',body:body as unknown as Body})
  if(!current(binding,epoch))return
  pending.value=command;await apply(command,store,binding,epoch)
 }catch(e){failure(e,binding,epoch)}finally{if(current(binding,epoch))busy.value=false}
}
function failure(e:unknown,binding:NonNullable<ReturnType<typeof captureSessionBinding>>,epoch:number){
 if(!current(binding,epoch)||handleUnauthorized(e,binding))return
 error.value=e instanceof ApiError?e.message:'导入未完成；输入与原命令保留。'+String(e)
}
async function retry(){
 const binding=captureSessionBinding(),epoch=viewEpoch,store=adapter,command=pending.value
 if(!binding||!store||!command||busy.value||!current(binding,epoch))return
 busy.value=true;error.value=''
 try{await apply(command,store,binding,epoch)}catch(e){failure(e,binding,epoch)}finally{if(current(binding,epoch))busy.value=false}
}
async function acknowledge(){
 const binding=captureSessionBinding(),epoch=viewEpoch,store=adapter,command=pending.value
 if(!binding||!store||!command||busy.value||!current(binding,epoch))return
 busy.value=true
 try{await store.commands.acknowledgeStoredResult(command);if(current(binding,epoch)){pending.value=null;historical.value=true}}
 catch(e){failure(e,binding,epoch)}finally{if(current(binding,epoch))busy.value=false}
}
async function loadBranch(id:string){
 const binding=captureSessionBinding(),epoch=viewEpoch,store=adapter
 if(!binding||!store)return
 await draftQueue
 if(!current(binding,epoch))return
 if(unsavedInput.value){error.value='输入尚未安全落盘，请勿退出或载入其他草稿。';return}
 try{const d=await store.load();if(!current(binding,epoch))return;const branch=d.branches.find(b=>b.id===id);if(!branch)return
  raw.value=branch.raw;selectedBranch.value=id;branchHeadGeneration=d.generation;branches.value=d.branches;draftCursor.generation=branch.sourceGeneration;reset();draftFailure=Error('载入的分支尚未明确解决来源冲突。')
 }catch(e){error.value=String(e)}
}
async function promoteBranch(){
 const binding=captureSessionBinding(),epoch=viewEpoch,store=adapter,id=selectedBranch.value,expectedHead=branchHeadGeneration
 if(!binding||!store||!id)return
 await draftQueue
 try{if(!current(binding,epoch))return;if(unsavedInput.value)throw Error('输入尚未落盘，请勿退出。');if(id!==selectedBranch.value)throw Error('分支有新的编辑，请重新核对后采用。')
  const d=await store.promoteBranch(id,expectedHead);if(!current(binding,epoch))return
  raw.value=d.raw;headDraft.value=d.raw;draftCursor.generation=d.generation;branches.value=d.branches;selectedBranch.value=null;draftFailure=null;reset()
 }catch(e){if(current(binding,epoch))error.value='采用分支未成功；输入仍保留，请勿退出。'+String(e)}
}
</script>

<template>
 <main class="page">
  <RouterLink to="/">返回审核队列</RouterLink>
  <h1>导入题目</h1><RouterLink to="/document-import">文档与批量 JSON 导入工作台</RouterLink>
  <p>选择单题 JSON 文件，或粘贴其内容。导入后是第 1 版待审草稿，须由另一位审校员二审后发布。</p>
  <p>支持自编及已授权题目；请填写来源和使用依据，审校员仍须核验。PDF、图片和 Word 请使用文档导入工作台。</p>
  <p><a href="/examples/question-import.json" download>下载自编工程样题示例</a>（未经学科审校，仅供本地演示）</p>
  <label>题目文件 <input type="file" accept=".json,application/json" @change="selectFile" /></label>
  <label class="import-json">JSON 内容<textarea v-model="raw" rows="14" spellcheck="false" @input="edit" /></label>
  <p v-if="parsed.error" role="alert">{{ parsed.error }}</p>
  <p v-if="raw" role="status" data-testid="import-draft-state">{{ unsavedInput ? (draftFailure ? '尚未保存到本机，请勿退出。' : '正在保存到本机…') : (draftFailure ? '冲突分支已保存，请明确选择来源。' : '本机草稿已保存。') }}</p>
  <section v-if="parsed.value" aria-label="导入预览"><h2>{{ parsed.value.question.title }}</h2><p>来源：{{ parsed.value.source.source_name }}；使用依据：{{ parsed.value.source.source_license }}</p><MathText :text="parsed.value.question.content.stem" /></section>
  <label><input v-model="confirmed" type="checkbox" :disabled="busy || !!result" />我已核对来源与使用依据，确认仅导入为待审草稿。</label>
  <p v-if="error" role="alert" style="white-space:pre-wrap">{{ error }}</p>
  <section v-if="pending" aria-label="原导入恢复">
   <p>原导入命令已保留。续改内容独立保存在本机；恢复始终使用原请求，不发送续改内容。</p>
   <button v-if="pending.phase === 'result_known'" data-testid="import-ack" :disabled="busy" @click="acknowledge">确认已保存的历史导入结果（无需联网）</button>
   <button v-else data-testid="import-retry" :disabled="busy" @click="retry">恢复原导入</button>
  </section>
  <section v-if="branches.length" aria-label="本机冲突草稿">
   <details><summary>查看当前主草稿（采用分支前会备份）</summary><pre>{{ headDraft }}</pre></details>
   <p>以下独立分支保留原来源。载入仅供查看，不会自动替换当前草稿或提交。</p>
   <button v-for="branch in branches" :key="branch.id" :data-testid="'import-branch-'+branch.id" @click="loadBranch(branch.id)">载入冲突分支（来源 {{ branch.sourceGeneration }}）</button>
   <button v-if="selectedBranch" data-testid="import-promote-branch" @click="promoteBranch">确认采用已载入分支，保留当前草稿备份</button>
  </section>
  <button data-testid="import-submit" :disabled="!parsed.value || !confirmed || busy || !!result || !!pending || !!selectedBranch" @click="submit">{{ busy ? '正在导入…' : '导入为待审草稿' }}</button>
  <p v-if="historical" role="status">原导入已保存为待审草稿；续改内容保留，请核对后另行提交。这是历史命令结果，不代表题目当前状态。</p>
  <section v-if="result" role="status"><p>已保存为待审草稿。程序校验发现 {{ result.check_problems.length }} 个问题。</p><RouterLink :to="{ name:'question',params:{id:result.id} }">打开草稿，检查并编辑</RouterLink></section>
 </main>
</template>
<style scoped>.import-json{display:block;margin:1rem 0}textarea{display:block;width:100%;box-sizing:border-box;font-family:monospace}section{margin:1rem 0}</style>







