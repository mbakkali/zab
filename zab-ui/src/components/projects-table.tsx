import { Fragment, useMemo, useState } from 'react'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronRight } from 'lucide-react'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import { ProjectActions, type OverviewProject } from '@/components/project-actions'

export type { OverviewProject }

const columnHelper = createColumnHelper<OverviewProject>()

function SortIcon({ dir }: { dir: false | 'asc' | 'desc' }) {
  if (dir === 'asc') return <ArrowUp className="ml-1 inline size-3.5 opacity-60" />
  if (dir === 'desc') return <ArrowDown className="ml-1 inline size-3.5 opacity-60" />
  return <ArrowUpDown className="ml-1 inline size-3.5 opacity-40" />
}

export function ProjectsTable({
  projects,
  shortenHome,
  onOpenSkill,
  miningProjectPath,
  onMineMemory,
  onRunSecurityScan,
}: {
  projects: OverviewProject[]
  shortenHome: (path: string) => string
  onOpenSkill: (path: string) => void
  miningProjectPath?: string | null
  onMineMemory?: (path: string, name: string) => void | Promise<void>
  onRunSecurityScan?: (preset: string, path: string) => void
}) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'name', desc: false }])

  const columns = useMemo(
    () => [
      columnHelper.display({
        id: 'expand',
        header: () => null,
        cell: ({ row }) => {
          const hasSkills = row.original.skills.length > 0
          if (!hasSkills) return null
          return (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground rounded p-0.5"
              aria-label={row.getIsExpanded() ? 'Replier les skills' : 'Déplier les skills'}
              onClick={row.getToggleExpandedHandler()}
            >
              {row.getIsExpanded() ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            </button>
          )
        },
        size: 32,
      }),
      columnHelper.accessor('name', {
        header: 'Projet',
        cell: ({ getValue, row }) => (
          <div className="min-w-[8rem]">
            <p className="font-medium">{getValue()}</p>
            {row.original.workspace_parent ? (
              <p className="text-muted-foreground truncate text-[10px]">{row.original.workspace_parent}</p>
            ) : null}
          </div>
        ),
      }),
      columnHelper.accessor('org', {
        header: 'Org',
        cell: ({ getValue }) => (
          <span className="bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 inline-flex rounded-full px-2 py-0.5 text-[11px] font-medium">
            {getValue()}
          </span>
        ),
      }),
      columnHelper.accessor(
        (row) => (row.git_repo ? row.git_branch || 'git' : '—'),
        {
          id: 'git',
          header: 'Git',
          cell: ({ row }) => {
            const p = row.original
            if (!p.git_repo) {
              return <span className="text-muted-foreground text-xs">sans git</span>
            }
            return (
              <div className="flex flex-col gap-0.5">
                <span
                  className={cn(
                    'inline-flex w-fit rounded-full px-2 py-0.5 text-[11px] font-medium',
                    'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100',
                  )}
                  title={p.origin_https || undefined}
                >
                  {p.git_branch || 'git'}
                </span>
                {p.remote_host ? (
                  <span className="text-muted-foreground text-[10px] capitalize">{p.remote_host}</span>
                ) : null}
              </div>
            )
          },
        },
      ),
      columnHelper.accessor((row) => row.skills.length, {
        id: 'skills',
        header: 'Skills',
        cell: ({ getValue, row }) => (
          <button
            type="button"
            className="text-primary text-xs hover:underline disabled:no-underline"
            disabled={getValue() === 0}
            onClick={row.getToggleExpandedHandler()}
          >
            {getValue()} skill{getValue() !== 1 ? 's' : ''}
          </button>
        ),
      }),
      columnHelper.accessor('path', {
        header: 'Chemin',
        cell: ({ getValue }) => (
          <span className="text-muted-foreground block max-w-[14rem] truncate font-mono text-[10px]" title={getValue()}>
            {shortenHome(getValue())}
          </span>
        ),
      }),
      columnHelper.display({
        id: 'actions',
        header: 'Actions',
        cell: ({ row }) => (
          <ProjectActions
            p={row.original}
            compact
            miningProjectPath={miningProjectPath}
            onMineMemory={onMineMemory}
            onRunSecurityScan={onRunSecurityScan}
          />
        ),
      }),
    ],
    [shortenHome, miningProjectPath, onMineMemory, onRunSecurityScan],
  )

  const table = useReactTable({
    data: projects,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
    getRowCanExpand: (row) => row.original.skills.length > 0,
  })

  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-800">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id}>
              {hg.headers.map((header) => {
                const canSort = header.column.getCanSort()
                return (
                  <TableHead key={header.id} className={header.id === 'actions' ? 'min-w-[18rem]' : undefined}>
                    {header.isPlaceholder ? null : canSort ? (
                      <button
                        type="button"
                        className="hover:text-foreground inline-flex items-center text-left font-medium"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        <SortIcon dir={header.column.getIsSorted()} />
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </TableHead>
                )
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="text-muted-foreground h-24 text-center">
                Aucun projet.
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <Fragment key={row.id}>
                <TableRow data-state={row.getIsExpanded() ? 'expanded' : undefined}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell
                      key={cell.id}
                      className={cn(
                        cell.column.id === 'path' && 'whitespace-normal',
                        cell.column.id === 'actions' && 'whitespace-normal',
                      )}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
                {row.getIsExpanded() ? (
                  <TableRow className="bg-zinc-50/80 hover:bg-zinc-50/80 dark:bg-zinc-950/40">
                    <TableCell colSpan={columns.length} className="py-3 whitespace-normal">
                      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                        {row.original.skills.map((s) => (
                          <li
                            key={s.path}
                            className="rounded-md border border-zinc-200 bg-background px-2.5 py-2 dark:border-zinc-800"
                          >
                            <button
                              type="button"
                              onClick={() => onOpenSkill(s.path)}
                              className="text-primary hover:underline"
                            >
                              <code className="font-mono text-[11px]">{s.id}</code>
                            </button>
                            <button
                              type="button"
                              className="text-muted-foreground mt-0.5 block truncate text-left text-[10px] hover:text-foreground"
                              onClick={() => {
                                window.location.href = `vscode://file${s.path}`
                              }}
                              title={s.path}
                            >
                              {s.rel_from_home ? shortenHome(s.rel_from_home) : shortenHome(s.path)}
                            </button>
                          </li>
                        ))}
                      </ul>
                    </TableCell>
                  </TableRow>
                ) : null}
              </Fragment>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  )
}
