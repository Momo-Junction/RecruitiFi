import { useEffect, useState } from 'react'

export const demoRoles = ['talent', 'employer', 'organizer'] as const
export type DemoRole = typeof demoRoles[number]
export type DemoAccount = { demo_account_id: string; display_name: string; available: boolean; error?: string } & (
  { role: 'talent'; candidate_id: number } | { role: 'employer'; company_id: number } | { role: 'organizer' }
)
export const demoAccountKey = 'recruitifi.demoAccount'
let memoryAccount: DemoAccount | null = null
export function isDemoAccount(value: unknown): value is DemoAccount {
  if (!value || typeof value !== 'object') return false
  const account = value as Record<string, unknown>
  return typeof account.demo_account_id === 'string' && typeof account.display_name === 'string' && account.available === true && (
    account.role === 'organizer' || (account.role === 'talent' && Number.isSafeInteger(account.candidate_id) && Number(account.candidate_id) > 0)
    || (account.role === 'employer' && Number.isSafeInteger(account.company_id) && Number(account.company_id) > 0)
  )
}

// One shared demo session; caller-selected public IDs do not authorize API access.
export function readDemoAccount(browser: Pick<Window, 'sessionStorage'> | undefined = typeof window === 'undefined' ? undefined : window): DemoAccount | null {
  if (!browser) return null
  let value: string | null
  try { value = browser.sessionStorage.getItem(demoAccountKey) }
  catch { return memoryAccount }
  try {
    const stored: unknown = JSON.parse(value ?? 'null')
    return isDemoAccount(stored) ? stored : null
  } catch { return null }
}
export function resolveDemoRoute(path: string, selected: DemoAccount | null) {
  if (path !== '/' && selected && demoRoles.some((role) => path === `/${role}`)) {
    return { account: selected, path: `/${selected.role}` }
  }
  return { account: null, path: '/' }
}
export function createDemoNavigation(browser: Pick<Window, 'location' | 'history' | 'sessionStorage'>) {
  function current() {
    return resolveDemoRoute(browser.location.pathname, readDemoAccount(browser))
  }
  function sync() {
    const route = current()
    if (browser.location.pathname !== route.path) browser.history.replaceState(null, '', route.path)
    return route.account
  }
  function select(account: DemoAccount | null) {
    if (account && !isDemoAccount(account)) throw new Error('Choose an available demo account.')
    memoryAccount = account
    try {
      browser.sessionStorage.removeItem('recruitifi.demoRole')
      if (account) browser.sessionStorage.setItem(demoAccountKey, JSON.stringify(account))
      else browser.sessionStorage.removeItem(demoAccountKey)
    } catch { /* In-memory selection works; refresh needs browser storage. */ }
    const path = account ? `/${account.role}` : '/'
    if (browser.location.pathname !== path) browser.history.pushState(null, '', path)
    return account
  }
  return { current, sync, select }
}
export function useDemoNavigation() {
  const [navigation] = useState(() => typeof window === 'undefined' ? null : createDemoNavigation(window))
  const [account, setAccount] = useState<DemoAccount | null>(() => navigation?.current().account ?? null)
  useEffect(() => {
    if (!navigation) return
    const sync = () => setAccount(navigation.sync())
    sync()
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [navigation])
  return { account, selectAccount: (next: DemoAccount | null) => {
    if (!next && typeof window !== 'undefined') {
      void fetch('/api/evidence-session', { credentials: 'same-origin', cache: 'no-store' }).then(async response => {
        if (response.ok) {
          const data = await response.json()
          await fetch('/api/evidence-session', { method: 'DELETE', credentials: 'same-origin', headers: { 'X-Recruitifi-CSRF': data.csrf } })
        }
      }).catch(() => {})
    }
    setAccount(navigation?.select(next) ?? null)
  } }
}

export function requireDemoOwner(role: 'talent' | 'employer', identityId: number) {
  const account = readDemoAccount()
  if (account && (account.role !== role || (account.role === 'talent' ? account.candidate_id : account.role === 'employer' ? account.company_id : undefined) !== identityId)) {
    throw new Error('This operation belongs to a different demo account. Log out to switch accounts.')
  }
}
