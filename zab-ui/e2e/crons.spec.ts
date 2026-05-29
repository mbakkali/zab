import { expect, test } from '@playwright/test'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

test.describe('Zab Crons E2E + UI', () => {
  test('API GET /api/crons et POST /api/crons/sync', async ({ request }) => {
    // 1) Test de la récupération du cache
    const resGet = await request.get('/api/crons')
    expect(resGet.ok()).toBeTruthy()
    const getBody = (await resGet.json()) as { crons: any[] }
    expect(Array.isArray(getBody.crons)).toBeTruthy()

    // 2) Test du déclenchement d'un sync
    const resSync = await request.post('/api/crons/sync')
    expect(resSync.ok()).toBeTruthy()
    const syncBody = (await resSync.json()) as { crons: any[] }
    expect(Array.isArray(syncBody.crons)).toBeTruthy()
  })

  test('Navigation vers #crons et capture des captures d\'écran', async ({ page }) => {
    // S'assurer que le dossier .screenshots existe
    const screenshotDir = path.resolve(__dirname, '../.screenshots')
    if (!fs.existsSync(screenshotDir)) {
      fs.mkdirSync(screenshotDir, { recursive: true })
    }

    // 1) Charger la page Crons
    await page.goto('/#crons')
    await page.waitForLoadState('networkidle')

    // Attendre la disparition du spinner de chargement principal ou de l'affichage
    await expect(page.getByRole('heading', { name: 'Crons & Schedulers' })).toBeVisible()

    // Attendre que la liste ou le texte de chargement/vide apparaisse
    await page.waitForTimeout(2000) // Donne le temps au chargement initial de l'API de se faire

    // Prendre une capture d'écran de l'onglet Crons global
    await page.screenshot({ path: path.join(screenshotDir, 'after-crons.png'), fullPage: true })
    console.log('Saved after-crons.png')

    // 2) Tenter de cliquer sur la première carte s'il y en a pour afficher les logs
    // On repère les cartes de crons par leur source ("hermes" ou "gcp") ou le titre cliquable
    const cronCards = page.locator('div.divide-y > div.cursor-pointer')
    const count = await cronCards.count()
    
    if (count > 0) {
      // Cliquer sur le premier cron pour charger ses logs
      await cronCards.first().click()
      
      // Attendre que le panneau de détail des logs apparaisse à droite
      await page.waitForTimeout(2000) // Temps d'attente pour le chargement des logs GCP/Hermes
      
      // Prendre une capture d'écran du détail splitscreen
      await page.screenshot({ path: path.join(screenshotDir, 'after-crons-detail.png'), fullPage: true })
      console.log('Saved after-crons-detail.png')
    } else {
      console.log('No crons detected in the list, skipping splitscreen screenshot.')
    }
  })
})
