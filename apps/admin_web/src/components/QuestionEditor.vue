<script setup lang="ts">
import { computed, reactive, ref, watch, onBeforeUnmount } from 'vue'
import { createQuestionVersion } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized } from '../api/guard'
import type { AdminQuestionDetail, AdminQuestionEdit } from '../api/types'
import { explainError } from '../decisions'
import type { EditorBody, EditorDetail, EditorForm } from '../editing'
import { formFromDetail, isUnchanged, requestFromForm } from '../editing'
import { PROOF_STAGES, STAGE_LABEL } from '../labels'
import { captureSessionBinding, isCurrentSessionBinding } from '../session'
import MathText from './MathText.vue'
import { useQuestionCommands } from '../question-write-recovery'
import type { components } from '../api/schema'
import type { Body,Json } from '../api/write-command-store'
import MediaAttachments from './MediaAttachments.vue'
import StringList from './StringList.vue'

const props = defineProps<{ detail: EditorDetail; localOnly?: boolean; initialForm?: EditorForm; draftRevision?:number|string; persistDraft?:(form:EditorForm,body:EditorBody|null,context:{isCurrent:()=>boolean})=>Promise<void> }>()
const emit = defineEmits<{ saved: [detail: AdminQuestionDetail]; cancel: []; refresh: []; draft: [form: EditorForm, body: EditorBody | null] }>()

const sourceDetail: EditorDetail = JSON.parse(JSON.stringify(props.detail))
const form = reactive<EditorForm>({...formFromDetail(props.detail), ...(props.initialForm ? JSON.parse(JSON.stringify(props.initialForm)) : {}), attachments: props.initialForm?.attachments || props.detail.content.attachments.map(item => ({...item}))})
const saving = ref(false),attachmentRevision=ref(0)
let mediaParentMounted=true
onBeforeUnmount(()=>{mediaParentMounted=false})
const failure = ref<{ code: string; message: string; lines: string[] } | null>(null)
const recovery=useQuestionCommands('edit',{id:sourceDetail.id,version:sourceDetail.version,reviewRevision:sourceDetail.review_revision??null},()=>JSON.parse(JSON.stringify(form)),value=>Object.assign(form,value),!!props.localOnly,()=>built.value.ok?{...built.value.body,expected_review_revision:sourceDetail.review_revision} as unknown as Body:null)

const isChoice = computed(() => ['single_choice', 'multiple_choice'].includes(props.detail.answer_mode))
const isFill = computed(() => props.detail.answer_mode === 'fill')
const isWritten = computed(() => props.detail.answer_mode === 'written')
const isExperiment = computed(() => props.detail.answer_mode === 'experiment')
const isProof = computed(() => props.detail.answer_mode === 'proof')
// 解答题、实验题、证明题：不自动评分，提交后对照要点自查；解答题和实验题分小问，证明题是一步一步的证明
const isSubjective = computed(() => isWritten.value || isExperiment.value || isProof.value)
const hasSubquestions = computed(() => isWritten.value || isExperiment.value)
// "所属小问"只能选已经有键的小问
const partChoices = computed(() => form.subquestions.filter((row) => row.key.trim() !== ''))
// 实验题的要点也可以针对某张数据表：从数据表那段 JSON 里读出表的键（JSON 写到一半时先当没有）
const tableChoices = computed<{ key: string; title: string }[]>(() => {
  if (!isExperiment.value) return []
  try {
    const parsed: unknown = JSON.parse(form.dataTablesJson)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is { key: string; title?: unknown } => !!item && typeof item.key === 'string' && item.key !== '')
      .map((item) => ({ key: item.key, title: typeof item.title === 'string' ? item.title : '' }))
  } catch {
    return []
  }
})
const built = computed(() => requestFromForm(form, sourceDetail))
const unchanged = computed(() => built.value.ok && isUnchanged(built.value.body, sourceDetail))
const sourceKnown = computed(() => typeof sourceDetail.review_revision === 'number' && Number.isSafeInteger(sourceDetail.review_revision) && sourceDetail.review_revision >= 1)
const canSave = computed(() => !saving.value && !recovery.pending.value && !recovery.blocked.value && (props.localOnly||recovery.loaded.value) && built.value.ok && !unchanged.value && (props.localOnly || sourceKnown.value))
const stale = computed(
  () => failure.value?.code === 'version_conflict' || failure.value?.code === 'invalid_transition' || failure.value?.code === 'review_revision_conflict',
)

function addOption(): void {
  const used = new Set(form.options.map((row) => row.key))
  const key = 'ABCDEFGHIJKL'.split('').find((letter) => !used.has(letter)) ?? `O${form.options.length + 1}`
  form.options.push({ key, text: '', analysis: '', correct: false })
}

function blankSettings(key: string, units = false): Record<string, unknown> {
  try { return JSON.parse(units ? form.unitsJson : form.rulesJson)[key] || {} } catch { return {} }
}
function settingList(key: string, field: string, units = false): string {
  const value = blankSettings(key, units)[field]
  return Array.isArray(value) ? value.filter(v => typeof v === 'string').join(',') : ''
}
function changeBlankSetting(key: string, field: string, event: Event, units = false) {
  const input = event.target as HTMLInputElement
  const raw = units ? form.unitsJson : form.rulesJson
  try {
    const all = JSON.parse(raw)
    if (!all || typeof all !== 'object' || Array.isArray(all)) return
    const existing = all[key] || {}
    const value = ['required', 'closure_flexible'].includes(field) ? input.checked
      : ['rel_tol', 'abs_tol'].includes(field) ? (input.value === '' ? undefined : Number(input.value))
      : ['accepted', 'variables'].includes(field) ? input.value.split(',').map(s => s.trim()).filter(Boolean) : input.value
    all[key] = { ...existing, [field]: value }
    if (units) form.unitsJson = JSON.stringify(all, null, 2)
    else form.rulesJson = JSON.stringify(all, null, 2)
  } catch { /* Preserve unfinished JSON; the existing validation explains how to fix it. */ }
}
function addBlank(): void {
  form.blanks.push({ key: `b${form.blanks.length + 1}`, label: '', unitHint: '', placeholder: '', answer: '' })
}

function addSubquestion(): void {
  const used = new Set(form.subquestions.map((row) => row.key))
  let next = form.subquestions.length + 1
  while (used.has(String(next))) next += 1
  form.subquestions.push({ key: String(next), stem: '', answer: '' })
}

function addStep(): void {
  form.proofSteps.push({ stage: 'reasoning', text: '', reason: '' })
}

/** 把参考证明里的一步往前（delta=-1）或往后（delta=1）挪一位。 */
function moveStep(index: number, delta: number): void {
  const target = index + delta
  if (target < 0 || target >= form.proofSteps.length) return
  const [step] = form.proofSteps.splice(index, 1)
  form.proofSteps.splice(target, 0, step!)
}

function addPoint(): void {
  const used = new Set(form.points.map((row) => row.key))
  let next = form.points.length + 1
  while (used.has(`p${next}`)) next += 1
  form.points.push({ key: `p${next}`, part: '', text: '' })
}

watch(form, () => {
  attachmentRevision.value++
  if(!props.localOnly)recovery.changed()
  if (props.localOnly) emit('draft', JSON.parse(JSON.stringify(form)), built.value.ok ? built.value.body : null)
}, { deep: true, flush:'sync' })

async function persistAttachments(next:components['schemas']['QuestionAttachment'][],context:{isCurrent:()=>boolean}):Promise<void>{
 const childCurrent=context.isCurrent
 const binding=captureSessionBinding(),serial=attachmentRevision.value,parentRevision=props.draftRevision,id=props.detail.id,version=props.detail.version
 const guard=()=>mediaParentMounted&&childCurrent()&&isCurrentSessionBinding(binding)&&attachmentRevision.value===serial&&props.draftRevision===parentRevision&&props.detail.id===id&&props.detail.version===version
 if(!guard())throw Error('附件目标草稿已变化，未关联。')
 if(!Array.isArray(next)||next.some(a=>!a||Object.keys(a).some(k=>!['kind','media_id','alt'].includes(k))||!['image','table'].includes(a.kind)||typeof a.alt!=='string'||(a.media_id!==null&&typeof a.media_id!=='string')))throw Error('附件引用格式未知，不持久化图片原文。')
 const snapshot:EditorForm=JSON.parse(JSON.stringify({...form,attachments:next}))
 try{
  if(props.localOnly){
   if(!props.persistDraft)throw Error('候选草稿未提供真实本机持久确认，附件未关联。')
   const result=requestFromForm(snapshot,sourceDetail)
   await props.persistDraft(snapshot,result.ok?result.body:null,{isCurrent:guard})
   if(!guard())throw Error('候选在保存期间发生变化，附件未应用。')
   Object.assign(form,snapshot)
  }else await recovery.persistSnapshot(snapshot,{isCurrent:guard})
 }catch(e){failure.value={code:'attachment_persistence',message:'附件未关联；输入保留，请勿退出。'+String(e),lines:[]};throw e}
}
async function save(): Promise<void> {
  if (props.localOnly) return
  const binding = captureSessionBinding()
  const result = built.value
  const revision = sourceDetail.review_revision
  if (!result.ok || !isCurrentSessionBinding(binding) || typeof revision !== 'number' || !sourceKnown.value) return
  const body: AdminQuestionEdit = { ...result.body, expected_review_revision: revision }
  saving.value = true
  failure.value = null
  try {
    const command=await recovery.run(body as unknown as Body,async(token,request,key)=>await createQuestionVersion(token,sourceDetail.id,request as unknown as AdminQuestionEdit,key) as unknown as Json)
    const saved=command?.result as unknown as AdminQuestionDetail|undefined
    if (!isCurrentSessionBinding(binding)) return
    if(saved)emit('saved', saved)
  } catch (error) {
    if (!isCurrentSessionBinding(binding) || handleUnauthorized(error, binding)) return
    if (error instanceof ApiError) {
      const items = error.details.errors
      const lines = Array.isArray(items)
        ? items.map((item) => {
            const entry = item as { field?: string; message?: string }
            return `${entry.field ?? ''}${entry.field ? '：' : ''}${entry.message ?? JSON.stringify(item)}`
          })
        : []
      failure.value = { code: error.code, message: explainError(error.code, error.message), lines }
    } else {
      failure.value = { code: 'unknown', message: '保存失败，请稍后重试', lines: [] }
    }
  } finally {
    if (isCurrentSessionBinding(binding)) saving.value = false
  }
}
async function retryWrite(){
 saving.value=true
 try{const command=await recovery.retry(async(token,request,key)=>await createQuestionVersion(token,sourceDetail.id,request as unknown as AdminQuestionEdit,key) as unknown as Json);if(command?.result)emit('saved',command.result as unknown as AdminQuestionDetail)}catch(e){failure.value={code:'recovery',message:String(e),lines:[]}}finally{saving.value=false}
}
</script>

<template>
  <section class="card editor" data-testid="editor">
    <p v-if="!localOnly" role="status" data-testid="edit-draft-state">{{ recovery.draftState.value }}</p>
    <p v-if="!localOnly && !sourceKnown" role="alert">缺少审核修订号，请保留本机编辑并刷新题目后明确重新发起。</p>
    <section v-if="!localOnly" aria-label="题目编辑恢复">
     <p v-if="recovery.message.value" role="status">{{ recovery.message.value }}</p>
     <button v-if="recovery.pending.value?.phase==='result_known'" data-testid="edit-ack" @click="recovery.ack()">确认已保存的历史结果（无需网络）</button>
     <button v-else-if="recovery.pending.value" data-testid="edit-retry" :disabled="saving" @click="retryWrite">恢复原保存命令</button>
     <details v-if="recovery.pending.value && recovery.pending.value.phase!=='result_known'"><summary>保留未知记录并停止本机重试</summary><p>原请求可能已成功。这里只停止本机重试，不取消服务器操作。新操作须另用新来源与新键。</p><button data-testid="edit-release" @click="recovery.release()">明确保留旧未知记录，停止重试</button></details>
     <details v-if="recovery.branches.value.length"><summary>比较当前主草稿</summary><pre>{{ recovery.headRaw.value }}</pre></details>
     <button v-for="branch in recovery.branches.value" :key="branch.id" @click="recovery.loadBranch(branch.id)">载入独立编辑分支</button>
     <button v-if="recovery.blocked.value" data-testid="edit-adopt" @click="recovery.adopt()">保留旧草稿并明确采用当前题目来源</button>
    </section>
    <fieldset :disabled="!recovery.loaded.value" style="border:0;padding:0;margin:0;min-width:0">
    <h2 v-if="localOnly">可视化校对答案、提示与解析</h2><h2 v-else>修改题目（保存后是第 {{ detail.version + 1 }} 版）</h2>
    <p v-if="localOnly" class="notice info small">改动先保存在本机，完整合法的表单同步到候选 JSON；未完整输入也会暂存。请完成后保存校对并重新人工确认。这里不会创建版本、判分或发布。</p><p v-else class="notice info small">
      保存会产生新版本，旧版本原样保留；新版本回到“待审”，审校人和解法确认全部清空，要由<strong>另一位</strong>审校员重新二审。
      你会成为新版本的提交者。保存时不做程序校验，结果在保存后的“程序校验”里。
    </p>

    <div class="grid">
      <label class="field wide">
        <span>标题</span>
        <input v-model="form.title" data-testid="title" maxlength="120" />
      </label>
      <label class="field">
        <span>难度</span>
        <select v-model.number="form.difficulty" data-testid="difficulty">
          <option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level">{{ level }}</option>
        </select>
      </label>
      <label class="field">
        <span>年级</span>
        <select v-model="form.grade" data-testid="grade">
          <option value="">不限</option>
          <option value="G10">高一</option>
          <option value="G11">高二</option>
          <option value="G12">高三</option>
        </select>
      </label>
    </div>

    <label class="field">
      <span>题干（公式写在 $…$ 里）</span>
      <textarea v-model="form.stem" rows="4" data-testid="stem" />
    </label>
    <p class="small preview"><span class="muted">预览：</span><MathText :text="form.stem" /></p>

    <MediaAttachments v-model="form.attachments" :question-id="detail.id || undefined" :question-version="detail.id && detail.version>0 ? detail.version : undefined" :draft-revision="`${draftRevision??''}:${attachmentRevision}`" :persist-attachments="persistAttachments" />
    <fieldset v-if="isChoice" class="group" data-testid="options">
      <legend>选项（勾选的是正确答案）</legend>
      <div v-for="(row, index) in form.options" :key="index" class="option-row">
        <input v-model="row.key" class="key" aria-label="选项键" maxlength="8" />
        <input v-model="row.correct" type="checkbox" :data-testid="`option-correct-${index}`" aria-label="正确" />
        <textarea v-model="row.text" rows="2" :data-testid="`option-text-${index}`" aria-label="选项内容" />
        <textarea v-model="row.analysis" rows="2" placeholder="这个选项的分析" aria-label="选项分析" />
        <button type="button" class="link" @click="form.options.splice(index, 1)">删除</button>
      </div>
      <button type="button" @click="addOption">添加选项</button>
    </fieldset>

    <fieldset v-if="isFill" class="group" data-testid="blanks">
      <legend>空位与标准答案</legend>
      <div v-for="(row, index) in form.blanks" :key="index" class="option-row blank-row">
        <input v-model="row.key" class="key" aria-label="空位键" maxlength="16" />
        <input v-model="row.answer" placeholder="标准答案" :data-testid="`blank-answer-${index}`" />
        <input v-model="row.unitHint" placeholder="单位提示" />
        <input v-model="row.placeholder" placeholder="输入框占位文字" />
        <button type="button" class="link" @click="form.blanks.splice(index, 1)">删除</button>
      </div>
      <fieldset v-for="(blank, index) in form.blanks" :key="index" class="group">
        <legend>{{ blank.key }} 的等价判定与单位</legend>
        <label>判定类型 <select :value="blankSettings(blank.key).type || ''" @change="changeBlankSetting(blank.key, 'type', $event)"><option value="">请选择</option><option value="numeric">数值</option><option value="expression">表达式</option><option value="interval">区间</option></select></label>
        <label>相对容差 <input type="number" step="any" min="0" :data-testid="`blank-rel-tol-${index}`" :value="blankSettings(blank.key).rel_tol" @input="changeBlankSetting(blank.key, 'rel_tol', $event)" /></label>
        <label>绝对容差 <input type="number" step="any" min="0" :value="blankSettings(blank.key).abs_tol" @input="changeBlankSetting(blank.key, 'abs_tol', $event)" /></label>
        <label>表达式变量（逗号分隔）<input :value="settingList(blank.key, 'variables')" @input="changeBlankSetting(blank.key, 'variables', $event)" /></label>
        <label><input type="checkbox" :checked="!!blankSettings(blank.key).closure_flexible" @change="changeBlankSetting(blank.key, 'closure_flexible', $event)" />允许区间端点等价写法</label>
        <label><input type="checkbox" :checked="!!blankSettings(blank.key, true).required" @change="changeBlankSetting(blank.key, 'required', $event, true)" />必须写单位</label>
        <label>单位等价写法（逗号分隔）<input :data-testid="`blank-unit-aliases-${index}`" :value="settingList(blank.key, 'accepted', true)" @input="changeBlankSetting(blank.key, 'accepted', $event, true)" /></label>
        <p>仅设置现有判定规则；无法确定的作答仍按既有规则弃判。</p>
      </fieldset>
      <button type="button" @click="addBlank">添加空位</button>
      <label class="field">
        <span>判定规则（JSON，每个空位一条）</span>
        <textarea v-model="form.rulesJson" rows="5" class="mono" data-testid="rules" />
      </label>
      <label class="field">
        <span>单位规则（JSON）</span>
        <textarea v-model="form.unitsJson" rows="4" class="mono" data-testid="units" />
      </label>
    </fieldset>

    <fieldset v-if="isExperiment" class="group" data-testid="safety">
      <legend>
        <label>
          <input v-model="form.safetyOn" type="checkbox" data-testid="safety-on" />
          安全提示（每道实验题必须有，上线前要你逐条确认）
        </label>
      </legend>
      <template v-if="form.safetyOn">
        <label class="field">
          <span>风险等级</span>
          <select v-model="form.safetyLevel" data-testid="safety-level">
            <option value="low">low：只涉及常规的低风险操作</option>
            <option value="medium">medium：需要提醒防护措施</option>
            <option value="high">high：高风险——现在不收录，程序校验会拦住</option>
          </select>
        </label>
        <StringList v-model="form.safetyNotes" label="安全提示（一条一行）" add-label="添加一条" :rows="2" />
      </template>
      <p class="muted small">
        这是纸面练习，不是操作指导：题目、提示和解法里都不要给现实操作的步骤诱导。高风险的实验现在不收录。
      </p>
    </fieldset>

    <fieldset v-if="isExperiment" class="group" data-testid="data-tables">
      <legend>数据表与留空格子的参考值</legend>
      <p class="muted small">
        数据表是一个 JSON 数组。每张表有 key、title、columns（key、label、unit）和 rows（key、label、cells）；
        cells 里每一列恰好一个格子 {"col": 列键, "text": 给定的数据}，<strong>text 为 null 的格子由学生填写</strong>。
        表、行、列的键只用字母、数字、下划线。留空格子的参考值写在下面，键是"表键.行键.列键"；学生提交之后才看得到它。
      </p>
      <label class="field">
        <span>数据表（JSON 数组）</span>
        <textarea v-model="form.dataTablesJson" rows="14" class="mono" data-testid="data-tables-json" />
      </label>
      <label class="field">
        <span>留空格子的参考值（JSON 对象，值是字符串）</span>
        <textarea v-model="form.referenceCellsJson" rows="6" class="mono" data-testid="reference-cells-json" />
      </label>
    </fieldset>

    <fieldset v-if="isProof" class="group" data-testid="proof-statement">
      <legend>已知与求证</legend>
      <p class="muted small">
        学生在题干下面看到“已知”（编号成 ①②③，写依据时可以引用）和“求证”。题干里已经写全了已知条件时，已知可以不填。
        参考证明不在这里，只在学生提交之后给出。
      </p>
      <StringList v-model="form.givens" label="已知条件（一条一行，至多 8 条）" add-label="添加一条" :rows="2" />
      <label class="field">
        <span>求证（公式写在 $…$ 里）</span>
        <textarea v-model="form.claim" rows="2" data-testid="claim" />
      </label>
      <p class="small preview"><span class="muted">预览：</span><MathText :text="form.claim" /></p>
    </fieldset>

    <fieldset v-if="isProof" class="group" data-testid="proof-steps">
      <legend>参考证明（一行一步，顺序就是证明的顺序）</legend>
      <p class="muted small">
        学生提交之后，会把自己写的证明和它并排对照；证明的写法不止一种，它只是一种参考，不参与任何判定。
        参考证明要示范“每一步都有依据”，最后一步必须是“结论”。
      </p>
      <div v-for="(row, index) in form.proofSteps" :key="index" class="option-row step-row">
        <select v-model="row.stage" aria-label="阶段" :data-testid="`step-stage-${index}`">
          <option v-for="stage in PROOF_STAGES" :key="stage" :value="stage">{{ STAGE_LABEL[stage] }}</option>
        </select>
        <textarea
          v-model="row.text"
          rows="2"
          placeholder="这一步写了什么（公式写在 $…$ 里）"
          aria-label="这一步"
          :data-testid="`step-text-${index}`"
        />
        <textarea v-model="row.reason" rows="2" placeholder="依据" aria-label="依据" :data-testid="`step-reason-${index}`" />
        <button type="button" class="link" :disabled="index === 0" :data-testid="`step-up-${index}`" @click="moveStep(index, -1)">
          上移
        </button>
        <button
          type="button"
          class="link"
          :disabled="index === form.proofSteps.length - 1"
          :data-testid="`step-down-${index}`"
          @click="moveStep(index, 1)"
        >
          下移
        </button>
        <button type="button" class="link" :data-testid="`step-delete-${index}`" @click="form.proofSteps.splice(index, 1)">
          删除
        </button>
      </div>
      <button type="button" data-testid="add-step" @click="addStep">添加一步</button>
    </fieldset>

    <fieldset v-if="hasSubquestions" class="group" data-testid="subquestions">
      <legend>小问与参考答案</legend>
      <p class="muted small">
        {{ isExperiment ? '实验题的文字小问（可以没有，只填数据表）' : '解答题分小问作答' }}。参考答案只用来给学生对照，不参与任何自动判定。
      </p>
      <div v-for="(row, index) in form.subquestions" :key="index" class="option-row sub-row">
        <input v-model="row.key" class="key" aria-label="小问键" maxlength="16" :data-testid="`subquestion-key-${index}`" />
        <textarea
          v-model="row.stem"
          rows="2"
          placeholder="这一问的题干（公式写在 $…$ 里）"
          aria-label="小问题干"
          :data-testid="`subquestion-stem-${index}`"
        />
        <textarea
          v-model="row.answer"
          rows="2"
          placeholder="参考答案"
          aria-label="参考答案"
          :data-testid="`subquestion-answer-${index}`"
        />
        <button type="button" class="link" :data-testid="`subquestion-delete-${index}`" @click="form.subquestions.splice(index, 1)">
          删除
        </button>
      </div>
      <button type="button" data-testid="add-subquestion" @click="addSubquestion">添加小问</button>
    </fieldset>

    <fieldset v-if="isSubjective" class="group" data-testid="points">
      <legend>自查要点（提交之后给学生对照）</legend>
      <p class="muted small">
        这是一张清单，不是评分标准：不带分值，也不会折算成分数。{{
          isProof
            ? '参考证明里出现过的每个阶段至少要有一条；"整份证明"是对全部作答的要求。'
            : `每个小问${isExperiment ? '、每张有留空格子的数据表' : ''}至少要有一条；"整份解答"是对全部作答的要求。`
        }}
      </p>
      <div v-for="(row, index) in form.points" :key="index" class="option-row point-row">
        <input v-model="row.key" class="key" aria-label="要点键" maxlength="16" :data-testid="`point-key-${index}`" />
        <select v-model="row.part" aria-label="所属" :data-testid="`point-part-${index}`">
          <option value="">{{ isProof ? '整份证明' : '整份解答' }}</option>
          <template v-if="isProof">
            <option v-for="stage in PROOF_STAGES" :key="stage" :value="stage">{{ STAGE_LABEL[stage] }}</option>
          </template>
          <template v-else>
            <option v-for="sub in partChoices" :key="sub.key" :value="sub.key">第 {{ sub.key }} 问</option>
            <option v-for="table in tableChoices" :key="`table-${table.key}`" :value="table.key">
              数据表 {{ table.key }}{{ table.title ? `（${table.title}）` : '' }}
            </option>
          </template>
        </select>
        <textarea v-model="row.text" rows="2" placeholder="要做到什么（公式写在 $…$ 里）" aria-label="要点" :data-testid="`point-text-${index}`" />
        <button type="button" class="link" :data-testid="`point-delete-${index}`" @click="form.points.splice(index, 1)">删除</button>
      </div>
      <button type="button" data-testid="add-point" @click="addPoint">添加要点</button>
    </fieldset>

    <fieldset class="group">
      <legend>教学辅助</legend>
      <label class="field">
        <span>知识点讲解（一句话）</span>
        <input v-model="form.concept" maxlength="200" />
      </label>
      <StringList v-model="form.hints" label="分层提示（由浅到深，不能泄露答案）" add-label="添加一层提示" />
      <label class="field">
        <span>换种讲法（可留空，留空时由模型网关生成）</span>
        <textarea v-model="form.conceptRephrase" rows="3" />
      </label>
      <StringList v-model="form.leakMarkers" label="额外的泄题标记（可选）" add-label="添加标记" :rows="1" />
      <details>
        <summary>审核引用范围</summary>
        <p class="small">引用随题目版本审校。修改来源文字后，请重新核对摘要和范围；系统不会自动移动旧引用。明确填写 [] 才清除所有注记。</p>
        <label class="field">
          <span>引用注记（JSON 数组）</span>
          <textarea v-model="form.referenceLinksJson" rows="7" data-testid="reference-links" placeholder="[]" />
        </label>
        <p class="small">每项包含 target_block_id、source_span（block_id、block_sha256、start、end）及 independent_safe。范围按 Unicode 字符计数，左闭右开；安全声明仍须通过独立审校及服务端防泄题检查。</p>
      </details>
      <label class="field">
        <span><input v-model="form.visualOn" type="checkbox" /> 带图解</span>
      </label>
      <div v-if="form.visualOn" class="grid">
        <label class="field">
          <span>模板</span>
          <input v-model="form.visualTemplate" placeholder="如 quadratic_graph" />
        </label>
        <label class="field wide">
          <span>说明文字</span>
          <input v-model="form.visualCaption" />
        </label>
        <label class="field wide">
          <span>参数（JSON，数字）</span>
          <textarea v-model="form.visualParamsJson" rows="3" class="mono" />
        </label>
      </div>
    </fieldset>

    <fieldset v-for="kind in (['standard', 'fast'] as const)" :key="kind" class="group" :data-testid="`solution-form-${kind}`">
      <legend>
        <label>
          <input v-model="form[kind].on" type="checkbox" :data-testid="`${kind}-on`" />
          {{ kind === 'standard' ? '标准解法' : '快速解法（必须写适用条件）' }}
        </label>
      </legend>
      <template v-if="form[kind].on">
        <StringList v-model="form[kind].steps" label="步骤" add-label="添加一步" />
        <label class="field">
          <span>答案</span>
          <input v-model="form[kind].finalAnswer" :data-testid="`${kind}-final`" />
        </label>
        <StringList v-model="form[kind].keyPoints" label="方法要点" add-label="添加要点" :rows="1" />
        <template v-if="kind === 'fast'">
          <StringList v-model="form.fast.conditions" label="适用条件" add-label="添加条件" :rows="1" />
          <label class="field">
            <span>不适用的情形</span>
            <textarea v-model="form.fast.boundary" rows="2" />
          </label>
        </template>
      </template>
    </fieldset>

    <fieldset class="group">
      <legend>其他</legend>
      <label class="field">
        <span>知识点（code，用逗号分隔）</span>
        <input v-model="form.knowledge" data-testid="knowledge" />
      </label>
      <label v-if="!isSubjective" class="field">
        <span>评分细则（JSON）</span>
        <textarea v-model="form.rubricJson" rows="3" class="mono" data-testid="rubric-json" />
      </label>
      <label class="field">
        <span>修改说明（可选，写进审核历史）</span>
        <input v-model="form.comment" maxlength="2000" data-testid="comment" />
      </label>
    </fieldset>

    <ul v-if="!built.ok" class="notice warn" data-testid="editor-errors">
      <li v-for="problem in built.errors" :key="problem">{{ problem }}</li>
    </ul>
    <p v-else-if="unchanged" class="muted small" data-testid="unchanged">还没有改动。</p>

    <div v-if="!localOnly" class="row">
      <button type="button" class="primary" data-testid="save" :disabled="!canSave" @click="save">
        {{ saving ? '保存中…' : '保存为新版本' }}
      </button>
      <button type="button" data-testid="cancel" :disabled="saving" @click="emit('cancel')">放弃修改</button>
    </div>

    <div v-if="failure" class="notice error" role="alert" data-testid="save-error">
      <p>{{ failure.message }}</p>
      <ul v-if="failure.lines.length">
        <li v-for="line in failure.lines" :key="line">{{ line }}</li>
      </ul>
      <button v-if="stale" type="button" class="link" @click="emit('refresh')">刷新题目</button>
    </div>
    </fieldset>
  </section>
</template>










