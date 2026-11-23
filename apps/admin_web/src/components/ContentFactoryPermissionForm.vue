<script setup lang="ts">
import { onBeforeUnmount, reactive, ref } from 'vue'
import { request } from '../api/client'
import { newIdempotencyKey } from '../api/guard'
import type { components } from '../api/schema'
import { useSession } from '../session'

type Review = components['schemas']['ContentFactoryPermissionReview']
const operations: Record<Review['operation'], string> = {
  read: '读取', internal_analysis: '内部分析', store_original: '保留原件',
  transform: '改编', generate_variants: '生成变式', print_pdf: '打印 PDF',
  commercial_distribution: '商业分发', send_to_external_ai: '发送给外部模型',
}
const state = useSession()
const form = reactive<Required<Review>>({
  source_id: '', operation: 'read', region_code: 'CN-51', decision: 'grant',
  evidence_ref: '', valid_from: '', valid_until: '',
})
const busy = ref(false)
const message = ref('')
const lookup = ref<{ sourceId: string; data: components['schemas']['ContentFactoryPermissionList'] }>()
const statuses = { scheduled: '未生效', active: '有效', expired: '已过期', revoked: '已撤回' }
const retryKeys = new Map<string, string>()
let mounted = true
onBeforeUnmount(() => { mounted = false })

async function loadPermissions(): Promise<void> {
  const session = state.session
  const sourceId = form.source_id
  if (!session || !sourceId || busy.value) return
  busy.value = true
  message.value = ''
  lookup.value = undefined
  try {
    const data = await request<components['schemas']['ContentFactoryPermissionList']>(
      'GET', '/admin/content-factory/source-permissions', { token: session.token, query: { source_id: sourceId } },
    )
    if (mounted && state.session === session) lookup.value = { sourceId, data }
  } catch (error) {
    if (mounted && state.session === session) {
      message.value = error instanceof Error ? error.message : '暂时无法查询许可'
    }
  } finally {
    if (mounted && state.session === session) busy.value = false
  }
}

async function submit(): Promise<void> {
  const session = state.session
  if (!session || busy.value) return
  const { source_id, operation, region_code, decision } = form
  const body: Review = { source_id, operation, region_code, decision }
  if (decision === 'grant') {
    const start = new Date(form.valid_from)
    const end = new Date(form.valid_until)
    if (!form.evidence_ref || !Number.isFinite(start.getTime()) || !(end > start)) {
      message.value = '请填写许可凭证，并确认结束时间晚于开始时间。'
      return
    }
    Object.assign(body, {
      evidence_ref: form.evidence_ref,
      valid_from: start.toISOString(),
      valid_until: end.toISOString(),
    })
  }
  const snapshot = JSON.stringify(body)
  const key = retryKeys.get(snapshot) ?? newIdempotencyKey()
  retryKeys.set(snapshot, key)
  busy.value = true
  message.value = ''
  lookup.value = undefined
  try {
    await request<components['schemas']['ContentFactorySourceReceipt']>(
      'POST', '/admin/content-factory/source-permissions', { token: session.token, body, idempotencyKey: key },
    )
    if (!mounted || state.session !== session) return
    retryKeys.delete(snapshot)
    message.value = decision === 'grant' ? '许可已核准' : '许可已撤回'
  } catch (error) {
    if (mounted && state.session === session) {
      message.value = error instanceof Error ? error.message : '暂时无法保存许可决定'
    }
  } finally {
    if (mounted && state.session === session) busy.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>题源许可审校</h2>
    <form @submit.prevent="submit">
      <fieldset :disabled="busy">
        <legend>许可范围和决定</legend>
        <label>题源 ID <input v-model.trim="form.source_id" name="source_id" required></label>
        <button type="button" :disabled="!form.source_id" @click="loadPermissions">查询当前许可</button>
        <label>地区
          <select v-model="form.region_code" name="region_code">
            <option value="CN-51">四川</option><option value="CN-50">重庆</option>
          </select>
        </label>
        <label>用途
          <select v-model="form.operation" name="operation">
            <option v-for="(label, operation) in operations" :key="operation" :value="operation">{{ label }}</option>
          </select>
        </label>
        <label>决定
          <select v-model="form.decision" name="decision">
            <option value="grant">核准</option><option value="revoke">撤回</option>
          </select>
        </label>
        <template v-if="form.decision === 'grant'">
          <label>许可凭证引用 <input v-model.trim="form.evidence_ref" name="evidence_ref" maxlength="512" required></label>
          <label>开始时间（本机时区） <input v-model="form.valid_from" type="datetime-local" name="valid_from" required></label>
          <label>结束时间（本机时区） <input v-model="form.valid_until" type="datetime-local" name="valid_until" required></label>
        </template>
        <button type="submit">{{ busy ? '保存中…' : '保存许可决定' }}</button>
      </fieldset>
    </form>
    <p v-if="message" role="status">{{ message }}</p>
    <template v-if="lookup && lookup.sourceId === form.source_id">
      <p v-if="!lookup.data.items.length" role="status">该题源暂无许可记录。</p>
      <ul v-else aria-label="当前许可">
        <li v-for="item in lookup.data.items" :key="item.region_code + item.operation">
          {{ item.region_code === 'CN-51' ? '四川' : '重庆' }} · {{ operations[item.operation] }} · {{ statuses[item.status] }}
          <div>{{ new Date(item.valid_from).toLocaleString() }} 至 {{ new Date(item.valid_until).toLocaleString() }}</div>
          <div>凭证 {{ item.evidence_ref }}</div>
        </li>
      </ul>
    </template>
  </section>
</template>
