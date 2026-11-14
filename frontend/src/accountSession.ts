/** Establish a server-issued selection; password verification depends on demo mode. */
export async function loginAccount(account: string, password = '') {
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

/** Public mode still establishes a signed demo selection and CSRF cookie. */
export async function loadAccountConfiguration(signal?: AbortSignal) {
  const response=await fetch('/api/evidence-session/config',{credentials:'same-origin',cache:'no-store',signal})
  if(!response.ok)throw new Error('Account configuration is unavailable.')
  const data=await response.json()
  if(typeof data.verified_login_required!=='boolean' || (data.password_free_demo!==undefined && typeof data.password_free_demo!=='boolean') || (data.password_free_demo && !data.verified_login_required))throw new Error('Invalid account configuration.')
  return {sessionRequired:data.verified_login_required as boolean,passwordFree:data.password_free_demo===true}
}
