<script setup lang="ts">
import {ref,shallowRef,watch,onBeforeUnmount} from 'vue'
import * as api from '../api/media'
import type {components} from '../api/schema'
import {handleUnauthorized} from '../api/guard'
import {useSession,captureSessionBinding,isCurrentSessionBinding} from '../session'
import {MediaWriteRecovery,type MediaSource} from '../media-write-recovery'
import type {Command} from '../api/write-command-store'
type S=components['schemas']
const model=defineModel<S['QuestionAttachment'][]>({required:true})
const props=defineProps<{questionId?:string;questionVersion?:number;authorId?:string|null;readonly?:boolean;draftRevision?:number|string;persistAttachments?:(next:S['QuestionAttachment'][],context:{isCurrent:()=>boolean})=>Promise<void>}>()
const session=useSession(),busy=ref(false),error=ref(''),preview=ref('')
const shownId=ref(''), shownSha=ref(''), imageLoaded=ref(false), reviewChecked=ref(false), reviewDone=ref('')
let previewGeneration=0
watch(()=>[session.session?.userId,props.questionId,props.questionVersion],()=>{previewGeneration++;preview.value='';error.value='';shownId.value='';shownSha.value='';imageLoaded.value=false;reviewChecked.value=false;reviewDone.value=''})
const componentContext=crypto.randomUUID()
const associationTargets=ref<Record<string,boolean>>({})
function currentSource():MediaSource{return {contextId:componentContext,...(props.questionId?{questionId:props.questionId}:{}),...(props.questionVersion!==undefined?{version:props.questionVersion}:{})}}
let lease=0, mounted=true, newIntentRequested=false
function newUpload(){selectedWorkspace.value='';newIntentRequested=true;lease++;busy.value=false;localStatus.value='新的上传使用独立工作区；旧结果未知历史保留'}
onBeforeUnmount(()=>{mounted=false;lease++;previewGeneration++})
const histories=shallowRef<Awaited<ReturnType<MediaWriteRecovery['read']>>['workspaces']>([])
const selectedWorkspace=ref(''), localStatus=ref('')
function recovery(){const auth=captureSessionBinding();if(!auth)throw Error('请重新登录');return new MediaWriteRecovery(auth.userId,auth.role)}
async function refresh(){const serial=lease,auth=captureSessionBinding();if(!auth)return;try{const r=recovery();await r.migrateLegacyUpload();await r.migrateLegacyDeclarations(props.questionId);if(!isCurrentSessionBinding(auth)||!mounted||serial!==lease)return;const state=await r.read();if(isCurrentSessionBinding(auth)&&mounted&&serial===lease)histories.value=state.workspaces}catch(e){if(isCurrentSessionBinding(auth)&&mounted&&serial===lease)error.value=String(e)}}
watch(()=>[session.session?.userId,session.session?.role,props.questionId,props.questionVersion],()=>{lease++;busy.value=false;selectedWorkspace.value='';associationTargets.value={};histories.value=[];void refresh()},{immediate:true,flush:'sync'})
function readFile(file:File):Promise<string>{return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]!);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file)})}
function kind(c:Command){return c.resource.split(':').at(-1)}
async function dispatch(r:MediaWriteRecovery,c:Command,guard:()=>boolean,token:string,selected?:{body:S['MediaBlobUpload'];bytes:Uint8Array}){
 const send=async(command:Command,body=command.body)=>{
  if(!guard())throw Error('操作上下文已改变；原命令保留在本机历史')
  const path=command.path, k=command.key
  if(path==='/media/uploads')return api.createMediaUpload(token,body as S['MediaUploadRequest'],k)
  const id=decodeURIComponent(path.split('/')[2]!)
  if(path.endsWith('/content'))return api.uploadMediaContent(token,id,body as S['MediaBlobUpload'],k)
  if(path.endsWith('/confirm'))return api.confirmMediaUpload(token,id,body as S['MediaConfirm'],k)
  if(path.endsWith('/review-confirmations'))return api.confirmQuestionMediaReview(token,decodeURIComponent(path.split('/')[3]!),decodeURIComponent(path.split('/')[5]!),body as S['MediaReviewConfirmation'],k)
  throw Error('不支持的媒体恢复动作')
 }
 return c.file?r.sendContent(c,selected,send):r.send(c,send)
}
async function upload(event:Event){
 const file=(event.target as HTMLInputElement).files?.[0],auth=captureSessionBinding()
 if(!file||!auth)return
 const serial=++lease,question=props.questionId,version=props.questionVersion,revision=props.draftRevision
 const guard=()=>mounted&&serial===lease&&isCurrentSessionBinding(auth)&&props.questionId===question&&props.questionVersion===version&&props.draftRevision===revision
 busy.value=true;error.value='';localStatus.value='正在保存本机命令'
 const r=recovery(),resume=selectedWorkspace.value
 try{
  if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>16*1024*1024)throw Error('请选择不超过16MB的PNG/JPEG/WebP，实际限额以服务端为准。')
  const encoded=await readFile(file);if(!guard())return
  const bytes=Uint8Array.from(atob(encoded),c=>c.charCodeAt(0))
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');if(!guard())return
  const metadata:S['MediaUploadRequest']={purpose:'question_attachment',mime:file.type as S['MediaUploadRequest']['mime'],size_bytes:file.size,sha256:hash}
  if(!resume&&!newIntentRequested&&histories.value.some(ws=>ws.active))throw Error('请恢复原命令，或明确开启新的上传；旧未知历史仍保留')
  const id=resume||crypto.randomUUID()
  if(resume){const old=await r.workspace(id);if(!guard())return;if(old.metadata?.sha256!==hash||old.metadata?.mime!==file.type||old.metadata?.size_bytes!==file.size)throw Error('请重选原文件；新文件须明确开启新的上传')}
  else {await r.createWorkspace(id,metadata,currentSource());if(!guard())return;selectedWorkspace.value=id;newIntentRequested=false}
  let c=await r.prepareCreate(id);if(!guard())return;localStatus.value='已保存本机命令'
  await dispatch(r,c,guard,auth.token);if(!guard())return;await r.ack(c);if(!guard())return
  c=await r.prepareContent(id,{body:{content_base64:encoded},bytes});if(!guard())return
  await dispatch(r,c,guard,auth.token,{body:{content_base64:encoded},bytes});if(!guard())return;await r.ack(c);if(!guard())return
  c=await r.prepareConfirm(id);if(!guard())return
  await dispatch(r,c,guard,auth.token);if(!guard())return;await r.ack(c);if(!guard())return
  const ws=await r.workspace(id);if(!guard())return
  const confirmed=ws.confirmed
  if(!confirmed||Date.parse(confirmed.expires_at)<=Date.now())throw Error('历史确认不证明附件当前仍有效，请核对附件')
  if(!resume&&!model.value.some(item=>item.media_id===confirmed.media_id)){const next=[...model.value,{kind:'image' as const,media_id:confirmed.media_id,alt:'待人工核对的附件说明'}];if(props.persistAttachments){await props.persistAttachments(next,{isCurrent:guard});if(!guard())return}model.value=next}
  localStatus.value='已保存上传历史';selectedWorkspace.value=''
 }catch(e){if(guard()){localStatus.value='结果未知；原命令已保留，请查看本机历史';error.value=e instanceof Error?e.message:String(e)}}finally{if(mounted&&serial===lease&&isCurrentSessionBinding(auth)){busy.value=false;await refresh()}}
}
async function historical(id:string,c:Command,action:'retry'|'ack'|'stop'){
 const auth=captureSessionBinding();if(!auth)return
 const serial=++lease,guard=()=>mounted&&serial===lease&&isCurrentSessionBinding(auth)
 busy.value=true;error.value=''
 try{const r=recovery();if(action==='ack')await r.ack(c);else if(action==='stop'){await r.releaseUnknown(c);if(guard()&&kind(c)==='declaration'){previewGeneration++;preview.value='';shownId.value='';shownSha.value='';imageLoaded.value=false;reviewChecked.value=false;reviewDone.value='';localStatus.value='已停止本机重试；服务器结果仍未知。新声明须重新授权预览并核对'}}else {if(c.file&&!['result_known','acked'].includes(c.phase)){selectedWorkspace.value=id;localStatus.value='重选原文件后继续原上传';return}await dispatch(r,c,guard,auth.token)}if(guard())localStatus.value='本机历史已保存；历史结果不证明当前引用有效'}catch(e){if(guard())error.value=String(e)}finally{if(guard()){busy.value=false;await refresh()}}
}
async function associate(id:string){
 const auth=captureSessionBinding()
 if(!auth||props.readonly||busy.value||!associationTargets.value[id])return
 const serial=++lease,source=currentSource(),revision=props.draftRevision,snapshot=JSON.stringify(model.value),workspace=selectedWorkspace.value
 const guard=()=>mounted&&serial===lease&&isCurrentSessionBinding(auth)&&props.questionId===source.questionId&&props.questionVersion===source.version&&props.draftRevision===revision&&JSON.stringify(model.value)===snapshot&&selectedWorkspace.value===workspace
 busy.value=true;error.value=''
 try{
  const r=recovery(),ws=await r.workspace(id);if(!guard())return
  const confirmed=ws.confirmed
  if(!confirmed||!ws.metadata||Date.parse(confirmed.expires_at)<=Date.now())throw Error('历史图片当前不可关联；原成功历史仍保留')
  if(!props.persistAttachments)throw Error('当前草稿尚未接入本机保存，不能加入引用')
  const confirmation=ws.commands.find(c=>kind(c)==='confirm')
  if(!confirmation)throw Error('缺少原确认回执')
  await r.ack(confirmation);if(!guard())return
  const content=await api.getMediaContent(auth.token,confirmed.media_id);if(!guard())return
  if(content.media_id!==confirmed.media_id||content.mime!==ws.metadata.mime||content.content_base64.length>22369624)throw Error('当前媒体与历史来源不匹配')
  const bytes=Uint8Array.from(atob(content.content_base64),c=>c.charCodeAt(0))
  const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');if(!guard())return
  if(sha!==ws.metadata.sha256||bytes.length!==ws.metadata.size_bytes)throw Error('当前媒体字节与历史来源不匹配')
  await r.recordAssociation(id,{target:source,mediaId:confirmed.media_id,sha256:sha,observedAt:Date.now()});if(!guard())return
  const next=model.value.some(item=>item.media_id===confirmed.media_id)?[...model.value]:[...model.value,{kind:'image' as const,media_id:confirmed.media_id,alt:'待人工核对的附件说明'}]
  await props.persistAttachments(next,{isCurrent:guard});if(!guard())return
  model.value=next;associationTargets.value[id]=false;localStatus.value='恢复图片已交本机草稿保存；原上传来源保留'
 }catch(e){if(guard()){error.value=`当前无法关联图片，原历史未判失败：${String(e)}`;localStatus.value='原上传历史保留'}}finally{if(mounted&&serial===lease&&isCurrentSessionBinding(auth)){busy.value=false;await refresh()}}
}
async function show(id:string){
 const binding=captureSessionBinding();if(!binding)return
 error.value='';const generation=++previewGeneration;imageLoaded.value=false;reviewChecked.value=false;reviewDone.value='';preview.value='';const token=binding.token
 try{
  let result:S['MediaContent']
  if(props.readonly&&props.questionId)result=await api.getQuestionMediaContent(token,props.questionId,id)
  else try{result=await api.getMediaContent(token,id)}catch(e){if(!isCurrentSessionBinding(binding)||!mounted||generation!==previewGeneration)return;if(!props.questionId)throw e;result=await api.getQuestionMediaContent(token,props.questionId,id)}
  if(!isCurrentSessionBinding(binding)||!mounted||generation!==previewGeneration)return
  if(result.media_id!==id)throw new Error('媒体引用不匹配')
  if(!['image/png','image/jpeg','image/webp'].includes(result.mime))throw new Error('仅允许图片预览')
  if(result.content_base64.length>22369624)throw new Error('图片超过预览上限')
  let sha=''
  if(props.questionVersion){const bytes=Uint8Array.from(atob(result.content_base64),c=>c.charCodeAt(0));sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('')}
  if(!isCurrentSessionBinding(binding)||!mounted||generation!==previewGeneration)return
  shownId.value=id;shownSha.value=sha;preview.value=`data:${result.mime};base64,${result.content_base64}`
 }catch(e){if(isCurrentSessionBinding(binding)&&mounted&&generation===previewGeneration&&!handleUnauthorized(e))error.value=e instanceof Error?e.message:String(e)}
}
async function declareReview(){
 const auth=captureSessionBinding()
 if(!auth||!props.questionId||!props.questionVersion||!imageLoaded.value||!reviewChecked.value||!shownSha.value||busy.value)return
 const serial=++lease,question=props.questionId,version=props.questionVersion,id=shownId.value,sha=shownSha.value,generation=previewGeneration
 const guard=()=>mounted&&serial===lease&&isCurrentSessionBinding(auth)&&props.questionId===question&&props.questionVersion===version&&generation===previewGeneration
 busy.value=true;error.value=''
 try{
  const r=recovery(),workspace=crypto.randomUUID()
  const state=await r.read();if(!guard())return
  const lane=state.workspaces.flatMap(w=>w.commands.filter(c=>kind(c)==='declaration'&&c.path===`/admin/questions/${question}/media/${id}/review-confirmations`&&c.body.expected_version===version&&c.body.sha256===sha&&!w.released.some(t=>t.key===c.key&&t.epoch===c.epoch&&t.snapshot===c.snapshot)))
  if(lane.some(c=>['prepared','unavailable','result_known','acked'].includes(c.phase))){localStatus.value='已有原声明待恢复或确认本机历史，请使用原命令；不另建新声明';return}
  const prepared=await r.prepareDeclarationLane(workspace,{questionId:question,version,mediaId:id,sha256:sha});if(!guard())return
  if(prepared.reused){localStatus.value=`已有原声明待恢复或确认本机历史；原工作区 ${prepared.workspaceId}，请使用原命令`;return}
  const c=prepared.command
  await dispatch(r,c,guard,auth.token);if(!guard())return;await r.ack(c);if(!guard())return
  reviewDone.value='已记录本人对本图当前版本的审校声明。';reviewChecked.value=false
 }catch(e){if(guard()){error.value=String(e);localStatus.value='结果未知；原声明保留在本机历史'}}finally{if(guard()){busy.value=false;await refresh()}}
}
function alt(index:number,event:Event){model.value=model.value.map((item,i)=>i===index?{...item,alt:(event.target as HTMLInputElement).value}:item)}
</script>
<template>
 <section class="media-attachments" data-testid="media-attachments"><h3>本地审核附件</h3>
 <p>临时图片只用于审核；默认存储关闭。确认附件不等于内容审核或发布，学生仅能读取已发布且独立审校声明有效的当前题面附件。请核对说明、原图及题面，勿上传未授权材料；仅限题面图片，勿混入答案、解析或泄题内容。</p>
 <label v-if="!readonly">上传PNG/JPEG/WebP <input type="file" accept="image/png,image/jpeg,image/webp" @change="upload"/></label>
 <p v-if="busy" role="status">上传并确认中，请保留当前页面；失败后重选同一文件复用原请求。</p>
 <p data-testid="media-local-status" role="status">{{localStatus}}</p>
 <section v-if="histories.length" data-testid="media-history"><h4>媒体本机历史</h4><p>历史回执不证明附件当前有效或已关联；停止仅停止本机重试，不代表服务器取消。</p><button type="button" @click="newUpload">明确开启新的上传</button><p v-if="selectedWorkspace">正在恢复 {{selectedWorkspace}}：请重选原文件</p><div v-for="ws in histories" :key="ws.id"><p>{{ws.id}} 原目标：{{ws.source?.questionId||'未知/新题'}} {{ws.source?.version!==undefined?`v${ws.source.version}`:'版本未知'}}</p><section v-if="ws.confirmed&&!readonly"><label><input v-model="associationTargets[ws.id]" data-testid="choose-association-target" type="checkbox" :disabled="busy"/>明确选择将此历史图片加入当前草稿 {{questionId||'新题'}} {{questionVersion!==undefined?`v${questionVersion}`:'版本未知'}}；保留原目标历史</label><button type="button" data-testid="associate-media" :disabled="busy||!associationTargets[ws.id]" @click="associate(ws.id)">将恢复图片加入当前草稿</button></section><div v-for="c in ws.commands" :key="c.key"><span>{{kind(c)}} {{c.phase}} {{c.key}}</span><button type="button" :disabled="busy" @click="historical(ws.id,c,'retry')">恢复原命令</button><button v-if="c.phase==='result_known'" type="button" :disabled="busy" @click="historical(ws.id,c,'ack')">仅确认本机历史</button><button v-if="c.phase==='prepared'||c.phase==='unavailable'" type="button" :disabled="busy" @click="historical(ws.id,c,'stop')">停止本机重试</button></div></div></section>
 <p v-if="error" role="alert">{{error}}</p>
 <div v-for="(item,index) in model" :key="`${item.media_id}:${index}`">
  <label>附件说明 <input :value="item.alt" :disabled="readonly||busy" @input="alt(index,$event)"/></label>
  <span>{{item.media_id||'无媒体引用'}}</span>
  <button v-if="item.media_id" data-testid="preview-media" type="button" @click="show(item.media_id)">授权预览附件</button>
  <button v-if="!readonly" type="button" :disabled="busy" @click="model=model.filter((_,i)=>i!==index)">移除本题引用</button>
 </div>
 <img v-if="preview" :key="preview" :src="preview" alt="已授权附件预览" @load="imageLoaded=true" @error="imageLoaded=false;error='图片解码失败，不能记录审校声明'"/>
 <section v-if="readonly&&questionId&&questionVersion&&shownId&&session.session?.userId!==authorId">
  <p>图片加载完成与明确勾选仅记录审校声明，程序不证明审校人实际完整看图。二审、发布前须逐图核对当前版本。</p>
  <label><input v-model="reviewChecked" data-testid="confirm-viewed-media" type="checkbox" :disabled="!imageLoaded||busy"/>我已查看并核对本图内容、来源及其与当前题面v{{questionVersion}}的关系，明确声明</label>
  <button type="button" data-testid="declare-media-review" :disabled="!imageLoaded||!reviewChecked||busy" @click="declareReview">记录本图当前版本审校声明</button><p role="status">{{reviewDone}}</p>
 </section>
 </section>
</template>
<style scoped>label{display:block;margin:.5rem 0}img{max-width:100%;max-height:60vh;object-fit:contain}.media-attachments{border:1px solid #bbb;padding:.7rem;margin:1rem 0}</style>
