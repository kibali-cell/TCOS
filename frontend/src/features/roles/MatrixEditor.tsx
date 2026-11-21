import { ACTION_LABELS, SCOPE_LABELS, cellKey, type Catalogue, type Cells } from './types'

interface Props {
  catalogue: Catalogue
  cells: Cells
  disabled: boolean
  onChange: (key: string, scope: string) => void
}

/** One row per module, one scope selector per action. Every cell is independent. */
export function MatrixEditor({ catalogue, cells, disabled, onChange }: Props) {
  return (
    <div className="matrix" role="group" aria-label="Permissions by module">
      {catalogue.modules.map((module) => (
        <fieldset key={module.code} className="matrix-row">
          <legend>{module.name}</legend>
          {catalogue.actions.map((action) => {
            const key = cellKey(module.code, action)
            return (
              <label key={action} className="matrix-cell">
                <span className="matrix-action">{ACTION_LABELS[action] ?? action}</span>
                <select
                  aria-label={`${module.name}: ${ACTION_LABELS[action] ?? action}`}
                  value={cells[key] ?? ''}
                  disabled={disabled}
                  onChange={(event) => onChange(key, event.target.value)}
                  className={cells[key] ? 'granted' : undefined}
                >
                  <option value="">No access</option>
                  {catalogue.scopes.map((scope) => (
                    <option key={scope} value={scope}>
                      {SCOPE_LABELS[scope] ?? scope}
                    </option>
                  ))}
                </select>
              </label>
            )
          })}
        </fieldset>
      ))}
    </div>
  )
}
