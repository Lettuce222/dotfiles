export type GtdItem = {
  body: string
  file: string
  section?: string
  attrs: Record<string, string>
  days_left?: number
}

export type InboxEntry = {
  worker: string
  ref: string
  kind: string
  summary: string
  body?: string
  choices: string[]
  window_id?: string | null
  dialog?: boolean
}

export type WorkerEntry = {
  name: string
  window_id?: string | null
  status: string
  item?: GtdItem | null
  open_reports?: number
  pr?: { number?: number; url?: string; state?: string; ci?: string } | null
}

export type PrEntry = {
  repo?: string
  number?: number
  title?: string
  url?: string
  states?: (string | { state?: string })[]
}

export type HubStatus = {
  generated_at?: string
  inbox: InboxEntry[]
  workers: WorkerEntry[]
  gtd: {
    doing: GtdItem[]
    waiting: GtdItem[]
    next: GtdItem[]
    next_total?: number
    due_soon: GtdItem[]
    inbox_total?: number
  }
  prs: {
    pending?: boolean
    review_requests: PrEntry[]
    own_action: PrEntry[]
    team_requests?: number
  }
  errors: Record<string, string>
}

export type Proposal = {
  id: string
  mark: string
  title: string
  attrs: Record<string, string>
}

export type Snapshot = {
  status: HubStatus | null
  proposals: Proposal[]
  error: string | null
  loadedAt: string
}

declare module 'claude-code' {
  interface PluginState {
    'hub-dashboard': {
      snapshot: Shaped<Snapshot | null>
      drafts: Shaped<Record<string, string>>
      handled: Shaped<Record<string, number>>
      collapsed: Shaped<string[]>
    }
  }
}
