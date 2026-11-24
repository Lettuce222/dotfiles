// The orchestrator's cards on the desk page: its questions (with --approval or not), its permission
// dialogs and answers not yet told to it (src/desk-asks.mjs makes the data). Every text is escaped,
// Markdown goes through renderMarkdown, and characters that do not show are shown by their code
// point, as on the panel, so nothing in what the user answers is hidden.
import { escapeHtml as esc, plainText, renderMarkdown, reveal } from './markdown.mjs'

/** The answer keys with Shift, by position: Q W E R. A permission's are allow, deny, a reason, the terminal. */
export const ANSWER_KEYS = ['Q', 'W', 'E', 'R']
export const PERMISSION_ORDER = ['allow', 'deny', 'reason', 'terminal']

const visible = (value) => reveal(esc(value ?? ''))
const visibleMarkdown = (value) => reveal(renderMarkdown(String(value ?? '')))

/** m:ss left before a permission goes back to the terminal's dialog. */
export function timeLeft(expiresAt, now) {
  const s = Math.max(0, Math.floor((expiresAt - now) / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** Whether a card waits on the user: not answered yet, and not only waiting to be told. */
export const waits = (card) => card.kind !== 'kept' && card.pressed === null

/** One line for the card's row in あなたの番. */
export function askTitle(card) {
  if (card.kind === 'permission') {
    const command = typeof card.input?.command === 'string' ? card.input.command : typeof card.input?.file_path === 'string' ? card.input.file_path : ''
    return `許可の確認: ${card.toolName}${command ? ` ${command.split('\n')[0]}` : ''}`
  }
  return plainText(String(card.question ?? '').split('\n').find((line) => line.trim()) ?? '')
}

/** The row's title as HTML: escaped, with the characters that do not show made visible. */
export const askTitleHtml = (card) => visible(askTitle(card))

/** The chips of the card's row. */
export function askChips(card, now) {
  const out = []
  if (card.kind === 'permission') {
    out.push('<span class="chip c-ask">許可の確認</span>')
    if (card.riskLabel) out.push(`<span class="chip ${card.dangerous || card.risk === 'outside' ? 'c-due' : 'c-me'}">${esc(card.riskLabel)}</span>`)
    if (waits(card)) out.push(`<span class="chip c-due" data-expires="${Number(card.expiresAt)}" data-prefix="残り ">残り ${timeLeft(card.expiresAt, now)}</span>`)
  } else if (card.kind === 'question') {
    out.push(`<span class="chip c-ask">${card.approval ? '承認の問い' : '窓口の問い'}</span>`)
  } else {
    out.push('<span class="chip c-me">知らせ待ち</span>')
  }
  if (card.pressed !== null && card.pressed !== undefined && card.kind !== 'kept') out.push('<span class="chip c-run">送っています</span>')
  return out.join(' ')
}

function callBlock(label, value) {
  if (typeof value !== 'string' || value === '') return ''
  return `<p class="note">${esc(label)}</p><pre class="preview">${visible(value)}</pre>`
}

function permissionBody(card) {
  const input = card.input ?? {}
  if (card.toolName === 'Bash' && typeof input.command === 'string') {
    const description = typeof input.description === 'string' && input.description.trim() ? `<p>${visible(input.description)}</p>` : ''
    const rest = Object.fromEntries(Object.entries(input).filter(([name]) => !['command', 'description'].includes(name)))
    return `${description}${callBlock('コマンド', input.command)}${Object.keys(rest).length ? callBlock('ほかの引数', JSON.stringify(rest, null, 2)) : ''}`
  }
  if (typeof input.file_path === 'string' && ['Write', 'Edit', 'MultiEdit', 'NotebookEdit'].includes(card.toolName)) {
    const rest = Object.fromEntries(Object.entries(input).filter(([name]) => !['file_path', 'content', 'old_string', 'new_string'].includes(name)))
    return `${callBlock('ファイル', input.file_path)}${callBlock('書く中身', input.content)}${callBlock('置き換える前', input.old_string)}${callBlock('置き換えたあと', input.new_string)}${Object.keys(rest).length ? callBlock('ほかの引数', JSON.stringify(rest, null, 2)) : ''}`
  }
  return callBlock('引数', JSON.stringify(input, null, 2))
}

function button(card, choice, index, label, detail, extra = '') {
  const key = ANSWER_KEYS[index] ? `<kbd>⇧${ANSWER_KEYS[index]}</kbd>` : ''
  return `<button class="opt ${extra}" data-oa="${esc(card.id)}" data-choice="${esc(choice)}">${key}<span>${label}<small>${detail}</small></span></button>`
}

const written = (card, label, hint) =>
  `<div class="written"><label class="note" for="oa-text">${esc(label)}（<kbd>Enter</kbd> で書く欄へ、<kbd>⌘</kbd>+<kbd>Enter</kbd> で送る）</label><textarea id="oa-text" data-oa-text="${esc(card.id)}" rows="3" placeholder="${esc(hint)}"></textarea><button class="btn" data-oa-send="${esc(card.id)}">送る</button></div>`

/**
 * The card in the right column.
 * @param at { now, armed } armed: the id of a dangerous permission pressed once
 */
export function askDetail(card, { now, armed = null }) {
  if (card.kind === 'kept') {
    const line = card.line
      ? `<p class="note">届かないあいだは、次の 1 行を窓口のターミナルに貼って送っても同じです。</p><pre class="preview" data-oa-line>${visible(card.line)}</pre><div class="actions"><button class="btn primary" data-oa-retry="${esc(card.id)}">いま試し直す</button><button class="btn" data-oa-copy="${esc(card.id)}">窓口に貼る 1 行をコピー</button></div>`
      : ''
    return `<div class="head"><h2>窓口の問い</h2></div><div class="card ask"><h3>答えは残してあります</h3>${visibleMarkdown(card.question)}<p><b>${visible(card.label)}</b></p><p class="note">${esc(card.note)}</p>${line}</div>`
  }
  const sending = card.pressed !== null && card.pressed !== undefined
  const status = sending ? `<p class="status">「${visible(card.pressed)}」を窓口に返しています…</p>` : ''
  const failure = card.failure ? `<p class="status bad">${esc(card.failure)}</p>` : ''
  const note = card.ready ? '' : `<p class="note">${esc(card.note ?? '')}</p>`
  if (card.kind === 'permission') {
    const agent = card.agentType ? `（サブエージェント ${visible(card.agentType)}）` : ''
    const risk = card.riskLabel ? ` <span class="chip ${card.dangerous || card.risk === 'outside' ? 'c-due' : 'c-me'}">${esc(card.riskLabel)}</span>` : ''
    const where = card.where ? `<p class="note">場所: ${visible(card.where)}</p>` : ''
    const after = '。過ぎると、窓口のターミナルに確認ダイアログが出ます。'
    const left = `<p class="deadline" data-expires="${Number(card.expiresAt)}" data-prefix="残り " data-suffix="${after}">残り ${timeLeft(card.expiresAt, now)}${after}</p>`
    let actions = ''
    if (card.ready && !sending) {
      const allow = card.canAllow
        ? button(card, 'allow', 0, armed === card.id ? 'もう一度押すと許可（今回だけ）' : '許可（今回だけ）', card.dangerous ? '危険なコマンドです。2 回押すと許可します' : 'この 1 回だけ実行します。許可のルールは足しません', armed === card.id ? 'armed' : '')
        : '<p class="note">外に出る操作です。許可は、窓口のターミナルの確認で中身を全部読んでから押してください。</p>'
      actions = `${allow}${button(card, 'deny', 1, '拒否', '実行しません。窓口の Claude には、拒否されたと返します')}${button(card, 'reason', 2, '理由を書いて拒否', '下の欄に理由を書いて送ります')}${button(card, 'terminal', 3, 'ターミナルで確かめる', '待たずに、窓口のターミナルに確認ダイアログを出します')}${written(card, '拒否する理由', '拒否する理由')}`
    }
    return `<div class="head"><h2>許可の確認${risk}</h2></div><div class="card ask"><h3>窓口の ${visible(card.toolName)}${agent} を実行してよいですか</h3>${permissionBody(card)}${where}${left}${note}${actions}${status}${failure}</div>`
  }
  const badge = card.approval ? '<span class="chip c-ask">承認の問い</span> ' : ''
  const body = card.body ? `<div class="box">${visibleMarkdown(card.body)}</div>` : ''
  let actions = ''
  if (card.ready && !sending) {
    const options = card.options.map((option, i) => button(card, String(i + 1), i, `${visible(option.label)}${card.recommended === i + 1 ? '（推奨）' : ''}`, option.description ? visibleMarkdown(option.description) : '', card.recommended === i + 1 ? 'rec' : '')).join('')
    actions = `${options}${written(card, 'ほかの答え（Other）', '選択肢に無い答えや補足を、そのまま窓口に渡します')}`
  }
  return `<div class="head"><h2>${badge}窓口の問い</h2></div><div class="card ask"><div class="q">${visibleMarkdown(card.question)}</div>${body}${note}${actions}${status}${failure}</div>`
}

/** The strip at the top of the desk while the orchestrator waits on the user, or ''. */
export function alertHtml(cards, now) {
  const waiting = cards.filter(waits)
  if (!waiting.length) return ''
  const permissions = waiting.filter((card) => card.kind === 'permission')
  const questions = waiting.length - permissions.length
  const soonest = permissions.reduce((min, card) => Math.min(min, card.expiresAt), Infinity)
  const parts = []
  if (permissions.length) parts.push(`許可の確認 ${permissions.length}（残り <span data-expires="${soonest}">${timeLeft(soonest, now)}</span>）`)
  if (questions) parts.push(`問い ${questions}`)
  return `<button class="alert-go" data-alert>窓口が答えを待っています: ${parts.join('・')}　<kbd>q</kbd> で見る</button>`
}
