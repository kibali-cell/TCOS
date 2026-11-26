import { useState } from 'react'

import { ApiError, api, apiFile } from '../lib/api'
import { formatDateTime, formatSize } from '../lib/format'
import { FileUpload, type DocumentInfo } from './FileUpload'

interface Props {
  parentType: string
  parentId: string
  files: DocumentInfo[]
  canAttach: boolean
  onChange: () => void
}

/** Files on a record, each downloaded through the permission-checked endpoint. */
export function FileAttachments({ parentType, parentId, files, canAttach, onChange }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  async function download(file: DocumentInfo) {
    setBusyId(file.id)
    setError(null)
    try {
      const { blob } = await apiFile(`/documents/${file.id}/download/`)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.name
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status !== 0
          ? caught.message
          : 'Could not reach the server.',
      )
    } finally {
      setBusyId(null)
    }
  }

  async function remove(file: DocumentInfo) {
    setBusyId(file.id)
    setError(null)
    try {
      await api(`/documents/${file.id}/archive/`, { method: 'POST' })
      onChange()
    } catch (caught) {
      setError(
        caught instanceof ApiError && caught.status !== 0
          ? caught.message
          : 'Could not reach the server.',
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="card" aria-labelledby="attachments-heading">
      <h2 id="attachments-heading">Attachments</h2>
      {files.length === 0 ? (
        <p className="muted">No files attached.</p>
      ) : (
        <ul className="file-list">
          {files.map((file) => (
            <li key={file.id}>
              <span>
                <strong>{file.name}</strong>{' '}
                <span className="muted small">
                  {formatSize(file.size_bytes)} · {file.uploaded_by ?? 'Unknown'} ·{' '}
                  {formatDateTime(file.uploaded_at)}
                  {file.scan_status === 'NOT_SCANNED' ? ' · not virus-scanned' : ''}
                </span>
              </span>
              <span>
                <button
                  type="button"
                  className="button"
                  disabled={busyId === file.id}
                  onClick={() => void download(file)}
                  aria-label={`Download ${file.name}`}
                >
                  Download
                </button>{' '}
                {file.can_archive && (
                  <button
                    type="button"
                    className="button"
                    disabled={busyId === file.id}
                    onClick={() => void remove(file)}
                    aria-label={`Remove ${file.name}`}
                  >
                    Remove
                  </button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {canAttach && (
        <FileUpload
          parentType={parentType}
          parentId={parentId}
          onUploaded={onChange}
          hint="PDF, images, Word, Excel or text files, up to 10 MB."
        />
      )}
    </section>
  )
}
