/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

interface ImportMetaEnv {
  /** 后端 API 的地址，缺省为本机开发服务器。 */
  readonly VITE_API_BASE?: string
}
