<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { getQuestion } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized } from '../api/guard'
import type { AdminQuestionDetail, QuestionReviewState, ReviewDecisionType, Subject } from '../api/types'
import DecisionPanel from '../components/DecisionPanel.vue'
import QuestionEditor from '../components/QuestionEditor.vue'
import MathText from '../components/MathText.vue'
import StatusBadge from '../components/StatusBadge.vue'
import { canEdit, DECISION_LABEL, HISTORY_LABEL, PART_LABEL } from '../decisions'
import { formatTime, MODE_LABEL, shortId, SOLUTION_LABEL, SUBJECT_LABEL } from '../labels'
import { useSession } from '../session'

const route = useRoute()
const session = useSession()
const detail = ref<AdminQuestionDetail | null>(null)
const loading = ref(false)
const error = ref<{ status: number; message: string } | null>(null)
const done = ref<string | null>(null)
const savedVersion = ref<number | null>(null)
const editing = ref(false)

const id = computed(() => String(route.params.id ?? ''))
const answerRows = computed<[string, string][]>(() => {
  const value = detail.value?.answer.value
  if (Array.isArray(value)) return [['正确选项', value.map(String).join('、')]]
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>).map(([key, answer]) => [
      `空 ${key}`,
      String(answer),
    ])
  }
  return []
})
const visualParams = computed(() =>
  Object.entries(detail.value?.teaching.visual?.params ?? {})
    .map(([key, value]) => `${key} = ${value}`)
    .join('，'),
)

async function load(): Promise<void> {
  if (!session.session) return
  loading.value = true
  error.value = null
  try {
    detail.value = await getQuestion(session.session.token, id.value)
  } catch (failure) {
    if (handleUnauthorized(failure)) return
    detail.value = null
    error.value =
      failure instanceof ApiError
        ? { status: failure.status, message: failure.status === 404 ? '没有这道题。' : failure.message }
        : { status: 0, message: '加载失败' }
  } finally {
    loading.value = false
  }
}

watch(id, () => void load(), { immediate: true })

async function decided(_state: QuestionReviewState, decision: ReviewDecisionType): Promise<void> {
  done.value = `已执行：${DECISION_LABEL[decision]}`
  savedVersion.value = null
  await load()
}

async function refresh(): Promise<void> {
  done.value = null
  savedVersion.value = null
  await load()
}

function saved(next: AdminQuestionDetail): void {
  detail.value = next
  editing.value = false
  done.value = `已保存为第 ${next.version} 版，状态回到待审；要由另一位审校员重新二审`
  savedVersion.value = next.version
}
</script>

<template>
  <main class="page">
    <p><RouterLink :to="{ name: 'queue' }">← 返回审核队列</RouterLink></p>
    <p v-if="loading && !detail" class="muted" role="status">加载中…</p>
    <p v-if="error" class="notice error" role="alert" data-testid="load-error">{{ error.message }}</p>

    <div v-if="detail" class="layout" :class="{ wide: editing }">
      <div class="main">
        <header class="card head">
          <h1>{{ detail.title }}</h1>
          <p>
            <StatusBadge :status="detail.status" />
            <span class="meta">
              {{ SUBJECT_LABEL[detail.subject as Subject] ?? detail.subject }} · {{ MODE_LABEL[detail.answer_mode] }} ·
              难度 {{ detail.difficulty }} · 第 {{ detail.version }} 版
            </span>
          </p>
          <p class="notice info small" data-testid="source">
            来源：{{ detail.source.label }}（许可：{{ detail.source.source_license }}）
          </p>
          <p v-if="!editing" class="row">
            <button
              type="button"
              data-testid="edit"
              :disabled="!canEdit(detail.status)"
              @click="editing = true"
            >
              编辑题目
            </button>
            <span v-if="!canEdit(detail.status)" class="muted small">已上线的题要先下线，才能修改。</span>
          </p>
          <p class="meta small">
            提交者 <span class="mono">{{ shortId(detail.created_by) }}</span> · 审校人
            <span class="mono">{{ shortId(detail.reviewed_by) }}</span> · 上线时间 {{ formatTime(detail.published_at) }} ·
            更新 {{ formatTime(detail.updated_at) }}
          </p>
        </header>

        <p v-if="done" class="notice success" role="status" data-testid="done">
          {{ done }}
          <RouterLink
            v-if="savedVersion !== null && savedVersion > 1"
            data-testid="saved-compare"
            :to="{
              name: 'compare',
              params: { id: detail.id },
              query: { from: String(savedVersion - 1), to: String(savedVersion) },
            }"
          >
            查看这次改了什么
          </RouterLink>
        </p>

        <section class="card" data-testid="checks">
          <h2>程序校验</h2>
          <p v-if="detail.check_problems.length === 0" class="ok">
            ✓ 通过：结构完整、答案能通过自己的判定规则、提示与错项分析不泄题、解法条件齐全、图解参数在白名单内。
          </p>
          <template v-else>
            <p class="bad">发现 {{ detail.check_problems.length }} 个问题，修改后才能二审或上线：</p>
            <ul class="problems">
              <li v-for="problem in detail.check_problems" :key="problem">{{ problem }}</li>
            </ul>
          </template>
          <p class="muted small">程序校验只能保证结构自洽，学科内容本身对不对要靠你审。</p>
        </section>

        <template v-if="!editing">
        <section class="card">
          <h2>题面</h2>
          <p class="stem"><MathText :text="detail.content.stem" /></p>
          <ul v-if="detail.content.options.length" class="options">
            <li v-for="option in detail.content.options" :key="option.key">
              <strong>{{ option.key }}</strong> <MathText :text="option.text" />
            </li>
          </ul>
          <ul v-if="detail.content.blanks.length" class="options">
            <li v-for="blank in detail.content.blanks" :key="blank.key">
              空 <strong>{{ blank.key }}</strong>
              <span v-if="blank.unit_hint" class="muted">（{{ blank.unit_hint }}）</span>
            </li>
          </ul>
        </section>

        <section class="card">
          <h2>答案</h2>
          <dl class="kv">
            <template v-for="[label, value] in answerRows" :key="label">
              <dt>{{ label }}</dt>
              <dd><MathText :text="value" /></dd>
            </template>
          </dl>
          <details
            v-if="Object.keys(detail.answer.equivalence_rules).length || Object.keys(detail.answer.units).length"
          >
            <summary>判定规则与单位</summary>
            <pre>{{
              JSON.stringify(
                { equivalence_rules: detail.answer.equivalence_rules, units: detail.answer.units },
                null,
                2,
              )
            }}</pre>
          </details>
        </section>

        <section
          v-for="solution in detail.solutions"
          :key="solution.kind"
          class="card"
          :data-testid="`solution-${solution.kind}`"
        >
          <h2>
            {{ SOLUTION_LABEL[solution.kind] }}
            <span class="badge" :class="solution.reviewed ? 'badge-published' : 'badge-draft'">
              {{ solution.reviewed ? `已审核 · ${shortId(solution.reviewed_by)}` : '未审核' }}
            </span>
          </h2>
          <template v-if="solution.conditions">
            <p class="small"><strong>适用条件</strong></p>
            <ul>
              <li v-for="condition in solution.conditions" :key="condition">
                <MathText :text="condition" />
              </li>
            </ul>
            <p v-if="solution.boundary" class="small">
              <strong>不适用的情形</strong>：<MathText :text="solution.boundary" />
            </p>
          </template>
          <ol class="steps">
            <li v-for="step in solution.steps" :key="step"><MathText :text="step" /></li>
          </ol>
          <p><strong>答案</strong>：<MathText :text="solution.final_answer" /></p>
          <ul v-if="solution.key_points.length" class="points">
            <li v-for="point in solution.key_points" :key="point">{{ point }}</li>
          </ul>
        </section>

        <section class="card">
          <h2>教学辅助</h2>
          <p v-if="detail.teaching.concept"><strong>知识点讲解</strong>：{{ detail.teaching.concept }}</p>
          <p class="small"><strong>分层提示</strong>（不能泄露答案）</p>
          <ol class="steps">
            <li v-for="hint in detail.teaching.hints" :key="hint"><MathText :text="hint" /></li>
          </ol>
          <p v-if="detail.teaching.concept_rephrase" class="small">
            <strong>换种讲法</strong>：<MathText :text="detail.teaching.concept_rephrase" />
          </p>
          <template v-if="Object.keys(detail.teaching.option_analysis).length">
            <p class="small"><strong>选项分析</strong></p>
            <ul>
              <li v-for="(text, key) in detail.teaching.option_analysis" :key="key">
                <strong>{{ key }}</strong> <MathText :text="text" />
              </li>
            </ul>
          </template>
          <p v-if="detail.teaching.visual" class="small">
            <strong>图解</strong>：{{ detail.teaching.visual.template_id }}（{{ visualParams }}）——
            {{ detail.teaching.visual.caption }}
          </p>
        </section>

        <section class="card">
          <h2>知识点与地区标记</h2>
          <p>
            <span v-for="node in detail.knowledge" :key="node.id" class="badge">{{ node.title }}</span>
            <span v-if="detail.knowledge.length === 0" class="muted">没有关联知识点</span>
          </p>
          <ul v-if="detail.region_tags.length">
            <li v-for="tag in detail.region_tags" :key="tag.recommended_region_code">
              推荐地区 {{ tag.recommended_region_code }}
              <template v-if="tag.exam_year_from || tag.exam_year_to">
                · 考试年份 {{ tag.exam_year_from ?? '…' }}–{{ tag.exam_year_to ?? '…' }}
              </template>
              · {{ tag.review_status === 'approved' ? '已审核' : `审核状态：${tag.review_status}` }}
              <span v-if="tag.note" class="muted">（{{ tag.note }}）</span>
            </li>
          </ul>
          <p v-else class="muted small">没有地区标记，按"全国通用基础题"处理。</p>
        </section>
        </template>
        <QuestionEditor
          v-else
          :key="detail.version"
          :detail="detail"
          @saved="saved"
          @cancel="editing = false"
          @refresh="refresh"
        />

        <section class="card" data-testid="history">
          <h2>版本与审核历史</h2>
          <p class="small">
            版本：
            <RouterLink
              v-for="version in detail.versions"
              :key="version.version"
              class="badge"
              :data-testid="`version-${version.version}`"
              :title="`查看第 ${version.version} 版的完整内容`"
              :to="{
                name: 'compare',
                params: { id: detail.id },
                query: { from: String(version.version), to: String(version.version), all: '1' },
              }"
            >
              v{{ version.version }} · {{ formatTime(version.created_at) }}
            </RouterLink>
          </p>
          <p v-if="detail.versions.length > 1" class="small">
            <RouterLink
              data-testid="compare-latest"
              :to="{
                name: 'compare',
                params: { id: detail.id },
                query: { from: String(detail.version - 1), to: String(detail.version) },
              }"
            >
              对比最近两个版本
            </RouterLink>
          </p>
          <ol v-if="detail.history.length" class="history">
            <li v-for="entry in detail.history" :key="entry.id">
              <strong>{{ HISTORY_LABEL[entry.action] }}</strong>
              <span class="muted">
                {{ entry.from_status ?? '—' }} → {{ entry.to_status ?? '—' }} · 第 {{ entry.version ?? '?' }} 版 ·
                <span class="mono">{{ shortId(entry.actor_id) }}</span> · {{ formatTime(entry.created_at) }}
              </span>
              <p v-if="entry.changes && entry.changes.length" class="small">
                改动了：{{ entry.changes.map((part) => PART_LABEL[part] ?? part).join('、') }}
                <RouterLink
                  v-if="entry.version !== null && entry.version > 1"
                  :data-testid="`compare-entry-${entry.version}`"
                  :to="{
                    name: 'compare',
                    params: { id: detail.id },
                    query: { from: String(entry.version - 1), to: String(entry.version) },
                  }"
                >
                  与上一版对比
                </RouterLink>
              </p>
              <p v-if="entry.comment" class="comment">{{ entry.comment }}</p>
            </li>
          </ol>
          <p v-else class="muted small">还没有审核记录。</p>
        </section>
      </div>

      <aside v-if="!editing" class="side">
        <DecisionPanel :detail="detail" @decided="decided" @refresh="refresh" />
      </aside>
    </div>
  </main>
</template>
