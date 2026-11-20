// Adapted from andoshin11/orca-milestone test/questions.test.mjs (MIT, see ../LICENSE and ../NOTICE.md).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { pendingCall, pendingQuestion } from '../src/claude-sessions.mjs'
import { answerKeys, createNextSender, isDangerous, offersOf, questionButtons, questionForm } from '../src/next-actions.mjs'
import { buildHubModel } from '../src/hub-model.mjs'
import { renderHub } from '../src/hub-render.mjs'
import { renderMarkdown as md } from '../src/markdown.mjs'

// orca-milestone's model and render, in the Hub's terms: the focused workspace with its cards.
const buildModel = (focused, lists, agents = [], offers = []) => buildHubModel([], lists, agents, { focused, offers })
const renderBody = renderHub

const line = (content) => JSON.stringify({ type: 'assistant', message: { content } })
const result = (id) => JSON.stringify({ type: 'user', message: { content: [{ type: 'tool_result', tool_use_id: id }] } })
const ask = (questions, id = 'toolu_q') => ({ toolUseId: id, questions })
const option = (label, description = '') => ({ label, description })
const single = (extra = {}) => ({ question: '公開の時期は？', multiSelect: false, options: [option('今週', 'すぐ'), option('来週')], ...extra })
const waiting = (extra = {}) => ({ agentType: 'claude', state: 'waiting', toolName: 'AskUserQuestion', paneKey: 'tab:leaf', hasLivePty: true, stateStartedAt: 7, ...extra })
const worktree = (agents) => ({ path: '/work/app', agents })

test('pendingQuestion and pendingCall find the last call that has no result yet', () => {
  const asked = line([{ type: 'tool_use', id: 'q1', name: 'AskUserQuestion', input: { questions: [single()] } }])
  assert.deepEqual(pendingQuestion(`${asked}\n`), { toolUseId: 'q1', questions: [single()] })
  assert.equal(pendingQuestion(`${asked}\n${result('q1')}\n`), null)
  const bash = line([{ type: 'tool_use', id: 'b1', name: 'Bash', input: { command: 'ls' } }])
  assert.deepEqual(pendingCall(`{"broken\n${bash}`), { toolUseId: 'b1', name: 'Bash', input: { command: 'ls' } })
  assert.equal(pendingCall(`${bash}\n${result('b1')}`), null)
  const inFolder = JSON.stringify({ ...JSON.parse(bash), cwd: '/w/a/apps' })
  assert.equal(pendingCall(inFolder).cwd, '/w/a/apps', 'the folder the shell was in')
})

test('one question with one answer becomes cards; anything else a form, within limits', () => {
  assert.deepEqual(questionButtons(ask([single()])).suggestions.map((s) => [s.label, s.keys]), [['今週', '1'], ['来週', '2']])
  assert.equal(questionButtons(ask([single({ multiSelect: true })])), null)
  assert.equal(questionForm(ask([single(), single({ multiSelect: true })])).length, 2)
  assert.equal(questionForm(ask([single({ options: [] })])), null)
  assert.equal(questionForm(ask(Array(5).fill(single()))), null)
})

test('answerKeys ticks then tabs on several answers, and refuses answers that do not fit', () => {
  const form = questionForm(ask([single({ multiSelect: true }), single()]))
  assert.deepEqual(answerKeys(form, [[0, 1], [1]]), ['1', '2', '\t', '2'])
  for (const answers of [[[0]], [[], [0]], [[0, 0], [0]], [[0], [0, 1]], [[2], [0]], [[0.5], [0]], 'x']) {
    assert.equal(answerKeys(form, answers), null, JSON.stringify(answers))
  }
})

test('offersOf reads a question, a form and a permission for the agent waiting on them', async () => {
  const readQuestion = async () => ask([single()])
  const [question] = await offersOf([worktree([waiting()])], { readQuestion })
  assert.equal(question.kind, 'question')
  assert.equal(question.question, '公開の時期は？')

  const [form] = await offersOf([worktree([waiting()])], { readQuestion: async () => ask([single(), single()]) })
  assert.equal(form.kind, 'form')
  assert.equal(form.questions.length, 2)

  const readCall = async () => ({ toolUseId: 'b1', name: 'Bash', input: { command: 'rm -rf build' } })
  const [permission] = await offersOf([worktree([waiting({ toolName: 'Bash' })])], { readCall })
  assert.equal(permission.kind, 'permission')
  assert.equal(permission.question, 'Bash を許可しますか？ rm -rf build')
  assert.equal(permission.dangerous, true)
  assert.deepEqual(permission.suggestions.map((s) => s.label), ['許可', '拒否'])

  // The transcript says the call is over or is another one: nothing to press.
  assert.deepEqual(await offersOf([worktree([waiting({ toolName: 'Bash' })])], { readCall: async () => null }), [])
  assert.deepEqual(await offersOf([worktree([waiting({ toolName: 'Write' })])], { readCall }), [])
})

test('while several calls of one turn wait unwritten, a shell command comes from Orca and its menu', async () => {
  const MENU_FOR = (command) => `Bash command\n ${command}\n Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, and always allow\n   4. No\n Esc to cancel · Tab to amend`
  const agent = waiting({ toolName: 'Bash', toolInput: 'touch allowed.txt' })
  const [offer] = await offersOf([worktree([agent])], { readPane: async () => MENU_FOR('touch allowed.txt') })
  assert.equal(offer.question, 'Bash を許可しますか？ touch allowed.txt')
  assert.deepEqual(await offersOf([worktree([agent])], { readPane: async () => MENU_FOR('rm -rf x') }), [], 'another menu')
  assert.deepEqual(await offersOf([worktree([agent])], { readPane: async () => 'no menu' }), [])
  assert.deepEqual(await offersOf([worktree([waiting({ toolName: 'Write', toolInput: 'a.txt' })])], { readPane: async () => MENU_FOR('a.txt') }), [], 'only a shell command')
})


test('isDangerous catches the commands that deserve a second look', () => {
  for (const command of ['rm -rf x', 'sudo ls', 'git push --force', 'git reset --hard', 'kubectl delete pod a']) {
    assert.equal(isDangerous({ name: 'Bash', input: { command } }), true, command)
  }
  assert.equal(isDangerous({ name: 'Bash', input: { command: 'git push origin main' } }), false)
})

const MENU = (command) => `Bash command\n ${command}\n Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, and always allow\n   3. Yes, and switch to auto mode\n   4. No\n Esc to cancel · Tab to amend`

function setup(offer, screens) {
  const keys = []
  const shown = [...screens]
  const send = createNextSender({
    readOffers: async () => [offer],
    run: async (args) => {
      if (args[1] === 'list') return { result: { terminals: [{ handle: 'h1', tabId: 'tab', leafId: 'leaf', writable: true }] } }
      if (args[1] === 'read') return { result: { terminal: { tail: [shown.length > 1 ? shown.shift() : shown[0]] } } }
      keys.push(args[args.indexOf('--text') + 1])
      return { result: { send: { accepted: true } } }
    },
    wait: async () => {}
  })
  return { send, keys }
}

test('a question card presses its number, and a form presses its keys, then Enter on the review page', async () => {
  const [question] = await offersOf([worktree([waiting()])], { readQuestion: async () => ask([single()]) })
  const one = setup(question, [''])
  assert.deepEqual(await one.send({ offer: question.id, index: 1 }), { sent: true })
  assert.deepEqual(one.keys, ['2'])

  const [form] = await offersOf([worktree([waiting()])], { readQuestion: async () => ask([single({ multiSelect: true }), single()]) })
  const many = setup(form, ['Review your answers\n❯ 1. Submit answers'])
  assert.deepEqual(await many.send({ offer: form.id, answers: [[0, 1], [0]] }), { sent: true })
  assert.deepEqual(many.keys, ['1', '2', '\t', '1', '\r'])
  assert.deepEqual(await many.send({ offer: form.id, answers: [[0], [0]] }), { sent: false, reason: 'stale' }, 'sent once')

  const lost = setup(form, ['somewhere else'])
  await assert.rejects(lost.send({ offer: form.id, answers: [[0], [0]] }))
  assert.ok(!lost.keys.includes('\r'), 'never submits off the review page')
})

test('a permission presses 1 or Esc only on its menu, and a dangerous allow needs confirmed', async () => {
  const offerFor = async (command) =>
    (await offersOf([worktree([waiting({ toolName: 'Bash' })])], { readCall: async () => ({ toolUseId: 'b', name: 'Bash', input: { command } }) }))[0]
  const safe = await offerFor('touch a')
  const allow = setup(safe, [MENU('touch a')])
  assert.deepEqual(await allow.send({ offer: safe.id, index: 0 }), { sent: true })
  assert.deepEqual(allow.keys, ['1'])
  const deny = setup(safe, [MENU('touch a')])
  await deny.send({ offer: safe.id, index: 1 })
  assert.deepEqual(deny.keys, ['\u001b'])
  const elsewhere = setup(safe, [MENU('touch other')])
  assert.deepEqual(await elsewhere.send({ offer: safe.id, index: 0 }), { sent: false, reason: 'stale' })
  assert.deepEqual(elsewhere.keys, [])

  const risky = await offerFor('rm -rf build')
  const confirm = setup(risky, [MENU('rm -rf build')])
  assert.deepEqual(await confirm.send({ offer: risky.id, index: 0 }), { sent: false, reason: 'confirm' })
  assert.deepEqual(await confirm.send({ offer: risky.id, index: 0, confirmed: true }), { sent: true })
  assert.deepEqual(confirm.keys, ['1'])
})

test('the panel shows a question, a form and a permission in their own cards', async () => {
  const focused = { path: '/work/app', displayName: 'app', agentStates: ['waiting'] }
  const show = async (agent, readers) => renderBody(buildModel(focused, [], [], await offersOf([worktree([agent])], readers)))
  const question = await show(waiting(), { readQuestion: async () => ask([single({ question: '<いつ>' })]) })
  assert.ok(question.includes(`<div class="ask">${md('<いつ>')}</div>`))
  assert.ok(question.includes('data-index="1"'))
  const form = await show(waiting(), { readQuestion: async () => ask([single({ multiSelect: true }), single()]) })
  assert.ok(form.includes('複数選択できます'))
  assert.ok(form.includes('data-question="1" data-option="1" data-multi="0"'))
  assert.ok(form.includes('data-count="2" disabled>回答を送信'))
  const permission = await show(waiting({ toolName: 'Bash' }), { readCall: async () => ({ toolUseId: 'b', name: 'Bash', input: { command: 'sudo ls' } }) })
  assert.ok(permission.includes('危険なコマンド'))
  assert.ok(permission.includes('data-index="0" data-dangerous="1"'))
  assert.ok(!permission.includes('data-index="1" data-dangerous'), 'only allowing asks twice')

  const elsewhere = await show(waiting({ toolName: 'Bash' }), { readCall: async () => ({ toolUseId: 'c', name: 'Bash', input: { command: 'git push' }, cwd: '/work/app/apps/web' }) })
  assert.ok(elsewhere.includes('<span class="risk outside">外に出る</span>'))
  assert.ok(elsewhere.includes('<p class="where">場所: apps/web</p>'))
  const reading = await show(waiting({ toolName: 'Bash' }), { readCall: async () => ({ toolUseId: 'd', name: 'Bash', input: { command: 'git status' } }) })
  assert.ok(reading.includes('<span class="risk read">読むだけ</span>'))
  assert.ok(!reading.includes('class="where"'), 'no place when it runs in the workspace')
})

test('a Claude agent Orca calls working but whose turn is over waits, with its proposals', async () => {
  const { readWorkspaces } = await import('../src/orca-cli.mjs')
  const { turnEnded } = await import('../src/claude-sessions.mjs')
  const reply = 'できました\n```next\n[{"label":"A","prompt":"do a"}]\n```'
  const busy = { agentType: 'claude', state: 'working', paneKey: 'tab:leaf', hasLivePty: true, stateStartedAt: 7, lastAssistantMessage: reply }
  const worktrees = [
    { path: '/a', displayName: 'a', isActive: true, agents: [busy] },
    { path: '/b', displayName: 'b', agents: [{ ...busy, paneKey: 'tab:b' }] }
  ]
  const run = async () => ({ ok: true, result: { worktrees } })
  const read = await readWorkspaces('orca', run, { readTurnEnded: async (path) => path === '/a' })
  assert.deepEqual(read.active.agentStates, ['done'])
  assert.equal(read.active.background, true)
  assert.deepEqual(read.agents.map((agent) => [agent.path, agent.state, agent.background]), [['/a', 'done', true], ['/b', 'working', false]])
  assert.deepEqual(read.offers.map((offer) => offer.path), ['/a'])
  const failing = await readWorkspaces('orca', run, { readTurnEnded: async () => { throw new Error('no transcript') } })
  assert.deepEqual(failing.agents.map((agent) => agent.state), ['working', 'working'])

  const entry = (value) => JSON.stringify(value)
  const ended = entry({ type: 'system', subtype: 'turn_duration' })
  const said = entry({ type: 'assistant', message: { content: [{ type: 'text', text: 'done' }] } })
  const prompt = entry({ type: 'user', message: { content: 'next' } })
  assert.equal(turnEnded([said, ended, entry({ type: 'system', subtype: 'away_summary' }), entry({ type: 'pr-link' })].join('\n')), true)
  assert.equal(turnEnded([said, ended, prompt].join('\n')), null)
  assert.equal(turnEnded(said), null)
})

test('each turn of an agent with shells in the background gets cards of its own', async () => {
  const { readWorkspaces } = await import('../src/orca-cli.mjs')
  const { turnEnded } = await import('../src/claude-sessions.mjs')
  const reply = 'できました\n```next\n[{"label":"A","prompt":"do a"}]\n```'
  const busy = { agentType: 'claude', state: 'working', paneKey: 'tab:leaf', hasLivePty: true, stateStartedAt: 7, lastAssistantMessage: reply }
  const run = async () => ({ ok: true, result: { worktrees: [{ path: '/a', displayName: 'a', agents: [busy] }] } })
  const turn = async (at) => (await readWorkspaces('orca', run, { readTurnEnded: async () => at }))
  const first = await turn(1_000)
  const second = await turn(2_000)
  assert.notEqual(first.offers[0].id, second.offers[0].id, 'a card pressed in one turn leaves the next one usable')
  assert.equal((await turn(1_000)).offers[0].id, first.offers[0].id, 'the same turn keeps its cards')
  assert.ok((await turn(true)).offers[0].id, 'without the time, cards still show')

  const ended = JSON.stringify({ type: 'system', subtype: 'turn_duration', timestamp: '2026-11-12T06:03:28.391Z' })
  assert.equal(turnEnded(ended), Date.parse('2026-11-12T06:03:28.391Z'))
})

test('a turn stays over after compacting while idle, and Orca saying the agent is done is enough', async () => {
  const { readWorkspaces } = await import('../src/orca-cli.mjs')
  const { turnEnded } = await import('../src/claude-sessions.mjs')
  const entry = (value) => JSON.stringify(value)
  const ended = entry({ type: 'system', subtype: 'turn_duration', timestamp: '2026-11-13T06:40:43.000Z' })
  const compacted = [
    entry({ type: 'system', subtype: 'compact_boundary' }),
    entry({ type: 'user', isCompactSummary: true, message: { role: 'user', content: 'This session is being continued...' } }),
    entry({ type: 'attachment', attachment: { type: 'file' } }),
    entry({ type: 'system', subtype: 'informational' })
  ]
  assert.equal(turnEnded([ended, ...compacted].join('\n')), Date.parse('2026-11-13T06:40:43.000Z'))
  assert.equal(turnEnded([ended, ...compacted, entry({ type: 'user', message: { role: 'user', content: 'next' } })].join('\n')), null)

  const reply = 'できました\n```next\n[{"label":"A","prompt":"do a"}]\n```'
  const busy = { agentType: 'claude', state: 'working', paneKey: 'tab:leaf', hasLivePty: true, stateStartedAt: 7, lastAssistantMessage: reply, mainAgent: { state: 'done', stateStartedAt: 3_000 } }
  const run = async () => ({ ok: true, result: { worktrees: [{ path: '/a', displayName: 'a', agents: [busy] }] } })
  const read = await readWorkspaces('orca', run, { readTurnEnded: async () => { throw new Error('not read') } })
  assert.deepEqual(read.agents.map((agent) => [agent.state, agent.background, agent.since]), [['done', true, 3_000]])
  assert.equal(read.offers.length, 1)
  const still = await readWorkspaces('orca', async () => ({ ok: true, result: { worktrees: [{ path: '/a', displayName: 'a', agents: [{ ...busy, mainAgent: { state: 'working', stateStartedAt: 3_000 } }] }] } }))
  assert.deepEqual(still.agents.map((agent) => agent.state), ['working'], 'the agent itself still working stays working')
})

test('in an agent team, the lead stands for the workspace and its teammates go under it', async () => {
  const { readWorkspaces, joinTeams, mayHoldTeam } = await import('../src/orca-cli.mjs')
  const reply = 'できました\n```next\n[{"label":"A","prompt":"do a"}]\n```'
  const claude = (leaf, extra = {}) => ({ agentType: 'claude', state: 'done', paneKey: `tab:${leaf}`, hasLivePty: true, stateStartedAt: 7, lastAssistantMessage: '届いた通知は新しい依頼ではありません', ...extra })
  const lead = claude('lead', { lastAssistantMessage: reply })
  const worktree = { path: '/a', displayName: 'a', isActive: true, agents: [claude('mate1'), lead, claude('mate2', { state: 'working' })] }
  const terminals = [
    { tabId: 'tab', leafId: 'lead', agentIdentity: 'claude-agent-teams' },
    { tabId: 'tab', leafId: 'mate1', agentIdentity: null },
    { tabId: 'tab', leafId: 'mate2', agentIdentity: null }
  ]
  const run = async (cli, args) => ({ ok: true, result: args[0] === 'terminal' ? { terminals } : { worktrees: [worktree] } })
  const read = await readWorkspaces('orca', run)
  assert.deepEqual(read.active.agentStates, ['done'], 'a teammate at work does not make the lead busy')
  assert.equal(read.agents.length, 1)
  assert.deepEqual(read.offers.map((offer) => [offer.paneKey, offer.suggestions[0].label]), [['tab:lead', 'A']])

  assert.equal(mayHoldTeam([{ agents: [claude('x'), { ...claude('y'), paneKey: 'other:y' }] }]), false, 'agents in other tabs are not a team')
  assert.equal(joinTeams([worktree], []) [0], worktree, 'without a lead nothing changes')
  const other = { ...worktree, agents: [claude('mate1'), { ...lead, paneKey: 'other:lead' }] }
  assert.equal(joinTeams([other], [{ tabId: 'other', leafId: 'lead', agentIdentity: 'claude-agent-teams' }])[0], other, 'a Claude in another tab is no teammate')
})

test('a call that reaches past this machine can only be denied from the panel', async () => {
  const focused = { path: '/work/app', displayName: 'app', agentStates: ['waiting'] }
  for (const call of [
    { toolUseId: 'g', name: 'Bash', input: { command: 'gh pr comment 1 --body-file /tmp/x.md' } },
    { toolUseId: 'm', name: 'mcp__slack__send_message', input: { channel: 'C1', text: 'hi' } }
  ]) {
    const [offer] = await offersOf([worktree([waiting({ toolName: call.name })])], { readCall: async () => call })
    assert.deepEqual(offer.suggestions.map((s) => s.action), ['deny'], call.name)
    const html = renderBody(buildModel(focused, [], [], [offer]))
    assert.ok(html.includes('ターミナルの確認で中身を全部読んでから'), call.name)
  }
})

test('a question with previews gets no card: the terminal shows the previews in full', async () => {
  const withPreview = single({ options: [{ label: '送る', description: '', preview: '本文の全文' }, option('見送る')] })
  assert.deepEqual(await offersOf([worktree([waiting()])], { readQuestion: async () => ask([withPreview]) }), [])
  assert.deepEqual(await offersOf([worktree([waiting()])], { readQuestion: async () => ask([single(), withPreview]) }), [])
})
