import { createRouter, createWebHashHistory } from 'vue-router'
import { useSession } from './session'
import LoginView from './views/LoginView.vue'
import QuestionCompareView from './views/QuestionCompareView.vue'
import QueueView from './views/QueueView.vue'
import QuestionView from './views/QuestionView.vue'
import BatchReviewView from './views/BatchReviewView.vue'
import ImportView from './views/ImportView.vue'
import DocumentImportView from './views/DocumentImportView.vue'

export const router = createRouter({
  // 哈希路由：静态托管、vite preview 都不需要额外的重写规则
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: LoginView },
    { path: '/', name: 'queue', component: QueueView },
    { path: '/batch-review', name: 'batch-review', component: BatchReviewView },
    { path: '/import', name: 'import', component: ImportView },
    { path: '/document-import', name: 'document-import', component: DocumentImportView },
    { path: '/questions/:id', name: 'question', component: QuestionView },
    { path: '/questions/:id/compare', name: 'compare', component: QuestionCompareView },
  ],
})

router.beforeEach((to) => {
  const signedIn = useSession().session !== null
  if (!signedIn && to.name !== 'login') return { name: 'login' }
  if (signedIn && to.name === 'login') return { name: 'queue' }
  return true
})
