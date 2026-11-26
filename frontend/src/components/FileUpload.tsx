import { useRef, useState } from 'react'

import { ApiError, apiUpload, fieldErrors } from '../lib/api'

export interface DocumentInfo {
  id: string
  name: string
  content_type: string
  size_bytes: number
  classification: string
  scan_status: string
  uploaded_by: string | null
  uploaded_at: string
  can_archive: boolean
}

interface Props {
  parentType: string
  parentId: string
  onUploaded: (document: DocumentInfo) => void
  /** Shown to the person; the server enforces the real limits. */
  hint?: string
}

type Phase =
  | { kind: 'idle' }
  | { kind: 'uploading'; name: string; fraction: number }
  | { kind: 'failed'; name: string; message: string; file: File }

function describe(caught: unknown): string {
  if (caught instanceof ApiError && caught.status !== 0) {
    return fieldErrors(caught).file?.[0] ?? caught.message
  }
  return 'Could not reach the server. Check your connection and try again.'
}

/** Pick a file, send it, show progress and any error. Online only: nothing is queued. */
export function FileUpload({ parentType, parentId, onUploaded, hint }: Props) {
  const input = useRef<HTMLInputElement>(null)
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })

  async function send(file: File) {
    setPhase({ kind: 'uploading', name: file.name, fraction: 0 })
    try {
      const document = await apiUpload<DocumentInfo>(
        '/documents/',
        { parent_type: parentType, parent_id: parentId },
        file,
        (fraction) => setPhase({ kind: 'uploading', name: file.name, fraction }),
      )
      setPhase({ kind: 'idle' })
      onUploaded(document)
    } catch (caught) {
      setPhase({ kind: 'failed', name: file.name, message: describe(caught), file })
    } finally {
      if (input.current) input.current.value = ''
    }
  }

  const uploading = phase.kind === 'uploading'
  return (
    <div className="dropzone">
      <label htmlFor="file-upload-input" className="button">
        Choose a file
      </label>
      <input
        id="file-upload-input"
        ref={input}
        type="file"
        className="visually-hidden"
        disabled={uploading}
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) void send(file)
        }}
      />
      {hint && <p className="muted small">{hint}</p>}
      {phase.kind === 'uploading' && (
        <div className="upload-row" role="status">
          <span>{phase.name}</span>
          <progress max={1} value={phase.fraction} aria-label={`Uploading ${phase.name}`} />
          <span>{Math.round(phase.fraction * 100)}%</span>
        </div>
      )}
      {phase.kind === 'failed' && (
        <div className="upload-row">
          <p role="alert" className="form-error">
            {phase.name}: {phase.message}
          </p>
          <button type="button" className="button" onClick={() => void send(phase.file)}>
            Try again
          </button>
          <button type="button" className="button" onClick={() => setPhase({ kind: 'idle' })}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  )
}
