/** Ouvre un fichier absolu dans VS Code / Cursor (ligne optionnelle). */
export function vscodeFileHref(absPath: string, line?: number | null): string {
  const p = absPath.trim()
  if (!p) return ''
  const suffix = line != null && line > 0 ? `:${line}:1` : ''
  if (p.startsWith('/')) return `vscode://file${p}${suffix}`
  return `vscode://file/${p}${suffix}`
}
