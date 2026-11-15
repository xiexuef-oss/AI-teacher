<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createLocalIdentity, getHealth } from '../api/admin'
import { ApiError } from '../api/client'
import type { Health, LocalRole } from '../api/types'
import { setSession } from '../session'

const router = useRouter()
const health = ref<Health | null>(null)
const message = ref<string | null>(null)
const busy = ref(false)

onMounted(async () => {
  try {
    health.value = await getHealth()
  } catch (error) {
    message.value = error instanceof ApiError ? error.message : '连不上服务器'
  }
})

async function signIn(role: Extract<LocalRole, 'reviewer' | 'admin'>): Promise<void> {
  busy.value = true
  message.value = null
  try {
    const identity = await createLocalIdentity(role)
    if (identity.role !== 'reviewer' && identity.role !== 'admin') {
      message.value = '服务端没有发放审核角色的身份'
      return
    }
    setSession({ token: identity.access_token, userId: identity.user_id, role: identity.role })
    await router.replace({ name: 'queue' })
  } catch (error) {
    message.value =
      error instanceof ApiError && error.status === 404
        ? '服务端没有开启本地身份 Mock。真实登录方式还没有定（Q-03），暂时只能在本机开发环境里用。'
        : error instanceof ApiError
          ? error.message
          : '登录失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <section class="card">
      <h1>内容审核后台</h1>
      <p class="muted">
        审核题目、答案和解法：draft → reviewed → published，发现问题可以撤回。每一步都会留下审计记录。
      </p>
      <p v-if="health && !health.local_identity_mock" class="notice warn" role="status">
        后端没有开启本地身份 Mock。真实登录方式还没有定（Q-03），审核后台暂时只能在本机开发环境里进入。
      </p>
      <template v-else>
        <p class="notice warn small">
          本地开发登录：每次点击都会在本机创建一个新的审核员身份，仅用于联调，不是真实账号。
        </p>
        <div class="row">
          <button class="primary" type="button" :disabled="busy" data-testid="sign-in-reviewer" @click="signIn('reviewer')">
            以审核员身份进入
          </button>
          <button type="button" :disabled="busy" data-testid="sign-in-admin" @click="signIn('admin')">
            以管理员身份进入
          </button>
        </div>
      </template>
      <p v-if="message" class="notice error" role="alert" data-testid="login-error">{{ message }}</p>
    </section>
  </main>
</template>
