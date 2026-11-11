import { createRouter, createWebHashHistory } from 'vue-router'
import { useSession } from './session'
import LoginView from './views/LoginView.vue'
import QueueView from './views/QueueView.vue'
import QuestionView from './views/QuestionView.vue'

export const router = createRouter({
  // 哈希路由：静态托管、vite preview 都不需要额外的重写规则
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    { path: '/', name: 'queue', component: QueueView },
    { path: '/questions/:id', name: 'question', component: QuestionView },
  ],
})

router.beforeEach((to) => {
  const signedIn = useSession().session !== null
  if (!signedIn && to.name !== 'login') return { name: 'login' }
  if (signedIn && to.name === 'login') return { name: 'queue' }
  return true
})
