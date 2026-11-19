// Orca plugin worker entry for Hub (local): shows every Claude Code session of this computer, the
// background ones (`claude --bg`) included, with its goal and progress, in a right-sidebar panel.
// Workers' asks show as cards; a pressed answer, or a line written to a worker, resumes that worker
// with the text (src/deliver.mjs). It never answers a permission and never writes an approval, and
// it refuses text that anything but a person or the panel drives into a terminal (src/send-guard.mjs).
//
// Adapted from andoshin11/orca-milestone main.mjs (MIT, see LICENSE and NOTICE.md).
import { homedir } from 'node:os'
import { join } from 'node:path'
import { resolveClaudeCli } from './src/claude-agents.mjs'
import { createHubWorker } from './src/hub-worker.mjs'
import { createLaunchHook } from './src/launch-hook.mjs'
import { createSendGuard } from './src/send-guard.mjs'
import { resolveOrcaCli } from './src/orca-cli.mjs'

export default function activate(orca) {
  const home = homedir()
  const worker = createHubWorker({
    orca,
    home,
    // The same folder the orchestrator scripts use (AGENT_ORCHESTRATOR_HOME, else ~/hub).
    hubRoot: process.env.AGENT_ORCHESTRATOR_HOME || join(home, 'hub'),
    cli: resolveOrcaCli(),
    claudeCli: resolveClaudeCli(home)
  })
  const sendGuard = createSendGuard()
  orca.hooks.on('agent.launch.before', createLaunchHook())
  orca.hooks.on('terminal.send', sendGuard.terminalSend)
  orca.hooks.on('agent.prompt.before', sendGuard.promptBefore)
  orca.panels.handle('view.get', () => worker.view())
  orca.panels.handle('workspace.open', ({ path }) => worker.openWorkspace(path))
  orca.panels.handle('report.open', ({ path }) => worker.openReport(path))
  orca.panels.handle('ask.answer', (params) => worker.answerAsk(params))
  orca.panels.handle('session.send', (params) => worker.sendToSession(params))
  orca.commands.register('hub.refresh', async () => {
    await worker.start()
    await worker.refresh(true)
    return 'Hub refreshed'
  })
  orca.events.on('agent.status.changed', async (event) => {
    await worker.start()
    worker.agentChanged(event)
  })
  orca.events.on('workspace.changed', async () => {
    await worker.start()
    worker.schedule(true)
  })
}
