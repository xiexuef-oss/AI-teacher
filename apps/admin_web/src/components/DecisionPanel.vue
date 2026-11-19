<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { reviewQuestion } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized } from '../api/guard'
import type {
  AdminQuestionDetail,
  QuestionReviewState,
  ReviewDecision,
  ReviewDecisionType,
} from '../api/types'
import {
  availableDecisions,
  blockedReason,
  commentRequired,
  DECISION_HELP,
  DECISION_LABEL,
  explainError,
} from '../decisions'
import { useQuestionCommands } from '../question-write-recovery'
import type { Body,Json } from '../api/write-command-store'
import { captureSessionBinding, isCurrentSessionBinding, useSession } from '../session'

const props = defineProps<{ detail: AdminQuestionDetail }>()
const emit = defineEmits<{
  decided: [state: QuestionReviewState, decision: ReviewDecisionType]
  refresh: []
}>()

const state = useSession()
const decisions = computed(() => availableDecisions(props.detail.status))
const selected = ref<ReviewDecisionType | null>(decisions.value[0] ?? null)
const comment = ref('')
const confirmFast = ref(false)
const busy = ref(false)
const error = ref<{ code: string; message: string; problems: string[] } | null>(null)
const sourceDetail=JSON.parse(JSON.stringify(props.detail)) as AdminQuestionDetail
const recovery=useQuestionCommands('review',{id:sourceDetail.id,version:sourceDetail.version,reviewRevision:sourceDetail.review_revision??null},()=>({selected:selected.value,comment:comment.value,confirmFast:confirmFast.value}),value=>{const v=value as {selected:ReviewDecisionType|null;comment:string;confirmFast:boolean};selected.value=v.selected;comment.value=v.comment;confirmFast.value=v.confirmFast},false,()=>decisionBody() as unknown as Body|null)
watch([selected,comment,confirmFast],()=>recovery.changed())

const hasFast = computed(() => props.detail.solutions.some((solution) => solution.kind === 'fast'))
const blocked = computed(() =>
  selected.value && state.session
    ? blockedReason(props.detail, selected.value, state.session.userId)
    : null,
)
const needsComment = computed(() => (selected.value ? commentRequired(selected.value) : false))
const sourceKnown = computed(() => typeof props.detail.review_revision === 'number' && Number.isSafeInteger(props.detail.review_revision) && props.detail.review_revision >= 1)
const canSubmit = computed(
  () =>
    selected.value !== null &&
    sourceKnown.value &&
    !busy.value && recovery.loaded.value && !recovery.pending.value && !recovery.blocked.value &&
    blocked.value === null &&
    (!needsComment.value || comment.value.trim().length > 0),
)
const staleError = computed(
  () => error.value?.code === 'version_conflict' || error.value?.code === 'invalid_transition' || error.value?.code === 'review_revision_conflict',
)

// 状态或版本变了（刚做完一个决策，或者刷新到了新内容）：回到第一个可选的决策
watch(
  () => [props.detail.status, props.detail.version, props.detail.review_revision] as const,
  () => {
    selected.value = decisions.value[0] ?? null
    confirmFast.value = false
    comment.value = ''
    error.value = null
  },
)
watch(selected, () => {
  error.value = null
})

function decisionBody():ReviewDecision|null{
 const decision=selected.value,revision=sourceDetail.review_revision;if(!decision||typeof revision!=='number')return null
 const body:ReviewDecision={decision,expected_version:sourceDetail.version,expected_review_revision:revision}
 if(comment.value.trim())body.comment=comment.value.trim()
 if(decision==='approve')body.solution_kinds=hasFast.value&&confirmFast.value?['standard','fast']:['standard']
 return body
}
async function submit(): Promise<void> {
  const binding = captureSessionBinding()
  const decision = selected.value
  const revision = sourceDetail.review_revision
  if (decision === null || !isCurrentSessionBinding(binding) || !sourceKnown.value || typeof revision !== 'number') return
  const body: ReviewDecision = { decision, expected_version: sourceDetail.version, expected_review_revision: revision }
  const note = comment.value.trim()
  if (note) body.comment = note
  if (decision === 'approve') {
    body.solution_kinds = hasFast.value && confirmFast.value ? ['standard', 'fast'] : ['standard']
  }
  busy.value = true
  error.value = null
  try {
    const command=await recovery.run(body as unknown as Body,async(token,request,key)=>await reviewQuestion(token,sourceDetail.id,request as unknown as ReviewDecision,key) as unknown as Json)
    const result=command?.result as unknown as QuestionReviewState|undefined
    if (!isCurrentSessionBinding(binding)) return
    if(result)emit('decided', result, decision)
  } catch (failure) {
    if (!isCurrentSessionBinding(binding) || handleUnauthorized(failure, binding)) return
    if (failure instanceof ApiError) {
      const problems = failure.details.problems
      error.value = {
        code: failure.code,
        message: explainError(failure.code, failure.message),
        problems: Array.isArray(problems) ? problems.map(String) : [],
      }
    } else {
      error.value = { code: 'unknown', message: '出了点问题，请稍后重试', problems: [] }
    }
  } finally {
    if (isCurrentSessionBinding(binding)) busy.value = false
  }
}
async function retryWrite(){busy.value=true;try{const command=await recovery.retry(async(token,body,key)=>await reviewQuestion(token,sourceDetail.id,body as unknown as ReviewDecision,key) as unknown as Json);if(command?.result)emit('decided',command.result as unknown as QuestionReviewState,(command.body as unknown as ReviewDecision).decision)}catch(e){error.value={code:'recovery',message:String(e),problems:[]}}finally{busy.value=false}}
</script>

<template>
  <section class="card decision-panel" data-testid="decision-panel">
    <p role="status" data-testid="review-draft-state">{{ recovery.draftState.value }}</p>
    <p v-if="!sourceKnown" role="alert">缺少审核修订号，请刷新题目并重新明确确认，旧操作不会自动补值。</p>
    <section aria-label="审核操作恢复">
     <p v-if="recovery.message.value" role="status">{{ recovery.message.value }}</p>
     <button v-if="recovery.pending.value?.phase==='result_known'" data-testid="review-ack" @click="recovery.ack()">确认已保存的历史结果（无需网络）</button>
     <button v-else-if="recovery.pending.value" data-testid="review-retry" :disabled="busy" @click="retryWrite">恢复原审核命令</button>
     <details v-if="recovery.pending.value && recovery.pending.value.phase!=='result_known'"><summary>保留未知记录并停止本机重试</summary><p>原请求可能已成功。这里只停止本机重试，不取消服务器操作。新操作须另用新来源与新键。</p><button data-testid="review-release" @click="recovery.release()">明确保留旧未知记录，停止重试</button></details>
     <details v-if="recovery.branches.value.length"><summary>比较当前主草稿</summary><pre>{{ recovery.headRaw.value }}</pre></details>
     <button v-for="branch in recovery.branches.value" :key="branch.id" @click="recovery.loadBranch(branch.id)">载入独立审核意见分支</button>
     <button v-if="recovery.blocked.value" data-testid="review-adopt" @click="recovery.adopt()">保留旧意见并明确采用当前题目来源</button>
    </section>
    <h2>审核决策</h2><p v-if="detail.content.attachments.some(item=>item.media_id)">有图片附件时，须先逐图授权预览并记录本人当前版本的审校声明；批量操作也不会自动代替声明。</p>
    <p v-if="decisions.length === 0" class="muted">
      这道题已经下线。下线是终态，不能再做任何决策；要重新使用，需要提交一个新版本。
    </p>
    <template v-else>
      <div class="choices" role="radiogroup" aria-label="审核决策">
        <label v-for="decision in decisions" :key="decision" class="choice">
          <input v-model="selected" :disabled="!recovery.loaded.value" type="radio" name="decision" :value="decision" />
          <strong>{{ DECISION_LABEL[decision] }}</strong>
        </label>
      </div>
      <p v-if="selected" class="muted small">{{ DECISION_HELP[selected] }}</p>

      <fieldset v-if="selected === 'approve'" class="kinds">
        <legend>确认通过的解法</legend>
        <label><input type="checkbox" checked disabled /> 标准解法（必须确认）</label>
        <label v-if="hasFast">
          <input v-model="confirmFast" :disabled="!recovery.loaded.value" type="checkbox" data-testid="confirm-fast" />
          快速解法（适用条件与边界都看过了才勾选）
        </label>
        <p v-if="hasFast && !confirmFast" class="muted small">
          不勾选时，快速解法保持"未审核"，学生看不到。
        </p>
      </fieldset>

      <label class="field">
        <span>{{ needsComment ? '原因（必填）' : '备注（可选）' }}</span>
        <textarea v-model="comment" :disabled="!recovery.loaded.value" rows="3" maxlength="2000" data-testid="comment" />
      </label>

      <p v-if="blocked" class="notice warn" role="status" data-testid="blocked">{{ blocked }}</p>

      <button
        class="primary"
        type="button"
        data-testid="submit-decision"
        :disabled="!canSubmit"
        @click="submit"
      >
        {{ busy ? '提交中…' : selected ? DECISION_LABEL[selected] : '' }}
      </button>

      <div v-if="error" class="notice error" role="alert" data-testid="decision-error">
        <p>{{ error.message }}</p>
        <ul v-if="error.problems.length">
          <li v-for="problem in error.problems" :key="problem">{{ problem }}</li>
        </ul>
        <button v-if="staleError" type="button" class="link" @click="emit('refresh')">
          刷新题目
        </button>
      </div>
    </template>
  </section>
</template>






