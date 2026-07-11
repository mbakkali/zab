import { expect, test, type APIRequestContext } from '@playwright/test'

type SearchApiRow = {
  document_id: string
  conversation_id?: string | null
  source: string
  wing: string | null
}

type BrowseApiRow = SearchApiRow & {
  message_count: number
  chunk_count: number
}

/** Aligné sur la logique d’agrégation provider du dashboard (pour filtre smoke). */
function providerSlugFromRow(row: SearchApiRow): string {
  const w = (row.wing ?? '').toLowerCase()
  if (
    row.source === 'cursor_agent_transcript' ||
    (row.source === 'agent_context_artifact' && w.startsWith('cursor'))
  )
    return 'cursor'
  if (row.source === 'claude_code_transcript') return 'claude'
  if (
    row.source === 'codex_transcript' ||
    (row.source === 'agent_context_artifact' && w.startsWith('codex'))
  )
    return 'codex'
  if (
    row.source === 'kimi_transcript' ||
    (row.source === 'agent_context_artifact' && w.startsWith('kimi'))
  )
    return 'kimi'
  if (row.source === 'hermes_transcript') return 'hermes'
  if (row.source === 'gemini_cli_transcript') return 'gemini'
  return row.source
}

async function probeSearchTerm(request: APIRequestContext): Promise<{
  term: string
  firstId: string
  detailId: string
  slug: string
} | null> {
  const envTerm = process.env.PLAYWRIGHT_CONVERSATIONS_SEARCH_TERM?.trim()
  const candidates = envTerm
    ? [envTerm]
    : ['user', 'assistant', 'tool', 'function', 'error', 'def', 'the', 'import', 'async']

  for (const term of candidates) {
    const r = await request.get(
      `/api/conversations/search?q=${encodeURIComponent(term)}&limit=5&offset=0`,
    )
    if (!r.ok()) continue
    const body = (await r.json()) as { results?: SearchApiRow[] }
    const row = body.results?.[0]
    if (row?.document_id) {
      return {
        term,
        firstId: row.document_id,
        detailId: row.conversation_id?.trim() || row.document_id,
        slug: providerSlugFromRow(row),
      }
    }
  }
  return null
}

async function probeHistory(request: APIRequestContext): Promise<BrowseApiRow | null> {
  const r = await request.get('/api/conversations/documents?limit=3&offset=0')
  if (!r.ok()) return null
  const body = (await r.json()) as { items?: BrowseApiRow[] }
  return body.items?.[0] ?? null
}

test.describe('conversations', () => {
  test('API providers et health', async ({ request }) => {
    const p = await request.get('/api/conversations/providers')
    expect(p.ok()).toBeTruthy()
    const pj = (await p.json()) as { providers: { id: string }[] }
    expect(Array.isArray(pj.providers)).toBeTruthy()
    expect(pj.providers.length).toBeGreaterThan(0)

    const h = await request.get('/api/conversations/health')
    expect(h.ok()).toBeTruthy()
    const hj = (await h.json()) as { severity: string }
    expect(['ok', 'warn', 'fail']).toContain(hj.severity)
  })

  test('navigation #conversations', async ({ page }) => {
    await page.goto('/#conversations')
    await expect(page.getByRole('heading', { name: 'Conversations' })).toBeVisible()
    await expect(page.locator('[data-testid="conversations-view"]')).toBeVisible()
    await expect(page.locator('[data-testid="conversations-health-banner"]')).toBeVisible()
    await expect(page.locator('[data-testid="conversations-search"]')).toBeVisible()
    await page.getByTestId('conversations-add-ai-provider').click()
    await expect(page).toHaveURL(/#config$/)
  })

  test('cartes providers après chargement', async ({ page }) => {
    await page.goto('/#conversations')
    await expect(page.getByRole('heading', { name: 'Conversations' })).toBeVisible()
    await page.getByTestId('conversations-refresh-health').click()
    await expect(page.locator('[data-testid="conversations-provider-cards"]')).toBeVisible()
    await expect(page.locator('[data-testid="conversation-provider-cursor"]')).toBeVisible()
    await expect(page.locator('[data-testid="conversation-provider-claude"]')).toBeVisible()
  })

  test('rafraîchir checks sans erreur', async ({ page }) => {
    await page.goto('/#conversations')
    await page.getByTestId('conversations-refresh-health').click()
    await expect(page.locator('[data-testid="conversations-health-banner"]')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Conversations' })).toBeVisible()
  })

  test('historique sans recherche affiche les conversations récentes', async ({ page, request }) => {
    const first = await probeHistory(request)
    test.skip(first === null, 'Historique conversations indisponible (Postgres non configuré ou base vide).')

    await page.goto('/#conversations')
    await expect(page.locator('[data-testid="conversations-results-table"]')).toBeVisible({
      timeout: 45_000,
    })
    await expect(page.locator('[data-testid="conversation-result-row"]').first()).toBeVisible()
    const detailResponse = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/conversations/document/${encodeURIComponent(first.conversation_id?.trim() || first.document_id)}`) &&
        r.request().method() === 'GET' &&
        r.ok(),
      { timeout: 45_000 },
    )
    await page.getByTestId(`conversation-open-detail-${first.document_id}`).click()
    await detailResponse
    await expect(page.getByTestId('conversation-detail-dialog')).toBeVisible({
      timeout: 30_000,
    })
  })

  test('recherche plein texte + résultats + détail (données Postgres réelles)', async ({
    page,
    request,
  }) => {
    const probe = await probeSearchTerm(request)
    test.skip(
      probe === null,
      'Aucune donnée trouvable via /api/conversations/search (Postgres vide, inaccessible ou pas de sync). Définissez PLAYWRIGHT_CONVERSATIONS_SEARCH_TERM si besoin.',
    )

    await page.goto('/#conversations')
    const searchInput = page.getByTestId('conversations-search')
    await searchInput.fill('')
    await searchInput.fill(probe.term)

    const resp = await page.waitForResponse(
      (r) =>
        r.url().includes('/api/conversations/search') &&
        r.request().method() === 'GET' &&
        r.ok(),
      { timeout: 45_000 },
    )
    const payload = (await resp.json()) as { results?: unknown[] }
    expect((payload.results ?? []).length).toBeGreaterThan(0)

    await expect(page.locator('[data-testid="conversations-results-table"]')).toBeVisible({
      timeout: 45_000,
    })
    await expect(page.locator('[data-testid="conversation-result-row"]').first()).toBeVisible()

    const detailResponse = page.waitForResponse(
      (r) =>
        r.url().includes(`/api/conversations/document/${encodeURIComponent(probe.detailId)}`) &&
        r.request().method() === 'GET' &&
        r.ok(),
      { timeout: 45_000 },
    )
    await page.getByTestId(`conversation-open-detail-${probe.firstId}`).click()
    await detailResponse
    await expect(page.getByTestId('conversation-detail-dialog')).toBeVisible({
      timeout: 30_000,
    })
  })

  test('checkbox provider applique un filtre multi-source', async ({ page }) => {
    test.setTimeout(90_000)
    const providerIds = ['cursor', 'claude', 'codex', 'hermes', 'gemini', 'kimi']
    await page.route('**/api/conversations/providers', async (route) => {
      await route.fulfill({
        json: {
          generated_at_utc: '2026-06-09T00:00:00Z',
          compact_index: { path: '/tmp/conversations-index.json' },
          providers: providerIds.map((id) => ({
            id,
            label: id === 'claude' ? 'Claude Code' : id === 'gemini' ? 'Gemini CLI' : id[0].toUpperCase() + id.slice(1),
            status: 'synced',
            postgres_documents: 10,
            local: {},
          })),
        },
      })
    })
    await page.route('**/api/conversations/health', async (route) => {
      await route.fulfill({
        json: {
          severity: 'ok',
          postgres: { configured: true, connected: true, document_count: 60 },
          integrity: null,
          recommendations: [],
          generated_at_utc: '2026-06-09T00:00:00Z',
        },
      })
    })
    await page.route('**/api/conversations/documents**', async (route) => {
      await route.fulfill({ json: { items: [], total: 0, conversation_storage: 'archive' } })
    })
    await page.route('**/api/conversations/search**', async (route) => {
      await route.fulfill({ json: { results: [] } })
    })

    await page.goto('/#conversations')
    await expect(page.getByTestId('conversations-provider-filter-hermes')).toBeChecked()
    await page.getByTestId('conversations-search').fill('user')
    await page.waitForResponse(
      (r) => r.url().includes('/api/conversations/search') && r.ok(),
      { timeout: 45_000 },
    )

    const filteredResponse = page.waitForResponse(
      (r) => {
        const u = new URL(r.url())
        const providers = u.searchParams.get('providers')
        return (
          r.url().includes('/api/conversations/search') &&
          r.ok() &&
          providers !== null &&
          !providers.split(',').includes('hermes')
        )
      },
      { timeout: 45_000 },
    )
    await page.getByTestId('conversations-provider-filter-hermes').click()
    await filteredResponse

    await expect(page.getByTestId('conversations-provider-filter-hermes')).not.toBeChecked()
    await expect(page.getByTestId('conversations-provider-filter-summary')).toContainText('5/6')
  })
})

/** Dry-run sync long : uniquement avec PLAYWRIGHT_CONVERSATIONS_JOB=dry-run */
test.describe('conversations jobs (optionnel)', () => {
  test.describe.configure({
    timeout: 900_000,
    retries: 0,
  })

  test('bouton Dry-run sync termine avec succès', async ({ page }) => {
    test.skip(
      process.env.PLAYWRIGHT_CONVERSATIONS_JOB !== 'dry-run',
      'Exporter PLAYWRIGHT_CONVERSATIONS_JOB=dry-run pour lancer ce test long.',
    )

    await page.goto('/#conversations')
    await page.getByTestId('conversations-dry-run').click()

    await expect(page.getByText('Dry-run completed', { exact: true })).toBeVisible({
      timeout: 880_000,
    })
  })
})
