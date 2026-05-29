import { expect, test, type APIRequestContext } from '@playwright/test'

type SearchApiRow = {
  document_id: string
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
      return { term, firstId: row.document_id, slug: providerSlugFromRow(row) }
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
    await page.getByTestId(`conversation-open-detail-${first.document_id}`).click()
    await expect(page.getByRole('dialog', { name: 'Conversation' })).toBeVisible({
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

    await page.getByTestId(`conversation-open-detail-${probe.firstId}`).click()
    await expect(page.getByRole('dialog', { name: 'Conversation' })).toBeVisible({
      timeout: 30_000,
    })
  })

  test('filtre provider conserve au moins un résultat quand pertinent', async ({
    page,
    request,
  }) => {
    const probe = await probeSearchTerm(request)
    test.skip(probe === null, 'Pas de données recherche pour ce filtre.')

    await page.goto('/#conversations')
    await page.getByTestId('conversations-search').fill(probe.term)
    await page.waitForResponse(
      (r) => r.url().includes('/api/conversations/search') && r.ok(),
      { timeout: 45_000 },
    )

    await page.getByTestId('conversations-provider-filter').selectOption(probe.slug)
    await page.waitForResponse(
      (r) => {
        const u = new URL(r.url())
        return (
          r.url().includes('/api/conversations/search') &&
          r.ok() &&
          u.searchParams.get('provider') === probe.slug
        )
      },
      { timeout: 45_000 },
    )

    const rows = page.locator('[data-testid="conversation-result-row"]')
    await expect(rows.first()).toBeVisible({ timeout: 45_000 })
    expect(await rows.count()).toBeGreaterThan(0)
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
