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
  assert.deepEqual(handlers, ['view.get', 'workspace.open'], 'no handler that sends to a session')
  assert.deepEqual(hooks, manifest.contributes.hooks.map((hook) => hook.event))
})

test('a Claude launch gets the task tools and the instructions, and nothing else', () => {
  const hook = createLaunchHook()
  const decided = hook({ agent: 'claude', command: 'claude', env: { KEPT: 'x' } }, (event) => event)
  assert.deepEqual(decided.env, { KEPT: 'x', CLAUDE_CODE_ENABLE_TODO_TOOLS: '1' })
  assert.ok(decided.command.startsWith("claude --append-system-prompt 'The user follows"))
  assert.ok(decided.command.includes('metadata: {"goal":'))
  assert.ok(!decided.command.includes('--settings'), 'no settings: the user hooks decide every permission')
  assert.ok(!decided.command.includes('info string is next'), 'no buttons that type into the session')
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

// The plugin must stay read-only: it shows progress and never acts on a session. These scan the
// code for the paths that were left out on purpose, so that a later edit cannot bring one back
// unnoticed.
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
  [/['"]send['"]/, 'orca terminal send'],
  [/['"]create['"]/, 'orca terminal create'],
  [/PermissionRequest/, 'a permission decision'],
  [/behavior\s*:/, 'a permission decision'],
  [/--settings/, 'settings on the command line'],
  [/next\.send|sendNext|grant/i, 'the cards that act on a session'],
  [/node:(https?|net|dgram|tls)\b|\bfetch\(|XMLHttpRequest|WebSocket/, 'the network']
]

/** What a source text does that the plugin must not, ignoring comments. */
function findForbidden(text) {
  const code = CODE_ONLY(text)
  return FORBIDDEN.filter(([pattern]) => pattern.test(code)).map(([, what]) => what)
}

test('the scanner flags each path that was left out, and not a comment about it', () => {
  const samples = {
    "run(['terminal', 'send', '--text', x])": 'orca terminal send',
    "run(['terminal', 'create', '--command', c])": 'orca terminal create',
    "const out = { decision: { behavior: 'allow' } }": 'a permission decision',
    "return `claude --settings '${json}'`": 'settings on the command line',
    "orca.panels.handle('next.send', f)": 'the cards that act on a session',
    "import https from 'node:https'": 'the network',
    'await fetch(url)': 'the network'
  }
  for (const [code, what] of Object.entries(samples)) assert.ok(findForbidden(code).includes(what), code)
  assert.deepEqual(findForbidden('// no orca terminal send, no --settings, no fetch(url)'), [])
})

test('no code sends to a terminal, answers a permission, adds settings or reaches the network', () => {
  for (const [file, text] of sources()) assert.deepEqual(findForbidden(text), [], file)
})

test('the Orca CLI is only asked to read', () => {
  const text = CODE_ONLY(readFileSync(join(root, 'src', 'orca-cli.mjs'), 'utf8'))
  const calls = [...text.matchAll(/run\(cli, \[([^\]]*)\]/g)].map((match) => match[1])
  assert.deepEqual(calls, ["'worktree', 'ps', '--limit', '1000', '--json'", "'terminal', 'list', '--json'"])
})

test('the manifest asks for no more than the upstream plugin, and the license stays', () => {
  assert.equal(manifest.license, 'MIT')
  assert.deepEqual(manifest.capabilities.map((c) => c.kind).sort(), ['agent:read', 'workspace:read', 'workspace:write'])
  assert.match(readFileSync(join(root, 'LICENSE'), 'utf8'), /Copyright \(c\) 2026 andoshin11/)
  assert.match(readFileSync(join(root, 'NOTICE.md'), 'utf8'), /637620c/)
})
