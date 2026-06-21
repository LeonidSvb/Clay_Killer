import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Project, Domain, Container, Database, Alert, CleanupItem } from './types'
import { projects, domains, services, alerts, cleanupItems } from './data'
import { useAppData } from './AppContext'

type View = 'projects' | 'domains' | 'databases' | 'containers' | 'services' | 'cleanup'
type Detail = { kind: 'project' | 'domain' | 'database' | 'container'; id: string } | null

const statusColor = {
  healthy:  'text-emerald-400',
  warning:  'text-amber-400',
  inactive: 'text-slate-500',
  orphaned: 'text-red-400',
} as const

const statusDot = {
  healthy:  'bg-emerald-400',
  warning:  'bg-amber-400',
  inactive: 'bg-slate-600',
  orphaned: 'bg-red-400',
} as const

const freshnessColor = {
  fresh:   'text-emerald-400',
  stale:   'text-amber-400',
  dead:    'text-red-400',
  unknown: 'text-slate-500',
} as const

// ─── Primitives ───────────────────────────────────────────────────────────────
function Badge({ status, label, className }: { status: keyof typeof statusColor; label?: string; className?: string }) {
  const bg = { healthy: 'bg-emerald-950 border-emerald-800', warning: 'bg-amber-950 border-amber-800', inactive: 'bg-slate-800 border-slate-700', orphaned: 'bg-red-950 border-red-800' }
  return (
    <span className={`text-xs px-1.5 py-0.5 rounded border ${bg[status]} ${statusColor[status]} ${className ?? ''}`}>
      {label ?? status}
    </span>
  )
}

function KV({ label, value, onClick, valueClass }: { label: string; value: string; onClick?: () => void; valueClass?: string }) {
  return (
    <div className="flex justify-between items-start py-1.5 border-b border-slate-200 dark:border-slate-800 last:border-0">
      <span className="text-slate-400 dark:text-slate-500 text-xs">{label}</span>
      {onClick
        ? <button onClick={onClick} className={`text-xs font-mono text-blue-500 dark:text-blue-400 hover:underline ${valueClass ?? ''}`}>{value}</button>
        : <span className={`text-xs font-mono text-slate-700 dark:text-slate-300 text-right max-w-[60%] break-all ${valueClass ?? ''}`}>{value}</span>
      }
    </div>
  )
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-4">
      <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">{title}</div>
      {children}
    </div>
  )
}

// ─── Detail panels ────────────────────────────────────────────────────────────
function ProjectDetail({ project, nav }: { project: Project; nav: (d: Detail) => void }) {
  const { containers, databases } = useAppData()
  const pDomains    = domains.filter(d => project.domainIds.includes(d.id))
  const pContainers = containers.filter(c => project.containerIds.includes(c.id))
  const pDbs        = databases.filter(d => project.dbIds.includes(d.id))
  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 flex items-center gap-4">
        <div>
          <div className="text-xl font-bold text-slate-900 dark:text-white">{project.name}</div>
          <div className="text-sm text-slate-400 mt-0.5">
            {project.type} · {project.deployType}
            {project.github && <> · <span className="font-mono">{project.github}</span></>}
            {project.path   && <> · <span className="font-mono">{project.path}</span></>}
          </div>
        </div>
        <div className="ml-auto">
          <Badge status={project.status} label={project.statusNote ?? project.status} />
        </div>
      </div>
      {project.note && (
        <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg px-4 py-3 text-sm text-red-600 dark:text-red-300">{project.note}</div>
      )}
      <div className="grid grid-cols-3 gap-3">
        <Block title="Domains">
          {pDomains.length === 0
            ? <p className="text-slate-400 dark:text-slate-600 text-xs">No public domain</p>
            : pDomains.map(d => (
              <div key={d.id}>
                <KV label="URL"      value={d.url}               onClick={() => nav({ kind: 'domain', id: d.id })} />
                <KV label="SSL"      value={d.ssl}               valueClass="text-emerald-400" />
                <KV label="Target"   value={d.target} />
                <KV label="Traefik"  value={d.traefikConfig ?? '—'} />
                {d.cloudflare && <KV label="Cloudflare" value="proxied" />}
                {d.basicAuth  && <KV label="Auth"       value="basic auth" valueClass="text-amber-400" />}
              </div>
            ))
          }
        </Block>
        <Block title="Containers">
          {pContainers.length === 0
            ? <p className="text-slate-400 dark:text-slate-600 text-xs">Runs on host (no container)</p>
            : pContainers.map(c => (
              <div key={c.id} className="mb-3 last:mb-0">
                <button onClick={() => nav({ kind: 'container', id: c.id })} className="text-xs font-mono text-blue-400 hover:underline font-semibold mb-1 block">{c.name}</button>
                {c.ram    && <KV label="RAM"    value={c.ram} />}
                {c.cpu    && <KV label="CPU"    value={c.cpu} />}
                {c.uptime && <KV label="Uptime" value={c.uptime} />}
              </div>
            ))
          }
        </Block>
        <Block title="Databases">
          {pDbs.length === 0
            ? <p className="text-slate-400 dark:text-slate-600 text-xs">No local database</p>
            : pDbs.map(d => (
              <div key={d.id} className="mb-3 last:mb-0">
                <button onClick={() => nav({ kind: 'database', id: d.id })} className="text-xs font-mono text-blue-400 hover:underline font-semibold mb-1 block">{d.name}</button>
                <KV label="Host"   value={d.host} />
                {d.schema && <KV label="Schema" value={d.schema} />}
                <KV label="Tables" value={`${d.tables.length}`} />
              </div>
            ))
          }
        </Block>
      </div>
      {pDbs.map(db => db.tables.length > 0 && (
        <div key={db.id} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-4">
          <div className="flex justify-between mb-3">
            <button onClick={() => nav({ kind: 'database', id: db.id })} className="text-xs uppercase tracking-widest text-blue-400 hover:underline">{db.name} — tables</button>
            <span className="text-xs text-slate-600">{db.tables.length} total</span>
          </div>
          <div className="divide-y divide-slate-200 dark:divide-slate-800">
            {db.tables.map(t => (
              <div key={t.name} className="flex items-center gap-3 py-2 text-xs">
                <span className="font-mono text-slate-700 dark:text-slate-300 flex-1">{t.name}</span>
                {t.rows      && <span className="text-slate-500 w-16 text-right">{t.rows}</span>}
                {t.lastWrite && <span className={`w-20 text-right ${freshnessColor[t.freshness]}`}>{t.lastWrite}</span>}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function DomainDetail({ domain, nav }: { domain: Domain; nav: (d: Detail) => void }) {
  const project = domain.projectId ? projects.find(p => p.id === domain.projectId) : null
  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5">
        <div className="text-xl font-bold text-slate-900 dark:text-white font-mono">{domain.url}</div>
        <div className="text-sm text-slate-500 mt-1">→ {domain.target}</div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Block title="Routing">
          <KV label="Target"     value={domain.target} />
          <KV label="Traefik"    value={domain.traefikConfig ?? '—'} />
          <KV label="SSL"        value={domain.ssl}    valueClass="text-emerald-400" />
          <KV label="Cloudflare" value={domain.cloudflare ? 'proxied' : 'DNS only'} />
          {domain.basicAuth && <KV label="Auth" value="basic auth enabled" valueClass="text-amber-400" />}
        </Block>
        <Block title="Project">
          {project
            ? <KV label="Project" value={project.name} onClick={() => nav({ kind: 'project', id: project.id })} />
            : <p className="text-slate-400 dark:text-slate-600 text-xs">No project linked</p>
          }
        </Block>
      </div>
    </div>
  )
}

function DatabaseDetail({ db, nav }: { db: Database; nav: (d: Detail) => void }) {
  const usedByProjects = projects.filter(p => db.usedBy.includes(p.id))
  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 flex items-center gap-4">
        <div>
          <div className="text-xl font-bold text-slate-900 dark:text-white">{db.name}</div>
          <div className="text-sm text-slate-400 font-mono mt-1">{db.host}{db.schema ? ` · schema: ${db.schema}` : ''}</div>
        </div>
        <Badge status={db.status} className="ml-auto" />
      </div>
      {db.status === 'orphaned' && (
        <div className="bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg px-4 py-3 text-sm text-red-600 dark:text-red-300">No active project uses this database. Safe to drop.</div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Block title="Info">
          <KV label="Instance" value={db.instance} />
          {db.schema && <KV label="Schema" value={db.schema} />}
          <KV label="Host"   value={db.host} />
          <KV label="Tables" value={`${db.tables.length}`} />
        </Block>
        <Block title="Used by projects">
          {usedByProjects.length === 0
            ? <p className="text-red-400 text-xs">Nobody writes to this database</p>
            : usedByProjects.map(p => (
              <KV key={p.id} label={p.type} value={p.name} onClick={() => nav({ kind: 'project', id: p.id })} />
            ))
          }
        </Block>
      </div>
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-4">
        <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Tables</div>
        <div className="divide-y divide-slate-200 dark:divide-slate-800">
          {db.tables.map(t => (
            <div key={t.name} className="flex items-center gap-3 py-2 text-xs">
              <span className={`font-mono flex-1 ${t.freshness === 'dead' ? 'text-red-400' : 'text-slate-700 dark:text-slate-300'}`}>{t.name}</span>
              {t.rows      && <span className="text-slate-500 w-16 text-right">{t.rows}</span>}
              {t.lastWrite && <span className={`w-24 text-right ${freshnessColor[t.freshness]}`}>{t.lastWrite}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function ContainerDetail({ container, nav }: { container: Container; nav: (d: Detail) => void }) {
  const project = container.projectId ? projects.find(p => p.id === container.projectId) : null
  return (
    <div className="space-y-4">
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 flex items-center gap-4">
        <div>
          <div className="text-xl font-bold text-slate-900 dark:text-white font-mono">{container.name}</div>
          {container.note && <div className="text-sm text-slate-400 mt-1">{container.note}</div>}
        </div>
        <Badge status={container.status} className="ml-auto" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Block title="Runtime">
          {container.ram    && <KV label="RAM"    value={container.ram} />}
          {container.cpu    && <KV label="CPU"    value={container.cpu} />}
          {container.uptime && <KV label="Uptime" value={container.uptime} />}
          <KV label="Status" value={container.status} valueClass={container.status === 'healthy' ? 'text-emerald-400' : 'text-amber-400'} />
        </Block>
        <Block title="Project">
          {project
            ? <KV label="Project" value={project.name} onClick={() => nav({ kind: 'project', id: project.id })} />
            : <p className="text-slate-400 dark:text-slate-600 text-xs">Infrastructure container</p>
          }
        </Block>
      </div>
    </div>
  )
}

// ─── Alerts banner ────────────────────────────────────────────────────────────
function AlertsBanner({ nav, navItem }: { nav: (d: Detail) => void; navItem: (v: View) => void }) {
  if (!alerts.length) return null
  const levelDot: Record<Alert['level'], string> = {
    error:   'bg-red-400',
    warning: 'bg-amber-400',
    info:    'bg-blue-400',
  }
  const viewKindMap: Record<string, 'project' | 'domain' | 'database' | 'container'> = {
    projects: 'project', domains: 'domain', databases: 'database', containers: 'container',
  }
  const handleGo = (a: Alert) => {
    if (a.targetView === 'services' || a.targetView === 'cleanup') {
      navItem(a.targetView as View)
    } else if (a.targetId && viewKindMap[a.targetView]) {
      nav({ kind: viewKindMap[a.targetView], id: a.targetId })
    } else {
      navItem(a.targetView as View)
    }
  }
  return (
    <div className="mb-5 rounded-lg border border-slate-300 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 p-3 space-y-2">
      <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Alerts</div>
      {alerts.map(a => (
        <div key={a.id} className="flex items-center gap-2 text-xs">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${levelDot[a.level]}`} />
          <span className="text-slate-700 dark:text-slate-300 flex-1">{a.message}</span>
          <button onClick={() => handleGo(a)} className="text-blue-500 dark:text-blue-400 hover:underline flex-shrink-0">view →</button>
        </div>
      ))}
    </div>
  )
}

// ─── List pages ───────────────────────────────────────────────────────────────
function ProjectsPage({ nav }: { nav: (d: Detail) => void }) {
  const { databases } = useAppData()
  return (
    <div className="grid grid-cols-3 gap-3">
      {projects.map(p => (
        <div
          key={p.id}
          onClick={() => nav({ kind: 'project', id: p.id })}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-4 cursor-pointer hover:border-slate-400 dark:hover:border-slate-600 hover:shadow-lg transition-all"
        >
          <div className="flex justify-between items-start mb-3">
            <div>
              <div className="font-semibold text-slate-900 dark:text-white text-sm">{p.name}</div>
              <div className="text-xs text-slate-500 mt-0.5">{p.type} · {p.deployType}</div>
            </div>
            <Badge status={p.status} label={p.statusNote ?? p.status} />
          </div>
          <div className="space-y-1">
            {p.domainIds.length > 0 && (
              <div className="flex gap-2 text-xs"><span className="text-slate-500 w-16">Domain</span><span className="font-mono text-blue-500 dark:text-blue-400 truncate">{domains.find(d => d.id === p.domainIds[0])?.url}</span></div>
            )}
            <div className="flex gap-2 text-xs"><span className="text-slate-500 w-16">Database</span><span className="font-mono text-slate-500 dark:text-slate-400">{p.dbIds.map(id => databases.find(d => d.id === id)?.name).join(', ') || '—'}</span></div>
            {p.github && <div className="flex gap-2 text-xs"><span className="text-slate-500 w-16">GitHub</span><span className="font-mono text-slate-500">{p.github}</span></div>}
          </div>
        </div>
      ))}
    </div>
  )
}

function DomainsPage({ nav }: { nav: (d: Detail) => void }) {
  return (
    <div className="space-y-2">
      {domains.map(d => {
        const project = d.projectId ? projects.find(p => p.id === d.projectId) : null
        return (
          <div
            key={d.id}
            onClick={() => nav({ kind: 'domain', id: d.id })}
            className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-4 py-3 flex items-center gap-4 cursor-pointer hover:border-slate-400 dark:hover:border-slate-600 transition-all"
          >
            <span className="font-mono text-blue-500 dark:text-blue-400 text-sm w-72">{d.url}</span>
            <span className="text-slate-500 text-xs">→ {d.target}</span>
            <div className="ml-auto flex gap-2 items-center">
              {d.basicAuth  && <span className="text-xs px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 border border-amber-800">auth</span>}
              <span className="text-xs px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">SSL ok</span>
              {d.cloudflare && <span className="text-xs px-1.5 py-0.5 rounded bg-blue-950 text-blue-400 border border-blue-800">CF</span>}
              {project && (
                <button onClick={e => { e.stopPropagation(); nav({ kind: 'project', id: project.id }) }} className="text-xs text-slate-400 hover:text-slate-700 dark:hover:text-white ml-1">
                  {project.name} →
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function DatabasesPage({ nav }: { nav: (d: Detail) => void }) {
  const { databases } = useAppData()
  return (
    <div className="grid grid-cols-2 gap-3">
      {databases.map(db => (
        <div
          key={db.id}
          onClick={() => nav({ kind: 'database', id: db.id })}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg p-4 cursor-pointer hover:border-slate-400 dark:hover:border-slate-600 transition-all"
        >
          <div className="flex justify-between items-start mb-3">
            <div>
              <div className="font-semibold text-slate-900 dark:text-white text-sm">{db.name}</div>
              <div className="font-mono text-xs text-slate-500 mt-0.5">{db.host}</div>
            </div>
            <Badge status={db.status} />
          </div>
          <div className="divide-y divide-slate-200 dark:divide-slate-800">
            {db.tables.slice(0, 4).map(t => (
              <div key={t.name} className="flex justify-between py-1.5 text-xs">
                <span className={`font-mono ${t.freshness === 'dead' ? 'text-red-400' : 'text-slate-700 dark:text-slate-300'}`}>{t.name}</span>
                <span className={freshnessColor[t.freshness]}>{t.lastWrite ?? ''}</span>
              </div>
            ))}
            {db.tables.length > 4 && <div className="py-1.5 text-xs text-slate-500">+ {db.tables.length - 4} more</div>}
          </div>
          {db.usedBy.length > 0 && (
            <div className="mt-3 text-xs text-slate-500">
              Used by: {db.usedBy.map(id => projects.find(p => p.id === id)?.name).join(', ')}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function ContainersPage({ nav }: { nav: (d: Detail) => void }) {
  const { containers } = useAppData()
  return (
    <div className="space-y-2">
      {containers.map(c => {
        const project = c.projectId ? projects.find(p => p.id === c.projectId) : null
        return (
          <div
            key={c.id}
            onClick={() => nav({ kind: 'container', id: c.id })}
            className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-4 py-3 flex items-center gap-4 cursor-pointer hover:border-slate-400 dark:hover:border-slate-600 transition-all"
          >
            <div className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot[c.status]}`} />
            <span className="font-mono text-slate-800 dark:text-slate-200 text-sm w-56">{c.name}</span>
            <span className="text-slate-500 text-xs flex-1">{c.note ?? (c.ram ? `${c.ram} · ${c.cpu}` : '')}</span>
            <div className="flex gap-3 items-center">
              {c.uptime && <span className="text-xs text-slate-500">up {c.uptime}</span>}
              {project && (
                <button onClick={e => { e.stopPropagation(); nav({ kind: 'project', id: project.id }) }} className="text-xs text-slate-400 hover:text-slate-700 dark:hover:text-white">
                  {project.name} →
                </button>
              )}
              <Badge status={c.status} />
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Services page ────────────────────────────────────────────────────────────
function ServicesPage() {
  const [openGroup,  setOpenGroup]  = useState<string | null>(null)
  const [openScript, setOpenScript] = useState<string | null>(null)
  const [openRun,    setOpenRun]    = useState<string | null>(null)

  const runDot: Record<string, string> = { ok: 'bg-emerald-400', error: 'bg-red-400', running: 'bg-blue-400' }
  const runText: Record<string, string> = { ok: 'text-emerald-400', error: 'text-red-400', running: 'text-blue-400' }

  return (
    <div className="space-y-2">
      {services.map(svc => (
        <div key={svc.id} className="rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden">
          {/* Service group strip */}
          <div
            onClick={() => {
              const opening = openGroup !== svc.id
              setOpenGroup(opening ? svc.id : null)
              setOpenScript(null)
              setOpenRun(null)
            }}
            className="flex items-center gap-3 px-4 py-3 bg-white dark:bg-slate-900 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors select-none"
          >
            <div className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDot[svc.status]}`} />
            <span className="font-semibold text-slate-900 dark:text-slate-100 text-sm w-36">{svc.name}</span>
            <span className="text-xs text-slate-400">{svc.scripts.length} scripts</span>
            {svc.github && <span className="text-xs font-mono text-slate-500 hidden lg:block">{svc.github}</span>}
            <span className="text-xs font-mono text-slate-500 hidden xl:block">{svc.path}</span>
            <div className="ml-auto flex items-center gap-3">
              {svc.statusNote && <span className={`text-xs ${statusColor[svc.status]}`}>{svc.statusNote}</span>}
              <Badge status={svc.status} />
              <span className={`text-slate-400 transition-transform duration-150 ${openGroup === svc.id ? 'rotate-90' : ''}`}>›</span>
            </div>
          </div>

          {/* Script strips */}
          {openGroup === svc.id && (
            <div className="border-t border-slate-200 dark:border-slate-700">
              {svc.scripts.map(scr => (
                <div key={scr.id}>
                  <div
                    onClick={() => {
                      const opening = openScript !== scr.id
                      setOpenScript(opening ? scr.id : null)
                      if (!opening) setOpenRun(null)
                    }}
                    className={`flex items-center gap-3 pl-8 pr-4 py-2.5 cursor-pointer border-t border-slate-100 dark:border-slate-800 first:border-t-0 transition-colors select-none ${
                      openScript === scr.id
                        ? 'bg-slate-50 dark:bg-slate-800'
                        : 'bg-white dark:bg-slate-900/70 hover:bg-slate-50 dark:hover:bg-slate-800/50'
                    }`}
                  >
                    <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      scr.lastRunStatus === 'ok' ? 'bg-emerald-400'
                      : scr.lastRunStatus === 'error' ? 'bg-red-400'
                      : 'bg-slate-500'
                    }`} />
                    <span className="font-mono text-sm text-slate-700 dark:text-slate-200 w-36">{scr.name}</span>
                    <span className="text-xs text-slate-400 w-44">{scr.schedule}</span>
                    <span className="text-xs text-slate-500">{scr.records.toLocaleString()} rec</span>
                    {scr.rate && <span className="text-xs text-slate-500">@ {scr.rate}</span>}
                    <div className="ml-auto flex items-center gap-3 text-xs text-slate-400">
                      <span>{scr.duration}</span>
                      <span>{scr.lastRun}</span>
                      <span className={`transition-transform duration-150 ${openScript === scr.id ? 'rotate-90' : ''}`}>›</span>
                    </div>
                  </div>

                  {/* Script detail */}
                  {openScript === scr.id && (
                    <div className="border-t border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40 pl-8 pr-4 py-4">
                      {/* 2-line compact info */}
                      <div className="text-xs text-slate-500 mb-4 space-y-0.5">
                        <div>
                          <span className="text-slate-400">file</span>{' '}
                          <span className="font-mono text-slate-700 dark:text-slate-300">{scr.file}</span>
                          {scr.source && <> · <span className="text-slate-400">source</span>{' '}<span className="text-slate-700 dark:text-slate-300">{scr.source}</span></>}
                          {scr.writesTo && scr.writesTo.length > 0 && <> · <span className="text-slate-400">writes</span>{' '}<span className="text-slate-700 dark:text-slate-300">{scr.writesTo.join(', ')}</span></>}
                        </div>
                        <div>
                          <span className="text-slate-400">last run</span>{' '}
                          <span className={scr.lastRunStatus === 'ok' ? 'text-emerald-400' : 'text-red-400'}>{scr.lastRun} ({scr.lastRunStatus})</span>
                          {' · '}<span className="text-slate-400">dur</span>{' '}<span className="text-slate-700 dark:text-slate-300">{scr.duration}</span>
                          {' · '}<span className="text-slate-400">records</span>{' '}<span className="text-slate-700 dark:text-slate-300">{scr.records.toLocaleString()}</span>
                          {scr.rate && <> · <span className="text-slate-400">rate</span>{' '}<span className="text-slate-700 dark:text-slate-300">{scr.rate}</span></>}
                        </div>
                      </div>

                      {/* Runs table */}
                      <div className="text-xs uppercase tracking-wider text-slate-500 mb-2">Runs</div>
                      <div className="rounded border border-slate-200 dark:border-slate-700 overflow-hidden">
                        {scr.runs.map(run => (
                          <div key={run.id}>
                            <div
                              onClick={() => setOpenRun(openRun === run.id ? null : run.id)}
                              className={`flex items-center gap-3 px-4 py-2 cursor-pointer text-xs border-b border-slate-200 dark:border-slate-700 last:border-0 transition-colors select-none ${
                                openRun === run.id
                                  ? 'bg-slate-100 dark:bg-slate-700'
                                  : 'bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800'
                              }`}
                            >
                              <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${runDot[run.status] ?? 'bg-slate-500'}`} />
                              <span className="font-mono text-slate-500 w-20">{run.id}</span>
                              <span className="text-slate-600 dark:text-slate-400 w-36">{run.started}</span>
                              <span className="text-slate-600 dark:text-slate-400 w-14">{run.duration}</span>
                              <span className="text-slate-600 dark:text-slate-400 flex-1">{run.records.toLocaleString()} records</span>
                              {run.errors > 0 && <span className="text-red-400 w-12 text-right">{run.errors} err</span>}
                              <span className={`w-10 text-right ${runText[run.status] ?? 'text-slate-500'}`}>{run.status}</span>
                            </div>
                            {/* Run detail */}
                            {openRun === run.id && (
                              <div className="bg-slate-50 dark:bg-slate-800 border-b border-slate-200 dark:border-slate-700 last:border-0 px-4 py-3 text-xs">
                                <div className="flex flex-wrap gap-5 text-slate-600 dark:text-slate-400 mb-3">
                                  <span><span className="text-slate-400">run</span> <span className="font-mono">{run.id}</span></span>
                                  <span><span className="text-slate-400">started</span> {run.started}</span>
                                  <span><span className="text-slate-400">duration</span> {run.duration}</span>
                                  <span><span className="text-slate-400">records</span> {run.records.toLocaleString()}</span>
                                  {run.errors > 0 && <span className="text-red-400">{run.errors} errors</span>}
                                </div>
                                <div className="rounded border border-slate-200 dark:border-slate-700 overflow-hidden">
                                  <div className="px-3 py-1.5 border-b border-slate-200 dark:border-slate-700 text-slate-400 font-mono text-xs bg-slate-100 dark:bg-slate-800">
                                    sample — first {Math.min(10, run.records)} of {run.records.toLocaleString()} records
                                  </div>
                                  <div className="max-h-36 overflow-auto bg-white dark:bg-slate-900">
                                    {Array.from({ length: Math.min(10, run.records) }, (_, i) => (
                                      <div key={i} className="px-3 py-1 font-mono text-xs text-slate-600 dark:text-slate-400 flex gap-4 border-b border-slate-100 dark:border-slate-800 last:border-0">
                                        <span className="text-slate-400 w-5 text-right">{i + 1}</span>
                                        <span className="text-blue-500 dark:text-blue-400">row_{String(i + 1).padStart(4, '0')}</span>
                                        <span className={run.errors > 0 && i >= run.records - run.errors ? 'text-red-400' : 'text-emerald-600 dark:text-emerald-400'}>
                                          {run.errors > 0 && i >= run.records - run.errors ? 'ERR: duplicate key' : 'upserted'}
                                        </span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ─── Cleanup page ─────────────────────────────────────────────────────────────
function CleanupPage({ nav, navItem }: { nav: (d: Detail) => void; navItem: (v: View) => void }) {
  const groups: { label: string; type: CleanupItem['type'] }[] = [
    { label: 'Projects',     type: 'project'  },
    { label: 'Databases',    type: 'database' },
    { label: 'Dead Tables',  type: 'table'    },
  ]
  const sevColor: Record<CleanupItem['severity'], string> = {
    high:   'text-red-400 border-red-800 bg-red-950',
    medium: 'text-amber-400 border-amber-800 bg-amber-950',
    low:    'text-slate-400 border-slate-700 bg-slate-800',
  }
  const handleView = (item: CleanupItem) => {
    if (!item.targetView) return
    if (item.targetId) {
      const kindMap: Record<string, 'project' | 'domain' | 'database' | 'container'> = {
        projects: 'project', domains: 'domain', databases: 'database', containers: 'container',
      }
      const kind = kindMap[item.targetView]
      if (kind) { nav({ kind, id: item.targetId }); return }
    }
    navItem(item.targetView as View)
  }

  return (
    <div className="space-y-6">
      {groups.map(group => {
        const items = cleanupItems.filter(i => i.type === group.type)
        if (!items.length) return null
        return (
          <div key={group.type}>
            <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">{group.label}</div>
            <div className="space-y-2">
              {items.map(item => (
                <div key={item.id} className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg px-4 py-3">
                  <div className="flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-mono text-sm font-semibold text-slate-800 dark:text-slate-200">{item.name}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded border ${sevColor[item.severity]}`}>{item.severity}</span>
                      </div>
                      <div className="text-xs text-slate-500 mb-1">{item.meta}</div>
                      <div className="text-xs text-slate-600 dark:text-slate-400">{item.reason}</div>
                    </div>
                    {item.targetView && (
                      <button
                        onClick={() => handleView(item)}
                        className="text-xs text-blue-500 dark:text-blue-400 hover:underline flex-shrink-0 mt-0.5"
                      >
                        view →
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Root App ─────────────────────────────────────────────────────────────────
export default function App() {
  const { containers, databases, serverStats, liveReady } = useAppData()
  const [dark, setDark]     = useState(true)
  const [view, setView]     = useState<View>('projects')
  const [detail, setDetail] = useState<Detail>(null)

  const nav = (d: Detail) => {
    setDetail(d)
    if (d) {
      if (d.kind === 'project')        setView('projects')
      else if (d.kind === 'domain')    setView('domains')
      else if (d.kind === 'database')  setView('databases')
      else                             setView('containers')
    }
  }

  const navItem = (v: View) => { setView(v); setDetail(null) }

  const title = detail
    ? detail.kind === 'project'   ? projects.find(p => p.id === detail.id)?.name
    : detail.kind === 'domain'    ? domains.find(d => d.id === detail.id)?.url
    : detail.kind === 'database'  ? databases.find(d => d.id === detail.id)?.name
    : containers.find(c => c.id === detail.id)?.name
    : view === 'cleanup' ? 'Cleanup'
    : view === 'services' ? 'Services'
    : view.charAt(0).toUpperCase() + view.slice(1)

  const navViews: View[] = ['projects', 'domains', 'databases', 'containers', 'services']
  const navDot: Record<View, string> = {
    projects:   'bg-emerald-400',
    domains:    'bg-emerald-400',
    databases:  'bg-emerald-400',
    containers: containers.some(c => c.status === 'warning') ? 'bg-amber-400' : 'bg-emerald-400',
    services:   services.some(s => s.status === 'warning')   ? 'bg-amber-400' : 'bg-emerald-400',
    cleanup:    'bg-red-400',
  }

  const sidebarItemClass = (active: boolean) =>
    `w-full text-left px-4 py-2 text-sm flex items-center gap-2 border-l-2 transition-colors ${
      active
        ? 'border-blue-500 bg-blue-50 dark:bg-slate-800 text-blue-700 dark:text-slate-100'
        : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'
    }`

  return (
    <div className={dark ? 'dark' : ''}>
      <div className="min-h-screen bg-slate-100 dark:bg-slate-950 text-slate-900 dark:text-slate-200">

        {/* Topbar */}
        <div className="sticky top-0 z-50 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-5 py-2.5 flex items-center gap-4">
          <div>
            <div className="font-bold text-sm text-slate-900 dark:text-slate-50 flex items-center gap-2">
              {serverStats.host}
              <span className={`w-1.5 h-1.5 rounded-full ${liveReady ? 'bg-emerald-400' : 'bg-slate-500'}`} title={liveReady ? 'live' : 'mock data'} />
            </div>
            <div className="text-xs font-mono text-slate-500">{serverStats.ip} · {serverStats.location}</div>
          </div>
          <div className="flex gap-5 ml-auto items-center text-xs text-slate-500">
            <span>CPU <strong className="text-slate-700 dark:text-slate-300">{serverStats.cpu}</strong></span>
            <span>RAM <strong className="text-slate-700 dark:text-slate-300">{serverStats.ram}</strong></span>
            <span>Disk <strong className="text-slate-700 dark:text-slate-300">{serverStats.disk}</strong></span>
            <span>Up <strong className="text-slate-700 dark:text-slate-300">{serverStats.uptime}</strong></span>
            {alerts.some(a => a.level === 'error') && (
              <button onClick={() => navItem('cleanup')} className="text-red-400 font-semibold">
                {alerts.filter(a => a.level === 'error').length} error{alerts.filter(a => a.level === 'error').length > 1 ? 's' : ''}
              </button>
            )}
            <button
              onClick={() => setDark(!dark)}
              className="ml-2 px-3 py-1 rounded border text-xs bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400"
            >
              {dark ? 'Light' : 'Dark'}
            </button>
          </div>
        </div>

        <div className="flex">
          {/* Sidebar */}
          <div className="w-48 shrink-0 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-950 min-h-[calc(100vh-49px)] py-3">
            {navViews.map(v => (
              <button key={v} onClick={() => navItem(v)} className={sidebarItemClass(view === v && !detail)}>
                <span className={`w-1.5 h-1.5 rounded-full ${navDot[v]}`} />
                {v.charAt(0).toUpperCase() + v.slice(1)}
              </button>
            ))}

            <div className="mt-3 mb-1 px-4 text-xs uppercase tracking-widest text-slate-400">Maintenance</div>
            <button onClick={() => navItem('cleanup')} className={sidebarItemClass(view === 'cleanup' && !detail)}>
              <span className={`w-1.5 h-1.5 rounded-full ${navDot['cleanup']}`} />
              Cleanup
              {cleanupItems.filter(i => i.severity === 'high').length > 0 && (
                <span className="ml-auto text-xs text-red-400">{cleanupItems.filter(i => i.severity === 'high').length}</span>
              )}
            </button>

            <div className="mt-4 mb-1 px-4 text-xs uppercase tracking-widest text-slate-400">Projects</div>
            {projects.map(p => (
              <button
                key={p.id}
                onClick={() => nav({ kind: 'project', id: p.id })}
                className={`w-full text-left px-4 py-1.5 text-xs flex items-center gap-2 border-l-2 transition-colors ${
                  detail?.kind === 'project' && detail.id === p.id
                    ? 'border-blue-500 bg-blue-50 dark:bg-slate-800 text-blue-700 dark:text-slate-100'
                    : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-300'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${statusDot[p.status]}`} />
                {p.name}
              </button>
            ))}
          </div>

          {/* Main content */}
          <div className="flex-1 p-6 overflow-auto">
            {/* Breadcrumb */}
            <div className="flex items-center gap-2 text-sm mb-5">
              {detail && (
                <>
                  <button onClick={() => navItem(view)} className="text-blue-500 dark:text-blue-400 hover:underline capitalize">{view}</button>
                  <span className="text-slate-500">/</span>
                </>
              )}
              <span className="font-semibold text-slate-900 dark:text-slate-100">{title}</span>
            </div>

            {/* Alerts banner — list views only */}
            {!detail && view !== 'cleanup' && <AlertsBanner nav={nav} navItem={navItem} />}

            {/* Overview stats — main 4 views only */}
            {!detail && ['projects', 'domains', 'databases', 'containers'].includes(view) && (
              <div className="grid grid-cols-5 gap-3 mb-6">
                {[
                  { label: 'Containers', value: String(containers.length), sub: `${containers.filter(c => c.status === 'warning').length} warning`, pct: Math.round(containers.filter(c => c.status === 'healthy').length / containers.length * 100), warn: containers.some(c => c.status === 'warning') },
                  { label: 'Domains',    value: String(domains.length),    sub: 'all active',   pct: 100, warn: false },
                  { label: 'Databases',  value: String(databases.length),  sub: `${new Set(databases.map(d => d.instance)).size} instances`, pct: 100, warn: databases.some(d => d.status !== 'healthy') },
                  { label: 'RAM',  value: `${serverStats.ramPct}%`,  sub: serverStats.ram,  pct: serverStats.ramPct,  warn: serverStats.ramPct > 75  },
                  { label: 'Disk', value: `${serverStats.diskPct}%`, sub: serverStats.disk, pct: serverStats.diskPct, warn: serverStats.diskPct > 80 },
                ].map(s => (
                  <div key={s.label} className="rounded-lg p-3 border bg-white dark:bg-slate-900 border-slate-200 dark:border-slate-800">
                    <div className="text-xs uppercase tracking-wider mb-1 text-slate-500">{s.label}</div>
                    <div className="text-xl font-bold text-slate-900 dark:text-slate-100">{s.value}</div>
                    <div className="text-xs mt-0.5 text-slate-500">{s.sub}</div>
                    <div className="h-0.5 rounded mt-2 bg-slate-200 dark:bg-slate-800">
                      <div className="h-full rounded" style={{ width: `${s.pct}%`, background: s.warn ? '#f59e0b' : '#3b82f6' }} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Detail panels */}
            {detail?.kind === 'project'   && <ProjectDetail   project={projects.find(p => p.id === detail.id)!}    nav={nav} />}
            {detail?.kind === 'domain'    && <DomainDetail    domain={domains.find(d => d.id === detail.id)!}       nav={nav} />}
            {detail?.kind === 'database'  && <DatabaseDetail  db={databases.find(d => d.id === detail.id)!}         nav={nav} />}
            {detail?.kind === 'container' && <ContainerDetail container={containers.find(c => c.id === detail.id)!} nav={nav} />}

            {/* List pages */}
            {!detail && view === 'projects'   && <ProjectsPage   nav={nav} />}
            {!detail && view === 'domains'    && <DomainsPage    nav={nav} />}
            {!detail && view === 'databases'  && <DatabasesPage  nav={nav} />}
            {!detail && view === 'containers' && <ContainersPage nav={nav} />}
            {!detail && view === 'services'   && <ServicesPage />}
            {!detail && view === 'cleanup'    && <CleanupPage nav={nav} navItem={navItem} />}
          </div>
        </div>
      </div>
    </div>
  )
}
