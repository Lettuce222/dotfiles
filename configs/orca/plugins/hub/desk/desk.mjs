// The desk: one page that lists the items and the old cases and writes back through the Hub worker's API.
// No library. Every piece of text from the API is escaped before it goes into HTML, and the Markdown
// body goes through renderMarkdown, which escapes its own input.
import { renderMarkdown } from './markdown.mjs'
import { TAB_KEYS, deskKey, keyHints } from './keys.mjs'
import { boxOrder, filterRows, nextBox, shownRows, stepRow } from './sections.mjs'
import { PERMISSION_ORDER, alertHtml, askChips, askDetail, askTitle, askTitleHtml, timeLeft, waits } from './asks.mjs'

// ---------------------------------------------------------------- token and small helpers
// Orca opens the desk with its token in the address (?t=). The page keeps it in localStorage and
// takes it out of the address, which Orca shows and remembers: Orca loads that address again, with
// no token, when it shows the tab anew (in a new webview, so sessionStorage would be gone). The
// token changes at each start of the Hub worker; then opening the desk again from Orca brings the
// new one.
const TOKEN_KEY = 'desk-token'
const STALE = '鍵が古くなりました。Orca のステータスバーの「デスク」を押して開き直してください'
const storage = (() => { try { return window.localStorage } catch { return null } })()
{
  const q = new URLSearchParams(location.search)
  const fromUrl = q.get('t')
  if (fromUrl) {
    storage?.setItem(TOKEN_KEY, fromUrl)
    q.delete('t')
    const rest = q.toString()
    history.replaceState(null, '', location.pathname + (rest ? `?${rest}` : '') + location.hash)
  }
}
const token = () => storage?.getItem(TOKEN_KEY) ?? ''

const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
const $ = (id) => document.getElementById(id)
const mmdd = (d) => String(d).slice(5).replace('-', '/')
const safeUrl = (u) => (/^https?:\/\//i.test(String(u)) ? String(u) : null)

async function api(path, body) {
  const init = { headers: { 'X-Desk-Token': token() } }
  if (body) { init.method = 'POST'; init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body) }
  const res = await fetch(path, init)
  let json = null
  try { json = await res.json() } catch { json = null }
  return { status: res.status, ok: res.ok && json?.ok !== false, json: json ?? {} }
}

// ---------------------------------------------------------------- state
const LISTS = [['mine', 'あなたの番', 'y'], ['inbox', 'inbox', 'i'], ['next', '次の行動', 'n'], ['project', 'プロジェクト', 'p'],
  ['waiting', '連絡待ち', 'w'], ['someday', 'いつか／たぶん', 's'], ['reference', '資料', 'r']]
const HINTS = { mine: '承認・要判断・確かめてほしいもの', inbox: '1 件ずつ何をするか決めて移す（f）', next: '自分とエージェント。プロジェクトの「次」もここに出る',
  project: '要る行動を順に。次の行動に出ているものに印', waiting: '相手・渡した日・確かめる日', someday: '今はやらない', reference: '資料と成果物' }
const MINE_LABEL = { handback: 'あなたに戻った', ask: '問いがある', agent_done: '完了・確かめて', follow_up: '確かめる日が来た', due: '締め切り', conflict: 'ぶつかり' }
const AGENT_STATE = { working: ['c-run', '動いている'], attention: ['c-ask', 'あなた待ち'], idle: ['c-me', '待機'], done: ['c-done', '完了・確かめて'] }
const MOVE_TO = [['inbox', 'inbox', 'i'], ['next', '次の行動', 'n'], ['planned', 'プロジェクトのステップ（まだ）', 't'], ['waiting', '連絡待ち', 'w'], ['someday', 'いつか／たぶん', 's'], ['reference', '資料', 'r']]
const CASE_TO = [['inbox', 'inbox', 'i'], ['next', '次の行動', 'n'], ['step', 'ステップ', 't'], ['waiting', '連絡待ち', 'w'], ['someday', 'いつか', 's'], ['reference', '資料', 'r'], ['gcal', 'Google Calendar に入れる', 'c'], ['drop', '移さない', '-']]

let S = { today: '', rev: 0, counts: {}, migrate: { done: 0, total: 0 }, agents: {}, orchestrator: [], items: [], cases: [] }
let byId = {}
// The desk is one screen: every list is a section of the left column, one under the other, and
// the right column shows the selected item, or the migration. `cur` is the section of the selected
// row (an item of あなたの番 is in its own list too, so the same item can be two rows).
let cur = 'mine'
let sel = null
let pane = 'list'
let migKey = null // `${slug}|${section}|${index}`
let lastIdx = 0
let menuFor = null // the item id the move menu is open for

function parseHash() {
  const p = new URLSearchParams(location.hash.slice(1))
  pane = p.get('pane') === 'migrate' ? 'migrate' : 'list'
  const l = p.get('list')
  if (l && LISTS.some(([k]) => k === l)) cur = l
  sel = p.get('item') || null
}
function writeHash() {
  const p = new URLSearchParams()
  if (pane === 'migrate') p.set('pane', 'migrate')
  p.set('list', cur)
  if (sel) p.set('item', sel)
  const next = `#${p}`
  if (location.hash !== next) history.replaceState(null, '', location.pathname + location.search + next)
}

// ---------------------------------------------------------------- derived lists
const isMine = (t) => t.mine != null
const isAgent = (t) => t.actor === 'agent' || Boolean(t.worker)
// The orchestrator's cards (src/desk-asks.mjs) are the first rows of あなたの番.
const askRows = () => (S.orchestrator ?? []).map((card) => ({ id: `ask-${card.id}`, title: askTitle(card), card }))
function inList(name) {
  if (name === 'mine') return [...askRows(), ...S.items.filter(isMine)]
  return S.items.filter((t) => t.list === name)
}
function ordered(name) {
  const rows = inList(name)
  if (name !== 'next') return rows
  return [...rows.filter((t) => !isAgent(t) || t.actor === 'me'), ...rows.filter((t) => isAgent(t) && t.actor !== 'me')]
}
// The boxes of the left column, as in lazygit (desk/sections.mjs): `cur` is the box worked in (a
// list, or 'migrate'), and each box keeps the row selected in it and its filter (/).
const BOXES = boxOrder(LISTS)
const selByBox = {}
const filters = {}
let filtering = false
let helpOpen = false
const boxRows = (name) => filterRows(ordered(name), filters[name], (t) => t.title ?? '')
const projShort = (id) => (id ? (byId[id]?.short ?? id) : '')

function dueChip(d) {
  if (!d) return ''
  const days = (Date.parse(d) - Date.parse(S.today)) / 864e5
  const cls = days < 0 ? 'c-due' : days <= 2 ? 'c-soon' : 'c-me'
  return `<span class="chip ${cls}">${esc(mmdd(d))}</span>`
}
function actorChips(t, sec = cur) {
  const out = []
  if (t.mine && sec === 'mine') out.push(`<span class="chip c-ask">${esc(MINE_LABEL[t.mine] ?? t.mine)}</span>`)
  if (t.asks?.length && !(t.mine && sec === 'mine')) out.push('<span class="chip c-ask">要判断</span>')
  if (isAgent(t)) {
    out.push('<span class="chip c-agent">agent</span>')
    const st = AGENT_STATE[t.agent?.state]
    if (st) out.push(`<span class="chip ${st[0]}">${st[1]}</span>`)
  } else if (t.actor === 'me') out.push('<span class="chip c-me">me</span>')
  if (/^Google Calendar に入れる/.test(t.title ?? '')) out.push('<span class="chip c-gcal">Google Calendar</span>')
  return out.join(' ')
}
function bar(t) {
  const a = t.agent
  if (!a || !a.total) return ''
  return `<span class="bar"><i style="width:${Math.round((a.done / a.total) * 100)}%"></i></span> ${a.done}/${a.total}`
}
function stepState(s) {
  if (!s) return ['', '']
  if (s.list === 'done') return ['s-done', '済']
  if (s.list === 'planned') return ['', 'まだ']
  if (s.list === 'waiting') return ['', '<span class="chip c-me">待ち</span>']
  if (s.mine) return ['s-next', '<span class="chip c-ask">あなたの番</span>']
  return ['s-next', '<span class="chip c-run">次の行動</span>']
}
function stepsHtml(t, style = '') {
  return `<ol class="steps" ${style}>${(t.steps ?? []).map((id, i) => {
    const s = byId[id]
    const [cls, mark] = stepState(s)
    return `<li><span class="n">${i + 1}</span><span class="${cls}">${esc(s?.title ?? id)}</span><span class="mark">${mark}</span>${s && isAgent(s) ? '<span class="chip c-agent">agent</span>' : ''}</li>`
  }).join('')}</ol>`
}

// ---------------------------------------------------------------- render: chrome and list
function renderNav() {
  const a = S.agents ?? {}
  $('agents').textContent = `エージェント: 動いている ${a.working ?? 0}・完了 ${a.done ?? 0}・あなた待ち ${a.attention ?? 0}`
}

// The selected row of the box worked in is drawn reversed; the one of another box only marked.
function rowClass(t, sec) {
  if (t.id === sel && sec === cur && pane === 'list') return 'sel'
  return t.id === selByBox[sec] ? 'picked' : ''
}

function askRowHtml(t, sec) {
  const on = rowClass(t, sec)
  return `<div class="row ask-row ${on} ${waits(t.card) ? 'waits' : ''}" data-id="${esc(t.id)}" data-sec="${sec}"><span class="check"></span>
    <div><div class="title">${askTitleHtml(t.card)}</div></div>
    <div class="chips">${askChips(t.card, Date.now())}</div></div>`
}

function rowHtml(t, sec) {
  if (t.card) return askRowHtml(t, sec)
  const meta = []
  if (t.list === 'waiting') {
    meta.push(`相手: ${esc(t.who ?? '')}`, `渡した日: ${esc(mmdd(t.since ?? ''))}`)
    if (t.follow_up) meta.push(`確かめる日: ${esc(mmdd(t.follow_up))}${t.follow_up < S.today ? ' <span class="chip c-due">過ぎた</span>' : ''}`)
  }
  if (t.list === 'inbox' && t.source) meta.push(`入れた: ${esc(t.source)}`)
  if (t.worker) meta.push(`<code>${esc(t.worker)}</code> ${bar(t)}${t.agent?.inOrca ? ' <span class="goto">↘ 切り替え</span>' : ''}`)
  if (t.project && t.list !== 'project') meta.push(`<span class="chip c-proj">${esc(projShort(t.project))}</span>`)
  if (t.list === 'project' && t.outcome) meta.push(`望む結果: ${esc(t.outcome)}`)
  const on = rowClass(t, sec)
  return `<div class="row ${on}" data-id="${esc(t.id)}" data-sec="${sec}"><span class="check"></span>
    <div><div class="title">${esc(t.title)}</div>${meta.length ? `<div class="meta">${meta.map((m) => `<span>${m}</span>`).join('')}</div>` : ''}${t.list === 'project' ? stepsHtml(t) : ''}</div>
    <div class="chips">${actorChips(t, sec)} ${dueChip(t.due)}</div></div>`
}

function groupHtml(label, rows, k) {
  return rows.length ? `<div class="group">${label}（${rows.length}）</div>${rows.map((t) => rowHtml(t, k)).join('')}` : ''
}

// A box: its name and count on the top line of its frame, and its rows; while another box is worked
// in, only its first rows.
function boxHtml(k, label, i) {
  const all = boxRows(k)
  const focused = k === cur && pane === 'list'
  const rows = shownRows(all, focused)
  const query = filters[k] ? ` <span class="filter-on">/${esc(filters[k])}</span>` : ''
  const legend = `<legend data-box="${k}">[${TAB_KEYS[i]}] ${label} (${all.length})${query}</legend>`
  let body
  if (!all.length) body = '<div class="empty-row">（なし）</div>'
  else if (k === 'mine' && rows.some((t) => t.card)) {
    body = `${groupHtml('窓口が待っている', rows.filter((t) => t.card), k)}${groupHtml('項目', rows.filter((t) => !t.card), k)}`
  } else if (k === 'next' && focused) {
    body = `${groupHtml('自分', rows.filter((t) => !isAgent(t) || t.actor === 'me'), k)}${groupHtml('エージェント', rows.filter((t) => isAgent(t) && t.actor !== 'me'), k)}`
  } else body = rows.map((t) => rowHtml(t, k)).join('')
  const more = all.length > rows.length ? `<div class="more">… ほか ${all.length - rows.length} 件（<kbd>${TAB_KEYS[i]}</kbd>）</div>` : ''
  const hint = focused && all.length ? `<div class="box-hint">${HINTS[k]}</div>` : ''
  return `<fieldset class="box ${focused ? 'focused' : ''}" data-sec="${k}">${legend}${hint}${body}${more}</fieldset>`
}

function renderItems() {
  const m = S.migrate ?? { done: 0, total: 0 }
  const migrate = `<fieldset class="box ${pane === 'migrate' ? 'focused' : ''}" data-sec="migrate"><legend data-box="migrate">[${TAB_KEYS[LISTS.length]}] 移し替え (${m.done}/${m.total})</legend><div class="box-hint">旧案件を 1 行ずつ。開くと右に出す</div></fieldset>`
  const el = $('items')
  el.innerHTML = LISTS.map(([k, label], i) => boxHtml(k, label, i)).join('') + migrate
  el.querySelectorAll('.row').forEach((r) => { r.onclick = () => choose(r.dataset.id, true, r.dataset.sec) })
  el.querySelectorAll('[data-box]').forEach((b) => { b.onclick = () => focusBox(b.dataset.box) })
  el.querySelector('.box.focused .row.sel')?.scrollIntoView({ block: 'nearest' })
}

/** The key line at the bottom: the keys of the box worked in (lazygit's status line). */
function renderKeys() {
  const t = byId[sel]
  const hints = keyHints({ pane, card: Boolean(t?.card) && pane === 'list', filtering })
  $('keys').innerHTML = hints.map(([key, what]) => `<span><kbd>${esc(key)}</kbd> ${esc(what)}</span>`).join('')
}

// ? : every key, in the middle of the screen.
function openHelp() {
  helpOpen = true
  const rows = [
    ['h / l、Tab / ⇧Tab', '左の箱を移る'], ['q w e r t y u', 'リストの箱へ'], ['i', '移し替え（右に出す。Esc で戻る）'],
    ['j / k', '箱の中を上下'], ['/', '箱の中を絞り込む（Enter で決める、Esc でやめる）'], ['Enter', '右の箱へ（返事、窓口の問いには書いて答える）'],
    ['⇧Enter', '返事の欄で改行'], ['Esc', '欄やメニューから抜ける'], ['a', 'inbox に足す'], ['s', 'Orca のエディタで開く'], ['d', '成果物を開く'],
    ['f', '移す（メニュー）'], ['x', '完了'], ['v', 'エージェントの画面に切り替え'], ['⇧Q 〜 ⇧R', '窓口の問い・worker の問いに答える（許可の確認は 許可・拒否・理由・ターミナル）'],
    ['g + y i n p w s r m', 'リストの頭文字で箱へ'], ['?', 'この一覧を閉じる']
  ]
  $('menu').innerHTML = `<div class="menu help"><h3>キー</h3><table>${rows.map(([k, w]) => `<tr><td><kbd>${esc(k)}</kbd></td><td>${esc(w)}</td></tr>`).join('')}</table><div class="note" style="margin:4px 6px 0"><kbd>Esc</kbd> か <kbd>?</kbd> で閉じる</div></div>`
  $('menu').classList.add('on')
}
function closeHelp() {
  helpOpen = false
  $('menu').classList.remove('on')
}

// / : narrow the rows of the box worked in, from the bottom line.
function openFilter() {
  if (pane !== 'list') return
  filtering = true
  const input = $('filter')
  input.value = filters[cur] ?? ''
  $('filterbar').hidden = false
  renderKeys()
  input.focus()
}
function closeFilter(keep) {
  filtering = false
  if (!keep) delete filters[cur]
  $('filterbar').hidden = true
  $('filter').blur()
  render()
}
$('filter').addEventListener('input', (e) => {
  const query = e.target.value.trim()
  if (query) filters[cur] = query
  else delete filters[cur]
  render()
})

// ---------------------------------------------------------------- render: detail
const FM_KEYS = ['id', 'list', 'project', 'actor', 'worker', 'due', 'since', 'done', 'who', 'follow_up', 'then', 'outcome', 'short', 'from', 'source']
function linkList(urls) {
  return urls.map((u) => {
    const ok = safeUrl(u)
    return ok ? `<a href="${esc(ok)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a>` : esc(u)
  }).join('<br>')
}
function fmRows(t) {
  const rows = FM_KEYS.filter((k) => t[k] != null && t[k] !== '').map((k) => `<tr><td>${k}</td><td>${esc(t[k])}</td></tr>`)
  if (t.watch?.length) rows.push(`<tr><td>watch</td><td>${linkList(t.watch)}</td></tr>`)
  if (t.links?.length) rows.push(`<tr><td>links</td><td>${linkList(t.links)}</td></tr>`)
  if (t.steps?.length) rows.push(`<tr><td>steps</td><td>${t.steps.map(esc).join('<br>')}</td></tr>`)
  return rows.join('')
}
const TASK_MARK = { completed: 'd', in_progress: 'r', pending: 'p' }

function askCard(a) {
  const opts = (a.options ?? []).map((o, i) => `<button class="opt ${a.recommended === i + 1 ? 'rec' : ''}" data-ask="${esc(a.id)}" data-choice="${i + 1}">${i < 4 ? `<kbd>⇧${TAB_KEYS[i].toUpperCase()}</kbd>` : ''}<span>${esc(o.label)}${a.recommended === i + 1 ? '（推奨）' : ''}<small>${esc(o.description ?? '')}</small></span></button>`).join('')
  return `<div class="card ask"><h3>${esc(a.kind === 'approval' ? '承認' : '要判断')}: ${esc(a.question)}</h3>${opts}<div class="note">押した答えは worker に「承認ではありません」付きで届く。</div></div>`
}

// The id of a dangerous permission pressed once: the second press allows it.
let armed = null

function renderAskDetail(d, card) {
  const typed = d.querySelector('[data-oa-text]')
  const keep = typed?.dataset.oaText === card.id ? { value: typed.value, focused: document.activeElement === typed } : null
  d.innerHTML = askDetail(card, { now: Date.now(), armed })
  d.querySelectorAll('[data-oa]').forEach((b) => { b.onclick = () => answerCard(card, card.kind === 'permission' ? b.dataset.choice : Number(b.dataset.choice)) })
  d.querySelectorAll('[data-oa-send]').forEach((b) => { b.onclick = () => sendWritten(card) })
  d.querySelectorAll('[data-oa-retry]').forEach((b) => { b.onclick = () => retrySignal(card, b) })
  d.querySelectorAll('[data-oa-copy]').forEach((b) => { b.onclick = () => copyLine(card) })
  const area = d.querySelector('[data-oa-text]')
  if (area && keep) {
    // A redraw while writing keeps what was written.
    area.value = keep.value
    if (keep.focused) area.focus()
  }
}

// The reply to an item, under its detail: a line of its body in 「あなたの番への返事」, and the
// orchestrator is told there is one. What is being written stays through a redraw.
function replyBox(t) {
  if (t.list === 'done') return ''
  return `<div class="reply written"><label class="note" for="reply-text">返事（本文の「あなたの番への返事」に足し、窓口に知らせます。<kbd>Enter</kbd> で送る、<kbd>⇧</kbd>+<kbd>Enter</kbd> で改行、<kbd>Esc</kbd> で抜ける）</label><textarea id="reply-text" data-reply="${esc(t.id)}" rows="3" placeholder="この項目への返事"></textarea><button class="btn" data-reply-send>送る</button></div>`
}
function keptReply(d) {
  const area = d.querySelector('[data-reply]')
  return area ? { id: area.dataset.reply, value: area.value, focused: document.activeElement === area } : null
}
function restoreReply(d, t, kept) {
  const area = d.querySelector('[data-reply]')
  if (!area || !kept || kept.id !== t.id) return
  area.value = kept.value
  if (kept.focused) area.focus()
}
async function sendReply(t) {
  const area = $('detail').querySelector('[data-reply]')
  const text = area?.value.trim()
  if (!text) { area?.focus(); return }
  if (area) area.disabled = true
  const j = await write('/api/reply', { id: t.id, text })
  const now = $('detail').querySelector('[data-reply]')
  if (now) now.disabled = false
  if (!j) return
  if (now) { now.value = ''; now.blur() }
  toast('返事を書いた。窓口に知らせます')
}

function renderDetail() {
  const d = $('detail')
  const t = byId[sel]
  if (!t) { d.innerHTML = '<p class="empty">項目を選んでください</p>'; return }
  if (t.card) { renderAskDetail(d, t.card); return }
  const kept = keptReply(d)
  let left = ''
  if (t.asks?.length) left += t.asks.map((a, i) => askCard(a)).join('')
  if (t.agent) {
    const a = t.agent
    const st = AGENT_STATE[a.state]
    left += `<div class="card"><h3>worker <code>${esc(a.name)}</code>・${st ? st[1] : 'セッション無し'}${a.total ? `（${a.done}/${a.total}）` : ''}</h3>
      ${a.tasks?.length ? `<ul class="wsteps">${a.tasks.map((s) => `<li class="${TASK_MARK[s.status] ?? 'p'}">${esc(s.subject)}</li>`).join('')}</ul>` : '<div class="note">進み具合はまだ無い</div>'}
      ${a.inOrca ? '' : '<div class="note">Orca のターミナルの外（claude --bg）なので、画面は切り替えられない。</div>'}</div>`
  }
  if (t.list === 'project') left += `<div class="card"><h3>ステップ（順に）</h3>${stepsHtml(t, 'style="margin-left:0"')}</div>`
  left += `<div class="box"><h4>本文</h4>${t.body?.trim() ? renderMarkdown(t.body) : '<span class="note">（空）</span>'}`
  if (t.deliverables?.length) {
    left += `<h4>成果物</h4><ul>${t.deliverables.map((p, i) => `<li><a class="link" data-deliv="${i}">${esc(p)}</a></li>`).join('')}</ul>`
  }
  left += '</div>'
  d.innerHTML = `<div class="head"><h2>${esc(t.title)}</h2></div>
    <div>${actorChips(t, cur)} ${dueChip(t.due)} <span class="chip c-proj">${esc(t.list)}</span>${t.project && t.list !== 'project' ? ` <span class="chip c-proj">${esc(projShort(t.project))}</span>` : ''}</div>
    <div class="actions"><button class="btn primary" data-act="open">Orca のエディタで開く <kbd>s</kbd></button>${t.deliverables?.length ? '<button class="btn" data-act="deliv">成果物を開く <kbd>d</kbd></button>' : ''}<button class="btn" data-act="move">移す <kbd>f</kbd></button><button class="btn" data-act="done">完了 <kbd>x</kbd></button></div>
    <div class="cols"><div>${left}</div><div style="margin-top:8px"><table class="fm">${fmRows(t)}</table>
    ${t.path ? `<p class="note">ファイル: <code class="path">${esc(t.path)}</code></p>` : ''}</div></div>${replyBox(t)}`
  restoreReply(d, t, kept)
  d.querySelectorAll('[data-reply-send]').forEach((b) => { b.onclick = () => sendReply(t) })
  d.querySelectorAll('[data-act]').forEach((b) => { b.onclick = () => act(b.dataset.act) })
  d.querySelectorAll('[data-deliv]').forEach((a) => { a.onclick = () => openItem(t.id, t.deliverables[Number(a.dataset.deliv)]) })
  d.querySelectorAll('[data-ask]').forEach((b) => { b.onclick = () => answer(b.dataset.ask, Number(b.dataset.choice)) })
}

// ---------------------------------------------------------------- render: migrate
function migLines() {
  const out = []
  for (const c of S.cases) for (const l of c.lines) out.push({ c, l, key: `${c.slug}|${l.section}|${l.index}` })
  return out
}
const lineDone = (l) => Boolean(l.moved) || Boolean(l.dropped)

function renderMigrate() {
  const lines = migLines()
  const total = lines.length
  const done = lines.filter((x) => lineDone(x.l)).length
  if (!lines.some((x) => x.key === migKey)) migKey = lines.find((x) => !lineDone(x.l))?.key ?? lines[0]?.key ?? null
  const html = S.cases.map((c) => {
    let last = null
    const rows = c.lines.map((l) => {
      const key = `${c.slug}|${l.section}|${l.index}`
      const head = l.section !== last ? `<div class="sec">${esc(l.section)}</div>` : ''
      last = l.section
      const right = l.dropped ? '<span class="movedto">移さない（捨てた）</span>'
        : l.moved ? `<span class="movedto">移した → <a class="link" data-open="${esc(l.moved)}">${esc(l.moved)}</a></span>`
          : `<div class="mbtns">${CASE_TO.map(([to, label, k]) => `<button class="mb" data-to="${to}"><kbd>${k}</kbd>${label}</button>`).join('')}</div>`
      return `${head}<div class="mline ${lineDone(l) ? 'moved' : ''} ${key === migKey ? 'sel' : ''}" data-key="${esc(key)}"><span class="txt">${esc(l.label ?? l.text)}</span>${right}</div>`
    }).join('')
    const left = c.lines.filter((l) => !lineDone(l)).length
    const proj = c.project ? `<span class="note">プロジェクト: <a class="link" data-open="${esc(c.project)}">${esc(c.project)}</a></span>` : `<button class="mb" data-proj="${esc(c.slug)}">プロジェクトにする</button>`
    return `<div class="case"><div class="ch"><b>${esc(c.title)}</b><span class="note">${esc(c.slug)}</span><span class="note" style="margin-left:auto">残り ${left} 行</span>${proj}</div>${rows}</div>`
  }).join('')
  const el = $('migrate')
  const top = el.scrollTop
  el.innerHTML = `<div class="head"><h2>移し替え</h2><span class="hint">旧案件を 1 行ずつ。${total} 行のうち ${done} 行済み</span></div>
    <p class="note">押すと項目を作り、元の行に「移した → id」を書く。予定は「Google Calendar に入れる」次の行動になる。<kbd>j</kbd>/<kbd>k</kbd> で行、頭文字のキーで移す先。</p>${html || '<div class="empty">旧案件はありません</div>'}`
  el.scrollTop = top
  el.querySelector('.mline.sel')?.scrollIntoView({ block: 'nearest' })
  el.querySelectorAll('.mline').forEach((row) => {
    row.onclick = () => { migKey = row.dataset.key; renderMigrate() }
    row.querySelectorAll('[data-to]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); migKey = row.dataset.key; fromCase(row.dataset.key, b.dataset.to) } })
  })
  el.querySelectorAll('[data-open]').forEach((a) => { a.onclick = (e) => { e.stopPropagation(); openItem(a.dataset.open) } })
  el.querySelectorAll('[data-proj]').forEach((b) => { b.onclick = () => caseProject(b.dataset.proj) })
}

// ---------------------------------------------------------------- screens
/** The tab's title and the strip at the top: how many cards of the orchestrator wait on the user. */
function renderAlert() {
  const waiting = (S.orchestrator ?? []).filter(waits).length
  document.title = waiting ? `(${waiting}) デスク` : 'デスク'
  const el = $('alert')
  el.innerHTML = alertHtml(S.orchestrator ?? [], Date.now())
  el.hidden = !waiting
  el.querySelector('[data-alert]')?.addEventListener('click', () => showList('mine'))
}
// The time left of a permission, every second, without drawing the rest again.
setInterval(() => {
  const now = Date.now()
  document.querySelectorAll('[data-expires]').forEach((el) => {
    el.textContent = `${el.dataset.prefix ?? ''}${timeLeft(Number(el.dataset.expires), now)}${el.dataset.suffix ?? ''}`
  })
}, 1000)

function render() {
  const migrating = pane === 'migrate'
  $('detail').classList.toggle('on', !migrating)
  $('migrate').classList.toggle('on', migrating)
  if (!migrating) {
    const rows = boxRows(cur)
    if (!rows.some((t) => t.id === sel)) {
      // Keep the place in the box when the selected item left it.
      sel = rows[Math.min(lastIdx, rows.length - 1)]?.id ?? null
    }
    lastIdx = Math.max(0, rows.findIndex((t) => t.id === sel))
    selByBox[cur] = sel
  }
  renderNav()
  renderAlert()
  renderItems()
  if (migrating) renderMigrate()
  else renderDetail()
  $('detail').dataset.title = byId[sel]?.card ? '窓口の問い' : '詳細'
  $('migrate').dataset.title = '移し替え'
  renderKeys()
  writeHash()
}
/** Works in a box: a list's box, with the row it had selected, or the migration. */
function focusBox(name) {
  if (name === 'migrate') { showMigrate(); return }
  if (cur !== name) {
    if (filtering) closeFilter(true)
    cur = name
    sel = selByBox[name] ?? null
    lastIdx = Math.max(0, boxRows(name).findIndex((t) => t.id === sel))
  }
  pane = 'list'
  render()
  document.querySelector(`#items [data-sec="${name}"]`)?.scrollIntoView({ block: 'nearest' })
}
/** A box's key (q〜u): work in it. */
function showList(name) { focusBox(name) }
function showMigrate() {
  if (filtering) closeFilter(true)
  pane = 'migrate'
  render()
}
/** Esc on the migration: back to the box before. */
function backToList() { pane = 'list'; render() }
/** h / l, Tab / Shift+Tab: the box above or below. */
function stepBox(delta) {
  focusBox(nextBox(BOXES, pane === 'migrate' ? 'migrate' : cur, delta))
}

// ---------------------------------------------------------------- toast
let toastTimer
function toast(html, ms = 3500) {
  const el = $('toast')
  el.innerHTML = html
  el.classList.add('on')
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => el.classList.remove('on'), ms)
}

// ---------------------------------------------------------------- actions
// fetch throws when nothing answers: the server of this page stopped (the Hub worker started again
// on another port, or Orca closed it). Only Orca can give the page the current address and token.
const UNREACHABLE = 'デスクのサーバーにつながらない。Orca のステータスバーの「デスク」から開き直してください'

async function load() {
  let r
  try { r = await api('/api/state') } catch { toast(UNREACHABLE, 1e9); return }
  if (r.status === 401 || r.status === 403) { toast(STALE, 1e9); return }
  if (!r.json || !Array.isArray(r.json.items)) { toast('state を読めなかった'); return }
  S = { ...S, ...r.json }
  byId = Object.fromEntries([...S.items, ...askRows()].map((t) => [t.id, t]))
  if (armed && !(S.orchestrator ?? []).some((card) => card.id === armed)) armed = null
  render()
}

// A write: toast the error and reload the state when it did not go through (409 is a clash).
async function write(path, body, { quiet = false } = {}) {
  let r
  try { r = await api(path, body) } catch { toast(`書き込めなかった。${UNREACHABLE}`, 1e9); return null }
  if (!r.ok) {
    toast(`${r.status === 409 ? 'ぶつかった: ' : ''}${esc(r.json.error ?? `失敗した（${r.status}）`)}`)
    await load()
    return null
  }
  if (!quiet) await load()
  return r.json
}

async function choose(id, fromClick, sec = cur) {
  if (sec !== cur && filtering) closeFilter(true)
  sel = id
  cur = sec
  pane = 'list'
  lastIdx = Math.max(0, boxRows(cur).findIndex((t) => t.id === id))
  render()
  const t = byId[id]
  if (fromClick && t && isAgent(t)) await focusWorker(t)
}
async function focusWorker(t) {
  let r
  try { r = await api('/api/focus', { id: t.id }) } catch { toast(UNREACHABLE, 1e9); return }
  if (!r.ok) { toast(esc(r.json.error ?? '切り替えに失敗した')); return }
  const w = esc(t.worker ?? t.agent?.name ?? '')
  if (r.json.focused) toast(`Orca のエージェントの画面を <b>${w}</b> に切り替えた`)
  else if (r.json.reason === 'not-in-orca') toast(`<b>${w}</b> は Orca のターミナルの外（claude --bg）なので切り替えられない。進み具合は右に出す`)
  else toast(`切り替えなかった${r.json.reason ? `（${esc(r.json.reason)}）` : ''}`)
}
// j and k go up and down in the box worked in.
function move(delta) {
  const rows = boxRows(cur)
  const next = stepRow(rows, sel, delta)
  if (!next) return
  sel = next.id
  lastIdx = rows.indexOf(next)
  render()
}
async function openItem(id, path) {
  let r
  try { r = await api('/api/open', path ? { id, path } : { id }) } catch { toast(UNREACHABLE, 1e9); return }
  if (!r.ok) toast(esc(r.json.error ?? '開けなかった'))
}
async function addInbox() {
  const input = $('add')
  const title = input.value.trim()
  if (!title) return
  const j = await write('/api/add', { title })
  if (j) { input.value = ''; toast(`inbox に入れた: ${esc(title)}`) }
}
async function answer(askId, choice) {
  const shown = S.items.flatMap((item) => item.asks ?? []).find((a) => a.id === askId)
  const j = await write('/api/answer', { askId, choice, sha: shown?.sha })
  if (j) toast('答えを worker に送った（承認ではない）')
}
// An answer to the orchestrator's card: an option's number, or for a permission allow, deny, a
// reason (written below) or the terminal. A dangerous allow is pressed twice.
async function answerCard(card, pick) {
  if (!card.ready || card.pressed !== null) return
  if (pick === 'reason') { $('detail').querySelector('[data-oa-text]')?.focus(); return }
  if (card.kind === 'permission') {
    if (!PERMISSION_ORDER.includes(pick)) return
    if (pick === 'allow' && !card.canAllow) { toast('外に出る操作は、デスクでは許可できない。窓口のターミナルで確かめてください'); return }
    if (pick === 'allow' && card.dangerous && armed !== card.id) {
      armed = card.id
      renderDetail()
      toast('危険なコマンドです。もう一度押すと許可します')
      return
    }
  } else if (!Number.isInteger(pick) || pick < 1 || pick > card.options.length) return
  const confirmed = pick === 'allow' && card.dangerous
  armed = null
  const j = await write('/api/answer', { askId: card.id, sha: card.sha, choice: pick, ...(confirmed ? { confirmed: true } : {}) })
  if (j) toast(j.kept ? esc(j.message ?? '答えは残しました') : '窓口に返した')
}
// A kept answer: tell the orchestrator now, or copy the line to paste into its terminal.
async function retrySignal(card, button) {
  button.disabled = true
  toast('窓口に知らせています…（窓口が応答中なら、終わるまで待ちます）', 1e9)
  const j = await write('/api/resignal', { askId: card.id })
  if (j) toast('窓口に知らせた')
  button.disabled = false
}
async function copyLine(card) {
  try {
    await navigator.clipboard.writeText(card.line)
    toast('コピーした。窓口のターミナルに貼って Enter を押してください')
  } catch {
    // Without the clipboard API: select the line, for Cmd+C.
    const pre = $('detail').querySelector('[data-oa-line]')
    if (pre) window.getSelection()?.selectAllChildren(pre)
    toast('コピーできなかった。選んだ 1 行を ⌘+C でコピーしてください')
  }
}
async function sendWritten(card) {
  const area = $('detail').querySelector('[data-oa-text]')
  const text = area?.value.trim()
  if (!text) { area?.focus(); return }
  const j = await write('/api/answer', { askId: card.id, sha: card.sha, text })
  if (!j) return
  if (area) area.value = ''
  toast(j.kept ? esc(j.message ?? '答えは残しました') : card.kind === 'permission' ? '理由を添えて拒否した' : '書いた答えを窓口に返した')
}

function act(name) {
  const t = byId[sel]
  if (!t) return
  if (t.card) { toast('窓口の問いには、<kbd>⇧Q</kbd>〜<kbd>⇧R</kbd> か <kbd>Enter</kbd>（書いて答える）を使ってください'); return }
  if (name === 'open') openItem(t.id)
  else if (name === 'deliv') { if (t.deliverables?.length) openItem(t.id, t.deliverables[0]); else toast('成果物はまだ無い') }
  else if (name === 'move') openMenu(t)
  else if (name === 'done') doneItem(t)
}
async function doneItem(t) {
  const j = await write('/api/done', { id: t.id, hash: t.hash })
  if (!j) return
  const n = j.promoted?.length ?? 0
  toast(n ? `完了。次のステップを次の行動にした（${n} 件）` : '完了にした')
}
async function moveItem(t, list) {
  const j = await write('/api/move', { id: t.id, list, hash: t.hash })
  if (j) toast(`${esc(MOVE_TO.find(([k]) => k === list)?.[1] ?? list)} に移した`)
}

// the move menu
function openMenu(t) {
  menuFor = t.id
  $('menu').innerHTML = `<div class="menu"><h3>移す先: ${esc(t.title)}</h3>${MOVE_TO.map(([k, label, key]) => `<button data-to="${k}"><kbd>${key}</kbd>${label}</button>`).join('')}<div class="note" style="margin:4px 6px 0"><kbd>Esc</kbd> で閉じる</div></div>`
  $('menu').classList.add('on')
  $('menu').querySelectorAll('[data-to]').forEach((b) => { b.onclick = () => chooseMenu(b.dataset.to) })
}
function closeMenu() { menuFor = null; $('menu').classList.remove('on') }
function chooseMenu(list) {
  const t = byId[menuFor]
  closeMenu()
  if (t) moveItem(t, list)
}
$('menu').addEventListener('click', (e) => { if (e.target === $('menu')) { if (helpOpen) closeHelp(); else closeMenu() } })

// migrate
// Lines being moved: a key held down or pressed twice must not move one line twice.
const moving = new Set()

async function fromCase(key, to) {
  const x = migLines().find((m) => m.key === key)
  if (!x || lineDone(x.l) || moving.has(key)) return
  moving.add(key)
  try {
    await fromCaseOnce(key, to, x)
  } finally {
    moving.delete(key)
  }
}

async function fromCaseOnce(key, to, x) {
  if (to === 'step' && !x.c.project) { toast('先にプロジェクトにする（案件の見出しの「プロジェクトにする」）'); return }
  const body = { slug: x.c.slug, section: x.l.section, index: x.l.index, text: x.l.text, to }
  if (to === 'step') body.project = x.c.project
  const j = await write('/api/from-case', body)
  if (!j) return
  toast(to === 'drop' ? '移さないことにした' : `移した → ${esc(j.id ?? '')}`)
  // go to the next line that is not yet moved
  const lines = migLines()
  const i = lines.findIndex((m) => m.key === key)
  migKey = (lines.slice(i + 1).find((m) => !lineDone(m.l)) ?? lines[i])?.key ?? migKey
  if (pane === 'migrate') renderMigrate()
}
async function caseProject(slug) {
  const j = await write('/api/case-project', { slug })
  if (j) toast(`プロジェクトにした: ${esc(j.id ?? '')}`)
}
function migMove(delta) {
  const lines = migLines()
  if (!lines.length) return
  const i = Math.max(0, lines.findIndex((m) => m.key === migKey))
  migKey = lines[Math.max(0, Math.min(lines.length - 1, i + delta))].key
  renderMigrate()
}

// ---------------------------------------------------------------- keys
let gPending = false
document.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  if (e.target.id === 'filter') {
    if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); closeFilter(true) } else if (e.key === 'Escape') closeFilter(false)
    return
  }
  if (e.target.tagName === 'INPUT') {
    if (e.key === 'Enter') { e.preventDefault(); addInbox() } else if (e.key === 'Escape') e.target.blur()
    return
  }
  if (helpOpen) {
    e.preventDefault()
    if (e.key === 'Escape' || e.key === '?') closeHelp()
    return
  }
  if (e.target.tagName === 'TEXTAREA') {
    if (e.key === 'Escape') e.target.blur()
    return
  }
  const t = byId[sel]
  const hit = deskKey(e, { pane: pane === 'migrate' ? 'migrate' : 'list', gPending, menuOpen: Boolean(menuFor), hasItem: Boolean(t), lists: LISTS, moveTo: MOVE_TO, caseTo: CASE_TO })
  gPending = false
  if (menuFor) e.preventDefault()
  if (!hit) return
  switch (hit.do) {
    case 'close': return closeMenu()
    case 'menu': return chooseMenu(hit.to)
    case 'g': gPending = true; return
    case 'help': e.preventDefault(); openHelp(); return
    case 'filter': e.preventDefault(); openFilter(); return
    case 'box': e.preventDefault(); stepBox(hit.delta); return
    case 'add': e.preventDefault(); $('add').focus(); return
    case 'list': return showList(hit.list)
    case 'migrate': return showMigrate()
    case 'back': return backToList()
    case 'migMove': return migMove(hit.delta)
    case 'fromCase': if (migKey) fromCase(migKey, hit.to); return
    case 'move': return move(hit.delta)
    case 'write':
      // Enter: into the box under the item, the reply or the written answer to the orchestrator.
      e.preventDefault()
      $('detail').querySelector(t.card ? '[data-oa-text]' : '[data-reply]')?.focus()
      return
    case 'agent':
      if (!t.card && isAgent(t)) focusWorker(t)
      return
    case 'act': return act(hit.act)
    case 'answer': {
      e.preventDefault()
      if (t.card) { answerCard(t.card, t.card.kind === 'permission' ? PERMISSION_ORDER[hit.choice - 1] : hit.choice); return }
      const a = t.asks?.[0]
      if (a?.options?.[hit.choice - 1]) answer(a.id, hit.choice)
      return
    }
  }
})

// In the reply box and the written answer: Enter sends, Shift+Enter starts a new line. Not while
// a Japanese word is being converted (isComposing, keyCode 229), and not when the box is empty.
document.addEventListener('keydown', (e) => {
  const box = e.target
  if (box.tagName !== 'TEXTAREA' || !(box.dataset.oaText || box.dataset.reply) || e.key !== 'Enter') return
  if (e.isComposing || e.keyCode === 229 || e.shiftKey || e.altKey) return
  e.preventDefault()
  if (!box.value.trim()) return
  if (box.dataset.reply) {
    const t = byId[box.dataset.reply]
    if (t) sendReply(t)
    return
  }
  const card = (S.orchestrator ?? []).find((c) => c.id === box.dataset.oaText)
  if (card) sendWritten(card)
})
window.addEventListener('hashchange', () => {
  parseHash()
  render()
})

// ---------------------------------------------------------------- live updates
let events = null
function connect() {
  events?.close()
  events = new EventSource(`/api/events?t=${encodeURIComponent(token())}`)
  events.addEventListener('change', () => { load() })
  events.onerror = () => { events.close(); setTimeout(connect, 5000) }
}

parseHash()
await load()
connect()
