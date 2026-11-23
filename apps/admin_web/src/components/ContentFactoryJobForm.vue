<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { request } from '../api/client'
import { newIdempotencyKey } from '../api/guard'
import type { components } from '../api/schema'
import { useSession } from '../session'

type JobState = components['schemas']['ContentFactoryJobState']
type JobRequest = components['schemas']['ContentFactoryJobRequest']
const path = '/admin/content-factory/jobs'
const state = useSession()
const sourceId = ref('')
const region = ref<JobRequest['region_code']>('CN-51')
const jobId = ref('')
const job = ref<JobState>()
const busy = ref(false)
const message = ref('')
const retryKeys = new Map<string, string>()
const statuses: Record<JobState['status'], string> = {
  queued: '排队中', running: '执行中', retry_wait: '等待重试',
  review_required: '待审核', failed: '失败', cancelled: '已取消',
}
const sourceClasses = {
  original: '自编', licensed: '授权资料', open: '开放许可资料', public_reference: '公开参考资料',
}
const currentJob = computed(() => job.value?.id === jobId.value.toLowerCase() ? job.value : undefined)
const canCancel = computed(() => {
  const status = currentJob.value?.status
  return status === 'queued' || status === 'running' || status === 'retry_wait'
})
let mounted = true
onBeforeUnmount(() => { mounted = false })

async function send(method: 'GET' | 'POST', url: string, body?: JobRequest): Promise<void> {
  const session = state.session
  if (!session || busy.value) return
  const snapshot = JSON.stringify([url, body])
  const key = method === 'POST' ? retryKeys.get(snapshot) ?? newIdempotencyKey() : undefined
  if (key) retryKeys.set(snapshot, key)
  busy.value = true
  message.value = ''
  try {
    const result = await request<JobState>(method, url, {
      token: session.token,
      ...(body && { body }),
      ...(key && { idempotencyKey: key }),
    })
    if (!mounted || state.session !== session) return
    retryKeys.delete(snapshot)
    job.value = result
    jobId.value = result.id
  } catch (error) {
    if (mounted && state.session === session) {
      message.value = error instanceof Error ? error.message : '暂时无法操作教研任务。'
    }
  } finally {
    if (mounted && state.session === session) busy.value = false
  }
}

function submit(): void {
  if (sourceId.value) {
    void send('POST', path, { kind: 'analyze_source', source_id: sourceId.value, region_code: region.value })
  }
}

function refresh(): void {
  if (jobId.value) void send('GET', `${path}/${encodeURIComponent(jobId.value)}`)
}

function cancel(): void {
  if (canCancel.value) void send('POST', `${path}/${encodeURIComponent(jobId.value)}/cancel`)
}
</script>

<template>
  <section class="card">
    <h2>题源分析任务</h2>
    <form aria-label="提交题源分析" @submit.prevent="submit">
      <fieldset :disabled="busy">
        <legend>提交题源分析</legend>
        <label>题源 ID <input v-model.trim="sourceId" required></label>
        <label>授权地区
          <select v-model="region">
            <option value="CN-51">四川</option><option value="CN-50">重庆</option>
          </select>
        </label>
        <button type="submit">提交分析</button>
      </fieldset>
    </form>
    <form aria-label="查询教研任务" @submit.prevent="refresh">
      <label>任务 ID <input v-model.trim="jobId" required :disabled="busy"></label>
      <button type="submit" :disabled="busy">查询状态</button>
    </form>
    <p v-if="currentJob" role="status">
      {{ statuses[currentJob.status] }} · 已尝试 {{ currentJob.attempts }} 次
    </p>
    <dl v-if="currentJob?.result">
      <dt>元数据检查结果</dt><dd>{{ currentJob.result.title }}</dd>
      <dt>题源 ID</dt><dd>{{ currentJob.result.source_id }}</dd>
      <dt>地区</dt><dd>{{ currentJob.result.region_code === 'CN-51' ? '四川' : '重庆' }}</dd>
      <dt>来源类别</dt><dd>{{ sourceClasses[currentJob.result.source_class] }}</dd>
      <dt>SHA-256</dt><dd class="mono">{{ currentJob.result.sha256 }}</dd>
      <template v-if="currentJob.result.document">
        <dt>正文检查</dt>
        <dd>
          {{ currentJob.result.document.pages }} 页 · {{ currentJob.result.document.text_chars }} 字符 ·
          {{ currentJob.result.document.needs_ocr_pages }} 页待 OCR
        </dd>
        <template v-if="currentJob.result.document.knowledge_suggestions?.length">
          <dt>待审核知识点</dt>
          <dd>
            <ul>
              <li v-for="candidate in currentJob.result.document.knowledge_suggestions" :key="candidate.knowledge_id">
                {{ candidate.title }} · 页码 {{ candidate.matched_pages.join('、') }}
              </li>
            </ul>
          </dd>
        </template>
      </template>
    </dl>
    <button v-if="canCancel" type="button" data-testid="cancel-content-factory-job" :disabled="busy" @click="cancel">
      取消任务
    </button>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
