<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { createQuestionVersion } from '../api/admin'
import { ApiError } from '../api/client'
import { handleUnauthorized, newIdempotencyKey } from '../api/guard'
import type { AdminQuestionDetail } from '../api/types'
import { explainError } from '../decisions'
import { canonical, formFromDetail, isUnchanged, requestFromForm } from '../editing'
import { useSession } from '../session'
import MathText from './MathText.vue'
import StringList from './StringList.vue'

const props = defineProps<{ detail: AdminQuestionDetail }>()
const emit = defineEmits<{ saved: [detail: AdminQuestionDetail]; cancel: []; refresh: [] }>()

const session = useSession()
const form = reactive(formFromDetail(props.detail))
const saving = ref(false)
const failure = ref<{ code: string; message: string; lines: string[] } | null>(null)
let pending: { fingerprint: string; key: string } | null = null

const isChoice = computed(() => ['single_choice', 'multiple_choice'].includes(props.detail.answer_mode))
const isFill = computed(() => props.detail.answer_mode === 'fill')
const isWritten = computed(() => props.detail.answer_mode === 'written')
// "所属小问"只能选已经有键的小问
const partChoices = computed(() => form.subquestions.filter((row) => row.key.trim() !== ''))
const built = computed(() => requestFromForm(form, props.detail))
const unchanged = computed(() => built.value.ok && isUnchanged(built.value.body, props.detail))
const canSave = computed(() => !saving.value && built.value.ok && !unchanged.value)
const stale = computed(
  () => failure.value?.code === 'version_conflict' || failure.value?.code === 'invalid_transition',
)

function addOption(): void {
  const used = new Set(form.options.map((row) => row.key))
  const key = 'ABCDEFGHIJKL'.split('').find((letter) => !used.has(letter)) ?? `O${form.options.length + 1}`
  form.options.push({ key, text: '', analysis: '', correct: false })
}

function addBlank(): void {
  form.blanks.push({ key: `b${form.blanks.length + 1}`, label: '', unitHint: '', placeholder: '', answer: '' })
}

function addSubquestion(): void {
  const used = new Set(form.subquestions.map((row) => row.key))
  let next = form.subquestions.length + 1
  while (used.has(String(next))) next += 1
  form.subquestions.push({ key: String(next), stem: '', answer: '' })
}

function addPoint(): void {
  const used = new Set(form.points.map((row) => row.key))
  let next = form.points.length + 1
  while (used.has(`p${next}`)) next += 1
  form.points.push({ key: `p${next}`, part: '', text: '' })
}

async function save(): Promise<void> {
  const result = built.value
  if (!result.ok || !session.session) return
  // 同一次保存重试时复用幂等键；内容变了就是另一次保存
  const fingerprint = canonical(result.body)
  if (pending === null || pending.fingerprint !== fingerprint) {
    pending = { fingerprint, key: newIdempotencyKey() }
  }
  saving.value = true
  failure.value = null
  try {
    const saved = await createQuestionVersion(session.session.token, props.detail.id, result.body, pending.key)
    pending = null
    emit('saved', saved)
  } catch (error) {
    if (handleUnauthorized(error)) return
    if (error instanceof ApiError) {
      const items = error.details.errors
      const lines = Array.isArray(items)
        ? items.map((item) => {
            const entry = item as { field?: string; message?: string }
            return `${entry.field ?? ''}${entry.field ? '：' : ''}${entry.message ?? JSON.stringify(item)}`
          })
        : []
      failure.value = { code: error.code, message: explainError(error.code, error.message), lines }
    } else {
      failure.value = { code: 'unknown', message: '保存失败，请稍后重试', lines: [] }
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="card editor" data-testid="editor">
    <h2>修改题目（保存后是第 {{ detail.version + 1 }} 版）</h2>
    <p class="notice info small">
      保存会产生新版本，旧版本原样保留；新版本回到“待审”，审校人和解法确认全部清空，要由<strong>另一位</strong>审校员重新二审。
      你会成为新版本的提交者。保存时不做程序校验，结果在保存后的“程序校验”里。
    </p>

    <div class="grid">
      <label class="field wide">
        <span>标题</span>
        <input v-model="form.title" data-testid="title" maxlength="120" />
      </label>
      <label class="field">
        <span>难度</span>
        <select v-model.number="form.difficulty" data-testid="difficulty">
          <option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level">{{ level }}</option>
        </select>
      </label>
      <label class="field">
        <span>年级</span>
        <select v-model="form.grade" data-testid="grade">
          <option value="">不限</option>
          <option value="G10">高一</option>
          <option value="G11">高二</option>
          <option value="G12">高三</option>
        </select>
      </label>
    </div>

    <label class="field">
      <span>题干（公式写在 $…$ 里）</span>
      <textarea v-model="form.stem" rows="4" data-testid="stem" />
    </label>
    <p class="small preview"><span class="muted">预览：</span><MathText :text="form.stem" /></p>

    <fieldset v-if="isChoice" class="group" data-testid="options">
      <legend>选项（勾选的是正确答案）</legend>
      <div v-for="(row, index) in form.options" :key="index" class="option-row">
        <input v-model="row.key" class="key" aria-label="选项键" maxlength="8" />
        <input v-model="row.correct" type="checkbox" :data-testid="`option-correct-${index}`" aria-label="正确" />
        <textarea v-model="row.text" rows="2" :data-testid="`option-text-${index}`" aria-label="选项内容" />
        <textarea v-model="row.analysis" rows="2" placeholder="这个选项的分析" aria-label="选项分析" />
        <button type="button" class="link" @click="form.options.splice(index, 1)">删除</button>
      </div>
      <button type="button" @click="addOption">添加选项</button>
    </fieldset>

    <fieldset v-if="isFill" class="group" data-testid="blanks">
      <legend>空位与标准答案</legend>
      <div v-for="(row, index) in form.blanks" :key="index" class="option-row blank-row">
        <input v-model="row.key" class="key" aria-label="空位键" maxlength="16" />
        <input v-model="row.answer" placeholder="标准答案" :data-testid="`blank-answer-${index}`" />
        <input v-model="row.unitHint" placeholder="单位提示" />
        <input v-model="row.placeholder" placeholder="输入框占位文字" />
        <button type="button" class="link" @click="form.blanks.splice(index, 1)">删除</button>
      </div>
      <button type="button" @click="addBlank">添加空位</button>
      <label class="field">
        <span>判定规则（JSON，每个空位一条）</span>
        <textarea v-model="form.rulesJson" rows="5" class="mono" data-testid="rules" />
      </label>
      <label class="field">
        <span>单位规则（JSON）</span>
        <textarea v-model="form.unitsJson" rows="4" class="mono" data-testid="units" />
      </label>
    </fieldset>

    <fieldset v-if="isWritten" class="group" data-testid="subquestions">
      <legend>小问与参考答案</legend>
      <p class="muted small">解答题分小问作答。参考答案只用来给学生对照，不参与任何自动判定。</p>
      <div v-for="(row, index) in form.subquestions" :key="index" class="option-row sub-row">
        <input v-model="row.key" class="key" aria-label="小问键" maxlength="16" :data-testid="`subquestion-key-${index}`" />
        <textarea
          v-model="row.stem"
          rows="2"
          placeholder="这一问的题干（公式写在 $…$ 里）"
          aria-label="小问题干"
          :data-testid="`subquestion-stem-${index}`"
        />
        <textarea
          v-model="row.answer"
          rows="2"
          placeholder="参考答案"
          aria-label="参考答案"
          :data-testid="`subquestion-answer-${index}`"
        />
        <button type="button" class="link" :data-testid="`subquestion-delete-${index}`" @click="form.subquestions.splice(index, 1)">
          删除
        </button>
      </div>
      <button type="button" data-testid="add-subquestion" @click="addSubquestion">添加小问</button>
    </fieldset>

    <fieldset v-if="isWritten" class="group" data-testid="points">
      <legend>自查要点（提交之后给学生对照）</legend>
      <p class="muted small">
        这是一张清单，不是评分标准：不带分值，也不会折算成分数。每个小问至少要有一条；"整份解答"是对全部作答的要求。
      </p>
      <div v-for="(row, index) in form.points" :key="index" class="option-row point-row">
        <input v-model="row.key" class="key" aria-label="要点键" maxlength="16" :data-testid="`point-key-${index}`" />
        <select v-model="row.part" aria-label="所属小问" :data-testid="`point-part-${index}`">
          <option value="">整份解答</option>
          <option v-for="sub in partChoices" :key="sub.key" :value="sub.key">第 {{ sub.key }} 问</option>
        </select>
        <textarea v-model="row.text" rows="2" placeholder="要做到什么（公式写在 $…$ 里）" aria-label="要点" :data-testid="`point-text-${index}`" />
        <button type="button" class="link" :data-testid="`point-delete-${index}`" @click="form.points.splice(index, 1)">删除</button>
      </div>
      <button type="button" data-testid="add-point" @click="addPoint">添加要点</button>
    </fieldset>

    <fieldset class="group">
      <legend>教学辅助</legend>
      <label class="field">
        <span>知识点讲解（一句话）</span>
        <input v-model="form.concept" maxlength="200" />
      </label>
      <StringList v-model="form.hints" label="分层提示（由浅到深，不能泄露答案）" add-label="添加一层提示" />
      <label class="field">
        <span>换种讲法（可留空，留空时由模型网关生成）</span>
        <textarea v-model="form.conceptRephrase" rows="3" />
      </label>
      <StringList v-model="form.leakMarkers" label="额外的泄题标记（可选）" add-label="添加标记" :rows="1" />
      <label class="field">
        <span><input v-model="form.visualOn" type="checkbox" /> 带图解</span>
      </label>
      <div v-if="form.visualOn" class="grid">
        <label class="field">
          <span>模板</span>
          <input v-model="form.visualTemplate" placeholder="如 quadratic_graph" />
        </label>
        <label class="field wide">
          <span>说明文字</span>
          <input v-model="form.visualCaption" />
        </label>
        <label class="field wide">
          <span>参数（JSON，数字）</span>
          <textarea v-model="form.visualParamsJson" rows="3" class="mono" />
        </label>
      </div>
    </fieldset>

    <fieldset v-for="kind in (['standard', 'fast'] as const)" :key="kind" class="group" :data-testid="`solution-form-${kind}`">
      <legend>
        <label>
          <input v-model="form[kind].on" type="checkbox" :data-testid="`${kind}-on`" />
          {{ kind === 'standard' ? '标准解法' : '快速解法（必须写适用条件）' }}
        </label>
      </legend>
      <template v-if="form[kind].on">
        <StringList v-model="form[kind].steps" label="步骤" add-label="添加一步" />
        <label class="field">
          <span>答案</span>
          <input v-model="form[kind].finalAnswer" :data-testid="`${kind}-final`" />
        </label>
        <StringList v-model="form[kind].keyPoints" label="方法要点" add-label="添加要点" :rows="1" />
        <template v-if="kind === 'fast'">
          <StringList v-model="form.fast.conditions" label="适用条件" add-label="添加条件" :rows="1" />
          <label class="field">
            <span>不适用的情形</span>
            <textarea v-model="form.fast.boundary" rows="2" />
          </label>
        </template>
      </template>
    </fieldset>

    <fieldset class="group">
      <legend>其他</legend>
      <label class="field">
        <span>知识点（code，用逗号分隔）</span>
        <input v-model="form.knowledge" data-testid="knowledge" />
      </label>
      <label v-if="!isWritten" class="field">
        <span>评分细则（JSON）</span>
        <textarea v-model="form.rubricJson" rows="3" class="mono" data-testid="rubric-json" />
      </label>
      <label class="field">
        <span>修改说明（可选，写进审核历史）</span>
        <input v-model="form.comment" maxlength="2000" data-testid="comment" />
      </label>
    </fieldset>

    <ul v-if="!built.ok" class="notice warn" data-testid="editor-errors">
      <li v-for="problem in built.errors" :key="problem">{{ problem }}</li>
    </ul>
    <p v-else-if="unchanged" class="muted small" data-testid="unchanged">还没有改动。</p>

    <div class="row">
      <button type="button" class="primary" data-testid="save" :disabled="!canSave" @click="save">
        {{ saving ? '保存中…' : '保存为新版本' }}
      </button>
      <button type="button" data-testid="cancel" :disabled="saving" @click="emit('cancel')">放弃修改</button>
    </div>

    <div v-if="failure" class="notice error" role="alert" data-testid="save-error">
      <p>{{ failure.message }}</p>
      <ul v-if="failure.lines.length">
        <li v-for="line in failure.lines" :key="line">{{ line }}</li>
      </ul>
      <button v-if="stale" type="button" class="link" @click="emit('refresh')">刷新题目</button>
    </div>
  </section>
</template>
