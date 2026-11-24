// The desk over HTTP, end to end: the server of src/desk-server.mjs with the handlers of
// src/desk.mjs and the real gtd.py, in a temporary hub folder. Orca is faked: opening a file,
// focusing a terminal and answering an ask only record what they were asked.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { request } from 'node:http'
import { homedir, tmpdir } from 'node:os'
import { join } from 'node:path'
import { after, before, beforeEach, test as nodeTest } from 'node:test'
import { resolvePython } from '../src/deliver.mjs'
import { createDesk } from '../src/desk.mjs'
import { createDeskServer } from '../src/desk-server.mjs'
import { createGtd } from '../src/gtd.mjs'

const plugin = join(import.meta.dirname, '..')
const script = join(plugin, '..', '..', '..', 'agent', 'skills', 'agents-orchestrator', 'scripts', 'gtd.py')
const python = process.env.PYTHON || resolvePython(homedir())
// gtd.py lives in the agents-orchestrator skill of the same dotfiles; a checkout without it skips.
const skip = existsSync(script) ? false : 'gtd.py is not in this checkout'
const test = (name, fn) => nodeTest(name, { skip }, fn)

const CASE = `# 架空の作り直し
略称: 作り直し

## TODO
- [11/25] 新しい API のテストを足す

## Waiting
- レビュー待ち → 直す

## Later
- 旧モジュールを消す
`

let hub
let server
let desk
let base
let token
let calls

function gtdCli(...args) {
  return JSON.parse(execFileSync(python, [script, ...args], { env: { ...process.env, AGENT_ORCHESTRATOR_HOME: hub, GTD_HOME: '', GTD_BY: 'agent:test' } }).toString().trim().split('\n').pop())
}

const workers = [
  { name: 'research-bg', sessionId: 's1', kind: 'background', state: 'working', done: 1, total: 3, step: '表を作る', tasks: [{ subject: '調べる', status: 'completed' }, { subject: '表を作る', status: 'in_progress' }, { subject: '書く', status: 'pending' }], orcaPath: null },
  { name: 'chore-done', sessionId: 's2', kind: 'background', state: 'done', done: 2, total: 2, tasks: [], orcaPath: null },
  { name: 'orchestrator', sessionId: 's3', kind: 'interactive', state: 'idle', done: 0, total: 0, tasks: [], orcaPath: '/x/hub' }
]
const asks = [
  { id: '20261124-100000-aaaaaaaa', sha: 'a'.repeat(64), kind: 'decide', worker: 'research-bg', question: '期間はどちら', options: [{ label: '4 週', description: '変化が見える' }, { label: '四半期', description: '比べやすい' }], recommended: 1 },
  { id: '20261124-100000-bbbbbbbb', sha: 'b'.repeat(64), kind: 'permission', worker: 'orchestrator', toolName: 'Bash' }
]

before(async () => {
  if (skip) return
  hub = mkdtempSync(join(tmpdir(), 'hub-desk-'))
  mkdirSync(join(hub, 'state', 'cases'), { recursive: true })
  writeFileSync(join(hub, 'state', 'cases', 'refactor.md'), CASE)
  gtdCli('init')
  calls = []
  const gtd = createGtd({ python, script, env: { AGENT_ORCHESTRATOR_HOME: hub, GTD_HOME: '', GTD_TODAY: '2026-11-24' } })
  desk = createDesk({
    gtd,
    hubRoot: hub,
    snapshot: () => ({ workers, asks }),
    openFile: async (path) => {
      calls.push(['open', path])
      return true
    },
    focusWorker: async (worker) => {
      calls.push(['focus', worker.name])
      return { focused: true }
    },
    answerAsk: async (answer) => {
      calls.push(['answer', answer])
      return { ok: true }
    },
    onReply: (id) => calls.push(['reply', id]),
    watchDir: () => ({ close() {} })
  })
  server = createDeskServer({ pluginDir: plugin, handlers: desk.handlers, token: 'test-token-123' })
  const started = await server.start()
  desk.start(server)
  base = `http://127.0.0.1:${started.port}`
  token = 'test-token-123'
  assert.equal(started.url, `${base}/?t=${token}`)
})

after(async () => {
  if (skip) return
  desk.stop()
  await server.close()
  rmSync(hub, { recursive: true, force: true })
})

beforeEach(() => {
  calls = []
})

async function api(path, body, headers = {}) {
  const init = { headers: { 'X-Desk-Token': token, ...headers } }
  if (body !== undefined) {
    init.method = 'POST'
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const res = await fetch(base + path, init)
  return { status: res.status, json: await res.json() }
}

async function cli(...args) {
  const result = gtdCli(...args)
  // What fs.watch tells the desk in Orca; the watcher is faked here.
  desk.changed()
  await new Promise((resolve) => setTimeout(resolve, 250))
  return result
}

const state = async () => (await api('/api/state')).json
const itemFile = (id) => join(hub, 'gtd', 'items', `${id}.md`)

function rawGet(path, host) {
  return new Promise((resolve, reject) => {
    const req = request({ host: '127.0.0.1', port: server.port, path, headers: { Host: host } }, (res) => {
      res.resume()
      resolve(res.statusCode)
    })
    req.on('error', reject)
    req.end()
  })
}

test('the page and its scripts come with a strict policy and need no token, since they hold no data', async () => {
  for (const address of ['/', `/?t=${token}`, '/?t=old']) {
    const page = await fetch(base + address)
    assert.equal(page.status, 200, 'Orca loads the address the page left, without the token, again')
    assert.match(page.headers.get('content-security-policy'), /default-src 'none'; script-src 'self'.*frame-ancestors 'none'/)
    assert.equal(page.headers.get('access-control-allow-origin'), null)
    const html = await page.text()
    assert.match(html, /<script type="module" src="\/desk.mjs">/)
    assert.ok(!html.includes(token), 'the page never holds the token')
  }
  assert.equal((await api('/api/state', undefined, { 'X-Desk-Token': '' })).status, 403, 'the data needs it')
  for (const path of ['/desk.mjs', '/keys.mjs', '/sections.mjs', '/asks.mjs', '/desk.css', '/markdown.mjs']) {
    const res = await fetch(base + path)
    assert.equal(res.status, 200, path)
    assert.equal(res.headers.get('access-control-allow-origin'), null)
  }
  assert.equal((await fetch(`${base}/../main.mjs`)).status, 404)
  assert.equal((await fetch(`${base}/src/desk.mjs`)).status, 404)
})

test('a request for another host name is refused (DNS rebinding)', async () => {
  assert.equal(await rawGet('/', `evil.example:${server.port}`), 421)
  assert.equal(await rawGet(`/api/state`, `evil.example:${server.port}`), 421)
  assert.equal(await rawGet('/', `localhost:${server.port}`), 200)
})

test('the API needs the token, POST, JSON and this origin', async () => {
  assert.equal((await api('/api/state', undefined, { 'X-Desk-Token': 'wrong' })).status, 403)
  const plain = await fetch(`${base}/api/add`, { method: 'POST', headers: { 'X-Desk-Token': token, 'Content-Type': 'text/plain' }, body: '{"title":"x"}' })
  assert.equal(plain.status, 415)
  assert.equal((await api('/api/add', { title: 'x' }, { Origin: 'https://evil.example' })).status, 403)
  assert.equal((await fetch(`${base}/api/add`, { headers: { 'X-Desk-Token': token } })).status, 405)
  assert.equal((await api('/api/nothing', {})).status, 404)
  assert.equal((await api('/api/add', { title: '' })).status, 400)
  assert.equal((await api('/api/add', { title: 'x'.repeat(301) })).status, 400)
})

test('add puts a line in the inbox, by the user, and tells the open pages', async () => {
  const events = []
  const controller = new AbortController()
  const stream = await fetch(`${base}/api/events?t=${token}`, { signal: controller.signal })
  const reader = stream.body.getReader()
  const read = (async () => {
    for (;;) {
      const { value, done } = await reader.read()
      if (done) break
      events.push(new TextDecoder().decode(value))
      if (events.join('').split('event: change').length > 2) break
    }
  })()
  const { status, json } = await api('/api/add', { title: '  会議で出た:   12/3 の勉強会  ' }, { Origin: base })
  assert.equal(status, 200)
  assert.match(json.id, /^20261124-[0-9a-f]{4}$/)
  assert.match(readFileSync(itemFile(json.id), 'utf8'), /^---\nid: .*\ntitle: "会議で出た: 12\/3 の勉強会"\nlist: inbox\n/)
  await read
  controller.abort()
  assert.match(events.join(''), /event: change\ndata: \{"rev":\d+\}/)
  const shown = await state()
  assert.equal(shown.counts.inbox, 1)
  const log = readFileSync(join(hub, 'gtd', '.log', 'changes.jsonl'), 'utf8').trim().split('\n').map((line) => JSON.parse(line))
  assert.equal(log.at(-1).by, 'user')
})

test('move and done check the hash; done moves the project to its next step', async () => {
  const project = await cli('add', 'プロジェクト', '--list', 'project', '--id', 'proj', '--outcome', 'できている')
  const first = await cli('step', 'add', 'proj', '--title', '1 つ目')
  const second = await cli('step', 'add', 'proj', '--title', '2 つ目')
  assert.ok(project.id)
  let shown = await state()
  const one = shown.items.find((item) => item.id === first.id)
  assert.equal(one.list, 'next')
  const stale = await api('/api/move', { id: one.id, list: 'someday', hash: '0000000000000000' })
  assert.equal(stale.status, 409)
  assert.match(stale.json.error, /ほかの人が先に直した/)
  const done = await api('/api/done', { id: one.id, hash: one.hash })
  assert.equal(done.status, 200)
  assert.deepEqual(done.json.promoted, [second.id])
  shown = await state()
  assert.equal(shown.items.find((item) => item.id === second.id).list, 'next')
  assert.equal((await api('/api/move', { id: one.id, list: 'calendar' })).status, 400)
  assert.equal((await api('/api/move', { id: one.id, list: 'someday', hash: 'not-a-hash' })).status, 400)
  const flag = await api('/api/add', { title: '--by' })
  assert.equal(flag.status, 200)
  assert.equal((await state()).items.find((item) => item.id === flag.json.id).title, '--by')
  assert.equal((await api('/api/move', { id: '../x', list: 'next' })).status, 400)
  assert.equal((await api('/api/done', { id: '20990101-0000' })).status, 404)
})

test('open shows the item or one of its deliverables in the editor, and nothing outside them', async () => {
  const { id } = await cli('add', '成果物のある項目', '--list', 'next')
  mkdirSync(join(hub, 'gtd', 'items', id), { recursive: true })
  writeFileSync(join(hub, 'gtd', 'items', id, 'report.md'), '# 報告')
  assert.equal((await api('/api/open', { id })).json.opened, true)
  assert.equal((await api('/api/open', { id, path: 'report.md' })).json.opened, true)
  assert.deepEqual(calls, [['open', itemFile(id)], ['open', join(hub, 'gtd', 'items', id, 'report.md')]])
  for (const path of ['../other.md', '/etc/hosts', 'a/../../x.md']) assert.equal((await api('/api/open', { id, path })).status, 400, path)
  assert.equal((await api('/api/open', { id, path: 'missing.md' })).status, 404)
  symlinkSync('/etc/hosts', join(hub, 'gtd', 'items', id, 'hosts.md'))
  assert.equal((await api('/api/open', { id, path: 'hosts.md' })).status, 400, 'a link out of the items')
  const shown = (await state()).items.find((item) => item.id === id)
  assert.deepEqual(shown.deliverables, ['report.md'])
})

test('an item of a worker shows its progress and asks, and goes to the user when it asks or is done', async () => {
  const asking = await cli('add', '指標をまとめる', '--list', 'next', '--actor', 'agent', '--worker', 'research-bg')
  const finished = await cli('add', '議事録の下書き', '--list', 'next', '--actor', 'agent', '--worker', 'chore-done')
  const shown = await state()
  const a = shown.items.find((item) => item.id === asking.id)
  assert.equal(a.mine, 'ask')
  assert.deepEqual(a.agent, { name: 'research-bg', state: 'working', done: 1, total: 3, step: '表を作る', tasks: workers[0].tasks, inOrca: false })
  assert.deepEqual(a.asks, [{ id: asks[0].id, sha: asks[0].sha, kind: 'decide', question: '期間はどちら', recommended: 1, options: asks[0].options }])
  assert.equal(shown.items.find((item) => item.id === finished.id).mine, 'agent_done')
  assert.deepEqual(shown.agents, { working: 1, done: 1, attention: 1 })
  assert.equal(shown.counts.mine, shown.items.filter((item) => item.mine).length)
})

test('focus switches only to a worker in an Orca terminal; answer passes the ask with its hash', async () => {
  const bg = await cli('add', '動いている', '--list', 'next', '--actor', 'agent', '--worker', 'research-bg')
  const orch = await cli('add', '窓口の番', '--list', 'next', '--actor', 'agent', '--worker', 'orchestrator')
  const none = await cli('add', '人の番', '--list', 'next')
  assert.deepEqual((await api('/api/focus', { id: bg.id })).json, { ok: true, focused: false, reason: 'not-in-orca' })
  assert.deepEqual((await api('/api/focus', { id: none.id })).json, { ok: true, focused: false, reason: 'no-worker' })
  assert.deepEqual((await api('/api/focus', { id: orch.id })).json, { ok: true, focused: true })
  assert.deepEqual(calls, [['focus', 'orchestrator']])
  assert.equal((await api('/api/answer', { askId: asks[0].id, choice: 2 })).status, 200)
  assert.deepEqual(calls.at(-1), ['answer', { id: asks[0].id, sha: asks[0].sha, choice: 2 }])
  assert.equal((await api('/api/answer', { askId: 'nope', choice: 1 })).status, 409)
  // Never the orchestrator's permission dialog, never a stale card, never a choice that is not a number.
  assert.equal((await api('/api/answer', { askId: asks[1].id, choice: 1 })).status, 409)
  assert.equal((await api('/api/answer', { askId: asks[1].id, choice: 'allow' })).status, 400)
  assert.equal((await api('/api/answer', { askId: asks[0].id, choice: 1, sha: 'c'.repeat(64) })).status, 409)
  assert.equal(calls.filter(([name]) => name === 'answer').length, 1)
})

test('the migration: every line of the old cases, moving one marks it, and steps need a project', async () => {
  let shown = await state()
  const refactor = shown.cases.find((c) => c.slug === 'refactor')
  assert.deepEqual(refactor.lines.map((line) => [line.section, line.index, line.moved, line.dropped]), [['TODO', 0, null, false], ['Waiting', 0, null, false], ['Later', 0, null, false]])
  assert.deepEqual(shown.migrate, { done: 0, total: 3 })
  const todo = refactor.lines[0]
  const moved = await api('/api/from-case', { slug: 'refactor', section: 'TODO', index: 0, text: todo.text, to: 'next' })
  assert.equal(moved.status, 200)
  assert.match(readFileSync(join(hub, 'state', 'cases', 'refactor.md'), 'utf8'), new RegExp(`- \\[11/25\\] 新しい API のテストを足す 〔移した→${moved.json.id}〕`))
  const again = await api('/api/from-case', { slug: 'refactor', section: 'TODO', index: 0, text: todo.text, to: 'next' })
  assert.equal(again.status, 409)
  const step = await api('/api/from-case', { slug: 'refactor', section: 'Later', index: 0, text: refactor.lines[2].text, to: 'step' })
  assert.equal(step.status, 400)
  assert.match(step.json.error, /プロジェクト/)
  const project = await api('/api/case-project', { slug: 'refactor' })
  assert.equal(project.status, 200)
  const stepped = await api('/api/from-case', { slug: 'refactor', section: 'Later', index: 0, text: refactor.lines[2].text, to: 'step' })
  assert.equal(stepped.status, 200)
  assert.equal((await api('/api/from-case', { slug: 'refactor', section: 'Waiting', index: 0, text: refactor.lines[1].text, to: 'drop' })).status, 200)
  shown = await state()
  const after = shown.cases.find((c) => c.slug === 'refactor')
  assert.equal(after.project, project.json.id)
  assert.deepEqual(after.lines.map((line) => [line.moved, line.dropped]), [[moved.json.id, false], [null, true], [stepped.json.id, false]])
  assert.deepEqual(shown.migrate, { done: 3, total: 3 })
  assert.equal((await api('/api/from-case', { slug: '../etc', section: 'TODO', index: 0, text: '', to: 'next' })).status, 400)
  assert.equal((await api('/api/from-case', { slug: 'refactor', section: 'Other', index: 0, text: '', to: 'next' })).status, 400)
})

test('a save from the editor is logged by the user, and the recorder waits ten minutes', async () => {
  const { id } = await cli('add', '人が直す', '--list', 'next')
  const path = itemFile(id)
  await new Promise((resolve) => setTimeout(resolve, 5100))
  writeFileSync(path, readFileSync(path, 'utf8') + '\n- 直した')
  desk.changed(`items/${id}.md`)
  await new Promise((resolve) => setTimeout(resolve, 400))
  const log = readFileSync(join(hub, 'gtd', '.log', 'changes.jsonl'), 'utf8').trim().split('\n').map((line) => JSON.parse(line))
  assert.deepEqual([log.at(-1).id, log.at(-1).action, log.at(-1).by], [id, 'edit', 'user'])
  await desk.recordOnce()
  const status = execFileSync('git', ['-C', join(hub, 'gtd'), 'status', '--porcelain']).toString()
  assert.match(status, new RegExp(`items/${id}\\.md`), 'not committed yet: the editor shows it in file diff')
  assert.ok(existsSync(join(hub, 'gtd', '.git')))
})

test('a reply goes into the item\'s body under あなたの番への返事, by user, and the orchestrator is told', async () => {
  const added = await api('/api/add', { title: '方針を決める' }, { Origin: base })
  const id = added.json.id
  const { status } = await api('/api/reply', { id, text: 'A 案で。\n来週まで' }, { Origin: base })
  assert.equal(status, 200)
  const body = readFileSync(itemFile(id), 'utf8')
  assert.match(body, /## あなたの番への返事\n\n- \d\d\/\d\d: A 案で。 来週まで(\n|$)/)
  assert.deepEqual(calls.filter(([kind]) => kind === 'reply'), [['reply', id]])
  const log = readFileSync(join(hub, 'gtd', '.log', 'changes.jsonl'), 'utf8').trim().split('\n').map((line) => JSON.parse(line))
  assert.equal(log.at(-1).by, 'user')
  assert.equal((await api('/api/reply', { id, text: '  ' }, { Origin: base })).status, 400)
})
