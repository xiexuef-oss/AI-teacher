<script setup lang="ts">
import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { request } from '../api/client'
import { newIdempotencyKey } from '../api/guard'
import type { components } from '../api/schema'
import { useSession } from '../session'

type Upload = components['schemas']['ContentFactoryOriginalUpload']
const state = useSession()
const sourceId = ref('')
const region = ref<Upload['region_code']>('CN-51')
const selectedFile = shallowRef<File>()
const fileInput = ref<HTMLInputElement>()
const busy = ref(false)
const message = ref('')
const attempts = new WeakMap<File, Map<string, string>>()
let mounted = true
onBeforeUnmount(() => { mounted = false })

function selectFile(event: Event): void {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0]
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).slice(String(reader.result).indexOf(',') + 1))
    reader.onerror = () => reject(new Error('读取文件失败。'))
    reader.readAsDataURL(file)
  })
}

async function upload(): Promise<void> {
  const session = state.session
  const file = selectedFile.value
  const id = sourceId.value
  const regionCode = region.value
  if (!session || !file || !id || busy.value) return
  if (file.size === 0 || file.size > 16 * 1024 * 1024) {
    message.value = '请选择非空且不超过 16 MiB 的文件。'
    return
  }
  const scope = JSON.stringify([id, regionCode])
  const keys = attempts.get(file) ?? new Map<string, string>()
  attempts.set(file, keys)
  const key = keys.get(scope) ?? newIdempotencyKey()
  keys.set(scope, key)
  busy.value = true
  message.value = ''
  try {
    const body: Upload = {
      filename: file.name,
      content_base64: await readBase64(file),
      region_code: regionCode,
    }
    if (!mounted || state.session !== session) return
    const result = await request<components['schemas']['ContentFactoryOriginalReceipt']>(
      'POST', `/admin/content-factory/sources/${encodeURIComponent(id)}/original`,
      { token: session.token, body, idempotencyKey: key },
    )
    if (!mounted || state.session !== session) return
    keys.delete(scope)
    message.value = `原件已暂存，到期时间 ${new Date(result.expires_at).toLocaleString()}`
    selectedFile.value = undefined
    if (fileInput.value) fileInput.value.value = ''
  } catch (error) {
    if (mounted && state.session === session) {
      message.value = error instanceof Error ? error.message : '暂时无法上传原件。'
    }
  } finally {
    if (mounted && state.session === session) busy.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>上传题源原件</h2>
    <p>选择与登记摘要一致、已取得留存许可的原件。</p>
    <form aria-label="上传题源原件" @submit.prevent="upload">
      <fieldset :disabled="busy">
        <legend>原件与授权地区</legend>
        <label>题源 ID <input v-model.trim="sourceId" name="source_id" required></label>
        <label>地区
          <select v-model="region">
            <option value="CN-51">四川</option><option value="CN-50">重庆</option>
          </select>
        </label>
        <label>原件 <input ref="fileInput" type="file" required @change="selectFile"></label>
        <button type="submit">{{ busy ? '上传中…' : '上传原件' }}</button>
      </fieldset>
    </form>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
