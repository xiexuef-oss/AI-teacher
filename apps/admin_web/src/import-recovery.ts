/** Import recovery data is temporary and isolated by the authenticated user. */
export function clearImportRecovery(userId: string): void {
  const prefix = `document-import:${userId}:`
  for (const name of Object.keys(localStorage)) {
    if (name.startsWith(prefix)) localStorage.removeItem(name)
  }
}
export function expireImportRecovery(userId: string, now = Date.now()): void {
  const raw = localStorage.getItem(`document-import:${userId}:expires`)
  // Legacy data without a retention bound must not survive indefinitely.
  if (!raw || !Number.isFinite(Number(raw)) || Number(raw) <= now) clearImportRecovery(userId)
}
export function boundImportRecovery(userId: string, expiresAt: number): void {
  const name = `document-import:${userId}:expires`
  const current = Number(localStorage.getItem(name))
  localStorage.setItem(name, String(current > Date.now() ? Math.min(current, expiresAt) : expiresAt))
}
