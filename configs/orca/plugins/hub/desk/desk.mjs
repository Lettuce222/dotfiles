// The desk: one page that lists the items and the old cases and writes back through the Hub worker's API.
// No library. Every piece of text from the API is escaped before it goes into HTML, and the Markdown
// body goes through renderMarkdown, which escapes its own input.
import { renderMarkdown } from './markdown.mjs'

// ---------------------------------------------------------------- token and small helpers
const TOKEN_KEY = 'desk-token'
{
  const q = new URLSearchParams(location.search)
  const fromUrl = q.get('t')
  if (fromUrl) {
    sessionStorage.setItem(TOKEN_KEY, fromUrl)
    q.delete('t')
    const rest = q.toString()
    history.replaceState(null, '', location.pathname + (rest ? `?${rest}` : '') + location.hash)
  }
}
const token = () => sessionStorage.getItem(TOKEN_KEY) ?? ''

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
const HINTS = { mine: '承認・要判断・確かめてほしいもの', inbox: '1 件ずつ何をするか決めて移す（m）', next: '自分とエージェント。プロジェクトの「次」もここに出る',
  project: '要る行動を順に。次の行動に出ているものに印', waiting: '相手・渡した日・確かめる日', someday: '今はやらない', reference: '資料と成果物' }
const MINE_LABEL = { handback: 'あなたに戻った', ask: '問いがある', agent_done: '完了・確かめて', follow_up: '確かめる日が来た', due: '締め切り', conflict: 'ぶつかり' }
const AGENT_STATE = { working: ['c-run', '動いている'], attention: ['c-ask', 'あなた待ち'], idle: ['c-me', '待機'], done: ['c-done', '完了・確かめて'] }
const MOVE_TO = [['inbox', 'inbox', 'i'], ['next', '次の行動', 'n'], ['planned', 'プロジェクトのステップ（まだ）', 't'], ['waiting', '連絡待ち', 'w'], ['someday', 'いつか／たぶん', 's'], ['reference', '資料', 'r']]
const CASE_TO = [['inbox', 'inbox', 'i'], ['next', '次の行動', 'n'], ['step', 'ステップ', 't'], ['waiting', '連絡待ち', 'w'], ['someday', 'いつか', 's'], ['reference', '資料', 'r'], ['gcal', 'Google Calendar に入れる', 'c'], ['drop', '移さない', '-']]

let S = { today: '', rev: 0, counts: {}, migrate: { done: 0, total: 0 }, agents: {}, items: [], cases: [] }
let byId = {}
let cur = 'mine'
let sel = null
let pane = 'list'
let migKey = null // `${slug}|${section}|${index}`
let lastIdx = 0
let menuFor = null // the item id the move menu is open for

function parseHash() {
  const p = new URLSearchParams(location.hash.slice(1))
  if (p.get('pane') === 'migrate') { pane = 'migrate'; return }
  pane = 'list'
  const l = p.get('list')
  if (l && LISTS.some(([k]) => k === l)) cur = l
  sel = p.get('item') || null
}
function writeHash() {
  const p = new URLSearchParams()
  if (pane === 'migrate') p.set('pane', 'migrate')
  else { p.set('list', cur); if (sel) p.set('item', sel) }
  const next = `#${p}`
  if (location.hash !== next) history.replaceState(null, '', location.pathname + location.search + next)
}

// ---------------------------------------------------------------- derived lists
const isMine = (t) => t.mine != null
const isAgent = (t) => t.actor === 'agent' || Boolean(t.worker)
function inList(name) {
  if (name === 'mine') return S.items.filter(isMine)
  return S.items.filter((t) => t.list === name)
}
function ordered(name) {
  const rows = inList(name)
  if (name !== 'next') return rows
  return [...rows.filter((t) => !isAgent(t) || t.actor === 'me'), ...rows.filter((t) => isAgent(t) && t.actor !== 'me')]
}
const projShort = (id) => (id ? (byId[id]?.short ?? id) : '')

function dueChip(d) {
  if (!d) return ''
  const days = (Date.parse(d) - Date.parse(S.today)) / 864e5
  const cls = days < 0 ? 'c-due' : days <= 2 ? 'c-soon' : 'c-me'
  return `<span class="chip ${cls}">${esc(mmdd(d))}</span>`
}
function actorChips(t) {
  const out = []
  if (t.mine && cur === 'mine') out.push(`<span class="chip c-ask">${esc(MINE_LABEL[t.mine] ?? t.mine)}</span>`)
  if (t.asks?.length && !(t.mine && cur === 'mine')) out.push('<span class="chip c-ask">要判断</span>')
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
  const tabs = LISTS.map(([k, label], i) => {
    const n = k === 'mine' ? inList('mine').length : (S.counts[k] ?? inList(k).length)
    return `<button class="tab ${k === cur && pane !== 'migrate' ? 'on' : ''}" data-list="${k}"><kbd>${i + 1}</kbd>${label}<span class="n ${k === 'mine' && n ? 'hot' : ''}">${n}</span></button>`
  }).join('')
  $('tabs').innerHTML = `${tabs}<button class="tab ${pane === 'migrate' ? 'on' : ''}" data-pane="migrate"><kbd>8</kbd>移し替え<span class="n">${S.migrate.done}/${S.migrate.total}</span></button>`
  const a = S.agents ?? {}
  $('agents').textContent = `エージェント: 動いている ${a.working ?? 0}・完了 ${a.done ?? 0}・あなた待ち ${a.attention ?? 0}`
}

function rowHtml(t) {
  const meta = []
  if (t.list === 'waiting') {
    meta.push(`相手: ${esc(t.who ?? '')}`, `渡した日: ${esc(mmdd(t.since ?? ''))}`)
    if (t.follow_up) meta.push(`確かめる日: ${esc(mmdd(t.follow_up))}${t.follow_up < S.today ? ' <span class="chip c-due">過ぎた</span>' : ''}`)
  }
  if (t.list === 'inbox' && t.source) meta.push(`入れた: ${esc(t.source)}`)
  if (t.worker) meta.push(`<code>${esc(t.worker)}</code> ${bar(t)}${t.agent?.inOrca ? ' <span class="goto">↘ 切り替え</span>' : ''}`)
  if (t.project && t.list !== 'project') meta.push(`<span class="chip c-proj">${esc(projShort(t.project))}</span>`)
  if (t.list === 'project' && t.outcome) meta.push(`望む結果: ${esc(t.outcome)}`)
  return `<div class="row ${t.id === sel ? 'sel' : ''}" data-id="${esc(t.id)}"><span class="check"></span>
    <div><div class="title">${esc(t.title)}</div><div class="meta">${meta.map((m) => `<span>${m}</span>`).join('')}</div>${t.list === 'project' ? stepsHtml(t) : ''}</div>
    <div class="chips">${actorChips(t)} ${dueChip(t.due)}</div></div>`
}

function renderItems() {
  const label = LISTS.find(([k]) => k === cur)[1]
  let html = `<div class="head"><h2>${label}</h2><span class="hint">${HINTS[cur]}</span></div>`
  const rows = inList(cur)
  if (!rows.length) html += '<div class="empty">空です</div>'
  else if (cur === 'next') {
    const ord = ordered('next')
    const mineRows = ord.filter((t) => !isAgent(t) || t.actor === 'me')
    const ag = ord.filter((t) => isAgent(t) && t.actor !== 'me')
    html += `<div class="group">自分（${mineRows.length}）</div>${mineRows.map(rowHtml).join('')}<div class="group">エージェント（${ag.length}）・押すと Orca のエージェントの画面も切り替わる</div>${ag.map(rowHtml).join('')}`
  } else html += rows.map(rowHtml).join('')
  const el = $('items')
  const top = el.scrollTop
  el.innerHTML = html
  el.scrollTop = top
  el.querySelectorAll('.row').forEach((r) => { r.onclick = () => choose(r.dataset.id, true) })
  el.querySelector('.row.sel')?.scrollIntoView({ block: 'nearest' })
}

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
  const opts = (a.options ?? []).map((o, i) => `<button class="opt ${a.recommended === i + 1 ? 'rec' : ''}" data-ask="${esc(a.id)}" data-choice="${i + 1}"><kbd>⇧${i + 1}</kbd><span>${esc(o.label)}${a.recommended === i + 1 ? '（推奨）' : ''}<small>${esc(o.description ?? '')}</small></span></button>`).join('')
  return `<div class="card ask"><h3>${esc(a.kind === 'approval' ? '承認' : '要判断')}: ${esc(a.question)}</h3>${opts}<div class="note">押した答えは worker に「承認ではありません」付きで届く。</div></div>`
}

function renderDetail() {
  const d = $('detail')
  const t = byId[sel]
  if (!t) { d.innerHTML = '<p class="empty">項目を選んでください</p>'; return }
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
    <div>${actorChips(t)} ${dueChip(t.due)} <span class="chip c-proj">${esc(t.list)}</span>${t.project && t.list !== 'project' ? ` <span class="chip c-proj">${esc(projShort(t.project))}</span>` : ''}</div>
    <div class="actions"><button class="btn primary" data-act="open">Orca のエディタで開く <kbd>o</kbd></button>${t.deliverables?.length ? '<button class="btn" data-act="deliv">成果物を開く <kbd>e</kbd></button>' : ''}<button class="btn" data-act="move">移す <kbd>m</kbd></button><button class="btn" data-act="done">完了 <kbd>x</kbd></button></div>
    <div class="cols"><div>${left}</div><div style="margin-top:8px"><table class="fm">${fmRows(t)}</table>
    ${t.path ? `<p class="note">ファイル: <code class="path">${esc(t.path)}</code></p>` : ''}</div></div>`
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
function render() {
  const lst = pane !== 'migrate'
  $('items').classList.toggle('on', lst)
  $('detail').classList.toggle('on', lst)
  $('migrate').classList.toggle('on', !lst)
  if (lst) {
    const rows = ordered(cur)
    if (!byId[sel] || !rows.some((t) => t.id === sel)) {
      // keep the place in the list when the selected item left it
      sel = rows.length ? rows[Math.min(lastIdx, rows.length - 1)].id : null
    }
    lastIdx = Math.max(0, rows.findIndex((t) => t.id === sel))
  }
  renderNav()
  if (lst) { renderItems(); renderDetail() } else renderMigrate()
  writeHash()
}
function showList(name) { cur = name; pane = 'list'; sel = null; lastIdx = 0; render() }
function showMigrate() { pane = 'migrate'; render() }

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
  if (r.status === 401 || r.status === 403) { toast('トークンが合わない。Orca から開き直してください', 1e9); return }
  if (!r.json || !Array.isArray(r.json.items)) { toast('state を読めなかった'); return }
  S = { ...S, ...r.json }
  byId = Object.fromEntries(S.items.map((t) => [t.id, t]))
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

async function choose(id, fromClick) {
  sel = id
  lastIdx = Math.max(0, ordered(cur).findIndex((t) => t.id === id))
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
function move(delta) {
  const rows = ordered(cur)
  if (!rows.length) return
  const i = rows.findIndex((t) => t.id === sel)
  const next = rows[Math.max(0, Math.min(rows.length - 1, (i < 0 ? 0 : i + delta)))]
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
function act(name) {
  const t = byId[sel]
  if (!t) return
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
$('menu').addEventListener('click', (e) => { if (e.target === $('menu')) closeMenu() })

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
  const k = e.key
  if (e.target.tagName === 'INPUT') {
    if (k === 'Enter') { e.preventDefault(); addInbox() } else if (k === 'Escape') e.target.blur()
    return
  }
  if (menuFor) {
    e.preventDefault()
    if (k === 'Escape') closeMenu()
    else { const hit = MOVE_TO.find(([, , key]) => key === k); if (hit) chooseMenu(hit[0]) }
    return
  }
  if (gPending) {
    gPending = false
    if (k === 'm') return showMigrate()
    const hit = LISTS.find((l) => l[2] === k)
    if (hit) showList(hit[0])
    return
  }
  if (k === 'g') { gPending = true; return }
  if (k === 'a') { e.preventDefault(); $('add').focus(); return }
  if (pane === 'migrate') {
    if (k >= '1' && k <= '7') return showList(LISTS[Number(k) - 1][0])
    if (k === 'j') return migMove(1)
    if (k === 'k') return migMove(-1)
    const hit = CASE_TO.find(([, , key]) => key === k)
    if (hit && migKey) fromCase(migKey, hit[0])
    return
  }
  const t = byId[sel]
  // Shift+1-4 answer the first open question of the selected item. The digits alone always switch
  // the tabs, so that switching a tab never sends an answer by mistake.
  const digit = /^Digit([1-4])$/.exec(e.code ?? '')?.[1]
  if (e.shiftKey && digit && t?.asks?.length) {
    e.preventDefault()
    const a = t.asks[0]
    if (a.options?.[Number(digit) - 1]) answer(a.id, Number(digit))
    return
  }
  if (k >= '1' && k <= '7') return showList(LISTS[Number(k) - 1][0])
  if (k === '8') return showMigrate()
  if (k === 'j') return move(1)
  if (k === 'k') return move(-1)
  if (k === 'Enter' && t && isAgent(t)) return focusWorker(t)
  if (!t) return
  if (k === 'o') act('open')
  else if (k === 'e') act('deliv')
  else if (k === 'm') act('move')
  else if (k === 'x') act('done')
})

$('tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button')
  if (!b) return
  if (b.dataset.list) showList(b.dataset.list)
  else if (b.dataset.pane) showMigrate()
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
