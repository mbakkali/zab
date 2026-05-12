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
    await expect(page.getByRole('button', { name: /Vue d\u2019ensemble/i })).toBeVisible()
  })

  test('navigation sidebar depuis #orgs', async ({ page }) => {
    await page.goto('/#orgs')
    await expect(page.getByRole('heading', { name: 'Organisations' })).toBeVisible()
    await page.getByRole('button', { name: /Vue d\u2019ensemble/i }).click()
    await expect(page.getByRole('heading', { name: 'Vue d\u2019ensemble' })).toBeVisible()
  })

  test('navigation sidebar depuis #projects', async ({ page }) => {
    await page.goto('/#projects')
    await expect(page.getByRole('heading', { name: 'Projets' })).toBeVisible()
  })

  test('navigation sidebar depuis #tasks_inbox', async ({ page }) => {
    await page.goto('/#tasks_inbox')
    await expect(page.getByRole('heading', { name: 'Tâches (multi-outils)' })).toBeVisible()
  })

  test('menu burger visible sur vue étroite', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    await expect(page.getByRole('button', { name: /menu de navigation/i })).toBeVisible()
  })

  test('onglet Connecteurs — grille et détail', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Connecteurs' }).click()
    await expect(page.locator('[data-testid="connectors-subtitle"]')).toBeVisible()
    const grid = page.locator('[data-testid="connectors-grid"]')
    await expect(grid).toBeVisible()
    const cards = grid.getByRole('button', { name: 'Voir' })
    const count = await cards.count()
    if (count === 0) {
      await expect(page.getByText('Aucun connecteur ne correspond.')).toBeVisible()
      return
    }
    await cards.first().click()
    await expect(page.locator('[data-testid="connector-detail-dialog"]')).toBeVisible()
    await expect(page.locator('[data-testid="connector-forms-list"]')).toBeVisible()
  })
})
