<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { request } from '../api/client'
import { newIdempotencyKey } from '../api/guard'
import type { components } from '../api/schema'
import { useSession } from '../session'

type Draft = components['schemas']['ContentFactoryQuestionTypeDraft']
type Node = components['schemas']['ContentFactoryKnowledgeNode']
type Relation = Draft['knowledge'][number]['relation']
const state = useSession()
const subject = ref<Draft['subject']>('math')
const code = ref('')
const title = ref('')
const province = ref<NonNullable<Draft['province_code']> | ''>('')
const year = ref<number | ''>('')
const curriculum = ref('')
const specification = ref('{}')
const nodes = ref<Node[]>([])
const relations = ref<Record<string, Relation | ''>>({})
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const keys = new Map<string, string>()
let mounted = true
onBeforeUnmount(() => { mounted = false })

watch(subject, async (selected, _, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  const session = state.session
  nodes.value = []
  relations.value = {}
  message.value = ''
  if (!session) return
  loading.value = true
  try {
    const catalog = await request<components['schemas']['ContentFactoryKnowledgeCatalog']>(
      'GET', '/admin/content-factory/knowledge-nodes', { token: session.token, query: { subject: selected } },
    )
    if (current && state.session === session) nodes.value = catalog.items
  } catch {
    if (current && state.session === session) message.value = '暂时无法读取知识点。'
  } finally {
    if (current && state.session === session) loading.value = false
  }
}, { immediate: true })

async function save(): Promise<void> {
  const session = state.session
  if (!session || saving.value || loading.value) return
  let details: unknown
  try {
    details = JSON.parse(specification.value)
  } catch {
    message.value = '题型规格须为 JSON 对象。'
    return
  }
  if (!details || typeof details !== 'object' || Array.isArray(details)) {
    message.value = '题型规格须为 JSON 对象。'
    return
  }
  const knowledge = nodes.value.flatMap(({ id }) => {
    const relation = relations.value[id]
    return relation ? [{ knowledge_id: id, relation }] : []
  })
  if (!knowledge.length || knowledge.length > 50) {
    message.value = '请选择 1 至 50 个知识点关联。'
    return
  }
  const body: Draft = {
    code: code.value, title: title.value, subject: subject.value,
    specification: details as Draft['specification'], knowledge,
    ...(province.value && { province_code: province.value }),
    ...(year.value && { exam_year: year.value }),
    ...(curriculum.value && { curriculum_version: curriculum.value }),
  }
  const snapshot = JSON.stringify(body)
  const key = keys.get(snapshot) ?? newIdempotencyKey()
  keys.set(snapshot, key)
  saving.value = true
  message.value = ''
  try {
    const result = await request<components['schemas']['ContentFactoryQuestionTypeReceipt']>(
      'POST', '/admin/content-factory/question-types', { token: session.token, body, idempotencyKey: key },
    )
    if (mounted && state.session === session) message.value = `草稿已创建，题型 ID：${result.id}`
  } catch (error) {
    if (mounted && state.session === session) {
      message.value = error instanceof Error ? error.message : '暂时无法创建草稿。'
    }
  } finally {
    if (mounted && state.session === session) saving.value = false
  }
}
</script>

<template>
  <section class="card">
    <h2>创建题型草稿</h2>
    <form aria-label="题型草稿" @submit.prevent="save">
      <fieldset :disabled="saving">
        <legend>题型信息</legend>
        <label>学科
          <select v-model="subject">
            <option value="math">数学</option><option value="physics">物理</option><option value="chemistry">化学</option>
          </select>
        </label>
        <label>编码 <input v-model.trim="code" name="code" maxlength="90" required></label>
        <label>标题 <input v-model.trim="title" name="title" maxlength="200" required></label>
        <label>地区
          <select v-model="province">
            <option value="">未指定</option><option value="CN-51">四川</option><option value="CN-50">重庆</option>
          </select>
        </label>
        <label>考试年份 <input v-model.number="year" type="number" min="1" max="9999"></label>
        <label>教材版本 <input v-model.trim="curriculum" maxlength="80"></label>
        <label>题型规格（JSON） <textarea v-model="specification" rows="3" required></textarea></label>
        <fieldset :disabled="loading">
          <legend>关联知识点</legend>
          <p v-if="loading" role="status">正在读取知识点…</p>
          <label v-for="node in nodes" :key="node.id">
            {{ node.title }}
            <select v-model="relations[node.id]" :aria-label="`${node.title}的关联`">
              <option :value="undefined">未关联</option>
              <option value="primary">主要</option><option value="prerequisite">前置</option><option value="supporting">辅助</option>
            </select>
          </label>
        </fieldset>
        <button type="submit" :disabled="loading">创建草稿</button>
      </fieldset>
      <p v-if="message" role="status">{{ message }}</p>
    </form>
  </section>
</template>
