import 'katex/dist/katex.min.css'
import { createApp } from 'vue'
import { setUnauthorizedHandler } from './api/guard'
import App from './App.vue'
import { router } from './router'
import './styles.css'

setUnauthorizedHandler(() => void router.replace({ name: 'login' }))
createApp(App).use(router).mount('#app')
