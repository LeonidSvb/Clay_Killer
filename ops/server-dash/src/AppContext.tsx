import { createContext, useContext, useState, useEffect } from 'react'
import type { ReactNode } from 'react'
import type { Container, Database } from './types'
import { containers as mockContainers, databases as mockDatabases, serverStats as mockStats } from './data'

interface ServerStats {
  host: string
  ip: string
  location: string
  cpu: string
  ram: string
  ramPct: number
  disk: string
  diskPct: number
  uptime: string
}

interface AppData {
  containers: Container[]
  databases: Database[]
  serverStats: ServerStats
  liveReady: boolean
}

const defaultStats: ServerStats = {
  host: mockStats.host,
  ip: mockStats.ip,
  location: mockStats.location,
  cpu: mockStats.cpu,
  ram: mockStats.ram,
  ramPct: mockStats.ramPct,
  disk: mockStats.disk,
  diskPct: mockStats.diskPct,
  uptime: mockStats.uptime,
}

export const AppCtx = createContext<AppData>({
  containers: mockContainers,
  databases: mockDatabases,
  serverStats: defaultStats,
  liveReady: false,
})

export const useAppData = () => useContext(AppCtx)

const API = import.meta.env.VITE_API_URL ?? ''

async function apiFetch<T>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${API}${path}`)
    if (!r.ok) return null
    return r.json() as Promise<T>
  } catch {
    return null
  }
}

function mergeContainers(live: Container[], mock: Container[]): Container[] {
  const byName = Object.fromEntries(mock.map(c => [c.name, c]))
  return live.map(c => ({
    ...c,
    projectId: byName[c.name]?.projectId,
    note: byName[c.name]?.note,
  }))
}

function mergeDatabases(live: Database[], mock: Database[]): Database[] {
  const byId = Object.fromEntries(mock.map(d => [d.id, d]))
  return live.map(d => ({
    ...d,
    status: byId[d.id]?.status ?? d.status,
    usedBy: byId[d.id]?.usedBy ?? d.usedBy ?? [],
  }))
}

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [containers, setContainers] = useState<Container[]>(mockContainers)
  const [databases, setDatabases]   = useState<Database[]>(mockDatabases)
  const [stats, setStats]           = useState<ServerStats>(defaultStats)
  const [liveReady, setLiveReady]   = useState(false)

  useEffect(() => {
    let mounted = true

    async function refresh() {
      const [liveContainers, liveDatabases, liveStats] = await Promise.all([
        apiFetch<Container[]>('/api/containers'),
        apiFetch<Database[]>('/api/databases'),
        apiFetch<ServerStats>('/api/status'),
      ])
      if (!mounted) return
      if (liveContainers) setContainers(mergeContainers(liveContainers, mockContainers))
      if (liveDatabases)  setDatabases(mergeDatabases(liveDatabases, mockDatabases))
      if (liveStats)      setStats(liveStats)
      setLiveReady(true)
    }

    refresh()
    const t = setInterval(refresh, 30_000)
    return () => { mounted = false; clearInterval(t) }
  }, [])

  return (
    <AppCtx.Provider value={{ containers, databases, serverStats: stats, liveReady }}>
      {children}
    </AppCtx.Provider>
  )
}
