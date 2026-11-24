import assert from 'node:assert/strict'
import { test } from 'node:test'
import { deskMessage, failureOf, findDeskTab, pageIdOf, redact } from '../src/desk-tab.mjs'
import { createHubWorker } from '../src/hub-worker.mjs'
import { createDeskServer } from '../src/desk-server.mjs'
import { createServer } from 'node:http'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const HOME = '/Users/me'
const HUB = `${HOME}/hub`
const TOKEN = 'secret-token-abc'
const URL_ = `http://127.0.0.1:54178/?t=${TOKEN}`
const SELECTOR = `id:repo::${HUB}`

const HUB_ENTRIES = [
  { path: HUB, worktreeId: `repo::${HUB}::workspace:other`, isMainWorktree: false, isActive: false, isArchived: false, address: { worktree: `id:repo::${HUB}::workspace:other` } },
  { path: HUB, worktreeId: `repo::${HUB}`, isMainWorktree: true, isActive: true, isArchived: false, address: { worktree: SELECTOR } }
]

/** A worker whose Orca CLI answers from `answers`, by the command's first two words. */
function setup(answers, { worktrees = HUB_ENTRIES } = {}) {
  const runs = []
  const logs = []
  const hostCalls = []
  const orca = {
    log: (line) => logs.push(line),
    host: {
      call: async (method, params) => {
        hostCalls.push({ method, params })
        return { opened: true }
      }
    },
    panels: { post: () => {} }
  }
  const runCli = async (cli, args) => {
    runs.push(args)
    const key = args.slice(0, 2).join(' ')
    if (key === 'worktree ps') return { ok: true, result: { worktrees } }
    const answer = answers[key]
    if (typeof answer === 'function') return answer(args)
    if (answer instanceof Error) throw answer
    return answer
  }
  const worker = createHubWorker({ orca, home: HOME, hubRoot: HUB, cli: 'orca', runCli, readClaude: async () => [], watchDir: () => ({ close() {} }) })
  return { worker, runs, logs, hostCalls }
}

/** An error like execFile's: the command line, then what the CLI printed on stderr; its JSON on stdout. */
function cliError(code, message) {
  const error = new Error(`Command failed: orca tab create --url ${URL_} --json\n${message}`)
  error.response = { ok: false, error: { code, message } }
  return error
}

const deskTab = (fields) => ({ browserPageId: 'page-1', url: URL_, title: 'デスク', active: false, ...fields })

test('a page id is the tab list\'s browserPageId, and the older names still read', () => {
  assert.equal(pageIdOf({ browserPageId: 'b' }), 'b')
  assert.equal(pageIdOf({ pageId: 'p' }), 'p')
  assert.equal(pageIdOf({ id: 'i' }), 'i')
  assert.equal(pageIdOf({}), null)
  assert.equal(pageIdOf({ browserPageId: '' }), null)
})

test('the desk\'s tab is one on its origin: the active one, else the last opened', () => {
  const origin = 'http://127.0.0.1:54178'
  const other = { browserPageId: 'x', url: 'http://127.0.0.1:5417/?t=1' }
  assert.equal(findDeskTab([other], origin), null, 'a port that only starts the same is another server, and not titled デスク')
  assert.equal(findDeskTab([deskTab({ browserPageId: 'a' }), deskTab({ browserPageId: 'b' })], origin).browserPageId, 'b')
  assert.equal(findDeskTab([deskTab({ browserPageId: 'a', active: true }), deskTab({ browserPageId: 'b' })], origin).browserPageId, 'a')
  assert.equal(findDeskTab(undefined, origin), null)
})

test('no text that leaves the module holds the desk\'s token', () => {
  assert.equal(redact(`open ${URL_} now`), 'open http://127.0.0.1:54178/?t=… now')
  assert.equal(failureOf(cliError('browser_tab_not_found', `Browser page x out of range ${URL_}`)), 'browser_tab_not_found: Browser page x out of range http://127.0.0.1:54178/?t=…')
  const plain = new Error(`Command failed: orca tab create --url ${URL_} --json\nspawn orca ENOENT`)
  assert.equal(failureOf(plain), 'spawn orca ENOENT', 'the command line is dropped')
  assert.equal(failureOf({ ok: false }), 'ok でない応答')
})

test('the message names what failed and why', () => {
  assert.equal(deskMessage({ opened: true, reused: true }), 'デスクを前に出しました')
  assert.equal(deskMessage({ opened: true, reused: false }), 'デスクを開きました')
  assert.equal(deskMessage({ opened: false, reason: 'create-failed', detail: 'runtime_error: x' }), 'デスクのタブを作れませんでした（runtime_error: x）')
  assert.equal(deskMessage({ opened: false, reason: 'no-desk' }), 'デスクのサーバーが動いていません')
  assert.equal(deskMessage({ opened: false, reason: 'unknown' }), 'デスクを開く途中で失敗しました')
})

test('an open desk tab is loaded anew at the current URL and switched to with --focus by its browserPageId, after the hub\'s workspace is shown', async () => {
  const { worker, runs, hostCalls } = setup({
    'tab list': { ok: true, result: { tabs: [deskTab({ browserPageId: 'page-1' })] } },
    'goto --url': { ok: true, result: { url: URL_ } },
    'tab switch': { ok: true, result: { switched: 0, browserPageId: 'page-1' } }
  })
  assert.deepEqual(await worker.openDesk(URL_), { opened: true, reused: true })
  assert.deepEqual(hostCalls, [{ method: 'workspace.open', params: { workspaceId: `repo::${HUB}` } }], 'the main hub workspace, where the desk lives')
  assert.deepEqual(runs.slice(1), [
    ['tab', 'list', '--worktree', SELECTOR, '--json'],
    ['goto', '--url', URL_, '--page', 'page-1', '--worktree', SELECTOR, '--json'],
    ['tab', 'switch', '--page', 'page-1', '--worktree', SELECTOR, '--focus', '--json']
  ], 'no new tab')
})

test('a desk tab of an earlier start, on a port nobody serves now, is loaded at the current URL', async () => {
  const stale = deskTab({ browserPageId: 'old', url: 'http://127.0.0.1:54178/' })
  const { worker, runs } = setup({
    'tab list': { ok: true, result: { tabs: [{ browserPageId: 'x', url: 'http://127.0.0.1:3000/', title: 'something else' }, stale] } },
    'goto --url': { ok: true },
    'tab switch': { ok: true }
  })
  assert.deepEqual(await worker.openDesk(URL_), { opened: true, reused: true })
  assert.deepEqual(runs.find((args) => args[0] === 'goto'), ['goto', '--url', URL_, '--page', 'old', '--worktree', SELECTOR, '--json'])
  assert.equal(runs.filter((args) => args[1] === 'create').length, 0)
})

test('a tab that cannot be loaded anew is replaced by a new one', async () => {
  const { worker, runs, logs } = setup({
    'tab list': { ok: true, result: { tabs: [deskTab()] } },
    'goto --url': cliError('browser_tab_not_found', 'gone'),
    'tab create': { ok: true, result: { browserPageId: 'page-new' } },
    'tab switch': { ok: true }
  })
  assert.deepEqual(await worker.openDesk(URL_), { opened: true, reused: false })
  assert.equal(runs.filter((args) => args[1] === 'create').length, 1)
  assert.match(logs.join('\n'), /opening another: browser_tab_not_found: gone/)
})

test('the desk server takes the port it is given, and another when that one is taken', async () => {
  const taken = createServer()
  await new Promise((resolve) => taken.listen(0, '127.0.0.1', resolve))
  const busy = taken.address().port
  const logs = []
  const desk = createDeskServer({ pluginDir: '/nowhere', handlers: {}, log: (line) => logs.push(line) })
  try {
    const { port } = await desk.start(busy)
    assert.notEqual(port, busy)
    assert.match(logs.join('\n'), new RegExp(`127.0.0.1:${busy} is taken`))
  } finally {
    await desk.close()
  }
  await new Promise((resolve) => taken.close(resolve))
  const again = createDeskServer({ pluginDir: '/nowhere', handlers: {} })
  try {
    assert.equal((await again.start(busy)).port, busy, 'a free port is used as given')
  } finally {
    await again.close()
  }
})

test('a new desk tab opens in a pane above the one in use and is switched to, since tab create leaves it behind', async () => {
  const { worker, runs } = setup({
    'tab list': { ok: true, result: { tabs: [] } },
    'tab create': { ok: true, result: { browserPageId: 'page-new' } },
    'tab switch': { ok: true, result: { switched: 1, browserPageId: 'page-new' } }
  })
  assert.deepEqual(await worker.openDesk(URL_), { opened: true, reused: false })
  assert.deepEqual(runs.slice(2), [
    ['tab', 'create', '--url', URL_, '--worktree', SELECTOR, '--split', 'up', '--json'],
    ['tab', 'switch', '--page', 'page-new', '--worktree', SELECTOR, '--focus', '--json']
  ])
})

test('a tab that cannot be switched to is replaced by a new one', async () => {
  const { worker, runs, logs } = setup({
    'tab list': { ok: true, result: { tabs: [deskTab({ browserPageId: 'gone' })] } },
    'goto --url': { ok: true },
    'tab switch': (args) => {
      if (args[3] === 'gone') throw cliError('browser_tab_not_found', 'Browser page gone out of range (0-0)')
      return { ok: true }
    },
    'tab create': { ok: true, result: { browserPageId: 'page-new' } }
  })
  assert.deepEqual(await worker.openDesk(URL_), { opened: true, reused: false })
  assert.equal(runs.filter((args) => args[1] === 'create').length, 1)
  assert.match(logs.join('\n'), /could not show the desk's tab, opening another: browser_tab_not_found/)
})

test('every failure says why in the log and the result, without the token', async () => {
  const cases = [
    [{ 'tab list': { ok: true, result: { tabs: [] } }, 'tab create': cliError('runtime_error', `No active worktree for ${URL_}`) }, 'create-failed', 'runtime_error: No active worktree for http://127.0.0.1:54178/?t=…'],
    [{ 'tab list': { ok: true, result: { tabs: [] } }, 'tab create': { ok: false, error: { code: 'x', message: 'refused' } } }, 'create-failed', 'x: refused'],
    [{ 'tab list': { ok: true, result: { tabs: [] } }, 'tab create': { ok: true, result: {} } }, 'focus-failed', 'tab create の応答に browserPageId がありません'],
    [
      { 'tab list': { ok: true, result: { tabs: [] } }, 'tab create': { ok: true, result: { browserPageId: 'p' } }, 'tab switch': { ok: false, error: { code: 'browser_unavailable', message: 'no window' } } },
      'focus-failed',
      'browser_unavailable: no window'
    ]
  ]
  for (const [answers, reason, detail] of cases) {
    const { worker, logs } = setup(answers)
    const result = await worker.openDesk(URL_)
    assert.deepEqual(result, { opened: false, reason, detail }, reason)
    const logged = logs.join('\n')
    assert.ok(logged.includes(`could not open the desk: ${deskMessage(result)}`), logged)
    assert.ok(!logged.includes(TOKEN), 'no token in the log')
    assert.ok(!deskMessage(result).includes(TOKEN), 'no token in the toast')
  }
})

test('no desk server, or no hub workspace in Orca, opens nothing and says so', async () => {
  const none = setup({})
  assert.deepEqual(await none.worker.openDesk(null), { opened: false, reason: 'no-desk' })
  assert.deepEqual(none.runs, [])
  const lost = setup({}, { worktrees: [] })
  assert.deepEqual(await lost.worker.openDesk(URL_), { opened: false, reason: 'no-hub' })
  assert.deepEqual(lost.runs.map((args) => args.slice(0, 2).join(' ')), ['worktree ps'], 'no tab is opened in another workspace')
  assert.match(lost.logs.join('\n'), /Orca に hub のワークスペースが見つかりません/)
})

test('a page with no token or an old one is told, in Japanese, to open the desk again from Orca', async () => {
  const token = 'tok-' + 'x'.repeat(20)
  const desk = createDeskServer({ pluginDir: join(import.meta.dirname, '..'), handlers: { state: async () => ({}) }, token })
  const { port } = await desk.start(0)
  try {
    for (const given of [undefined, 'old-token']) {
      const res = await fetch(`http://127.0.0.1:${port}/api/state`, { headers: given ? { 'X-Desk-Token': given } : {} })
      assert.equal(res.status, 403)
      const body = await res.json()
      assert.equal(body.error, '鍵が古くなりました。Orca のステータスバーの「デスク」を押して開き直してください')
      assert.ok(!JSON.stringify(body).includes(token))
    }
  } finally {
    await desk.close()
  }
  const page = readFileSync(join(import.meta.dirname, '..', 'desk', 'desk.mjs'), 'utf8')
  assert.match(page, /const STALE = '鍵が古くなりました。Orca のステータスバーの「デスク」を押して開き直してください'/)
  assert.match(page, /if \(r\.status === 401 \|\| r\.status === 403\) \{ toast\(STALE, 1e9\)/)
  assert.match(page, /storage\?\.setItem\(TOKEN_KEY, fromUrl\)/, 'kept in localStorage: Orca shows a tab anew in a new webview')
  assert.doesNotMatch(page, /sessionStorage\./)
})

test('a desk tab on the desk\'s origin is loaded anew whatever its title (a page Orca titled by its text)', async () => {
  const { worker, runs } = setup({
    'tab list': { ok: true, result: { tabs: [deskTab({ browserPageId: 'p403', url: 'http://127.0.0.1:54178/', title: 'token' })] } },
    'goto --url': { ok: true },
    'tab switch': { ok: true }
  })
  assert.deepEqual(await worker.openDesk(URL_), { opened: true, reused: true })
  assert.deepEqual(runs.find((args) => args[0] === 'goto'), ['goto', '--url', URL_, '--page', 'p403', '--worktree', SELECTOR, '--json'])
})
