import { expect, test } from '@playwright/test'

/**
 * Ouvre chaque page du dashboard et vérifie :
 *  1. le chargement initial (cold) reste sous le budget de 500 ms côté front ;
 *  2. chaque vue lazy se monte sans erreur JS (un import dynamique cassé
 *     remonterait en `pageerror`) et sous le budget de 500 ms ;
 *  3. le chunk réseau de chaque vue se télécharge en moins de 500 ms.
 */

const PAGE_BUDGET_MS = 500

// Identifiants de navigation (= hash de route) exposés par la sidebar.
const NAV_IDS = [
  'overview',
  'system_check',
  'cli_check',
  'capabilities',
  'source_health',
  'logs',
  'orgs',
  'projects',
  'tasks_inbox',
  'channels',
  'conversations',
  'interactions',
  'workpackets',
  'plugins',
  'connectors',
  'catalog',
  'config',
  'tests',
  'security',
  'memory',
  'ide',
  'models',
  'workstation',
  'skills',
  'crons',
] as const

/** Attend que la vue soit réellement montée (le fallback <Suspense> n'est qu'un spinner). */
async function waitViewMounted(page: import('@playwright/test').Page) {
  await page.waitForFunction(
    () => {
      const container = document.querySelector('.max-w-7xl')
      if (!container) return false
      return !!container.querySelector(
        '[data-testid], section, table, h1, h2, h3, form, [role="tabpanel"]',
      )
    },
    { timeout: 20_000 },
  )
}

test('chargement initial (cold) sous 500 ms', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

  await page.goto('/')
  await expect(page.getByRole('button', { name: /^Overview$/ })).toBeVisible()
  await waitViewMounted(page)

  const timing = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming
    const fcp = performance
      .getEntriesByType('paint')
      .find((p) => p.name === 'first-contentful-paint')
    return {
      domContentLoaded: Math.round(nav.domContentLoadedEventEnd),
      loadEvent: Math.round(nav.loadEventEnd),
      firstContentfulPaint: fcp ? Math.round(fcp.startTime) : null,
    }
  })

  // eslint-disable-next-line no-console
  console.log('[cold load]', JSON.stringify(timing))
  expect(errors, errors.join('\n')).toEqual([])
  expect(timing.domContentLoaded).toBeLessThan(PAGE_BUDGET_MS)
  if (timing.firstContentfulPaint != null) {
    expect(timing.firstContentfulPaint).toBeLessThan(PAGE_BUDGET_MS)
  }
})

test('chaque page s’ouvre sans erreur JS et sous budget', async ({ page }) => {
  const errorsByPage = new Map<string, string[]>()
  let current = 'init'
  const record = (msg: string) => {
    const list = errorsByPage.get(current) ?? []
    list.push(msg)
    errorsByPage.set(current, list)
  }
  page.on('pageerror', (e) => record(`pageerror: ${e.message}`))

  await page.goto('/')
  await expect(page.getByRole('button', { name: /^Overview$/ })).toBeVisible()

  const results: { id: string; mountMs: number; chunkMs: number | null }[] = []

  for (const id of NAV_IDS) {
    current = id
    const start = Date.now()
    await page.goto(`/#${id}`)
    await waitViewMounted(page)
    const mountMs = Date.now() - start

    // Durée réseau du chunk lazy de cette vue (via Resource Timing), si applicable.
    const chunkMs = await page.evaluate((navId) => {
      const key = navId.replace(/_/g, '-')
      const entries = performance
        .getEntriesByType('resource')
        .filter((r) => r.name.includes(`/assets/${key}`) || r.name.includes(`${key}-view`))
      if (entries.length === 0) return null
      return Math.round(Math.max(...entries.map((r) => (r as PerformanceResourceTiming).duration)))
    }, id)

    results.push({ id, mountMs, chunkMs })
  }

  // eslint-disable-next-line no-console
  console.table(results)

  const pagesWithErrors = [...errorsByPage.entries()].filter(([, v]) => v.length > 0)
  expect(
    pagesWithErrors,
    pagesWithErrors.map(([k, v]) => `${k}:\n  ${v.join('\n  ')}`).join('\n'),
  ).toEqual([])

  const overBudget = results.filter((r) => r.mountMs >= PAGE_BUDGET_MS)
  expect(
    overBudget,
    `Pages au-dessus de ${PAGE_BUDGET_MS} ms:\n` +
      overBudget.map((r) => `  ${r.id}: ${r.mountMs} ms`).join('\n'),
  ).toEqual([])
})
