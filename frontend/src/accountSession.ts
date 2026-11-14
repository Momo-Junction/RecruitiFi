/** Existing server-verified demo session, reused at application entry only. */
export async function loginAccount(account: string, password: string) {
  const response = await fetch('/api/evidence-session', {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account, password }),
  })
  if (!response.ok) throw new Error(response.status === 429 ? 'Too many sign-in attempts. Try again later.' : 'Account sign-in failed. Check credentials and server configuration.')
  const identity = await response.json()
  const current = await fetch('/api/evidence-session', { credentials: 'same-origin', cache: 'no-store' })
  if (!current.ok || (await current.json()).account_id !== account) throw new Error('The server session could not be verified.')
  return identity
}
