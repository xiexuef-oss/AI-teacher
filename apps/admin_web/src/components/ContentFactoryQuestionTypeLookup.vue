<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { request } from '../api/client'
import { newIdempotencyKey } from '../api/guard'
import type { components } from '../api/schema'
import { useSession } from '../session'

const state = useSession()
const props = defineProps<{ canReview: boolean }>()
const query = ref('')
const detail = ref<components['schemas']['ContentFactoryQuestionTypeDetail']>()
const busy = ref(false)
const message = ref('')
const notes = ref('')
const reviewKeys = new Map<string, string>()
const statuses = { draft: '草稿', approved: '已审校', deprecated: '已停用' }
const subjects = { math: '数学', physics: '物理', chemistry: '化学' }
const relations = { primary: '主要', prerequisite: '前置', supporting: '辅助' }
let mounted = true
onBeforeUnmount(() => { mounted = false })

async function lookup(): Promise<void> {
  const session = state.session
  if (!session || !query.value || busy.value) return
  busy.value = true
  detail.value = undefined
  message.value = ''
  notes.value = ''
  try {
    const item = await request<components['schemas']['ContentFactoryQuestionTypeDetail']>(
      'GET', `/admin/content-factory/question-types/${encodeURIComponent(query.value)}`,
      { token: session.token },
    )
    if (mounted && state.session === session) detail.value = item
  } catch (error) {
    if (mounted && state.session === session) {
      message.value = error instanceof Error ? error.message : '暂时无法查询题型。'
    }
  } finally {
    if (mounted && state.session === session) busy.value = false
  }
}

async function review(): Promise<void> {
  const session = state.session
  const item = detail.value
  if (!props.canReview || !session || busy.value || !notes.value ||
      !item || item.id !== query.value.toLowerCase() || item.status === 'deprecated') return
  const body: components['schemas']['ContentFactoryQuestionTypeReview'] = {
    decision: item.status === 'draft' ? 'approve' : 'deprecate',
    notes: notes.value,
  }
  const snapshot = JSON.stringify([item.id, body])
  const key = reviewKeys.get(snapshot) ?? newIdempotencyKey()
  reviewKeys.set(snapshot, key)
  busy.value = true
  message.value = ''
  try {
    const result = await request<components['schemas']['ContentFactoryQuestionTypeDetail']>(
      'POST', `/admin/content-factory/question-types/${encodeURIComponent(item.id)}/review`,
      { token: session.token, body, idempotencyKey: key },
    )
    if (!mounted || state.session !== session) return
    reviewKeys.delete(snapshot)
    detail.value = result
    notes.value = ''
    message.value = '审校决定已保存'
  } catch (error) {
    if (mounted && state.session === session) {
      message.value = error instanceof Error ? error.message : '暂时无法保存审校决定。'
    }
  } finally {
    if (mounted && state.session === session) busy.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>查询题型</h2>
    <form aria-label="查询题型" @submit.prevent="lookup">
      <label>题型 ID <input v-model.trim="query" required :disabled="busy"></label>
      <button type="submit" :disabled="busy">{{ busy ? '查询中…' : '查询' }}</button>
    </form>
    <p v-if="message" role="status">{{ message }}</p>
    <template v-if="detail && detail.id === query.toLowerCase()">
      <h3>{{ detail.definition.title }} · {{ statuses[detail.status] }}</h3>
      <dl>
        <dt>编码</dt><dd>{{ detail.definition.code }}</dd>
        <dt>学科</dt><dd>{{ subjects[detail.definition.subject] }}</dd>
        <dt v-if="detail.definition.province_code">地区</dt>
        <dd v-if="detail.definition.province_code">{{ detail.definition.province_code === 'CN-51' ? '四川' : '重庆' }}</dd>
        <dt v-if="detail.definition.exam_year">考试年份</dt>
        <dd v-if="detail.definition.exam_year">{{ detail.definition.exam_year }}</dd>
        <dt v-if="detail.definition.curriculum_version">教材版本</dt>
        <dd v-if="detail.definition.curriculum_version">{{ detail.definition.curriculum_version }}</dd>
      </dl>
      <h4>知识点关联</h4>
      <ul>
        <li v-for="link in detail.definition.knowledge" :key="link.knowledge_id + link.relation">
          {{ relations[link.relation] }} · {{ link.knowledge_id }}
        </li>
      </ul>
      <h4>题型规格</h4>
      <pre>{{ JSON.stringify(detail.definition.specification, null, 2) }}</pre>
      <form v-if="canReview && detail.status !== 'deprecated'" aria-label="审校题型" @submit.prevent="review">
        <label>审校意见
          <textarea v-model.trim="notes" rows="3" required maxlength="1000" :disabled="busy"></textarea>
        </label>
        <button type="submit" :disabled="busy">{{ detail.status === 'draft' ? '核准题型' : '停用题型' }}</button>
      </form>
    </template>
  </section>
</template>
