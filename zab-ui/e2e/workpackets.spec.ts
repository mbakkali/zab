import { test, expect } from '@playwright/test'

test.describe('WorkPackets view', () => {
  test('loads #workpackets tab', async ({ page }) => {
    await page.goto('/#workpackets')
    await expect(page.getByTestId('workpackets-view')).toBeVisible()
    await expect(page.getByTestId('workpackets-view').getByText('WorkPackets', { exact: true })).toBeVisible()
  })
})

test.describe('Interactions view', () => {
  test('loads #interactions tab', async ({ page }) => {
    await page.goto('/#interactions')
    await expect(page.getByTestId('interactions-view')).toBeVisible()
    await expect(page.getByText('Channels connectés')).toBeVisible()
    await expect(page.getByText('Inbox par entreprise')).toBeVisible()
  })

  test('clicking a channel opens the Tools Catalog', async ({ page }) => {
    await page.goto('/#interactions')
    const firstChannel = page.getByTestId('channel-card').first()
    await expect(firstChannel).toBeVisible({ timeout: 10_000 })
    await firstChannel.click()
    await expect(page).toHaveURL(/#catalog/)
    await expect(page.getByTestId('tools-catalog-view')).toBeVisible()
  })
})
