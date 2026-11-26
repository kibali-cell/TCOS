import { useId, useState, type FormEvent } from 'react'

import { api } from '../../lib/api'
import type { Paged, Person } from './types'

/** Search by name, then choose. Names only; the server never sends contact details. */
export function PersonPicker({
  label,
  value,
  onChange,
}: {
  label: string
  value: Person | null
  onChange: (person: Person | null) => void
}) {
  const id = useId()
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<Person[] | null>(null)
  const [failed, setFailed] = useState(false)

  async function search(event: FormEvent) {
    event.preventDefault()
    setFailed(false)
    try {
      const body = await api<Paged<Person>>(
        `/organisation/people/?q=${encodeURIComponent(query.trim())}`,
      )
      setFound(body.results)
    } catch {
      setFound(null)
      setFailed(true)
    }
  }

  return (
    <div className="field">
      <label htmlFor={`${id}-q`}>{label}</label>
      {value && (
        <p className="small">
          Chosen: <strong>{value.full_name}</strong>{' '}
          <button type="button" className="button" onClick={() => onChange(null)}>
            Clear {label.toLowerCase()}
          </button>
        </p>
      )}
      <div className="button-row">
        <input
          id={`${id}-q`}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') void search(event)
          }}
          placeholder="Type a name"
        />
        <button type="button" className="button" onClick={search}>
          Find {label.toLowerCase()}
        </button>
      </div>
      {failed && (
        <p role="alert" className="form-error">
          Could not search just now.
        </p>
      )}
      {found && found.length === 0 && <p className="muted small">Nobody matches.</p>}
      {found && found.length > 0 && (
        <select
          aria-label={`${label} results`}
          value=""
          onChange={(event) => {
            const person = found.find((item) => item.id === event.target.value)
            if (person) {
              onChange(person)
              setFound(null)
              setQuery('')
            }
          }}
        >
          <option value="">Choose a person…</option>
          {found.map((person) => (
            <option key={person.id} value={person.id}>
              {person.full_name} ({person.username})
            </option>
          ))}
        </select>
      )}
    </div>
  )
}
