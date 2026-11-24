// Adapted from andoshin11/orca-milestone test/main.test.mjs (MIT, see ../LICENSE and ../NOTICE.md).
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import activate from '../main.mjs'
import { createLaunchHook, withTaskInstructions } from '../src/launch-hook.mjs'

const root = join(import.meta.dirname, '..')
const manifest = JSON.parse(readFileSync(join(root, 'orca-plugin.json'), 'utf8'))

test('registers the commands and events declared in the manifest, and starts nothing on activate', () => {
  const commands = []
  const events = []
  const handlers = []
  const hooks = []
  activate({
    host: { call: () => assert.fail('activate must not call the host') },
    events: { on: (event) => events.push(event) },
    commands: { register: (id) => commands.push(id) },
    panels: { handle: (name) => handlers.push(name), post: () => assert.fail('activate must not post') },
    hooks: { on: (hook) => hooks.push(hook) },
    log: () => {}
  })
  assert.deepEqual(commands, manifest.contributes.commands.map((command) => command.id))
  assert.deepEqual(events, manifest.contributes.events.map((event) => event.on))
  assert.deepEqual(handlers, ['view.get', 'workspace.open', 'report.open', 'ask.answer', 'session.send', 'next.send', 'case.act', 'desk.open'], 'no handler that writes an approval')
  assert.deepEqual(hooks, manifest.contributes.hooks.map((hook) => hook.event))
})

test('a Claude launch gets the task tools and the instructions, and nothing else', () => {
  const hook = createLaunchHook()
  const decided = hook({ agent: 'claude', command: 'claude', env: { KEPT: 'x' } }, (event) => event)
  assert.deepEqual(decided.env, { KEPT: 'x', CLAUDE_CODE_ENABLE_TODO_TOOLS: '1' })
  assert.ok(decided.command.startsWith("claude --append-system-prompt 'The user follows"))
  assert.ok(decided.command.includes('metadata: {"goal":'))
  assert.ok(!decided.command.includes('--settings'), 'no settings: the user hooks decide every permission')
  assert.ok(decided.command.includes('info string is next'), 'the next steps become buttons in the panel')
  assert.ok(!decided.command.includes('\n'), 'typed into a terminal, where a newline is Enter')
  assert.equal(decided.command.match(/'/g).length, 2, 'the instructions hold no quote of their own')
})

test('an Agent Teams launch gets the same, and Codex or an unknown agent passes untouched', () => {
  const hook = createLaunchHook()
  const { command, env } = hook({ agent: 'claude-agent-teams', command: 'orca claude-teams --x', env: {} }, (e) => e)
  assert.deepEqual(env, { CLAUDE_CODE_ENABLE_TODO_TOOLS: '1' })
  assert.ok(command.startsWith("orca claude-teams --append-system-prompt 'The user follows"))
  assert.ok(command.endsWith(' --x'))
  for (const agent of ['codex', 'gemini']) {
    assert.equal(hook({ agent, command: agent, env: {} }, () => assert.fail('passes')), undefined)
  }
})

test('withTaskInstructions keeps the command line and leaves existing instructions alone', () => {
  const command = withTaskInstructions("/bin/claude --teammate-mode auto 'do it'")
  assert.ok(command.startsWith('/bin/claude --append-system-prompt '))
  assert.ok(command.endsWith(" --teammate-mode auto 'do it'"))
  for (const launcher of ['orca-ide claude-teams', 'orca-dev claude-teams', '/opt/bin/orca claude-teams']) {
    assert.ok(withTaskInstructions(launcher).startsWith(`${launcher} --append-system-prompt `), launcher)
  }
  for (const untouched of ['env X=1 claude', 'claudette', 'orca claude-teamsx', 'orca worktree list',
    "claude --append-system-prompt 'mine'", 'claude --append-system-prompt-file /f']) {
    assert.equal(withTaskInstructions(untouched), untouched)
  }
})

// The plugin acts on a session only by handing a worker text (src/deliver.mjs) and by typing a
// pressed card into an Orca terminal the way a person would (src/next-actions.mjs). It never answers
// a permission through a hook, never allows the rest of a turn, never writes an approval, never runs
// gh or git and never reaches the network. These scan the code for the paths that were left out on
// purpose, so that a later edit cannot bring one back unnoticed.
function sources() {
  const files = []
  for (const dir of ['', 'src', 'panel']) {
    for (const name of readdirSync(join(root, dir))) {
      if (name.endsWith('.mjs')) files.push([join(dir, name), readFileSync(join(root, dir, name), 'utf8')])
    }
  }
  return files
}

const CODE_ONLY = (text) => text.replace(/^\s*(\/\/|\*|\/\*).*$/gm, '')

const FORBIDDEN = [
  [/['"]terminal['"],\s*['"]create['"]|terminal\.create/, 'orca terminal create'],
  [/PermissionRequest/, 'a permission decision'],
  [/behavior\s*:/, 'a permission decision'],
  [/--settings/, 'settings on the command line'],
  [/grant|allow-rest/i, 'allowing the rest of a turn'],
  [/['"]gh['"]|\/gh['"]/, 'gh'],
  [/['"](push|git)['"]/, 'git'],
  [/approvals\.py|state\/approvals/, 'an approval record'],
  [/node:(https?|net|dgram|tls)\b|\bfetch\(|XMLHttpRequest|WebSocket/, 'the network']
]

/** What a source text does that the plugin must not, ignoring comments. */
function findForbidden(text) {
  const code = CODE_ONLY(text)
  return FORBIDDEN.filter(([pattern]) => pattern.test(code)).map(([, what]) => what)
}

test('the scanner flags each path that was left out, and not a comment about it', () => {
  const samples = {
    "run(['terminal', 'create', '--command', c])": 'orca terminal create',
    "const out = { decision: { behavior: 'allow' } }": 'a permission decision',
    "return `claude --settings '${json}'`": 'settings on the command line',
    "await grantRest(found.sessionId)": 'allowing the rest of a turn',
    "run('gh', ['pr', 'comment'])": 'gh',
    "run(git, ['push', 'origin'])": 'git',
    "join(home, '.claude', 'hooks', 'approvals.py')": 'an approval record',
    "import https from 'node:https'": 'the network',
    'await fetch(url)': 'the network'
  }
  for (const [code, what] of Object.entries(samples)) assert.ok(findForbidden(code).includes(what), code)
  assert.deepEqual(findForbidden('// no orca terminal send, no --settings, no fetch(url)'), [])
})

test('no code answers a permission through a hook, approves, adds settings or reaches the network', () => {
  for (const [file, text] of sources()) {
    // src/risk.mjs names gh and git to tell what a waiting command does; it runs nothing (see the
    // test of which files spawn).
    // src/desk-server.mjs serves the desk on 127.0.0.1 (the test below holds it to that).
    const found = findForbidden(text)
      .filter((what) => !(file === join('src', 'risk.mjs') && ['gh', 'git'].includes(what)))
      .filter((what) => !(file === join('src', 'desk-server.mjs') && what === 'the network'))
    assert.deepEqual(found, [], file)
  }
})

test('only src/desk-server.mjs opens a socket: an HTTP server on 127.0.0.1, and nothing that calls out', () => {
  const serving = sources()
    .filter(([, source]) => /node:(https?|net|dgram|tls)\b/.test(CODE_ONLY(source)))
    .map(([file]) => file)
  assert.deepEqual(serving, [join('src', 'desk-server.mjs')])
  const text = CODE_ONLY(readFileSync(join(root, 'src', 'desk-server.mjs'), 'utf8'))
  assert.deepEqual([...text.matchAll(/from 'node:(https?|net|dgram|tls)'/g)].map((match) => match[1]), ['http'])
  assert.match(text, /import \{ createServer \} from 'node:http'/, 'the server only, not request or get')
  assert.deepEqual([...text.matchAll(/\.listen\(([^)]*)\)/g)].map((match) => match[1].split(',')[1]?.trim()), ["'127.0.0.1'"])
  assert.doesNotMatch(text, /\bfetch\(|Access-Control-Allow/, 'no call out and no CORS')
  assert.match(text, /timingSafeEqual/, 'the token is compared in constant time')
})

test('the Orca CLI runs the worker asks for outside src/orca-cli.mjs are reads, terminal switch and the desk tab', () => {
  const text = CODE_ONLY(readFileSync(join(root, 'src', 'hub-worker.mjs'), 'utf8'))
  const calls = [...text.matchAll(/runArgs\(\[([^\]]*)\]/g)].map((match) => match[1])
  assert.deepEqual(calls, [
    "'worktree', 'ps', '--limit', '1000', '--json'",
    "'terminal', 'switch', '--terminal', terminal, '--json'",
    "'worktree', 'ps', '--limit', '1000', '--json'",
    "'tab', 'switch', '--page', page, ...where, '--focus', '--json'",
    "'tab', 'list', ...where, '--json'",
    "'goto', '--url', url, '--page', open, ...where, '--json'",
    "'tab', 'create', '--url', url, ...where, '--split', 'right', '--json'"
  ])
})

test('the desk writes only through gtd.py, with --by user, and these commands', () => {
  const runner = CODE_ONLY(readFileSync(join(root, 'src', 'gtd.mjs'), 'utf8'))
  assert.deepEqual([...runner.matchAll(/exec\(([^)]*?)\{/g)].map((match) => match[1].trim()), ['python, [script, ...args],'])
  assert.match(runner, /join\(home, '\.claude', 'skills', 'agents-orchestrator', 'scripts', 'gtd\.py'\)/)
  const desk = CODE_ONLY(readFileSync(join(root, 'src', 'desk.mjs'), 'utf8'))
  const reads = [...desk.matchAll(/\bgtd\(\[([^\]]*)\]/g)].map((match) => match[1])
  assert.deepEqual(reads, ["'json'", "'cases'", "...args, '--by', 'user'", "'record', '--quiet', String(QUIET_S), '--by', 'user'"])
  const writes = [...desk.matchAll(/\bwrite\(\[([^,\]]*)/g)].map((match) => match[1])
  assert.deepEqual(writes, ["'add'", "'move'", "'done'", "'from-case'", "'case-project'"])
  assert.doesNotMatch(desk, /writeFile|rename\(|unlink|rm\(/, 'the desk writes no item itself (only a line of the change log)')
})

test('only src/next-actions.mjs and src/orchestrator.mjs type into an Orca terminal, and only 1, Esc, an answer or a prompt', () => {
  const typing = sources()
    .filter(([, source]) => /['"]send['"]/.test(CODE_ONLY(source)))
    .map(([file]) => file)
    .sort()
  assert.deepEqual(typing, [join('src', 'next-actions.mjs'), join('src', 'orchestrator.mjs')])
  const orchestrator = CODE_ONLY(readFileSync(join(root, 'src', 'orchestrator.mjs'), 'utf8'))
  assert.match(orchestrator, /const STASH_KEY = '\\u0013'/)
  assert.match(orchestrator, /agent\.state !== 'done'/, 'only into a session waiting for a prompt')
  const text = CODE_ONLY(readFileSync(join(root, 'src', 'next-actions.mjs'), 'utf8'))
  assert.match(text, /const ALLOW_ONCE_KEY = '1'/)
  assert.doesNotMatch(text, /['"]2['"]|['"]3['"]/, 'never the options that allow for good or switch modes')
})

test('the Orca CLI is only asked to read', () => {
  const text = CODE_ONLY(readFileSync(join(root, 'src', 'orca-cli.mjs'), 'utf8'))
  const calls = [...text.matchAll(/run\(cli, \[([^\]]*)\]/g)].map((match) => match[1])
  assert.deepEqual(calls, ["'worktree', 'ps', '--limit', '1000', '--json'", "'terminal', 'list', '--json'"])
})

test('the claude CLI is only asked to list the sessions, and nothing else runs a command', () => {
  const text = CODE_ONLY(readFileSync(join(root, 'src', 'claude-agents.mjs'), 'utf8'))
  const calls = [...text.matchAll(/run\(cli, \[([^\]]*)\]/g)].map((match) => match[1])
  assert.deepEqual(calls, ["'agents', '--json', '--all'"])
  const spawning = sources()
    .filter(([, source]) => /node:child_process/.test(CODE_ONLY(source)))
    .map(([file]) => file)
    .sort()
  assert.deepEqual(spawning, [join('src', 'cases.mjs'), join('src', 'claude-agents.mjs'), join('src', 'deliver.mjs'), join('src', 'gtd.mjs'), join('src', 'orca-cli.mjs')])
  // The cases are read with `cases.py json` and nothing else.
  const cases = CODE_ONLY(readFileSync(join(root, 'src', 'cases.mjs'), 'utf8'))
  assert.deepEqual([...cases.matchAll(/execFile\(([^)]*?)\{/g)].map((match) => match[1].trim()), ["python, [script, 'json'],"])
})

test('what the panel runs to act is the short list of src/deliver.mjs', () => {
  const text = CODE_ONLY(readFileSync(join(root, 'src', 'deliver.mjs'), 'utf8'))
  const calls = [...text.matchAll(/\brun\((\w+), \[([^\]]*)\]/g)].map((match) => `${match[1]}: ${match[2]}`)
  assert.deepEqual(calls, [
    "claudeCli: 'stop', session.id",
    "claudeCli: '--bg', '--resume', sessionId, '-n', session.name, '--permission-mode', 'auto', withPrefix(body)",
    "python: asksScript, 'answer', ask.id, '--by', 'panel', '--choice', String(choice), '--shown', ask.sha, ...(text ? ['--text', text",
    "python: casesScript, 'log', caseName, line"
  ])
  assert.match(text, /asksScript = join\(home, '\.claude', 'hooks', 'asks\.py'\)/)
  assert.match(text, /casesScript = join\(home, '\.claude', 'skills', 'agents-orchestrator', 'scripts', 'cases\.py'\)/)
  // Every other run(...) in the plugin is a read of src/claude-agents.mjs or src/orca-cli.mjs.
  for (const [file, source] of sources()) {
    if ([join('src', 'deliver.mjs'), join('src', 'claude-agents.mjs'), join('src', 'orca-cli.mjs'), join('src', 'cases.mjs'), join('src', 'gtd.mjs')].includes(file)) continue
    assert.doesNotMatch(CODE_ONLY(source), /execFile|spawn\(/, file)
  }
})

test('the manifest asks for no more than the upstream plugin, and the license stays', () => {
  assert.equal(manifest.license, 'MIT')
  assert.deepEqual(manifest.capabilities.map((c) => c.kind).sort(), ['agent:read', 'workspace:read', 'workspace:write'])
  assert.match(readFileSync(join(root, 'LICENSE'), 'utf8'), /Copyright \(c\) 2026 andoshin11/)
  assert.match(readFileSync(join(root, 'NOTICE.md'), 'utf8'), /637620c/)
})
