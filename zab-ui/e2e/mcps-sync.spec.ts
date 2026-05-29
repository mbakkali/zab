import { expect, test } from '@playwright/test'

test.describe('MCP locaux API + UI', () => {
  test('GET /api/mcps/sync-status et /api/mcps', async ({ request }) => {
    const st = await request.get('/api/mcps/sync-status')
    expect(st.ok()).toBeTruthy()
    expect(st.headers()['cache-control']).toContain('no-store')
    const j = (await st.json()) as { counts?: { servers_total?: number }; sources?: unknown }
    expect(j.counts).toBeTruthy()

    const list = await request.get('/api/mcps')
    expect(list.ok()).toBeTruthy()
    const body = (await list.json()) as { data: unknown[]; total: number }
    expect(Array.isArray(body.data)).toBeTruthy()
    expect(typeof body.total).toBe('number')
  })

  test('onglet Connecteurs — panneau MCP sync', async ({ page }) => {
    await page.goto('/#connectors')
    await expect(page.getByRole('heading', { name: 'Connectors' })).toBeVisible()
    await expect(page.getByTestId('mcp-sync-panel')).toBeVisible()
    await expect(page.getByTestId('mcp-sync-panel').getByRole('button', { name: /Scan local MCP/i })).toBeVisible()
  })
})
