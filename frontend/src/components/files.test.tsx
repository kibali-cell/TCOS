import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { mockApi } from '../test/mockApi'
import { FileAttachments } from './FileAttachments'
import { FileUpload, type DocumentInfo } from './FileUpload'

const DOC: DocumentInfo = {
  id: 'd1',
  name: 'invoice.pdf',
  content_type: 'application/pdf',
  size_bytes: 2048,
  classification: 'CONFIDENTIAL',
  scan_status: 'NOT_SCANNED',
  uploaded_by: 'Rita Requester',
  uploaded_at: '2026-11-20T04:00:00Z',
  can_archive: true,
}

interface Plan {
  status: number
  body: unknown
  progress?: number[]
}

/** A stand-in for XMLHttpRequest that answers from a plan and records what was sent. */
function stubXhr(plans: Plan[]) {
  const sent: { url: string; form: FormData; headers: Record<string, string> }[] = []
  class FakeXhr {
    static last: FakeXhr | null = null
    upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null }
    onload: (() => void) | null = null
    onerror: (() => void) | null = null
    onabort: (() => void) | null = null
    status = 0
    responseText = ''
    withCredentials = false
    headers: Record<string, string> = {}
    url = ''
    open(_method: string, url: string) {
      this.url = url
    }
    setRequestHeader(name: string, value: string) {
      this.headers[name] = value
    }
    abort() {
      this.onabort?.()
    }
    send(form: FormData) {
      FakeXhr.last = this
      sent.push({ url: this.url, form, headers: this.headers })
      const plan = plans.shift()!
      setTimeout(() => {
        for (const fraction of plan.progress ?? []) {
          this.upload.onprogress?.({
            lengthComputable: true,
            loaded: fraction * 100,
            total: 100,
          } as ProgressEvent)
        }
        this.status = plan.status
        this.responseText = JSON.stringify(plan.body)
        this.onload?.()
      }, 0)
    }
  }
  vi.stubGlobal('XMLHttpRequest', FakeXhr)
  return sent
}

afterEach(() => vi.unstubAllGlobals())

function pdf(name = 'invoice.pdf') {
  return new File(['%PDF-1.4'], name, { type: 'application/pdf' })
}

describe('FileUpload', () => {
  it('sends the file with the CSRF header, then reports the stored document', async () => {
    mockApi({})
    const sent = stubXhr([{ status: 201, body: DOC, progress: [0.5, 1] }])
    const onUploaded = vi.fn()
    render(
      <FileUpload parentType="approvals.ApprovalRequest" parentId="r1" onUploaded={onUploaded} />,
    )
    await userEvent.upload(screen.getByLabelText('Choose a file'), pdf())
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(DOC))
    expect(sent[0].url).toBe('/api/v1/documents/')
    expect(sent[0].headers['X-CSRFToken']).toBe('test-token')
    expect(sent[0].form.get('parent_type')).toBe('approvals.ApprovalRequest')
    expect(sent[0].form.get('parent_id')).toBe('r1')
    expect((sent[0].form.get('file') as File).name).toBe('invoice.pdf')
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('shows progress while uploading', async () => {
    mockApi({})
    let release: () => void = () => undefined
    class Slow {
      upload: { onprogress: ((e: ProgressEvent) => void) | null } = { onprogress: null }
      onload: (() => void) | null = null
      status = 201
      responseText = JSON.stringify(DOC)
      open() {}
      setRequestHeader() {}
      abort() {}
      send() {
        this.upload.onprogress?.({
          lengthComputable: true,
          loaded: 40,
          total: 100,
        } as ProgressEvent)
        release = () => this.onload?.()
      }
    }
    vi.stubGlobal('XMLHttpRequest', Slow)
    render(<FileUpload parentType="p" parentId="r1" onUploaded={() => undefined} />)
    await userEvent.upload(screen.getByLabelText('Choose a file'), pdf())
    const bar = await screen.findByRole('progressbar', { name: 'Uploading invoice.pdf' })
    expect(bar).toHaveAttribute('value', '0.4')
    expect(screen.getByText('40%')).toBeInTheDocument()
    release()
    await waitFor(() => expect(screen.queryByRole('progressbar')).not.toBeInTheDocument())
  })

  it('shows the server refusal and lets the person retry', async () => {
    mockApi({})
    const sent = stubXhr([
      {
        status: 400,
        body: {
          error: {
            code: 'validation_error',
            message: 'Invalid.',
            details: { file: ['This file type is not allowed.'] },
          },
        },
      },
      { status: 201, body: DOC },
    ])
    const onUploaded = vi.fn()
    render(<FileUpload parentType="p" parentId="r1" onUploaded={onUploaded} />)
    await userEvent.upload(screen.getByLabelText('Choose a file'), pdf('run.exe'))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'run.exe: This file type is not allowed.',
    )
    expect(onUploaded).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(onUploaded).toHaveBeenCalled())
    expect(sent).toHaveLength(2)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('says so when the server cannot be reached, without queueing anything', async () => {
    mockApi({})
    class Offline {
      upload = { onprogress: null }
      onerror: (() => void) | null = null
      open() {}
      setRequestHeader() {}
      abort() {}
      send() {
        setTimeout(() => this.onerror?.(), 0)
      }
    }
    vi.stubGlobal('XMLHttpRequest', Offline)
    render(<FileUpload parentType="p" parentId="r1" onUploaded={() => undefined} />)
    await userEvent.upload(screen.getByLabelText('Choose a file'), pdf())
    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not reach the server/)
    expect(window.localStorage.length + window.sessionStorage.length).toBe(0)
  })
})

describe('FileAttachments', () => {
  it('lists files with a download that uses the permission-checked endpoint', async () => {
    const fetchCalls: string[] = []
    document.cookie = 'csrftoken=test-token; path=/'
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        fetchCalls.push(String(input))
        return new Response('%PDF', {
          status: 200,
          headers: { 'Content-Disposition': 'attachment; filename="invoice.pdf"' },
        })
      }),
    )
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    render(
      <FileAttachments
        parentType="p"
        parentId="r1"
        files={[DOC]}
        canAttach={false}
        onChange={() => undefined}
      />,
    )
    expect(screen.getByText('invoice.pdf')).toBeInTheDocument()
    expect(screen.getByText(/not virus-scanned/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Choose a file')).not.toBeInTheDocument() // cannot attach
    await userEvent.click(screen.getByRole('button', { name: 'Download invoice.pdf' }))
    await waitFor(() => expect(fetchCalls).toEqual(['/api/v1/documents/d1/download/']))
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('shows a refusal instead of a file when access is denied', async () => {
    mockApi({
      'GET /documents/d1/download/': {
        status: 404,
        body: { error: { code: 'not_found', message: 'Not found.', details: null } },
      },
    })
    render(
      <FileAttachments
        parentType="p"
        parentId="r1"
        files={[DOC]}
        canAttach
        onChange={() => undefined}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Download invoice.pdf' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found.')
    expect(screen.getByLabelText('Choose a file')).toBeInTheDocument()
  })

  it('removes a file through the archive endpoint and tells the page to reload', async () => {
    const onChange = vi.fn()
    const { calls } = mockApi({ 'POST /documents/d1/archive/': { body: { ...DOC } } })
    render(
      <FileAttachments parentType="p" parentId="r1" files={[DOC]} canAttach onChange={onChange} />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Remove invoice.pdf' }))
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(calls[0].path).toBe('/documents/d1/archive/')
  })

  it('hides Remove when the server says the file cannot be removed', () => {
    render(
      <FileAttachments
        parentType="p"
        parentId="r1"
        files={[{ ...DOC, can_archive: false }]}
        canAttach={false}
        onChange={() => undefined}
      />,
    )
    expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  })
})
