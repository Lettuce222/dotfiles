// Orca plugin worker entry for Hub (local). Two parts:
// - the panel (right sidebar): the orchestrator's permission dialogs and questions as cards, the way
//   into the desk with how many items wait, and on demand the view from before hub v2 (every Claude
//   Code session with its goal and progress, and the cases). A pressed answer, or a line written to a
//   worker, resumes that worker with the text (src/deliver.mjs). It never answers a permission
//   through a hook and never writes an approval;
// - the desk (hub v2): one page served on 127.0.0.1 with a token made at each start, opened in a
//   browser tab of Orca (src/desk-server.mjs, src/desk.mjs, desk/). Its writes are gtd.py commands.
//
// Adapted from andoshin11/orca-milestone main.mjs (MIT, see LICENSE and NOTICE.md).
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { existsSync } from 'node:fs'
import { resolveClaudeCli } from './src/claude-agents.mjs'
import { resolvePython } from './src/deliver.mjs'
import { createDesk } from './src/desk.mjs'
import { createDeskServer } from './src/desk-server.mjs'
import { createGtd, gtdScriptOf } from './src/gtd.mjs'
import { createHubWorker } from './src/hub-worker.mjs'
import { createLaunchHook } from './src/launch-hook.mjs'
import { resolveOrcaCli } from './src/orca-cli.mjs'

const STATUS_ID = 'hub-desk'
// The workers' progress changes without a file of the gtd folder changing; looked at this often.
const COUNTS_MS = 10_000

export default function activate(orca) {
  const home = homedir()
  // The same folder the orchestrator scripts use (AGENT_ORCHESTRATOR_HOME, else ~/hub).
  const hubRoot = process.env.AGENT_ORCHESTRATOR_HOME || join(home, 'hub')
  const worker = createHubWorker({
    orca,
    home,
    hubRoot,
    cli: resolveOrcaCli(),
    claudeCli: resolveClaudeCli(home)
  })

  // The desk starts with the worker's first call, never in activate.
  let desk = null
  let deskServer = null
  let deskStarting = null
  let lastStatus = null
  let lastWorkers = null

  async function showCounts() {
    if (!desk) return
    const { workers = [], asks = [] } = worker.snapshot()
    const seen = JSON.stringify([workers.map((w) => [w.name, w.state, w.done, w.total, w.step]), asks.map((a) => a.id)])
    if (lastWorkers !== null && seen !== lastWorkers) deskServer?.notify()
    lastWorkers = seen
    try {
      const counts = await desk.counts()
      worker.setDeskCounts(counts)
      const text = `デスク あなたの番 ${counts.mine}・inbox ${counts.inbox}`
      if (text !== lastStatus) {
        lastStatus = text
        await orca.host.call('statusBar.update', { id: STATUS_ID, text, tone: counts.mine ? 'warning' : 'neutral', tooltip: 'hub のデスクを開く' }).catch(() => {})
      }
    } catch (error) {
      worker.setDeskCounts({ error: error.message })
    }
  }

  function startDesk() {
    deskStarting ??= (async () => {
      const script = gtdScriptOf(home)
      if (!existsSync(script)) {
        worker.setDeskCounts({ error: 'no-gtd' })
        // Tried again on the next call, once dotfiles put gtd.py in place.
        throw Object.assign(new Error('no-gtd'), { quiet: true })
      }
      const gtd = createGtd({ python: resolvePython(home), script, env: { AGENT_ORCHESTRATOR_HOME: hubRoot } })
      desk = createDesk({
        gtd,
        hubRoot,
        snapshot: () => worker.snapshot(),
        openFile: (path) => worker.openFile(path),
        focusWorker: (summary) => worker.focusWorker(summary),
        answerAsk: (request) => worker.answerAsk(request),
        log: (line) => orca.log(line),
        onChange: () => void showCounts()
      })
      deskServer = createDeskServer({ pluginDir: dirname(fileURLToPath(import.meta.url)), handlers: desk.handlers, log: (line) => orca.log(line) })
      const { port } = await deskServer.start()
      desk.start(deskServer)
      orca.log(`hub: the desk is served on 127.0.0.1:${port}`)
      await showCounts()
      setInterval(() => void showCounts(), COUNTS_MS).unref?.()
    })().catch((error) => {
      if (!error.quiet) {
        orca.log(`hub: could not start the desk: ${error.message}`)
        worker.setDeskCounts({ error: error.message })
      }
      deskStarting = null
    })
    return deskStarting
  }

  async function start() {
    await worker.start()
    void startDesk()
  }

  async function openDesk() {
    await start()
    await startDesk()
    return worker.openDesk(deskServer?.url ?? null)
  }

  orca.hooks.on('agent.launch.before', createLaunchHook())
  orca.panels.handle('view.get', async () => {
    void startDesk()
    return worker.view()
  })
  orca.panels.handle('workspace.open', ({ path }) => worker.openWorkspace(path))
  orca.panels.handle('report.open', ({ path }) => worker.openReport(path))
  orca.panels.handle('ask.answer', (params) => worker.answerAsk(params))
  orca.panels.handle('session.send', (params) => worker.sendToSession(params))
  orca.panels.handle('next.send', (request) => worker.sendNext(request))
  orca.panels.handle('case.act', (request) => worker.actOnCase(request))
  orca.panels.handle('desk.open', () => openDesk())
  orca.commands.register('hub.refresh', async () => {
    await start()
    await worker.refresh(true)
    return 'Hub refreshed'
  })
  orca.commands.register('hub.desk.open', async () => {
    const result = await openDesk()
    return result.opened ? 'デスクを開きました' : `デスクを開けませんでした（${result.reason}）`
  })
  orca.events.on('agent.status.changed', async (event) => {
    await start()
    worker.agentChanged(event)
    // An item's worker changed: the desk shows its state.
    deskServer?.notify()
  })
  orca.events.on('workspace.changed', async () => {
    await start()
    worker.schedule(true)
  })
}
