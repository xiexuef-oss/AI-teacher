<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { getQuestion, getQuestionVersion } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized } from '../api/guard'
import type { AdminQuestionDetail, AdminVersionSnapshot } from '../api/types'
import FieldDiffView from '../components/FieldDiffView.vue'
import { compareSnapshots } from '../compare'
import { formatTime, shortId } from '../labels'
import { useSession } from '../session'

const route = useRoute()
const router = useRouter()
const session = useSession()

const detail = ref<AdminQuestionDetail | null>(null)
const left = ref<AdminVersionSnapshot | null>(null)
const right = ref<AdminVersionSnapshot | null>(null)
const from = ref(0)
const to = ref(0)
const showAll = ref(false)
const loading = ref(false)
const error = ref<string | null>(null)

const id = computed(() => String(route.params.id ?? ''))
const same = computed(() => from.value === to.value)
const comparison = computed(() => (left.value && right.value ? compareSnapshots(left.value, right.value) : null))
const everything = computed(() => showAll.value || same.value)
const visibleSections = computed(() =>
  (comparison.value?.sections ?? [])
    .filter((item) => everything.value || item.changed)
    .map((item) => ({ ...item, fields: item.fields.filter((field) => everything.value || field.changed) })),
)

function versionLabel(version: number): string {
  const entry = detail.value?.versions.find((item) => item.version === version)
  const current = detail.value?.version === version ? ' · 当前版本' : ''
  return `第 ${version} 版${current}${entry ? ` · 提交者 ${shortId(entry.created_by)} · ${formatTime(entry.created_at)}` : ''}`
}

function parseVersion(value: unknown, fallback: number): number {
  const number = Number(Array.isArray(value) ? value[0] : value)
  return Number.isInteger(number) && number >= 1 ? number : fallback
}

async function load(): Promise<void> {
  if (!session.session) return
  loading.value = true
  error.value = null
  try {
    if (detail.value === null || detail.value.id !== id.value) {
      detail.value = await getQuestion(session.session.token, id.value)
    }
    const current = detail.value.version
    to.value = parseVersion(route.query.to, current)
    from.value = parseVersion(route.query.from, Math.max(1, to.value - 1))
    showAll.value = route.query.all === '1'
    const [a, b] = await Promise.all([
      getQuestionVersion(session.session.token, id.value, from.value),
      getQuestionVersion(session.session.token, id.value, to.value),
    ])
    left.value = a
    right.value = b
  } catch (failure) {
    if (handleUnauthorized(failure)) return
    left.value = right.value = null
    error.value =
      failure instanceof ApiError
        ? failure.status === 404
          ? '没有这道题，或者没有这个版本。'
          : failure.message
        : '加载失败'
  } finally {
    loading.value = false
  }
}

watch(() => [route.params.id, route.query.from, route.query.to, route.query.all], () => void load(), {
  immediate: true,
})

function choose(): void {
  void router.replace({
    query: { from: String(from.value), to: String(to.value), ...(showAll.value ? { all: '1' } : {}) },
  })
}
</script>

<template>
  <main class="page">
    <p class="row">
      <RouterLink :to="{ name: 'question', params: { id } }" data-testid="back-question">← 返回这道题</RouterLink>
      <RouterLink :to="{ name: 'queue' }">审核队列</RouterLink>
    </p>
    <h1>版本对比<span v-if="detail">：{{ detail.title }}</span></h1>

    <p v-if="loading && !comparison" class="muted" role="status">加载中…</p>
    <p v-if="error" class="notice error" role="alert" data-testid="compare-error">{{ error }}</p>

    <template v-if="detail">
      <div class="card controls" data-testid="controls">
        <label>
          从
          <select v-model.number="from" data-testid="from" @change="choose">
            <option v-for="item in detail.versions" :key="item.version" :value="item.version">
              {{ versionLabel(item.version) }}
            </option>
          </select>
        </label>
        <label>
          到
          <select v-model.number="to" data-testid="to" @change="choose">
            <option v-for="item in detail.versions" :key="item.version" :value="item.version">
              {{ versionLabel(item.version) }}
            </option>
          </select>
        </label>
        <label class="inline">
          <input v-model="showAll" type="checkbox" data-testid="show-all" :disabled="same" @change="choose" />
          显示没有改动的部分
        </label>
      </div>

      <template v-if="comparison">
        <p v-if="same" class="notice info" data-testid="summary">
          选的是同一个版本，下面是它的完整内容（左右两边一样）。
        </p>
        <p v-else-if="!comparison.changed" class="notice info" data-testid="summary">这两个版本没有任何区别。</p>
        <p v-else class="notice warn" data-testid="summary">
          改动了：{{ comparison.changedTitles.join('、') }}
        </p>

        <section v-for="item in visibleSections" :key="item.key" class="card" :data-testid="`section-${item.key}`">
          <h2>{{ item.title }}</h2>
          <FieldDiffView
            v-for="field in item.fields"
            :key="field.key"
            :field="field"
            :left-label="`第 ${from} 版`"
            :right-label="`第 ${to} 版`"
          />
        </section>
      </template>
    </template>
  </main>
</template>
