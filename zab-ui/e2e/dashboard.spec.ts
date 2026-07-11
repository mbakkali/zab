import { expect, test } from '@playwright/test'

test.describe('zab dashboard', () => {
  test('API health', async ({ request }) => {
    const res = await request.get('/api/health')
    expect(res.ok()).toBeTruthy()
    const j = (await res.json()) as { status: string }
    expect(j.status).toBe('ok')
  })

  test('API connectors pagination', async ({ request }) => {
    const res = await request.get('/api/connectors?limit=5')
    expect(res.ok()).toBeTruthy()
    const j = (await res.json()) as {
      data: unknown[]
      pagination: { total: number; page: number; limit: number; total_pages: number }
    }
    expect(Array.isArray(j.data)).toBeTruthy()
    expect(typeof j.pagination.total).toBe('number')
  })

  test('overview contient orgs', async ({ request }) => {
    const res = await request.get('/api/overview')
    expect(res.ok()).toBeTruthy()
    const j = (await res.json()) as {
      orgs: unknown[]
      skills_root: string | null
      skills_root_configured: boolean
      user_config_path?: string
      skills_root_yaml_raw?: string | null
      zab_version?: string
    }
    expect(Array.isArray(j.orgs)).toBeTruthy()
    if (j.skills_root_configured && j.skills_root) {
      expect(j.skills_root.length).toBeGreaterThan(0)
    }
  })

  test('page SPA affiche zab', async ({ page }) => {
    await page.goto('/')
    await expect(page.locator('aside').getByText('zab', { exact: true }).first()).toBeVisible()
    await expect(page.getByRole('button', { name: /^Overview$/i })).toBeVisible()
  })

  test('language switcher EN par défaut puis FR', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('button', { name: /^Overview$/i })).toBeVisible()
    await page.locator('main').getByRole('button', { name: 'FR', exact: true }).click()
    await expect(page.getByRole('button', { name: /Vue d\u2019ensemble/i })).toBeVisible()
    await page.locator('main').getByRole('button', { name: 'EN', exact: true }).click()
    await expect(page.getByRole('button', { name: /^Overview$/i })).toBeVisible()
  })

  test('navigation sidebar depuis #orgs', async ({ page }) => {
    await page.goto('/#orgs')
    await expect(page.getByRole('heading', { name: 'Organizations' })).toBeVisible({
      timeout: 45_000,
    })
    await page.getByRole('button', { name: /^Overview$/i }).click()
    await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible()
  })

  test('navigation sidebar depuis #projects', async ({ page }) => {
    await page.goto('/#projects')
    await expect(page.getByRole('heading', { name: 'Projects', exact: true })).toBeVisible({
      timeout: 45_000,
    })
  })

  test('capabilities manifest UI', async ({ page, request }) => {
    const res = await request.get('/api/capabilities')
    expect(res.ok()).toBeTruthy()
    const manifest = (await res.json()) as {
      contract: string
      capabilities: { id: string }[]
      total: number
      complete: number
      partial: number
      summary: { total: number; complete: number; partial: number }
    }
    expect(manifest.contract).toBe('capability-manifest')
    expect(manifest.total).toBe(manifest.summary.total)
    expect(manifest.complete).toBe(manifest.summary.complete)
    expect(manifest.partial).toBe(manifest.summary.partial)
    expect(manifest.capabilities.some((capability) => capability.id === 'capabilities.manifest')).toBeTruthy()

    await page.goto('/#capabilities')
    await expect(page.getByRole('heading', { name: 'Capabilities' })).toBeVisible()
    await expect(page.locator('[data-testid="capabilities-view"]')).toBeVisible()
    await expect(page.locator('[data-testid="capabilities-total"]')).toHaveText(String(manifest.total))
    await expect(page.locator('[data-testid="capabilities-complete"]')).toHaveText(String(manifest.complete))
    await expect(page.locator('[data-testid="capabilities-partial"]')).toHaveText(String(manifest.partial))
    await expect(page.getByText('capabilities.manifest')).toBeVisible()
    await expect(page.getByText('Core', { exact: true }).first()).toBeVisible()
    await expect(page.getByText('MCP', { exact: true }).first()).toBeVisible()
  })

  test('source health UI', async ({ page }) => {
    await page.route('**/api/source-health**', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          contract: 'source-health',
          contract_version: '1.0',
          generated_at_utc: '2026-06-09T00:00:00+00:00',
          refresh: false,
          status_counts: { ok: 1 },
          sources: [
            {
              id: 'zab_inventory',
              kind: 'inventory',
              status: 'ok',
              freshness: 'local',
              last_checked_at: '2026-06-09T00:00:00+00:00',
              last_success_at: '2026-06-09T00:00:00+00:00',
              item_count: 3,
              auth: { status: 'not_applicable', secret_names: [], secret_values_exposed: false },
              safe_message: 'Inventory readable.',
              warnings: [],
            },
          ],
        }),
      })
    })

    await page.goto('/#source_health')
    await expect(page.locator('[data-testid="source-health-view"]')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Source Health' })).toBeVisible()
    await expect(page.locator('[data-testid="source-health-total"]')).toHaveText('1')
    await expect(page.getByText('zab_inventory')).toBeVisible()
  })

  test('research UI builds packet', async ({ page }) => {
    await page.route('**/api/research', async (route) => {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          contract: 'research-packet',
          contract_version: '1.0',
          generated_at_utc: '2026-06-09T00:00:00+00:00',
          query: 'comment rendre Zab dynamique ?',
          mode: 'plan',
          project: { id: 'zab', path: '/tmp/zab', confidence: 'high' },
          freshness: {},
          source_status: [{ source: 'zab_inventory', kind: 'inventory', status: 'ok', freshness: 'local', items_considered: 3 }],
          context_packet_markdown: '# Research Packet\n\n## Mission\ncomment rendre Zab dynamique ?',
          citations: [{ id: 'src_1', kind: 'contract', label: 'source-health', reason: 'Freshness.' }],
          conflicts: [],
          recommended_next_actions: ['Read the packet.'],
          warnings: [],
        }),
      })
    })

    await page.goto('/#research')
    await expect(page.locator('[data-testid="research-view"]')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Research' })).toBeVisible()
    await page.getByRole('button', { name: 'Run research' }).click()
    await expect(page.locator('[data-testid="research-packet"]')).toContainText('Research Packet')
    await expect(page.getByText('source-health')).toBeVisible()
  })

  test('cli check UI', async ({ page, request }) => {
    const res = await request.get('/api/cli-check')
    expect(res.ok()).toBeTruthy()
    const payload = (await res.json()) as { contract: string; checks: { id: string }[] }
    expect(payload.contract).toBe('cli-auth-checks')
    expect(Array.isArray(payload.checks)).toBeTruthy()

    await page.goto('/#cli_check')
    await expect(page.locator('[data-testid="cli-check-view"]')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'CLI auth' })).toBeVisible()
  })

  test('navigation sidebar depuis #tasks_inbox', async ({ page }) => {
    await page.goto('/#tasks_inbox')
    await expect(page.getByRole('heading', { name: 'Tasks', exact: true })).toBeVisible()
  })

  test('navigation sidebar depuis #conversations', async ({ page }) => {
    await page.goto('/#conversations')
    await expect(page.getByRole('heading', { name: 'Conversations' })).toBeVisible()
  })

  test('onglet Mémoire — scan projet et récupération config', async ({ page }) => {
    await page.goto('/#memory')
    await expect(page.getByRole('heading', { name: 'Memory' })).toBeVisible()
    await page.getByTestId('memory-tools-details').locator(':scope > summary').click()
    await expect(page.locator('[data-testid="memory-project-scan"]')).toBeVisible()
    await expect(page.locator('[data-testid="memory-config-recovery"]')).toBeVisible()
  })

  test('menu burger visible sur vue étroite', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    await expect(page.getByRole('button', { name: /open navigation menu/i })).toBeVisible()
  })

  test('onglet Connecteurs — grille et détail', async ({ page }) => {
    await page.goto('/')
    const connectorsResponse = page.waitForResponse(
      (r) => r.url().includes('/api/connectors?') && r.request().method() === 'GET' && r.ok(),
      { timeout: 45_000 },
    )
    await page.getByRole('button', { name: 'Connectors' }).click()
    await connectorsResponse
    await expect(page.locator('[data-testid="connectors-subtitle"]')).toBeVisible()
    const grid = page.locator('[data-testid="connectors-grid"]')
    const cards = grid.getByRole('button', { name: 'View' })
    const count = await cards.count()
    if (count === 0) {
      await expect(page.getByText('No connectors match.')).toBeVisible({ timeout: 45_000 })
      return
    }
    await expect(grid).toBeVisible()
    await cards.first().click()
    await expect(page.locator('[data-testid="connector-detail-dialog"]')).toBeVisible()
    await expect(page.locator('[data-testid="connector-forms-list"]')).toBeVisible()
  })
})
