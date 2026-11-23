<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { request } from '../api/client'
import { newIdempotencyKey } from '../api/guard'
import type { components } from '../api/schema'
import { useSession } from '../session'

type Registration = components['schemas']['ContentFactorySourceRegistration']
const state = useSession()
const title = ref('')
const sourceClass = ref<Registration['source_class']>('original')
const digest = ref('')
const result = ref('')
const busy = ref(false)
const attempts = new Map<string, string>()
let mounted = true
onBeforeUnmount(() => { mounted = false })

async function readDigest(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || busy.value) return
  const session = state.session
  busy.value = true
  result.value = ''
  digest.value = ''
  try {
    const bytes = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    if (mounted && state.session === session) {
      digest.value = Array.from(new Uint8Array(bytes), byte => byte.toString(16).padStart(2, '0')).join('')
    }
  } catch {
    if (mounted && state.session === session) result.value = '无法计算摘要，可手动输入 SHA-256。'
  } finally {
    if (mounted && state.session === session) busy.value = false
    input.value = ''
  }
}

async function register(): Promise<void> {
  const session = state.session
  if (!session || busy.value || !title.value || !/^[0-9a-f]{64}$/.test(digest.value)) return
  const body: Registration = { title: title.value, source_class: sourceClass.value, sha256: digest.value }
  const snapshot = JSON.stringify(body)
  const key = attempts.get(snapshot) ?? newIdempotencyKey()
  attempts.set(snapshot, key)
  busy.value = true
  result.value = ''
  try {
    const receipt = await request<components['schemas']['ContentFactorySourceReceipt']>(
      'POST', '/admin/content-factory/sources', { token: session.token, body, idempotencyKey: key },
    )
    if (mounted && state.session === session) {
      result.value = `题源已登记，待许可审校。题源 ID：${receipt.id}`
      title.value = ''
      digest.value = ''
    }
  } catch (error) {
    if (mounted && state.session === session) {
      result.value = error instanceof Error ? error.message : '暂时无法登记题源'
    }
  } finally {
    if (mounted && state.session === session) busy.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>登记教研题源</h2>
    <form @submit.prevent="register">
      <fieldset :disabled="busy">
        <legend>题源信息</legend>
        <label>资料标题 <input v-model.trim="title" name="title" required maxlength="255"></label>
        <label>
          来源类别
          <select v-model="sourceClass">
            <option value="original">自编</option>
            <option value="licensed">授权资料</option>
            <option value="open">开放许可资料</option>
            <option value="public_reference">公开参考资料</option>
          </select>
        </label>
        <label>选取文件计算摘要 <input type="file" @change="readDigest"></label>
        <label>
          SHA-256
          <input v-model.trim="digest" name="sha256" required pattern="[0-9a-f]{64}" maxlength="64">
        </label>
        <button type="submit">登记题源</button>
      </fieldset>
    </form>
    <p v-if="result" role="status">{{ result }}</p>
  </section>
</template>
