import { useEffect, useState } from 'react'

export const demoRoles = ['talent', 'employer', 'organizer'] as const
export type DemoRole = typeof demoRoles[number]
export const demoRoleKey = 'recruitifi.demoRole'
export function isDemoRole(value: unknown): value is DemoRole {
  return demoRoles.includes(value as DemoRole)
}

// These are demo navigation rules only; they do not authorize API access.
export function resolveDemoRoute(path: string, selected: DemoRole | null) {
  if (path === '/') return { role: null, path: '/' }
  if (selected && demoRoles.some((role) => path === `/${role}`)) {
    return { role: selected, path: `/${selected}` }
  }
  return { role: null, path: '/' }
}

export function createDemoNavigation(browser: Pick<Window, 'location' | 'history' | 'sessionStorage'>) {
  let memoryRole: DemoRole | null = null
  function selected() {
    try {
      const value = browser.sessionStorage.getItem(demoRoleKey)
      return isDemoRole(value) ? value : null
    } catch { return memoryRole }
  }
  function current() {
    return resolveDemoRoute(browser.location.pathname, selected())
  }
  function sync() {
    const route = current()
    if (browser.location.pathname !== route.path) browser.history.replaceState(null, '', route.path)
    return route.role
  }
  function select(role: DemoRole | null) {
    memoryRole = role
    try {
      if (role) browser.sessionStorage.setItem(demoRoleKey, role)
      else browser.sessionStorage.removeItem(demoRoleKey)
    } catch { /* Navigation still works when browser storage is unavailable. */ }
    const path = role ? `/${role}` : '/'
    if (browser.location.pathname !== path) browser.history.pushState(null, '', path)
    return role
  }
  return { current, sync, select }
}

export function useDemoNavigation() {
  const [navigation] = useState(() => typeof window === 'undefined' ? null : createDemoNavigation(window))
  const [role, setRole] = useState<DemoRole | null>(() => navigation?.current().role ?? null)
  useEffect(() => {
    if (!navigation) return
    const sync = () => setRole(navigation.sync())
    sync()
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [navigation])
  return { role, selectRole: (next: DemoRole | null) => setRole(navigation?.select(next) ?? null) }
}
