// What an agent in an Orca terminal offers the user to choose from in the panel, and sending the choice:
// - a proposal: the next steps it wrote at the end of its reply (the block the launch hook asks for)
// - a question: Claude Code's AskUserQuestion, as cards, or as a form for several questions or answers
// - a permission: a tool waiting to be allowed in Claude Code
// The panel says only which offer and which card: the worker reads the agent again when one is
// pressed, so a card from an earlier turn does nothing, and keys go to a menu only after its screen
// is read.
//
// Pressing a permission card types into the terminal what a person would press on the same menu:
// 1 (allow this once) or Esc. Claude Code shows that menu only after the PreToolUse hooks
// (approval-gate.py, external-post-guard.py, agent-ui-guard.py) let the call come that far, so a
// call a hook denied never gets a card, and the card is no stronger than the menu. A call that
// reaches past this machine (gh writes, MCP writes) gets no allow card: the menu shows the whole
// body to read, the card cannot. A question with previews (the orchestrator's approval questions)
// gets no card either, since the card shortens what the preview shows in full.
//
// Adapted from andoshin11/orca-milestone src/next-actions.mjs (MIT, see ../LICENSE and ../NOTICE.md).
// Left out: "allow the rest of this turn" (turn-grant.mjs, a PermissionRequest hook that would allow
// calls no one read), the restart card (restart.mjs) and Codex's permission menu.
import { createHash } from 'node:crypto'
import { basename } from 'node:path'
import { isDangerous } from './dangerous.mjs'
import { riskOf, whereOf } from './risk.mjs'

export { isDangerous }

const SUGGESTIONS_MAX = 3
const LABEL_MAX = 30
const PROMPT_MAX = 300
const REASON_MAX = 80
const QUESTION_MAX = 300
const OPTION_MAX = 60
const DETAIL_MAX = 200
// One key each: the menu takes the number of an option as a single key press.
const OPTIONS_MAX = 9
const QUESTIONS_MAX = 4
const NEXT_BLOCK = /```next[ \t]*\r?\n([\s\S]*?)\r?\n?```\s*$/
const CONTROL = /[\u0000-\u001f\u007f]/
const TRACKED_AGENTS = new Set(['claude', 'codex'])
const PERMISSION_STATES = ['waiting', 'permission']
const USED_MAX = 256
const SUBMIT_WAIT_SECONDS = '8'
const SEND_TIMEOUT_MS = 20_000
const SCREEN_LINES = '60'
// Claude Code's stash: it takes what is in the input box and puts it back after the next submit.
const STASH_KEY = '\u0013'
const STASH_WAIT_MS = 400
// Codex shows this while its input box is empty. Text in the box does not show on a screen read.
const CODEX_EMPTY_HINT = '? for shortcuts'
const TAB_KEY = '\t'
const SUBMIT_KEY = '\r'
const ESCAPE_KEY = '\u001b'
const ALLOW_ONCE_KEY = '1'
const KEY_WAIT_MS = 250
const REVIEW_WAIT_MS = 800
// On the review page the menu shows after the last question.
const REVIEW_PAGE = 'Submit answers'
// Claude Code's permission menu: the first option differs from nothing else on it, while the other
// numbers change with the tool (on Bash, 3 switches to auto mode), so only 1 is ever pressed.
const ALLOW_ONCE_LINE = /^\s*(?:❯\s*)?1\. Yes\s*$/m
const PERMISSION_FOOTER = 'Esc to cancel'

function shorten(text, max) {
  const chars = [...text.replace(/\s+/g, ' ').trim()]
  return chars.length > max ? `${chars.slice(0, max - 1).join('')}…` : chars.join('')
}

function isSuggestion(value) {
  if (typeof value?.label !== 'string' || typeof value?.prompt !== 'string') return false
  const label = value.label.trim()
  const prompt = value.prompt.trim()
  if (!label || !prompt || CONTROL.test(label) || CONTROL.test(prompt)) return false
  // The prompt goes on a command line as the value of an option.
  return [...label].length <= LABEL_MAX && [...prompt].length <= PROMPT_MAX && !prompt.startsWith('-')
}

/** Optional, and only shown: a bad one costs the reason, not the button. */
function reasonOf(reason) {
  if (typeof reason !== 'string' || !reason.trim() || CONTROL.test(reason)) return ''
  return shorten(reason, REASON_MAX)
}

/** The buttons of a reply, or none when its last thing is not a valid next block. */
export function parseSuggestions(message) {
  const block = NEXT_BLOCK.exec(message ?? '')
  if (!block) return []
  let list
  try {
    list = JSON.parse(block[1])
  } catch {
    return []
  }
  if (!Array.isArray(list)) return []
  return list
    .filter(isSuggestion)
    .slice(0, SUGGESTIONS_MAX)
    .map(({ label, prompt, reason }) => ({ label: label.trim(), prompt: prompt.trim(), reason: reasonOf(reason) }))
}

/**
 * The one live main agent of a workspace, or null. With two, a card could reach another agent
 * than the one shown. Orca keeps the record of a pane that has closed, without hasLivePty.
 */
function soleAgent(worktree) {
  if (worktree.isArchived) return null
  const agents = (worktree.agents ?? []).filter(
    (agent) => TRACKED_AGENTS.has(agent.agentType) && !agent.parentPaneKey && agent.hasLivePty === true
  )
  return agents.length === 1 ? agents[0] : null
}

/** Changes with every turn and every call, so a card shown for an earlier one matches nothing. */
function offerId(agent, extra = '') {
  return createHash('sha256').update(`${agent.paneKey}\n${agent.stateStartedAt}\n${extra}`).digest('hex').slice(0, 16)
}

function base(kind, worktree, agent, extra) {
  return { kind, id: offerId(agent, extra), path: worktree.path, agent: agent.agentType, paneKey: agent.paneKey }
}

/** What a workspace's agent proposes now: only one that finished its turn. */
export function nextOffer(worktree) {
  const agent = soleAgent(worktree)
  if (agent?.state !== 'done') return null
  const suggestions = parseSuggestions(agent.lastAssistantMessage)
  if (suggestions.length === 0) return null
  return { ...base('proposal', worktree, agent), suggestions }
}

/** A question whose options carry previews: the card would shorten them, so the terminal answers it. */
function hasPreview(asked) {
  return (asked?.questions ?? []).some((question) => (question?.options ?? []).some((option) => typeof option?.preview === 'string' && option.preview.trim()))
}

/**
 * The cards for one question that has one answer. The options keep their order and none is left
 * out, since the key to press is the position.
 */
export function questionButtons(asked) {
  if (asked?.questions?.length !== 1 || hasPreview(asked)) return null
  const [{ question, multiSelect, options }] = asked.questions
  if (typeof question !== 'string' || !question.trim() || multiSelect) return null
  if (!Array.isArray(options) || options.length === 0 || options.length > OPTIONS_MAX) return null
  if (!options.every((option) => typeof option?.label === 'string' && option.label.trim())) return null
  return {
    question: shorten(question, QUESTION_MAX),
    suggestions: options.map((option, index) => ({
      label: shorten(option.label, OPTION_MAX),
      keys: String(index + 1),
      detail: typeof option.description === 'string' ? shorten(option.description, DETAIL_MAX) : ''
    }))
  }
}

/** Several questions, or one with several answers: a form answered and sent at once. */
export function questionForm(asked) {
  const questions = asked?.questions
  if (!Array.isArray(questions) || questions.length === 0 || questions.length > QUESTIONS_MAX || hasPreview(asked)) return null
  const valid = questions.every(
    ({ question, options } = {}) =>
      typeof question === 'string' && question.trim() &&
      Array.isArray(options) && options.length > 0 && options.length <= OPTIONS_MAX &&
      options.every((option) => typeof option?.label === 'string' && option.label.trim())
  )
  if (!valid) return null
  return questions.map(({ question, multiSelect, options }) => ({
    question: shorten(question, QUESTION_MAX),
    multiSelect: multiSelect === true,
    options: options.map((option) => ({
      label: shorten(option.label, OPTION_MAX),
      detail: typeof option.description === 'string' ? shorten(option.description, DETAIL_MAX) : ''
    }))
  }))
}

/**
 * The keys that answer a form, or null for answers that do not fit it. A number on a question with
 * one answer moves to the next question by itself; with several answers it only ticks the option,
 * and Tab moves on. After the last question the menu shows a review page, left for the caller.
 */
export function answerKeys(questions, answers) {
  if (!Array.isArray(questions) || !Array.isArray(answers) || answers.length !== questions.length) return null
  const keys = []
  for (const [position, { multiSelect, options }] of questions.entries()) {
    const chosen = answers[position]
    if (!Array.isArray(chosen) || chosen.length === 0 || new Set(chosen).size !== chosen.length) return null
    if (!multiSelect && chosen.length !== 1) return null
    if (!chosen.every((index) => Number.isInteger(index) && index >= 0 && index < options.length)) return null
    keys.push(...chosen.map((index) => String(index + 1)))
    if (multiSelect) keys.push(TAB_KEY)
  }
  return keys
}

async function questionOffer(worktree, readQuestion) {
  const agent = soleAgent(worktree)
  if (agent?.agentType !== 'claude' || agent.state !== 'waiting' || agent.toolName !== 'AskUserQuestion') return null
  const asked = await readQuestion(worktree.path).catch(() => null)
  const buttons = questionButtons(asked)
  if (buttons) return { ...base('question', worktree, agent, asked.toolUseId), ...buttons }
  const questions = questionForm(asked)
  return questions ? { ...base('form', worktree, agent, asked.toolUseId), questions } : null
}


/** What a tool call would do, in a line, and a piece of it that its permission menu shows. */
function describeCall({ input }) {
  if (typeof input.command === 'string') {
    return { summary: shorten(input.command, QUESTION_MAX), menuHint: input.command.trim().split('\n')[0].slice(0, 24) }
  }
  if (typeof input.file_path === 'string') {
    return { summary: shorten(input.file_path, QUESTION_MAX), menuHint: basename(input.file_path) }
  }
  return { summary: shorten(JSON.stringify(input), QUESTION_MAX), menuHint: '' }
}

const ALLOW_CARD = { label: '許可', action: 'allow', detail: '今回だけ実行します' }
const DENY_CARD = { label: '拒否', action: 'deny', detail: '実行しません' }

/** A call that reaches past this machine is allowed only at the terminal, whose menu shows it in full. */
function permissionCards(risk) {
  return risk === 'outside' ? [DENY_CARD] : [ALLOW_CARD, DENY_CARD]
}

/**
 * The call a Claude Code menu asks about. The transcript says best, and it cannot say "waiting" after
 * the user answered at the terminal, as Orca can. But while several calls of one turn wait, Claude
 * Code has written none of them yet: then a shell command is taken from Orca, and only while its
 * menu is on the screen.
 */
async function claudeCall(worktree, agent, readCall, readPane) {
  const call = await readCall(worktree.path).catch(() => null)
  if (call) return call.name === agent.toolName ? call : null
  if (agent.toolName !== 'Bash' || typeof agent.toolInput !== 'string' || !agent.toolInput.trim()) return null
  const fromOrca = { toolUseId: agent.toolInput, name: 'Bash', input: { command: agent.toolInput } }
  const shown = await readPane(agent.paneKey).catch(() => null)
  return shown && isPermissionMenu(shown, describeCall(fromOrca).menuHint) ? fromOrca : null
}

async function permissionOffer(worktree, readCall, readPane) {
  const agent = soleAgent(worktree)
  if (agent?.agentType !== 'claude' || !PERMISSION_STATES.includes(agent.state) || !agent.toolName || agent.toolName === 'AskUserQuestion') return null
  const call = await claudeCall(worktree, agent, readCall, readPane)
  if (!call) return null
  const { summary, menuHint } = describeCall(call)
  const risk = riskOf(call)
  return {
    ...base('permission', worktree, agent, call.toolUseId),
    question: `${call.name} を許可しますか？ ${summary}`,
    menuHint,
    risk,
    where: whereOf(call, worktree.path),
    dangerous: isDangerous(call),
    // Said on the card when only the terminal can allow the call.
    terminalOnly: risk === 'outside',
    suggestions: permissionCards(risk)
  }
}

/** Keys are pressed only on Claude Code's menu for this very call, read from the screen just before. */
export function isPermissionMenu(screen, menuHint) {
  return ALLOW_ONCE_LINE.test(screen) && screen.includes(PERMISSION_FOOTER) && screen.includes(menuHint)
}

/**
 * What every workspace's agent offers now.
 * @param readQuestion resolves a workspace path to its Claude session's pending AskUserQuestion
 * @param readCall     resolves a workspace path to its Claude session's pending tool call
 * @param readPane     resolves a pane key to what its terminal shows now
 */
export async function offersOf(worktrees, { readQuestion = async () => null, readCall = async () => null, readPane = async () => null } = {}) {
  const offers = []
  for (const worktree of worktrees) {
    const offer =
      nextOffer(worktree) ??
      (await questionOffer(worktree, readQuestion)) ??
      (await permissionOffer(worktree, readCall, readPane))
    if (offer) offers.push(offer)
  }
  return offers
}

/** A workspace not on screen has no tab for its pane, and its terminal only records the key. */
function isPane(terminal, paneKey) {
  return terminal.recordedPaneKey === paneKey || `${terminal.tabId}:${terminal.leafId}` === paneKey
}

export async function readTerminalScreen(run, handle) {
  return readScreen(run, handle)
}

async function readScreen(run, handle) {
  return (await run(['terminal', 'read', '--terminal', handle, '--screen', '--limit', SCREEN_LINES, '--json'])).result.terminal.tail.join('\n')
}

/** What a pane shows now, or null when no terminal has it. */
export async function readPaneScreen(run, paneKey) {
  const { terminals } = (await run(['terminal', 'list', '--json'])).result
  const terminal = terminals.find((candidate) => isPane(candidate, paneKey))
  return terminal ? readScreen(run, terminal.handle) : null
}

/**
 * @param readOffers resolves to the offers of every workspace, read from Orca now
 * @param run        runs the Orca CLI with arguments and resolves to its JSON reply
 * @returns a function that takes `{ offer, index }` for a card, or `{ offer, answers }` for a form,
 *   and resolves to `{ sent: true }`, or to `{ sent: false, reason }`: `stale` when that card is no
 *   longer on offer, `typing` when Codex has a draft a prompt would join, or `confirm` to allow a
 *   dangerous command without `confirmed: true`. It throws when sending fails.
 */
export function createNextSender({ readOffers, run, wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) {
  const used = new Set()

  function take(offer) {
    used.add(offer)
    if (used.size > USED_MAX) used.delete(used.values().next().value)
  }

  /** Without Enter: a menu takes a number as one key press, and Enter would go on to the next. */
  async function press(handle, key) {
    const reply = await run(['terminal', 'send', '--terminal', handle, '--text', key, '--json'])
    if (!reply.result?.send?.accepted) throw new Error('the terminal did not accept the key')
  }

  /** Submits only from the review page, so that keys gone astray never answer on their own. */
  async function answerForm(handle, keys) {
    for (const key of keys) {
      await press(handle, key)
      await wait(KEY_WAIT_MS)
    }
    await wait(REVIEW_WAIT_MS)
    if (!(await readScreen(run, handle)).includes(REVIEW_PAGE)) throw new Error('the menu did not reach its review page')
    await press(handle, SUBMIT_KEY)
  }

  async function sendPrompt(found, handle, prompt) {
    if (found.agent === 'claude') {
      await press(handle, STASH_KEY)
      await wait(STASH_WAIT_MS)
    }
    const reply = await run(
      ['terminal', 'send', '--terminal', handle, '--text', prompt, '--enter', '--wait-submit', SUBMIT_WAIT_SECONDS, '--json'],
      SEND_TIMEOUT_MS
    )
    if (!reply.result?.send?.accepted) throw new Error('the terminal did not accept the prompt')
  }

  return async function send({ offer, index, answers, confirmed = false } = {}) {
    const stale = { sent: false, reason: 'stale' }
    if (typeof offer !== 'string' || used.has(offer)) return stale
    const found = (await readOffers()).find((candidate) => candidate.id === offer)
    if (!found) return stale
    const keys = answers !== undefined ? answerKeys(found.questions, answers) : null
    const suggestion = answers === undefined && Number.isInteger(index) ? found.suggestions?.[index] : null
    if (!keys && !suggestion) return stale
    if (suggestion?.action === 'allow' && found.dangerous && confirmed !== true) return { sent: false, reason: 'confirm' }
    const { terminals } = (await run(['terminal', 'list', '--json'])).result
    const terminal = terminals.find((candidate) => isPane(candidate, found.paneKey) && candidate.writable)
    if (!terminal) return stale
    if (suggestion?.action) {
      if (found.agent !== 'claude' || !isPermissionMenu(await readScreen(run, terminal.handle), found.menuHint)) return stale
    }
    if (found.kind === 'proposal' && found.agent === 'codex' && !(await readScreen(run, terminal.handle)).includes(CODEX_EMPTY_HINT)) {
      return { sent: false, reason: 'typing' }
    }
    // Checked again here, right before the send: a second press may have arrived during the reads.
    if (used.has(offer)) return stale
    take(offer)
    try {
      if (keys) await answerForm(terminal.handle, keys)
      else if (suggestion.action) await press(terminal.handle, suggestion.action === 'allow' ? ALLOW_ONCE_KEY : ESCAPE_KEY)
      else if (suggestion.keys) await press(terminal.handle, suggestion.keys)
      else await sendPrompt(found, terminal.handle, suggestion.prompt)
    } catch (error) {
      // A form stopped halfway has options ticked, so pressing the same keys again would untick them.
      if (!keys) used.delete(offer)
      throw error
    }
    return { sent: true }
  }
}
