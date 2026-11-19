<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { listQuestions } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized } from '../api/guard'
import type { AdminQuestionSummary, AdminStatusCounts, QuestionStatus, Subject } from '../api/types'
import StatusBadge from '../components/StatusBadge.vue'
import { STATUS_LABEL } from '../decisions'
import { formatTime, MODE_LABEL, shortId, SUBJECT_LABEL } from '../labels'
import { useSession } from '../session'

type Tab = QuestionStatus | 'all'
const TABS: Tab[] = ['draft', 'reviewed', 'published', 'withdrawn', 'all']

const router = useRouter()
const session = useSession()
const tab = ref<Tab>('draft')
const subject = ref<Subject | ''>('')
const items = ref<AdminQuestionSummary[]>([])
const counts = ref<AdminStatusCounts | null>(null)
const cursor = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const selected = ref<string[]>([])
function toggle(id: string) { selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : selected.value.length < 50 ? [...selected.value,id] : selected.value }

const tabLabel = (value: Tab): string => (value === 'all' ? '全部' : STATUS_LABEL[value])
const tabCount = (value: Tab): number | null => {
  const c = counts.value
  if (!c) return null
  return value === 'all' ? c.draft + c.reviewed + c.published + c.withdrawn : c[value]
}
const emptyText = computed(() =>
  tab.value === 'draft' ? '没有待审的题。' : `没有"${tabLabel(tab.value)}"的题。`,
)

async function load(append: boolean): Promise<void> {
  if (!session.session) return
  loading.value = true
  error.value = null
  try {
    const page = await listQuestions(session.session.token, {
      status: tab.value === 'all' ? undefined : tab.value,
      subject: subject.value || undefined,
      cursor: append ? cursor.value : undefined,
      limit: 20,
    })
    items.value = append ? [...items.value, ...page.items] : page.items
    counts.value = page.status_counts
    cursor.value = page.next_cursor
  } catch (failure) {
    if (handleUnauthorized(failure)) return
    error.value = failure instanceof ApiError ? failure.message : '加载失败'
  } finally {
    loading.value = false
  }
}

watch([tab, subject], () => void load(false), { immediate: true })

function open(id: string): void {
  void router.push({ name: 'question', params: { id } })
}
</script>

<template>
  <main class="page">
    <header class="page-head">
      <h1>审核队列</h1>
      <RouterLink :to="{ name: 'import' }">导入题目</RouterLink>
      <label class="inline">
        学科
        <select v-model="subject" data-testid="subject">
          <option value="">全部</option>
          <option v-for="(label, code) in SUBJECT_LABEL" :key="code" :value="code">{{ label }}</option>
        </select>
      </label>
    </header>

    <RouterLink v-if="selected.length" :to="{name:'batch-review',query:{ids:selected.join(',')}}">逐题确认批量审核（{{selected.length}}/50）</RouterLink>
    <nav class="tabs" role="tablist" aria-label="状态">
      <button
        v-for="value in TABS"
        :key="value"
        type="button"
        role="tab"
        class="tab"
        :class="{ active: tab === value }"
        :aria-selected="tab === value"
        :data-testid="`tab-${value}`"
        @click="tab = value"
      >
        {{ tabLabel(value) }}
        <span v-if="tabCount(value) !== null" class="count">{{ tabCount(value) }}</span>
      </button>
    </nav>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>

    <table v-if="items.length" class="queue" data-testid="queue">
      <thead>
        <tr>
          <th>选择</th><th>题目</th>
          <th>学科 / 题型</th>
          <th>难度</th>
          <th>来源</th>
          <th>状态</th>
          <th>版本</th>
          <th>提交者</th>
          <th>更新</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in items" :key="item.id" class="row-link" tabindex="0" @click="open(item.id)" @keydown.enter="open(item.id)">
<td @click.stop @keydown.enter.stop><input type="checkbox" :aria-label="`选择 ${item.title}`" :checked="selected.includes(item.id)" @change="toggle(item.id)" /></td>
          <td class="title">{{ item.title }}</td>
          <td>{{ SUBJECT_LABEL[item.subject as Subject] ?? item.subject }} · {{ MODE_LABEL[item.answer_mode] }}</td>
          <td>{{ item.difficulty }}</td>
          <td>{{ item.source.label }}</td>
          <td><StatusBadge :status="item.status" /></td>
          <td>v{{ item.version }}</td>
          <td class="mono">{{ shortId(item.created_by) }}</td>
          <td>{{ formatTime(item.updated_at) }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="!loading && !error" class="muted empty" data-testid="empty">{{ emptyText }}</p>

    <p v-if="loading" class="muted" role="status">加载中…</p>
    <button v-if="cursor && !loading" type="button" class="more" data-testid="more" @click="load(true)">
      加载更多
    </button>
  </main>
</template>
