import { useState } from 'react'
import type { Skill } from './api'

const categories = ['LinkedIn', 'GitHub', 'Portfolio', 'Published research', 'Certificate', 'Other'] as const
type Category = typeof categories[number]

export interface EvidenceLink {
  id: number
  category: Category
  title: string
  url: string
  skill?: string
}

const field = 'w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm'

export function ProfileEvidence({ links, skills, onChange }: {
  links: EvidenceLink[]
  skills: Skill[]
  onChange: (links: EvidenceLink[]) => void
}) {
  const [error, setError] = useState('')

  return (
    <details className="mt-5 rounded-xl border border-slate-200 bg-mist/40 p-3">
      <summary className="cursor-pointer text-sm font-bold text-espoo">Profile links{links.length > 0 && ` (${links.length})`}</summary>
      <p className="mt-2 text-sm text-slate-600">Share your work, projects, or certificates. Links stay in this demo session.</p>
      {links.length > 0 && (
        <ul className="mt-3 space-y-2">
          {links.map((link) => (
            <li key={link.id} className="flex items-start justify-between gap-3 rounded-lg bg-white p-3 text-sm">
              <div className="min-w-0">
                <a href={link.url} target="_blank" rel="noopener noreferrer" className="break-words font-semibold text-espoo underline">{link.title}</a>
                <p className="text-xs text-slate-600">{link.category}{link.skill && ` · ${link.skill}`}</p>
              </div>
              <button type="button" aria-label={`Remove link: ${link.title}`} className="cursor-pointer text-xs text-espoo underline"
                onClick={() => onChange(links.filter(({ id }) => id !== link.id))}>Remove</button>
            </li>
          ))}
        </ul>
      )}
      <form className="mt-3 grid gap-2" onSubmit={(event) => {
        event.preventDefault()
        const form = event.currentTarget
        const data = new FormData(form)
        const category = data.get('category') as Category
        const title = String(data.get('title') ?? '').trim()
        const url = URL.parse(String(data.get('url') ?? '').trim())
        if (!title || !url || !['https:', 'http:'].includes(url.protocol) || url.username || url.password) {
          setError('Enter a title and a public HTTP or HTTPS link.')
          return
        }
        if (links.some((link) => link.url === url.href)) {
          setError('This link is already on the profile.')
          return
        }
        const skill = skills.find(({ id }) => id === Number(data.get('skill')))?.name
        onChange([...links, { id: Math.max(0, ...links.map(({ id }) => id)) + 1, category, title, url: url.href, skill }])
        setError('')
        form.reset()
      }}>
        <label className="grid gap-1 text-xs font-semibold">Link type
          <select name="category" className={field}>{categories.map((category) => <option key={category}>{category}</option>)}</select>
        </label>
        <label className="grid gap-1 text-xs font-semibold">Title
          <input name="title" required maxLength={120} placeholder="e.g. Data analysis project" className={field} />
        </label>
        <label className="grid gap-1 text-xs font-semibold">Link URL
          <input name="url" type="url" required maxLength={2048} placeholder="https://…" className={field} />
        </label>
        <label className="grid gap-1 text-xs font-semibold">Related skill (optional)
          <select name="skill" className={field}>
            <option value="">No specific skill</option>
            {skills.map(({ id, name }) => <option value={id} key={id}>{name}</option>)}
          </select>
        </label>
        {error && <p role="alert" className="text-sm text-red-800">{error}</p>}
        <button type="submit" className="mt-1 w-fit cursor-pointer rounded-lg bg-espoo px-4 py-2 text-sm font-semibold text-white hover:bg-blue-900">Add link</button>
      </form>
    </details>
  )
}
