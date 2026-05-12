/** Raccourcit /Users/… → ~/ pour l’affichage. */
export function shortenHomeInPath(p: string): string {
  return p.replace(/^\/Users\/[^/]+/, '~')
}

/**
 * URL vscode://file pour ouvrir un SKILL.md.
 * - Chemin absolu : tel quel.
 * - Chemin relatif au dépôt skills : utilise ``skillsRepoRoot`` (par org) puis ``fallbackSkillsRoot``.
 */
export function vscodeFileHrefForSkill(
  skillPath: string,
  skillsRepoRoot: string | undefined | null,
  fallbackSkillsRoot: string | null | undefined,
): string | null {
  const p = skillPath.trim()
  if (!p) return null
  if (p.startsWith('/')) return `vscode://file${p}`
  const rootRaw = (skillsRepoRoot && skillsRepoRoot.length > 0 ? skillsRepoRoot : fallbackSkillsRoot) ?? ''
  const root = rootRaw.replace(/\/$/, '')
  if (!root) return null
  const rel = p.replace(/^\//, '')
  return `vscode://file${root}/${rel}`
}
