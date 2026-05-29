import { expect, test } from '@playwright/test'

test.describe('Skills synchronisation', () => {
  test('API sync-status', async ({ request }) => {
    const res = await request.get('/api/skills/sync-status')
    expect(res.ok()).toBeTruthy()
    const j = (await res.json()) as {
      global_repo?: { skill_md_count: number }
      hermes?: { config_path: string }
      zab_index?: { skills_total: number }
    }
    expect(j.global_repo).toBeTruthy()
    expect(j.hermes).toBeTruthy()
    expect(j.zab_index).toBeTruthy()
  })

  test('API sync-hints', async ({ request }) => {
    const res = await request.get('/api/skills/sync-hints?limit=20')
    expect(res.ok()).toBeTruthy()
    const j = (await res.json()) as { hints?: Record<string, { global_repo?: boolean }>; count?: number }
    expect(j.hints).toBeTruthy()
    expect(typeof j.count).toBe('number')
  })

  test('onglet Skills — panneau sync et boutons', async ({ page }) => {
    await page.goto('/#skills')
    await expect(page.getByRole('heading', { name: 'Skills', exact: true })).toBeVisible()
    const panel = page.getByTestId('skills-sync-panel')
    await expect(panel).toBeVisible()
    await expect(page.getByTestId('skills-sync-auto')).toBeVisible()
    await expect(page.getByTestId('skills-sync-scan')).toBeVisible()
    await expect(page.getByTestId('skills-sync-hermes')).toBeVisible()
    await expect(page.getByTestId('skills-sync-hermes-export')).toBeVisible()
    await expect(page.getByTestId('skills-sync-github')).toBeVisible()
    await expect(page.getByTestId('skills-sync-refresh-index')).toBeVisible()
  })

  test('onglet Skills — onglets statut registre', async ({ page }) => {
    await page.goto('/#skills')
    await expect(page.getByTestId('skills-registry-tab-adopted')).toBeVisible()
    await expect(page.getByTestId('skills-registry-tab-candidate')).toBeVisible()
    await page.getByTestId('skills-registry-tab-candidate').click()
    await expect(page.getByTestId('skills-registry-tab-candidate')).toBeVisible()
  })

  test('onglet Skills — bouton export Hermes', async ({ page }) => {
    await page.goto('/#skills')
    await expect(page.getByTestId('skills-sync-hermes-export')).toBeVisible()
  })

  test('onglet Skills — ne liste pas le miroir projects/skills comme source principale', async ({ page }) => {
    await page.goto('/#skills')
    await expect(page.getByRole('heading', { name: 'Skills', exact: true })).toBeVisible()
    await expect(page.getByText('/projects/skills/')).toHaveCount(0)
    await page.getByText('Technical details').click()
    await expect(page.getByText('Mirror /projects/skills', { exact: true }).first()).toBeVisible()
  })
})
