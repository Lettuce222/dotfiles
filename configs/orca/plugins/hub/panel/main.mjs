// Shows the body the worker renders: what it has when the panel opens, then each change it posts.
// Orca recreates the panel when its sidebar tab is switched, and nothing is posted while it is
// closed, so every open asks again. Asking again while open also keeps the worker from being
// stopped as idle, which would end its watch on the task lists.
//
// Adapted from andoshin11/orca-milestone panel/main.mjs (MIT, see ../LICENSE and ../NOTICE.md).
// Left out: the cards that sent next steps and answers to the session (panel/next.mjs).
// Added: a row of a hub worker opens its report.
import { scrollExpandedRows } from './expand.mjs'
import { openOnPress } from './open.mjs'
import { patchChildren } from './patch.mjs'

const RETRY_MS = 3000
// Orca stops a worker after 5 minutes without any call.
const KEEP_ALIVE_MS = 60_000

let pushes = 0
let loaded = false

const { plugin } = window.orca

plugin.on('view.changed', ({ html }) => {
  pushes += 1
  loaded = true
  patchChildren(document.body, html)
})

async function load() {
  const seen = pushes
  try {
    const { html } = await plugin.request('view.get')
    // A post that arrived while this was on its way is newer.
    if (pushes === seen) patchChildren(document.body, html)
    loaded = true
  } catch (error) {
    console.warn(`hub: view.get failed: ${error.code ?? error.message}`)
    if (!loaded) setTimeout(load, RETRY_MS)
  }
}

scrollExpandedRows(document.body)
openOnPress(document.body, ({ kind, path }) => {
  const name = kind === 'workspace' ? 'workspace.open' : 'report.open'
  plugin.request(name, { path }).catch((error) => {
    console.warn(`hub: ${name} failed: ${error.code ?? error.message}`)
  })
})

void load()
setInterval(load, KEEP_ALIVE_MS)
