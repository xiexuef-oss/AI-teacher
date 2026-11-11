<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { reviewQuestion } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized, newIdempotencyKey } from '../api/guard'
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
import { useSession } from '../session'

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
let pending: { fingerprint: string; key: string } | null = null

const hasFast = computed(() => props.detail.solutions.some((solution) => solution.kind === 'fast'))
const blocked = computed(() =>
  selected.value && state.session
    ? blockedReason(props.detail, selected.value, state.session.userId)
    : null,
)
const needsComment = computed(() => (selected.value ? commentRequired(selected.value) : false))
const canSubmit = computed(
  () =>
    selected.value !== null &&
    !busy.value &&
    blocked.value === null &&
    (!needsComment.value || comment.value.trim().length > 0),
)
const staleError = computed(
  () => error.value?.code === 'version_conflict' || error.value?.code === 'invalid_transition',
)

// 状态或版本变了（刚做完一个决策，或者刷新到了新内容）：回到第一个可选的决策
watch(
  () => [props.detail.status, props.detail.version] as const,
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

async function submit(): Promise<void> {
  const decision = selected.value
  if (decision === null || !state.session) return
  const body: ReviewDecision = { decision, expected_version: props.detail.version }
  const note = comment.value.trim()
  if (note) body.comment = note
  if (decision === 'approve') {
    body.solution_kinds = hasFast.value && confirmFast.value ? ['standard', 'fast'] : ['standard']
  }
  // 同一个动作重试时复用幂等键；内容变了就是另一个动作
  const fingerprint = JSON.stringify(body)
  if (pending === null || pending.fingerprint !== fingerprint) {
    pending = { fingerprint, key: newIdempotencyKey() }
  }

  busy.value = true
  error.value = null
  try {
    const result = await reviewQuestion(state.session.token, props.detail.id, body, pending.key)
    pending = null
    comment.value = ''
    emit('decided', result, decision)
  } catch (failure) {
    if (handleUnauthorized(failure)) return
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
    busy.value = false
  }
}
</script>

<template>
  <section class="card decision-panel" data-testid="decision-panel">
    <h2>审核决策</h2>
    <p v-if="decisions.length === 0" class="muted">
      这道题已经下线。下线是终态，不能再做任何决策；要重新使用，需要提交一个新版本。
    </p>
    <template v-else>
      <div class="choices" role="radiogroup" aria-label="审核决策">
        <label v-for="decision in decisions" :key="decision" class="choice">
          <input v-model="selected" type="radio" name="decision" :value="decision" />
          <strong>{{ DECISION_LABEL[decision] }}</strong>
        </label>
      </div>
      <p v-if="selected" class="muted small">{{ DECISION_HELP[selected] }}</p>

      <fieldset v-if="selected === 'approve'" class="kinds">
        <legend>确认通过的解法</legend>
        <label><input type="checkbox" checked disabled /> 标准解法（必须确认）</label>
        <label v-if="hasFast">
          <input v-model="confirmFast" type="checkbox" data-testid="confirm-fast" />
          快速解法（适用条件与边界都看过了才勾选）
        </label>
        <p v-if="hasFast && !confirmFast" class="muted small">
          不勾选时，快速解法保持"未审核"，学生看不到。
        </p>
      </fieldset>

      <label class="field">
        <span>{{ needsComment ? '原因（必填）' : '备注（可选）' }}</span>
        <textarea v-model="comment" rows="3" maxlength="2000" data-testid="comment" />
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
