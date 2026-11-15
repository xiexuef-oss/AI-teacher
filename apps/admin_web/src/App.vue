<script setup lang="ts">
import { useRouter } from 'vue-router'
import { shortId } from './labels'
import { clearSession, useSession } from './session'

const state = useSession()
const router = useRouter()

async function signOut(): Promise<void> {
  clearSession()
  await router.replace({ name: 'login' })
}
</script>

<template>
  <header class="topbar">
    <strong>AI 理科私教 · 内容审核</strong>
    <span v-if="state.session" class="who">
      {{ state.session.role === 'admin' ? '管理员' : '审核员' }}
      <span class="mono">{{ shortId(state.session.userId) }}</span>
      <button type="button" class="link" data-testid="sign-out" @click="signOut">退出</button>
    </span>
  </header>
  <RouterView />
</template>
