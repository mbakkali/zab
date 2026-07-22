#!/usr/bin/env node
/**
 * Local Dashlane Web writer for Zab.
 *
 * Contract:
 *   - reads one JSON object from stdin: { name, title, value, note? }
 *   - opens Dashlane Web with a persistent Playwright profile
 *   - creates one Secret named title with value
 *   - writes only redacted metadata to stdout
 *
 * The secret value is never accepted through argv and is never printed.
 */

import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { spawn } from 'node:child_process'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const DEFAULT_DASHLANE_URL = 'https://app.dashlane.com/#/credentials'
const DEFAULT_PROFILE_DIR = path.join(os.homedir(), '.local', 'share', 'zab', 'dashlane-writer-profile')
const DEFAULT_TIMEOUT_MS = 180_000

function usage() {
  return [
    'Usage: dashlane-secret-writer.mjs [--dry-run] [--probe-applescript]',
    '',
    'Reads JSON from stdin:',
    '  {"name":"QONTO_SECRET_KEY","title":"Z_QONTO_SECRET_KEY","value":"...","note":"optional"}',
    '',
    'Environment:',
    '  DASHLANE_WRITER_URL              Default: https://app.dashlane.com/#/credentials',
    '  DASHLANE_WRITER_MODE             auto|playwright|applescript (default: auto)',
    '  DASHLANE_WRITER_CDP_URL          Attach to an already-running Chrome, e.g. http://127.0.0.1:9222',
    '  DASHLANE_WRITER_ATTACH_CHROME=1  Shortcut for DASHLANE_WRITER_CDP_URL=http://127.0.0.1:9222',
    '  DASHLANE_WRITER_USER_DATA_DIR    Default: ~/.local/share/zab/dashlane-writer-profile',
    '  DASHLANE_WRITER_HEADLESS=1       Run headless; default is headed for login/MFA',
    '  DASHLANE_WRITER_TIMEOUT_MS       Default: 180000',
    '  DASHLANE_WRITER_BROWSER_CHANNEL  Default: chrome; set chromium to use bundled Chromium',
  ].join('\n')
}

function fail(reason, extra = {}) {
  const payload = { ok: false, reason, ...extra }
  process.stdout.write(`${JSON.stringify(payload)}\n`)
  process.exit(1)
}

function ok(payload) {
  process.stdout.write(`${JSON.stringify({ ok: true, ...payload })}\n`)
}

async function readStdinJson() {
  const chunks = []
  for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk))
  const raw = Buffer.concat(chunks).toString('utf8').trim()
  if (!raw) fail('stdin_json_missing')
  try {
    return JSON.parse(raw)
  } catch {
    fail('stdin_json_invalid')
  }
}

function cleanText(value) {
  return String(value ?? '').trim()
}

function validatePayload(input) {
  const name = cleanText(input.name)
  const title = cleanText(input.title)
  const value = cleanText(input.value)
  const note = cleanText(input.note)
  if (!name) fail('name_missing')
  if (!title) fail('title_missing')
  if (!value) fail('value_missing')
  if (value.startsWith('dl://')) fail('value_is_already_dashlane_reference', { title })
  return { name, title, value, note }
}

function referenceForTitle(title) {
  return `dl://${title}`
}

async function runProcess(command, args, options = {}) {
  return await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      ...options,
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8')
    })
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8')
    })
    child.on('error', reject)
    child.on('close', (code) => resolve({ code: code ?? 0, stdout, stderr }))
    if (options.input) {
      child.stdin.end(options.input)
    } else {
      child.stdin.end()
    }
  })
}

async function resolveWriterMode() {
  const requested = cleanText(process.env.DASHLANE_WRITER_MODE || 'auto').toLowerCase()
  if (requested && requested !== 'auto') return requested
  if (process.platform !== 'darwin') return 'playwright'
  try {
    const result = await runProcess('/usr/bin/pgrep', ['-x', 'Google Chrome'])
    return result.code === 0 && result.stdout.trim() ? 'applescript' : 'playwright'
  } catch {
    return 'playwright'
  }
}

async function writePrivateTempFile(prefix, content) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), prefix))
  const file = path.join(dir, 'payload')
  await fs.writeFile(file, content, { mode: 0o600 })
  return { dir, file }
}

async function removeTempDir(dir) {
  await fs.rm(dir, { recursive: true, force: true }).catch(() => {})
}

function compactError(text) {
  return String(text || '').replace(/\s+/g, ' ').trim().slice(0, 240)
}

async function importPlaywright() {
  try {
    const mod = await import('playwright')
    return mod.chromium ? mod : mod.default
  } catch {
    const localPlaywright = path.join(REPO_ROOT, 'zab-ui', 'node_modules', 'playwright', 'index.js')
    try {
      const mod = await import(pathToFileURL(localPlaywright).href)
      return mod.chromium ? mod : mod.default
    } catch {
      fail('playwright_not_installed', {
        hint: 'Run `cd zab-ui && npm install` or set ZAB_DASHLANE_SECRET_CREATE_COMMAND to another writer.',
      })
    }
  }
}

async function discoverChromeCdpUrl() {
  const explicitUrl =
    process.env.DASHLANE_WRITER_CDP_URL ||
    (process.env.DASHLANE_WRITER_ATTACH_CHROME === '1' ? 'http://127.0.0.1:9222' : '')
  if (explicitUrl) return explicitUrl

  const defaultUrl = 'http://127.0.0.1:9222'
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 350)
  try {
    const response = await fetch(`${defaultUrl}/json/version`, { signal: controller.signal })
    return response.ok ? defaultUrl : ''
  } catch {
    return ''
  } finally {
    clearTimeout(timer)
  }
}

async function openDashlaneBrowser(chromium) {
  const cdpUrl = await discoverChromeCdpUrl()
  if (cdpUrl) {
    try {
      const browser = await chromium.connectOverCDP(cdpUrl)
      const context = browser.contexts()[0] ?? (await browser.newContext())
      const page = context.pages()[0] ?? (await context.newPage())
      return {
        page,
        close: async () => {
          if (typeof browser.disconnect === 'function') browser.disconnect()
          // Some Playwright builds do not expose disconnect(); when the writer
          // process exits, the CDP connection is released without closing Chrome.
        },
      }
    } catch {
      let port = '9222'
      try {
        port = new URL(cdpUrl).port || port
      } catch {
        // Keep the default port in the hint.
      }
      fail('chrome_cdp_unavailable', {
        hint: `Start Chrome with --remote-debugging-port=${port} or unset DASHLANE_WRITER_CDP_URL.`,
      })
    }
  }

  const userDataDir = process.env.DASHLANE_WRITER_USER_DATA_DIR || DEFAULT_PROFILE_DIR
  const headless = process.env.DASHLANE_WRITER_HEADLESS === '1'
  const requestedChannel = process.env.DASHLANE_WRITER_BROWSER_CHANNEL || 'chrome'
  const launchOptions = {
    headless,
    viewport: { width: 1400, height: 1000 },
  }
  if (requestedChannel && requestedChannel !== 'chromium') {
    launchOptions.channel = requestedChannel
  }

  await fs.mkdir(userDataDir, { recursive: true })
  try {
    const context = await chromium.launchPersistentContext(userDataDir, launchOptions)
    const page = context.pages()[0] ?? (await context.newPage())
    return { page, close: async () => context.close().catch(() => {}) }
  } catch (error) {
    if (requestedChannel !== 'chrome') throw error
    const context = await chromium.launchPersistentContext(userDataDir, {
      headless,
      viewport: { width: 1400, height: 1000 },
    })
    const page = context.pages()[0] ?? (await context.newPage())
    return { page, close: async () => context.close().catch(() => {}) }
  }
}

async function runAppleScript(script, args = []) {
  const temp = await writePrivateTempFile('zab-osa-', script)
  try {
    const result = await runProcess('/usr/bin/osascript', [temp.file, ...args])
    return result
  } finally {
    await removeTempDir(temp.dir)
  }
}

async function enableChromeJavascriptAppleEvents() {
  const script = String.raw`
tell application "Google Chrome" to activate
delay 0.3
tell application "System Events"
  tell process "Google Chrome"
    try
      click menu item "Allow JavaScript from Apple Events" of menu 1 of menu item "Developer" of menu 1 of menu bar item "View" of menu bar 1
      delay 0.6
      try
        if exists button "Allow" of front window then click button "Allow" of front window
      end try
      try
        if exists button "OK" of front window then click button "OK" of front window
      end try
      return "ok"
    on error errMsg number errNo
      return "error:" & errNo & ":" & errMsg
    end try
  end tell
end tell
`
  const result = await runAppleScript(script)
  if (result.code !== 0 || !result.stdout.trim().startsWith('ok')) {
    fail('chrome_js_apple_events_enable_failed', { error: compactError(result.stderr || result.stdout) })
  }
}

async function executeChromeJavascript(jsSource, targetUrl = DEFAULT_DASHLANE_URL) {
  const jsTemp = await writePrivateTempFile('zab-dashlane-js-', jsSource)
  const osa = String.raw`
on run argv
  set jsPath to item 1 of argv
  set targetUrl to item 2 of argv
  set jsText to read POSIX file jsPath as «class utf8»
  tell application "Google Chrome"
    if not running then activate
    activate
    set matched to false
    try
      repeat with wi from 1 to count windows
        repeat with ti from 1 to count tabs of window wi
          set tabUrl to URL of tab ti of window wi
          set tabTitle to title of tab ti of window wi
          if tabUrl contains "app.dashlane.com" or (tabUrl contains "chrome-extension://" and tabTitle contains "Dashlane") then
            set active tab index of window wi to ti
            set index of window wi to 1
            set matched to true
            exit repeat
          end if
        end repeat
        if matched then exit repeat
      end repeat
    end try
    if not matched then
      open location targetUrl
      delay 4
    else
      try
        set currentUrl to URL of active tab of front window
        if currentUrl does not contain "#/credentials" and currentUrl does not contain "/credentials" then
          set URL of active tab of front window to targetUrl
          delay 4
        end if
      end try
    end if
    return execute active tab of front window javascript jsText
  end tell
end run
`
  try {
    const result = await runAppleScript(osa, [jsTemp.file, targetUrl])
    if (result.code !== 0) {
      const text = result.stderr || result.stdout
      if (text.includes('Executing JavaScript through AppleScript is turned off')) {
        fail('chrome_javascript_apple_events_disabled', {
          hint: 'In Chrome: View > Developer > Allow JavaScript from Apple Events, then restart Chrome if the setting is still not applied.',
        })
      }
      fail('chrome_applescript_execute_failed', { error: compactError(text) })
    }
    return result.stdout.trim()
  } finally {
    await removeTempDir(jsTemp.dir)
  }
}

function dashlaneDriverJavascript(payload) {
  const safePayload = JSON.stringify({
    title: payload.title,
    value: payload.value,
    note: payload.note || '',
  })
  return String.raw`
(() => {
  const payload = ${safePayload};
  const stateKey = '__zabDashlaneWriterResult';
  window[stateKey] = { ok: false, status: 'running', title: payload.title };
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalize = (value) => String(value || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  };
  const allDeep = (selector, root = document) => {
    const out = [];
    const visit = (node) => {
      try {
        if (node.querySelectorAll) out.push(...node.querySelectorAll(selector));
        const all = node.querySelectorAll ? node.querySelectorAll('*') : [];
        for (const child of all) {
          if (child.shadowRoot) visit(child.shadowRoot);
        }
      } catch {}
    };
    visit(root);
    return out;
  };
  const textOf = (el) => normalize([
    el?.innerText,
    el?.textContent,
    el?.getAttribute?.('aria-label'),
    el?.getAttribute?.('title'),
    el?.getAttribute?.('placeholder'),
    el?.getAttribute?.('name'),
    el?.getAttribute?.('id'),
  ].filter(Boolean).join(' '));
  const matches = (el, patterns) => patterns.some((pattern) => pattern.test(textOf(el)));
  const clickMatch = (selector, patterns) => {
    const el = allDeep(selector).find((candidate) => visible(candidate) && matches(candidate, patterns));
    if (!el) return false;
    el.scrollIntoView({ block: 'center', inline: 'center' });
    el.click();
    return true;
  };
  const labelFor = (el) => {
    const id = el.getAttribute?.('id');
    const labels = [];
    if (id) labels.push(...allDeep('label').filter((label) => label.getAttribute('for') === id));
    try {
      if (el.labels) labels.push(...Array.from(el.labels));
    } catch {}
    return normalize(labels.map((label) => label.innerText || label.textContent || '').join(' '));
  };
  const editableFields = () => allDeep('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]), textarea, [contenteditable=true]')
    .filter((field) => visible(field))
    .filter((field) => !/search|rechercher/.test(textOf(field)));
  const fieldMatches = (field, patterns) => {
    const haystack = textOf(field) + ' ' + labelFor(field);
    return patterns.some((pattern) => pattern.test(haystack));
  };
  const setNativeValue = (field, value) => {
    field.scrollIntoView({ block: 'center', inline: 'center' });
    field.focus();
    if (field.isContentEditable) {
      field.textContent = value;
    } else {
      const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const descriptor = Object.getOwnPropertyDescriptor(prototype, 'value');
      if (descriptor?.set) descriptor.set.call(field, value);
      else field.value = value;
    }
    field.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    field.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const waitFor = async (fn, timeout = 30000) => {
    const started = Date.now();
    while (Date.now() - started < timeout) {
      const value = fn();
      if (value) return value;
      await sleep(400);
    }
    return null;
  };
  (async () => {
    try {
      const addPatterns = [/add new/, /add secret/, /new secret/, /ajouter/, /nouveau/, /creer/, /creer un secret/, /create/];
      const clickedAdd = await waitFor(() => clickMatch('button, a, [role=button], [role=menuitem]', addPatterns), 45000);
      if (!clickedAdd) throw new Error('dashlane_add_button_not_found');
      await sleep(1000);
      clickMatch('button, a, [role=button], [role=menuitem], [role=option]', [/^secret$/, /secrets?/, /secure note/]);
      await sleep(1200);

      const namePatterns = [/secret name/, /^name$/, /item name/, /nom du secret/, /^nom$/, /titre/, /title/];
      const valuePatterns = [/secret value/, /^value$/, /valeur du secret/, /^valeur$/, /content/, /contenu/, /password/];
      const fields = await waitFor(() => {
        const current = editableFields();
        return current.length >= 2 ? current : null;
      }, 45000);
      if (!fields) throw new Error('dashlane_fields_not_found');

      const nameField = fields.find((field) => fieldMatches(field, namePatterns)) || fields[0];
      let valueField = fields.find((field) => field !== nameField && fieldMatches(field, valuePatterns));
      if (!valueField) valueField = fields.find((field) => field !== nameField);
      if (!nameField || !valueField) throw new Error('dashlane_name_or_value_field_not_found');
      setNativeValue(nameField, payload.title);
      setNativeValue(valueField, payload.value);

      if (payload.note) {
        const noteField = fields.find((field) => field !== nameField && field !== valueField && fieldMatches(field, [/note/, /description/]));
        if (noteField) setNativeValue(noteField, payload.note);
      }

      const savePatterns = [/^save$/, /save secret/, /add secret/, /enregistrer/, /sauvegarder/, /^creer$/, /^create$/];
      const saved = await waitFor(() => clickMatch('button, [role=button]', savePatterns), 30000);
      if (!saved) throw new Error('dashlane_save_button_not_found');
      await sleep(2500);
      window[stateKey] = {
        ok: true,
        status: 'created',
        title: payload.title,
        reference: 'dl://' + payload.title,
        web_url: location.href && location.href.startsWith('https://') ? location.href : 'https://app.dashlane.com/#/credentials',
      };
      payload.value = '';
    } catch (error) {
      payload.value = '';
      window[stateKey] = {
        ok: false,
        status: 'error',
        reason: String(error && error.message || error).slice(0, 160),
        title: payload.title,
      };
    }
  })();
  return 'started';
})();
`
}

async function createSecretWithAppleScript(payload) {
  const targetUrl = process.env.DASHLANE_WRITER_URL || DEFAULT_DASHLANE_URL
  const probe = await executeChromeJavascript('document.title', targetUrl)
  if (!probe && probe !== '') {
    fail('chrome_applescript_probe_failed')
  }
  const started = await executeChromeJavascript(dashlaneDriverJavascript(payload), targetUrl)
  if (!started.includes('started')) {
    fail('chrome_applescript_driver_not_started', { error: compactError(started) })
  }
  const timeoutMs = Number.parseInt(process.env.DASHLANE_WRITER_TIMEOUT_MS ?? `${DEFAULT_TIMEOUT_MS}`, 10)
  const startedAt = Date.now()
  while (Date.now() - startedAt < timeoutMs) {
    await new Promise((resolve) => setTimeout(resolve, 1_000))
    const raw = await executeChromeJavascript(
      "JSON.stringify(window.__zabDashlaneWriterResult || {ok:false,status:'missing'})",
      targetUrl,
    )
    let status
    try {
      status = JSON.parse(raw)
    } catch {
      continue
    }
    if (status.status === 'running' || status.status === 'missing') continue
    if (status.ok) {
      return {
        webUrl: status.web_url || DEFAULT_DASHLANE_URL,
        reference: status.reference || referenceForTitle(payload.title),
      }
    }
    fail(status.reason || 'chrome_applescript_writer_failed', { title: payload.title })
  }
  fail('chrome_applescript_writer_timeout', { title: payload.title })
}

async function clickFirst(page, candidates, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  let lastError = null
  while (Date.now() < deadline) {
    for (const candidate of candidates) {
      try {
        const locator = typeof candidate === 'function' ? candidate() : candidate
        const first = locator.first()
        if ((await first.count()) > 0 && (await first.isVisible().catch(() => false))) {
          await first.click({ timeout: 2_000 })
          return true
        }
      } catch (error) {
        lastError = error
      }
    }
    await page.waitForTimeout(400)
  }
  if (lastError) return false
  return false
}

async function fillFirst(page, candidates, value, timeoutMs) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    for (const candidate of candidates) {
      try {
        const locator = typeof candidate === 'function' ? candidate() : candidate
        const first = locator.first()
        if ((await first.count()) > 0 && (await first.isVisible().catch(() => false))) {
          await first.fill(value, { timeout: 2_000 })
          return true
        }
      } catch {
        // Try the next selector.
      }
    }
    await page.waitForTimeout(400)
  }
  return false
}

async function visibleEditableFields(page) {
  const fields = page.locator(
    'input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):not([type="submit"]), textarea, [contenteditable="true"]',
  )
  const count = await fields.count()
  const out = []
  for (let index = 0; index < count; index += 1) {
    const field = fields.nth(index)
    if (!(await field.isVisible().catch(() => false))) continue
    const aria = (await field.getAttribute('aria-label').catch(() => '')) ?? ''
    const placeholder = (await field.getAttribute('placeholder').catch(() => '')) ?? ''
    const type = (await field.getAttribute('type').catch(() => '')) ?? ''
    const text = `${aria} ${placeholder} ${type}`.toLowerCase()
    if (text.includes('search') || text.includes('rechercher')) continue
    out.push(field)
  }
  return out
}

async function fillByFallbackFields(page, title, value) {
  const fields = await visibleEditableFields(page)
  if (fields.length < 2) return false
  await fields[0].fill(title)
  await fields[1].fill(value)
  return true
}

async function waitForDashlaneApp(page, timeoutMs) {
  const addButton = page.getByRole('button', { name: /add new|add secret|ajouter|nouveau|créer|creer/i })
  const vaultNav = page.getByText(/credentials|identifiants|logins|secrets/i)
  const loginFields = page.locator('input[type="email"], input[type="password"]')
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if ((await addButton.count().catch(() => 0)) > 0) return true
    if ((await vaultNav.count().catch(() => 0)) > 0 && page.url().includes('dashlane')) return true
    if ((await loginFields.count().catch(() => 0)) > 0) {
      await page.waitForTimeout(1_000)
    } else {
      await page.waitForTimeout(500)
    }
  }
  fail('dashlane_login_or_app_timeout', {
    hint: 'A headed browser was opened. Log in to Dashlane once, then run the sync again.',
  })
}

async function chooseSecretTypeIfMenuAppears(page) {
  await page.waitForTimeout(500)
  await clickFirst(
    page,
    [
      () => page.getByRole('menuitem', { name: /^secret$|secrets|secret/i }),
      () => page.getByRole('option', { name: /^secret$|secrets|secret/i }),
      () => page.getByRole('button', { name: /^secret$|secrets|secret/i }),
      () => page.getByText(/^secret$|secrets|secret/i),
    ],
    2_500,
  )
}

async function createSecret({ title, value, note }) {
  const { chromium } = await importPlaywright()
  const timeoutMs = Number.parseInt(process.env.DASHLANE_WRITER_TIMEOUT_MS ?? `${DEFAULT_TIMEOUT_MS}`, 10)
  const browserHandle = await openDashlaneBrowser(chromium)
  const { page } = browserHandle
  page.setDefaultTimeout(Math.min(timeoutMs, 30_000))

  try {
    await page.goto(process.env.DASHLANE_WRITER_URL || DEFAULT_DASHLANE_URL, { waitUntil: 'domcontentloaded' })
    await waitForDashlaneApp(page, timeoutMs)

    const clickedAdd = await clickFirst(
      page,
      [
        () => page.getByRole('button', { name: /add new|add secret|ajouter|nouveau|créer|creer/i }),
        () => page.getByRole('link', { name: /add new|add secret|ajouter|nouveau|créer|creer/i }),
        () => page.locator('[aria-label*="Add" i], [aria-label*="Ajouter" i]').first(),
      ],
      20_000,
    )
    if (!clickedAdd) fail('dashlane_add_button_not_found')

    await chooseSecretTypeIfMenuAppears(page)

    const filledName = await fillFirst(
      page,
      [
        () => page.getByLabel(/secret name|name|nom du secret|nom/i),
        () => page.getByPlaceholder(/secret name|name|nom du secret|nom/i),
        () => page.locator('input[name*="title" i], input[name*="name" i]'),
      ],
      title,
      20_000,
    )

    const filledValue = await fillFirst(
      page,
      [
        () => page.getByLabel(/secret value|value|valeur du secret|valeur/i),
        () => page.getByPlaceholder(/secret value|value|valeur du secret|valeur/i),
        () => page.locator('textarea[name*="value" i], input[name*="value" i], input[type="password"]'),
      ],
      value,
      20_000,
    )

    if (!filledName || !filledValue) {
      const fallbackFilled = await fillByFallbackFields(page, title, value)
      if (!fallbackFilled) fail(filledName ? 'dashlane_value_field_not_found' : 'dashlane_name_field_not_found')
    }

    if (note) {
      await fillFirst(
        page,
        [
          () => page.getByLabel(/^note$|notes|description/i),
          () => page.getByPlaceholder(/^note$|notes|description/i),
          () => page.locator('textarea[name*="note" i], textarea[name*="description" i]'),
        ],
        note,
        2_500,
      )
    }

    const clickedSave = await clickFirst(
      page,
      [
        () => page.getByRole('button', { name: /^save$|save secret|add secret|enregistrer|sauvegarder|créer|creer/i }),
        () => page.locator('button[type="submit"]'),
      ],
      20_000,
    )
    if (!clickedSave) fail('dashlane_save_button_not_found')

    await page.waitForTimeout(1_500)
    await Promise.race([
      page.getByText(title, { exact: false }).first().waitFor({ state: 'visible', timeout: 15_000 }).catch(() => {}),
      page.waitForURL(/app\.dashlane\.com.*(credentials|secrets)/i, { timeout: 15_000 }).catch(() => {}),
    ])

    return { webUrl: page.url() }
  } finally {
    await browserHandle.close()
  }
}

async function main() {
  const args = new Set(process.argv.slice(2))
  if (args.has('--help') || args.has('-h')) {
    process.stdout.write(`${usage()}\n`)
    return
  }
  if (args.has('--enable-chrome-js-events')) {
    await enableChromeJavascriptAppleEvents()
    const targetUrl = process.env.DASHLANE_WRITER_URL || DEFAULT_DASHLANE_URL
    const title = await executeChromeJavascript('document.title', targetUrl)
    ok({ enabled: true, capability: 'chrome_javascript_apple_events', title })
    return
  }
  if (args.has('--probe-applescript')) {
    const targetUrl = process.env.DASHLANE_WRITER_URL || DEFAULT_DASHLANE_URL
    const title = await executeChromeJavascript('document.title', targetUrl)
    ok({ capability: 'chrome_javascript_apple_events', title, target_url: targetUrl })
    return
  }

  const payload = validatePayload(await readStdinJson())
  if (args.has('--dry-run')) {
    const mode = await resolveWriterMode()
    ok({
      dry_run: true,
      mode,
      title: payload.title,
      reference: referenceForTitle(payload.title),
      web_url: DEFAULT_DASHLANE_URL,
    })
    return
  }

  const mode = await resolveWriterMode()
  const { webUrl, reference } =
    mode === 'applescript' || mode === 'accessibility'
      ? await createSecretWithAppleScript(payload)
      : await createSecret(payload)
  ok({
    mode,
    title: payload.title,
    reference: reference || referenceForTitle(payload.title),
    web_url: webUrl && webUrl.startsWith('https://') ? webUrl : DEFAULT_DASHLANE_URL,
  })
}

main().catch((error) => {
  fail('dashlane_writer_unhandled_error', { error: String(error?.message || error).slice(0, 240) })
})
