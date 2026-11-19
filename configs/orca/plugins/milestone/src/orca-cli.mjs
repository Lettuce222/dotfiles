// Asks the Orca CLI which workspace is focused and what every agent is doing. The host
// API's workspace.readContext gives only a branch and a display name, which several repositories
// can share, and it says nothing about other workspaces, so both come from here. Only read
// commands are run (`worktree ps`, `terminal list`); nothing is sent to a terminal.
//
// Adapted from andoshin11/orca-milestone src/orca-cli.mjs (MIT, see ../LICENSE and ../NOTICE.md).
// Left out: the offers (next steps, questions, permissions) read for the cards.
import { execFile } from 'node:child_process'
import { existsSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'

/**
 * The CLI bundled with the Orca app that runs this worker, else `orca` on PATH. The worker runs one
 * of Orca's own binaries as Node: Orca.app/Contents/MacOS/Orca in older builds, and the helper
 * Orca.app/Contents/Frameworks/Orca Helper.app/Contents/MacOS/Orca Helper since about 1.4.262,
 * whose own bundle has no CLI. So every app bundle above the binary is tried, innermost first.
 */
export function resolveOrcaCli(execPath = process.execPath, exists = existsSync) {
  let dir = dirname(execPath)
  while (dir !== dirname(dir)) {
    if (basename(dir) === 'Contents') {
      const bundled = join(dir, 'Resources', 'bin', 'orca')
      if (exists(bundled)) return bundled
    }
    dir = dirname(dir)
  }
  return 'orca'
}

export function runOrca(cli, args, timeout = 10_000) {
  return new Promise((resolve, reject) => {
    execFile(cli, args, { timeout, maxBuffer: 16 * 1024 * 1024 }, (error, stdout) => {
      if (error) {
        reject(error)
        return
      }
      try {
        resolve(JSON.parse(stdout))
      } catch (parseError) {
        reject(parseError)
      }
    })
  })
}

const TRACKED_AGENTS = new Set(['claude', 'codex'])

function mainAgents(worktree) {
  return (worktree.agents ?? []).filter((agent) => TRACKED_AGENTS.has(agent.agentType) && !agent.parentPaneKey)
}

/**
 * Whether a workspace may hold a Claude agent team: several Claude agents in one tab. The teammates
 * of Agent Teams run in panes beside their lead, and Orca lists each as an agent of its own.
 */
export function mayHoldTeam(worktrees) {
  return worktrees.some((worktree) => {
    const tabs = mainAgents(worktree).filter((agent) => agent.agentType === 'claude').map((agent) => agent.paneKey?.split(':')[0])
    return new Set(tabs).size < tabs.length
  })
}

/**
 * The workspaces with each teammate under its lead, as `parentPaneKey`, so that the lead alone
 * stands for the team: its cards, its state. Orca marks the terminal of a lead with the agent
 * identity `claude-agent-teams`; the other Claude agents in its tab are its teammates.
 * @param terminals the terminals of `orca terminal list`
 */
export function joinTeams(worktrees, terminals) {
  const leads = new Set(
    (terminals ?? []).filter((terminal) => terminal.agentIdentity === 'claude-agent-teams' && terminal.tabId && terminal.leafId).map((terminal) => `${terminal.tabId}:${terminal.leafId}`)
  )
  if (leads.size === 0) return worktrees
  return worktrees.map((worktree) => {
    const lead = mainAgents(worktree).find((agent) => leads.has(agent.paneKey))
    if (!lead) return worktree
    const tab = lead.paneKey.split(':')[0]
    const isTeammate = (agent) => agent !== lead && !agent.parentPaneKey && agent.agentType === 'claude' && agent.paneKey?.split(':')[0] === tab
    if (!worktree.agents.some(isTeammate)) return worktree
    return { ...worktree, agents: worktree.agents.map((agent) => (isTeammate(agent) ? { ...agent, parentPaneKey: lead.paneKey } : agent)) }
  })
}

/**
 * When the agent itself finished its turn, as Orca reports it apart from the shells it left running
 * (`mainAgent`, seen in Orca 1.4.257), or null when Orca does not say.
 */
function mainAgentDone(agent) {
  const main = agent.mainAgent
  return main?.state === 'done' && Number.isFinite(main.stateStartedAt) ? main.stateStartedAt : null
}

/**
 * The workspaces with each Claude agent that Orca calls working but whose turn is over marked as
 * done, and `background`: shells it started go on running, and it waits for the user. Its proposals
 * then show as for any agent that finished. Its `stateStartedAt` becomes the end of the turn: Orca's
 * stays where the shells began, and the cards of every later turn would get the ids of the first.
 * @param readTurnEnded resolves a workspace path to when its Claude session ended its turn (true when
 *   the time is unknown), or null
 */
export async function settleAgents(worktrees, readTurnEnded) {
  const settled = []
  for (const worktree of worktrees) {
    const working = mainAgents(worktree).filter((agent) => agent.agentType === 'claude' && agent.state === 'working' && agent.hasLivePty === true)
    const ended = working.length !== 1 ? null : (mainAgentDone(working[0]) ?? (await readTurnEnded(worktree.path).catch(() => null)))
    if (!ended) {
      settled.push(worktree)
      continue
    }
    settled.push({ ...worktree, agents: worktree.agents.map((agent) => (agent === working[0] ? { ...agent, state: 'done', background: true, ...(typeof ended === 'number' ? { stateStartedAt: ended } : {}) } : agent)) })
  }
  return settled
}

/**
 * The focused workspace ({ path, displayName, agentStates, background }, or null) and the main
 * agents of every workspace that is not archived.
 * @param readers `readTurnEnded`, see settleAgents, and `readTerminals`, see joinTeams
 */
export async function readWorkspaces(cli, run = runOrca, readers = {}) {
  const response = await run(cli, ['worktree', 'ps', '--limit', '1000', '--json'])
  if (!response?.ok) {
    throw new Error(response?.error?.message ?? 'orca worktree ps failed')
  }
  const { readTurnEnded = async () => null, readTerminals = async () => (await run(cli, ['terminal', 'list', '--json']))?.result?.terminals ?? [] } = readers
  let listed = response.result.worktrees.filter((worktree) => !worktree.isArchived)
  if (mayHoldTeam(listed)) listed = joinTeams(listed, await readTerminals().catch(() => []))
  const worktrees = await settleAgents(listed, readTurnEnded)
  const active = worktrees.find((worktree) => worktree.isActive)
  return {
    active: active
      ? {
          path: active.path,
          displayName: active.displayName,
          agentStates: mainAgents(active).map((agent) => agent.state),
          background: mainAgents(active).some((agent) => agent.background === true)
        }
      : null,
    agents: worktrees.flatMap((worktree) =>
      mainAgents(worktree).map((agent) => ({
        workspace: worktree.displayName,
        repo: typeof worktree.repo === 'string' ? worktree.repo : null,
        path: worktree.path,
        focused: Boolean(worktree.isActive),
        state: agent.state,
        background: agent.background === true,
        since: agent.stateStartedAt ?? null
      }))
    )
  }
}
