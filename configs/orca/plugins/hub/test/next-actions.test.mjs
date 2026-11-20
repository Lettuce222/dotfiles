// Adapted from andoshin11/orca-milestone test/next-actions.test.mjs (MIT, see ../LICENSE and ../NOTICE.md).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createNextSender, nextOffer, parseSuggestions } from '../src/next-actions.mjs'
import { buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { renderMarkdown as md } from '../src/markdown.mjs'

// orca-milestone's model and render, in the Hub's terms: the focused workspace with its cards.
const buildModel = (focused, lists, agents = [], offers = []) => buildHubModel([], lists, agents, { focused, offers })
const renderBody = renderHub

const block = (list) => `done\n\n\`\`\`next\n${JSON.stringify(list)}\n\`\`\`\n`
const proposal = (extra = {}) => ({ label: 'PR を作る', prompt: 'PR を作ってください', ...extra })
const agent = (extra = {}) => ({
  agentType: 'claude',
  state: 'done',
  paneKey: 'tab:leaf',
  hasLivePty: true,
  stateStartedAt: 5,
  lastAssistantMessage: block([proposal({ reason: '確認が済んだため' })]),
  ...extra
})
const worktree = (agents, extra = {}) => ({ path: '/work/app', agents, ...extra })

test('parseSuggestions keeps up to three valid buttons from a block at the very end', () => {
  assert.deepEqual(parseSuggestions(block([proposal({ reason: ' 確認が済んだため ' })])), [{ ...proposal(), reason: '確認が済んだため' }])
  assert.equal(parseSuggestions(block([1, 2, 3, 4].map((n) => proposal({ label: `L${n}` })))).length, 3)
  for (const bad of [proposal({ prompt: '-rf' }), proposal({ label: 'あ'.repeat(31) }), proposal({ prompt: 'a\nb' }), { label: 'x' }]) {
    assert.deepEqual(parseSuggestions(block([bad])), [], JSON.stringify(bad))
  }
  assert.deepEqual(parseSuggestions(`${block([proposal()])}and more`), [])
  assert.deepEqual(parseSuggestions('```next\nnot json\n```'), [])
  assert.deepEqual(parseSuggestions(null), [])
})

test('a bad reason costs only the reason', () => {
  for (const reason of [undefined, 3, '', 'a\nb']) assert.equal(parseSuggestions(block([proposal({ reason })]))[0].reason, '', String(reason))
})

test('nextOffer comes from the one live main agent that finished its turn', () => {
  const offer = nextOffer(worktree([agent()]))
  assert.equal(offer.path, '/work/app')
  assert.equal(offer.agent, 'claude')
  assert.equal(offer.paneKey, 'tab:leaf')
  assert.equal(offer.suggestions.length, 1)
  assert.notEqual(offer.id, nextOffer(worktree([agent({ stateStartedAt: 6 })])).id, 'another turn, another offer')
  const none = (wt) => assert.equal(nextOffer(wt), null)
  none(worktree([agent({ state: 'working' })]))
  none(worktree([agent({ lastAssistantMessage: 'no block' })]))
  none(worktree([agent(), agent({ paneKey: 'tab:other' })]))
  none(worktree([agent({ agentType: 'gemini' })]))
  none(worktree([agent()], { isArchived: true }))
  // A closed pane's record and a teammate do not count as a second agent.
  assert.ok(nextOffer(worktree([agent(), agent({ paneKey: 'old', hasLivePty: undefined }), agent({ paneKey: 'mate', parentPaneKey: 'tab:leaf' })])))
})

function setupSender({ agentType = 'claude', screen = '? for shortcuts', accepted = true, terminals } = {}) {
  const offer = nextOffer(worktree([agent({ agentType })]))
  const calls = []
  const send = createNextSender({
    readOffers: async () => [offer],
    run: async (args) => {
      calls.push(args)
      if (args[1] === 'list') return { result: { terminals: terminals ?? [{ handle: 'h1', tabId: 'tab', leafId: 'leaf', writable: true }] } }
      if (args[1] === 'read') return { result: { terminal: { tail: [screen] } } }
      return { result: { send: { accepted } } }
    },
    wait: async () => {}
  })
  const sent = () => calls.filter((args) => args[1] === 'send').map((args) => args[args.indexOf('--text') + 1])
  return { offer, send, sent }
}

test('a press sends the prompt read again from the reply, after stashing a Claude draft', async () => {
  const context = setupSender()
  assert.deepEqual(await context.send({ offer: context.offer.id, index: 0 }), { sent: true })
  assert.deepEqual(context.sent(), ['\u0013', 'PR を作ってください'])
})

test('a second press, an old button and a missing terminal send nothing', async () => {
  const context = setupSender()
  await context.send({ offer: context.offer.id, index: 0 })
  assert.deepEqual(await context.send({ offer: context.offer.id, index: 0 }), { sent: false, reason: 'stale' })
  assert.deepEqual(await context.send({ offer: 'old', index: 0 }), { sent: false, reason: 'stale' })
  assert.deepEqual(await context.send({ offer: context.offer.id, index: 5 }), { sent: false, reason: 'stale' })
  assert.deepEqual(await context.send({ offer: 3, index: '0' }), { sent: false, reason: 'stale' })
  const closed = setupSender({ terminals: [{ handle: 'h1', tabId: 'tab', leafId: 'leaf', writable: false }] })
  assert.deepEqual(await closed.send({ offer: closed.offer.id, index: 0 }), { sent: false, reason: 'stale' })
  assert.equal(context.sent().length, 2)
})

test('Codex is sent nothing while its input box holds a draft, and gets no stash key', async () => {
  const typing = setupSender({ agentType: 'codex', screen: '› half a thought' })
  assert.deepEqual(await typing.send({ offer: typing.offer.id, index: 0 }), { sent: false, reason: 'typing' })
  assert.deepEqual(typing.sent(), [])
  const empty = setupSender({ agentType: 'codex' })
  assert.deepEqual(await empty.send({ offer: empty.offer.id, index: 0 }), { sent: true })
  assert.deepEqual(empty.sent(), ['PR を作ってください'])
})

test('a refused send throws and the button can be pressed again', async () => {
  const context = setupSender({ accepted: false })
  await assert.rejects(context.send({ offer: context.offer.id, index: 0 }))
  await assert.rejects(context.send({ offer: context.offer.id, index: 0 }), 'not marked as used')
})

test('the focused workspace shows its offer as cards, escaped, under its tasks', () => {
  const offer = nextOffer(worktree([agent({ lastAssistantMessage: block([proposal({ label: '<b>直す</b>', reason: '理由 & 背景' })]) })]))
  const sessions = [{ listId: 'l', cwd: '/work/app', goal: 'g', updatedAt: 1, tasks: [{ subject: 't', status: 'completed' }] }]
  const html = renderBody(buildModel({ path: '/work/app', displayName: 'app', agentStates: ['done'] }, sessions, [], [offer]))
  assert.ok(html.includes(`data-next="${offer.id}" data-index="0"`))
  assert.ok(html.includes('&lt;b&gt;直す&lt;/b&gt;'))
  assert.ok(html.includes(`<span class="reason">${md('理由 & 背景')}</span>`))
  assert.ok(html.indexOf('class="next proposal"') > html.indexOf('<ol><li class="completed">'), 'under the tasks')
  const elsewhere = renderBody(buildModel({ path: '/work/other', displayName: 'other', agentStates: [] }, [], [], [offer]))
  assert.ok(!elsewhere.includes('data-next'), 'only the focused workspace')
  const noTasks = renderBody(buildModel({ path: '/work/app', displayName: 'app', agentStates: ['done'] }, [], [], [offer]))
  assert.ok(noTasks.includes('data-next'), 'also without tasks')
})
