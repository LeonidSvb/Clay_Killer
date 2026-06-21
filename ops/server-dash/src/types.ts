export type Status = 'healthy' | 'warning' | 'inactive' | 'orphaned'

export interface DbTable {
  name: string
  rows?: string
  lastWrite?: string
  freshness: 'fresh' | 'stale' | 'dead' | 'unknown'
}

export interface Database {
  id: string
  name: string
  instance: string
  schema?: string
  host: string
  status: Status
  tables: DbTable[]
  usedBy: string[]  // project ids
}

export interface Domain {
  id: string
  url: string
  target: string
  traefikConfig?: string
  ssl: string
  cloudflare: boolean
  basicAuth: boolean
  projectId?: string
}

export interface Container {
  id: string
  name: string
  status: Status
  ram?: string
  cpu?: string
  uptime?: string
  projectId?: string
  note?: string
}

export interface Project {
  id: string
  name: string
  type: 'webapp' | 'cron' | 'automation'
  deployType: 'coolify' | 'manual' | 'host'
  github?: string
  status: Status
  statusNote?: string
  domainIds: string[]
  containerIds: string[]
  dbIds: string[]
  path?: string
  note?: string
}

export interface ScriptRun {
  id: string
  started: string
  duration: string
  records: number
  errors: number
  status: 'ok' | 'error' | 'running'
}

export interface Script {
  id: string
  name: string
  file: string
  schedule: string
  source?: string
  writesTo?: string[]
  lastRun: string
  lastRunStatus: 'ok' | 'error' | 'running' | 'never'
  duration: string
  records: number
  rate?: string
  runs: ScriptRun[]
}

export interface Service {
  id: string
  name: string
  path: string
  github?: string
  status: Status
  statusNote?: string
  scripts: Script[]
}

export interface Alert {
  id: string
  level: 'error' | 'warning' | 'info'
  message: string
  targetView: string
  targetId?: string
}

export interface CleanupItem {
  id: string
  name: string
  type: 'project' | 'database' | 'table'
  meta: string
  reason: string
  severity: 'high' | 'medium' | 'low'
  targetView?: string
  targetId?: string
}
