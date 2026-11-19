// Orca plugin worker entry: shows the Claude Code tasks of the focused workspace as milestones in a
// right-sidebar panel. Read-only: it never types into a terminal and never answers a permission.
//
// Adapted from andoshin11/orca-milestone main.mjs (MIT, see LICENSE and NOTICE.md).
import { homedir } from 'node:os'
import { createLaunchHook } from './src/launch-hook.mjs'
import { createMilestoneWorker } from './src/milestone-worker.mjs'
import { resolveOrcaCli } from './src/orca-cli.mjs'

export default function activate(orca) {
  const worker = createMilestoneWorker({
    orca,
    home: homedir(),
    cli: resolveOrcaCli()
  })
  orca.hooks.on('agent.launch.before', createLaunchHook())
  orca.panels.handle('view.get', () => worker.view())
  orca.panels.handle('workspace.open', ({ path }) => worker.openWorkspace(path))
  orca.commands.register('milestone.refresh', async () => {
    await worker.start()
    await worker.refresh(true)
    return 'Milestones refreshed'
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
