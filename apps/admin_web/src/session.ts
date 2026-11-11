import { reactive } from 'vue'

export interface Session {
  token: string
  userId: string
  role: 'reviewer' | 'admin'
}

const STORAGE_KEY = 'tutor_admin_session'

function load(): Session | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const value = JSON.parse(raw) as Partial<Session>
    if (value.token && value.userId && (value.role === 'reviewer' || value.role === 'admin')) {
      return { token: value.token, userId: value.userId, role: value.role }
    }
  } catch {
    // 存的东西读不懂就当没登录
  }
  return null
}

const state = reactive<{ session: Session | null }>({ session: load() })

export function useSession() {
  return state
}

export function setSession(session: Session): void {
  state.session = session
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session))
  } catch {
    // 存不进去也能继续用，刷新后需要重新登录
  }
}

export function clearSession(): void {
  state.session = null
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // 同上
  }
}
