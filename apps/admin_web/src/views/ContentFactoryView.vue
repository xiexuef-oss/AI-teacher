<script setup lang="ts">
import { ref, watch } from 'vue'
import { request } from '../api/client'
import { newIdempotencyKey } from '../api/guard'
import type { components } from '../api/schema'
import ContentFactoryPermissionForm from '../components/ContentFactoryPermissionForm.vue'
import ContentFactoryJobForm from '../components/ContentFactoryJobForm.vue'
import ContentFactoryOriginalForm from '../components/ContentFactoryOriginalForm.vue'
import ContentFactoryQuestionTypeForm from '../components/ContentFactoryQuestionTypeForm.vue'
import ContentFactoryQuestionTypeLookup from '../components/ContentFactoryQuestionTypeLookup.vue'
import ContentFactorySourceForm from '../components/ContentFactorySourceForm.vue'
import { useSession } from '../session'

const state = useSession()
const roles = ref<components['schemas']['ContentFactoryRoles']['roles'] | null>(null)
const failed = ref(false)
const labels = { editor: '编辑', reviewer: '审核', publisher: '发布', admin: '教研管理员' }
type RoleCommand = components['schemas']['ContentFactoryRoleAssignmentCommand']
const targetId = ref('')
const selectedRole = ref<RoleCommand['role']>('editor')
const enabled = ref(true)
const saving = ref(false)
const feedback = ref('')
const retryKeys = new Map<string, string>()

async function saveRole(): Promise<void> {
  const session = state.session
  if (session?.role !== 'admin' || saving.value || (roles.value === null && !failed.value)) return
  const body: RoleCommand = {
    user_id: targetId.value.trim(), role: selectedRole.value, enabled: enabled.value,
  }
  const command = JSON.stringify(body)
  const key = retryKeys.get(command) ?? newIdempotencyKey()
  retryKeys.set(command, key)
  saving.value = true
  feedback.value = ''
  try {
    const result = await request<components['schemas']['ContentFactoryRoles']>(
      'POST', '/admin/content-factory/role-assignments',
      { token: session.token, body, idempotencyKey: key },
    )
    if (state.session !== session) return
    retryKeys.delete(command)
    const assigned = result.roles.map(role => labels[role]).join('、')
    feedback.value = assigned ? `保存成功，目标账号岗位：${assigned}` : '保存成功，目标账号无教研岗位'
    if (body.user_id === session.userId) roles.value = result.roles
  } catch (error) {
    if (state.session === session) {
      feedback.value = error instanceof Error ? error.message : '暂时无法保存岗位'
    }
  } finally {
    if (state.session === session) saving.value = false
  }
}

watch(() => state.session, async (session, _, onCleanup) => {
  let current = true
  onCleanup(() => { current = false })
  roles.value = null
  failed.value = false
  targetId.value = ''
  selectedRole.value = 'editor'
  enabled.value = true
  saving.value = false
  feedback.value = ''
  retryKeys.clear()
  if (!session) return
  try {
    const result = await request<components['schemas']['ContentFactoryRoles']>(
      'GET', '/admin/content-factory/roles/me', { token: session.token },
    )
    if (current) roles.value = result.roles
  } catch {
    if (current) failed.value = true
  }
}, { immediate: true })
</script>

<template>
  <main class="page">
    <h1>自动化教研中心</h1>
    <p role="status">
      {{ failed ? '暂时无法读取教研岗位' : roles === null ? '正在读取教研岗位…' :
        roles.length ? roles.map(role => labels[role]).join('、') : '当前账号尚未分配教研岗位' }}
    </p>
    <p>导入有权用于教研的资料，将确认后的题目草稿交给学科审核人员。</p>
    <nav aria-label="教研工作台">
      <ul>
        <li><RouterLink :to="{ name: 'document-import' }">PDF、Word 与图片导入</RouterLink></li>
        <li><RouterLink :to="{ name: 'import' }">结构化题目批量导入</RouterLink></li>
        <li><RouterLink :to="{ name: 'queue' }">题目审核队列与纸包题源缺口</RouterLink></li>
      </ul>
    </nav>
    <ContentFactorySourceForm v-if="roles?.includes('editor')" :key="state.session?.token" />
    <ContentFactoryOriginalForm v-if="roles?.includes('editor')" />
    <ContentFactoryQuestionTypeForm v-if="roles?.includes('editor')" />
    <ContentFactoryJobForm v-if="roles?.includes('editor')" />
    <ContentFactoryPermissionForm v-if="roles?.includes('reviewer')" />
    <ContentFactoryQuestionTypeLookup
      v-if="roles?.includes('editor') || roles?.includes('reviewer')"
      :can-review="roles?.includes('reviewer') ?? false"
    />
    <section v-if="state.session?.role === 'admin'" class="card">
      <h2>教研岗位管理</h2>
      <form @submit.prevent="saveRole">
        <fieldset :disabled="saving || (roles === null && !failed)">
          <legend>分配或撤销岗位</legend>
          <label>
            后台账号 ID
            <input v-model.trim="targetId" required
              pattern="[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}" autocomplete="off">
          </label>
          <label>
            岗位
            <select v-model="selectedRole">
              <option v-for="(label, role) in labels" :key="role" :value="role">{{ label }}</option>
            </select>
          </label>
          <label>
            操作
            <select v-model="enabled">
              <option :value="true">分配</option>
              <option :value="false">撤销</option>
            </select>
          </label>
          <button type="submit">{{ saving ? '保存中…' : '保存' }}</button>
        </fieldset>
      </form>
      <p v-if="feedback" role="status">{{ feedback }}</p>
    </section>
  </main>
</template>
