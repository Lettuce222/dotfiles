// Copied from andoshin11/orca-milestone test/milestone-worker.test.mjs (MIT, see ../LICENSE and ../NOTICE.md).
import assert from 'node:assert/strict'
import { appendFile, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { test } from 'node:test'
import { createMilestoneWorker } from '../src/milestone-worker.mjs'
import { SESSION_A, SESSION_B, makeHome, markRunning, task, taskCalls, writeTasks, writeTranscript } from './helpers.mjs'

function fakeOrca() {
  const posts = []
  return {
    log: () => {},
    panels: { post: (event, payload) => posts.push({ event, payload }) },
    posts,
    shown: () => posts.at(-1).payload.html
  }
}

test('refresh posts the focused workspace tasks to the panel', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  await writeTranscript(home, SESSION_A, { cwd: '/work/app', prompt: 'Build milestones' })
  await writeTasks(home, SESSION_A, [task(1, 'Read spec', 'completed'), task(2, 'Write code', 'in_progress')])
  await writeTranscript(home, SESSION_B, { cwd: '/work/other', prompt: 'Something else' })
  await writeTasks(home, SESSION_B, [task(1, 'Unrelated', 'pending')])

  let cliCalls = 0
  const worker = createMilestoneWorker({
    orca,
    home,
    cli: 'orca',
    readOrca: async () => {
      cliCalls += 1
      return { active: { path: '/work/app', displayName: 'app', agentStates: ['working'] }, agents: [] }
    },
    watchDir: () => {}
  })

  await worker.refresh(true)
  const first = orca.shown()
  assert.ok(first.includes('Build milestones'))
  assert.ok(first.includes('1 / 2'))
  assert.ok(!first.includes('Unrelated'))

  await writeTasks(home, SESSION_A, [task(2, 'Write code', 'completed'), task(3, 'Run tests', 'in_progress')])
  await worker.refresh()
  const second = orca.shown()
  assert.ok(second.includes('2 / 3'))
  assert.equal(cliCalls, 1, 'a task change alone does not ask the CLI again')
})

test('a list Claude deletes after finishing stays on screen as done; a cleared unfinished one goes', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  await writeTranscript(home, SESSION_A, { cwd: '/work/app', prompt: 'Finish me' })
  await writeTranscript(home, SESSION_B, { cwd: '/work/app', prompt: 'Abandon me' })
  const doneDir = await writeTasks(home, SESSION_A, [task(1, 'Only step', 'completed')])
  const clearedDir = await writeTasks(home, SESSION_B, [task(1, 'Half step', 'in_progress')])
  const worker = createMilestoneWorker({
    orca,
    home,
    cli: 'orca',
    readOrca: async () => ({ active: { path: '/work/app', displayName: 'app', agentStates: [] }, agents: [] }),
    watchDir: () => {}
  })
  await worker.refresh(true)
  await rm(join(doneDir, '1.json'))
  await rm(join(clearedDir, '1.json'))
  await worker.refresh()
  const html = orca.shown()
  assert.ok(html.includes('Finish me'))
  assert.ok(html.includes('1 / 1'))
  assert.ok(!html.includes('Abandon me'))
})

test('a team lead\'s list, named session-<id prefix>, shows under its workspace', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  await writeTranscript(home, SESSION_A, { cwd: '/work/app', prompt: 'Team goal' })
  await writeTasks(home, 'session-11111111', [task(1, 'Plan', 'completed'), task(2, 'Build', 'pending')])
  await writeTasks(home, 'session-22222222', [])
  const worker = createMilestoneWorker({
    orca,
    home,
    cli: 'orca',
    readOrca: async () => ({ active: { path: '/work/app', displayName: 'app', agentStates: [] }, agents: [] }),
    watchDir: () => {}
  })
  await worker.refresh(true)
  const html = orca.shown()
  assert.ok(html.includes('Team goal'))
  assert.ok(html.includes('1 / 2'))
})

test('the heading follows the goal of the current tasks, not the first prompt of the session', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  await writeTranscript(home, SESSION_A, { cwd: '/work/app', prompt: 'First goal' })
  const transcript = join(home, '.claude', 'projects', '-work-app', `${SESSION_A}.jsonl`)
  await appendFile(
    transcript,
    [
      { type: 'user', cwd: '/work/app', message: { role: 'user', content: 'Second goal' } },
      { type: 'assistant', cwd: '/work/app', message: { role: 'assistant', content: [{ type: 'tool_use', name: 'TaskCreate', input: { subject: 'Step two' } }] } }
    ].map((line) => JSON.stringify(line)).join('\n') + '\n'
  )
  await writeTasks(home, SESSION_A, [task(1, 'Step two', 'pending')])
  const worker = createMilestoneWorker({
    orca,
    home,
    cli: 'orca',
    readOrca: async () => ({ active: { path: '/work/app', displayName: 'app', agentStates: [] }, agents: [] }),
    watchDir: () => {}
  })
  await worker.refresh(true)
  let html = orca.shown()
  assert.ok(html.includes('Second goal'))
  assert.ok(!html.includes('First goal'))

  await writeTasks(home, SESSION_A, [
    task(1, 'Step two', 'completed'),
    task(2, 'Step three', 'pending', { metadata: { goal: 'Goal Claude wrote' } })
  ])
  await worker.refresh()
  html = orca.shown()
  assert.ok(html.includes('Goal Claude wrote'))
  assert.ok(html.includes('0 / 1'), 'tasks of the earlier goal are left out')
  assert.ok(!html.includes('Step two'))
})

test('a finished list comes back from the transcript after a restart, and goes with its session', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  await writeTranscript(home, SESSION_A, {
    cwd: '/work/done',
    prompt: 'Do it',
    running: false,
    extra: taskCalls(
      [{ subject: 'Old step' }, { subject: 'New step', metadata: { goal: 'Second goal' } }],
      [{ taskId: '1', status: 'completed' }, { taskId: '2', status: 'completed' }]
    )
  })
  const running = await markRunning(home, SESSION_A)
  // Claude deleted the files of the finished list; only its high-water mark is left.
  const dir = await writeTasks(home, SESSION_A, [])
  await writeFile(join(dir, '.highwatermark'), '2')
  const options = {
    orca,
    home,
    cli: 'orca',
    readOrca: async () => ({
      active: { path: '/work/app', displayName: 'app', agentStates: [] },
      agents: [{ workspace: 'done', path: '/work/done', focused: false, state: 'done', since: 0 }]
    }),
    watchDir: () => {}
  }
  const worker = createMilestoneWorker(options)
  await worker.refresh(true)
  let html = orca.shown()
  assert.ok(html.includes('<span class="name">done</span>'))
  // Only the tasks of the newest goal show.
  assert.ok(html.includes('1 / 1'))
  assert.ok(html.includes('Second goal'))

  await rm(running)
  await worker.refresh()
  html = orca.shown()
  assert.ok(!html.includes('<span class="name">done</span>'), 'gone once the session ends')
})

test('a failing CLI leaves the panel showing that no workspace is known', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  const logs = []
  orca.log = (line) => logs.push(line)
  const worker = createMilestoneWorker({
    orca,
    home,
    cli: 'orca',
    readOrca: async () => {
      throw new Error('runtime unavailable')
    },
    watchDir: () => {}
  })
  await worker.refresh(true)
  assert.ok(orca.shown().includes('ワークスペースを開くと'))
  assert.match(logs.join('\n'), /runtime unavailable/)
})

test('a refresh posts only a real change, at once', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  await writeTranscript(home, SESSION_A, { cwd: '/work/app', prompt: 'App goal' })
  await writeTasks(home, SESSION_A, [task(1, 'One', 'pending'), task(2, 'Two', 'pending')])
  const worker = createMilestoneWorker({
    orca,
    home,
    cli: 'orca',
    readOrca: async () => ({ active: { path: '/work/app', displayName: 'app', agentStates: [] }, agents: [] }),
    watchDir: () => {}
  })
  await worker.refresh(true)
  assert.equal(orca.posts.length, 1)
  assert.equal(orca.posts[0].event, 'view.changed')

  await worker.refresh(true)
  assert.equal(orca.posts.length, 1, 'the same view is not posted again')

  await writeTasks(home, SESSION_A, [task(1, 'One', 'completed')])
  await worker.refresh()
  assert.equal(orca.posts.length, 2)
  assert.ok(orca.shown().includes('1 / 2'))
})

test('view answers with what the panel should show, even when Orca could not be read', async () => {
  const home = await makeHome()
  const orca = fakeOrca()
  const timers = []
  const realSetInterval = globalThis.setInterval
  globalThis.setInterval = (...args) => {
    const timer = realSetInterval(...args)
    timers.push(timer)
    return timer
  }
  try {
    const worker = createMilestoneWorker({
      orca,
      home,
      cli: 'orca',
      readOrca: async () => {
        throw new Error('runtime unavailable')
      },
      watchDir: () => {}
    })
    const { html } = await worker.view()
    assert.ok(html.includes('ワークスペースを開くと'))
    assert.equal(timers.length, 1, 'one slow sync; the rest is driven by events')
  } finally {
    globalThis.setInterval = realSetInterval
    timers.forEach(clearInterval)
  }
})

test('an agent event asks Orca again only when that pane changed state', async () => {
  const home = await makeHome()
  let asked = 0
  const worker = createMilestoneWorker({
    orca: fakeOrca(),
    home,
    cli: 'orca',
    readOrca: async () => {
      asked += 1
      return { active: null, agents: [] }
    },
    watchDir: () => {}
  })
  const settle = () => new Promise((resolve) => setTimeout(resolve, 200))

  worker.agentChanged({ paneKey: 'a', state: 'working' })
  await settle()
  assert.equal(asked, 1)

  worker.agentChanged({ paneKey: 'a', state: 'working' })
  await settle()
  assert.equal(asked, 1, 'the same state again')

  worker.agentChanged({ paneKey: 'a', state: 'waiting' })
  worker.agentChanged({ paneKey: 'b', state: 'working' })
  await settle()
  assert.equal(asked, 2, 'changes close together make one refresh')

  worker.agentChanged({ paneKey: 'b', state: 'working', mainAgent: { state: 'waiting' } })
  await settle()
  assert.equal(asked, 3, 'the main agent of a pane counts too')
})

test('openWorkspace opens the listed workspace at the path, and only logs a miss or a failure', async () => {
  const orca = fakeOrca()
  const logs = []
  orca.log = (line) => logs.push(line)
  const calls = []
  let fail = false
  orca.host = {
    call: async (method, params) => {
      calls.push([method, params])
      if (fail) throw new Error('refused')
      return {
        workspaces: [
          { id: 'identity:a', path: '/work/a' },
          { id: 'identity:b', path: '/work/b' }
        ]
      }
    }
  }
  const worker = createMilestoneWorker({ orca, home: await makeHome(), cli: 'orca', watchDir: () => {} })

  assert.deepEqual(await worker.openWorkspace('/work/b'), { opened: true })
  assert.deepEqual(calls.at(-1), ['workspace.open', { workspaceId: 'identity:b' }])

  calls.length = 0
  assert.deepEqual(await worker.openWorkspace('/work/gone'), { opened: false })
  assert.deepEqual(calls.map(([method]) => method), ['workspace.list'])
  assert.match(logs.join('\n'), /no workspace to open at \/work\/gone/)

  fail = true
  assert.deepEqual(await worker.openWorkspace('/work/a'), { opened: false })
  assert.match(logs.join('\n'), /could not open the workspace: refused/)
})
