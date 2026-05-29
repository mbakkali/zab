/** Démarre un job dashboard et attend la fin du flux SSE (logs + résumé). */

export type JobStreamResult = {
  status: string
  exit_code: number | null
  lines: string[]
}

async function postJobStart(preset: string, args?: Record<string, unknown>): Promise<{ id: string }> {
  const r = await fetch('/api/jobs/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preset, args }),
  })
  if (!r.ok) {
    const t = await r.text()
    throw new Error(t || r.statusText)
  }
  return r.json() as Promise<{ id: string }>
}

export function startJobAndCollectLines(
  preset: string,
  args?: Record<string, unknown>,
): Promise<JobStreamResult> {
  const lines: string[] = []
  return postJobStart(preset, args).then(
    (job) =>
      new Promise((resolve, reject) => {
        const es = new EventSource(`/api/jobs/${job.id}/stream`)
        es.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data) as {
              line?: string
              summary?: { status: string; exit_code: number | null }
            }
            if (typeof data.line === 'string') {
              lines.push(data.line)
            }
            if (data.summary) {
              es.close()
              resolve({
                status: data.summary.status,
                exit_code: data.summary.exit_code,
                lines,
              })
            }
          } catch (e) {
            es.close()
            reject(e instanceof Error ? e : new Error(String(e)))
          }
        }
        es.onerror = () => {
          es.close()
          reject(new Error('Flux SSE interrompu'))
        }
      }),
  )
}
