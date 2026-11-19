// Renders the Hub model to the HTML of the panel's body. It carries no clock, so the same model gives
// the same bytes and the worker posts only real changes. The styles are in panel/style.css.
//
// The row and task markup is adapted from andoshin11/orca-milestone src/render.mjs (MIT, see
// ../LICENSE and ../NOTICE.md).

const GOAL_MAX = 160
const DETAIL_MAX = 160
const SUBJECT_MAX = 200
const ROW_TASKS_SHORT = 8

export function escape(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  )
}

function clip(text, max) {
  const oneLine = String(text).replace(/\s+/g, ' ').trim()
  return oneLine.length > max ? `${oneLine.slice(0, max - 1)}…` : oneLine
}

const MARKS = { completed: '✓', in_progress: '●', pending: '○' }
const KIND_LABELS = { worker: 'worker', orca: 'Orca', session: '対話' }
const STATE_BADGES = { attention: '<span class="badge">あなたの番</span>', working: '<span class="working">作業中</span>', idle: '', done: '<span class="finished">済み</span>' }
const WATCHER_LABELS = { missing: '見つからない', stopped: '止まっている', blocked: '止まっている' }

function renderTask(task) {
  const subject = task.status === 'in_progress' && task.activeForm ? task.activeForm : task.subject
  const status = MARKS[task.status] ? task.status : 'pending'
  return `<li class="${status}"><span class="mark">${MARKS[status]}</span><span class="subject"><span class="strike">${escape(clip(subject, SUBJECT_MAX))}</span></span></li>`
}

function target(row) {
  if (row.open) return ` data-open="${escape(row.open)}"`
  if (row.report) return ` data-report="${escape(row.report)}"`
  return ''
}

function renderRow(row) {
  const percent = row.total === 0 ? 0 : Math.round((row.done / row.total) * 100)
  const of = row.total > 0 ? `<span class="of">${row.done} / ${row.total}</span>` : ''
  const bar = row.total > 0 ? `<div class="bar"><div style="width:${percent}%"></div></div>` : ''
  const finished = row.state !== 'attention' && row.total > 0 && row.done === row.total
  const mark = finished
    ? '<span class="check">✓</span>'
    : `<span class="dot ${row.state}"></span>`
  const kind = `<span class="kind">${KIND_LABELS[row.kind] ?? ''}</span>`
  const focused = row.focused ? ' focused' : ''
  const line = row.step ?? row.detail
  const sub = line ? `<div class="sub">${row.step ? '▶ ' : ''}${escape(clip(line, DETAIL_MAX))}</div>` : ''
  const where = row.where && row.where !== row.name ? `<span class="repo">${escape(row.where)}</span>` : ''
  const head = `<div class="top">${mark}<span class="name">${escape(row.name)}${where}</span>${kind}${STATE_BADGES[row.state] ?? ''}${of}</div>${sub}${bar}`
  const key = escape(`${row.key}\n${clip(row.goal ?? '', GOAL_MAX)}`)
  const open = target(row)
  const button = open
    ? `<div class="head" role="button" tabindex="0"${open}>${head}</div>`
    : `<div class="head">${head}</div>`
  if (row.total === 0 && !row.goal) return `<li class="row ${row.state}${focused}" data-key="${key}">${button}</li>`
  const goal = row.goal ? `<p class="goal">${escape(clip(row.goal, GOAL_MAX))}</p>` : ''
  const long = row.tasks.length > ROW_TASKS_SHORT ? ' long' : ''
  return `<li class="row ${row.state}${focused} has-detail${long}" data-key="${key}">${button}
<div class="detail"><div class="inner">${goal}<ol>${row.tasks.map(renderTask).join('')}</ol></div></div></li>`
}

function renderGroup(title, rows, className) {
  if (rows.length === 0) return ''
  return `<div class="group ${className}"><h2><span>${title}</span><span class="n">${rows.length}</span></h2>
<ol class="rows">${rows.map(renderRow).join('')}</ol></div>`
}

function renderWatcher(watcher) {
  if (!watcher) return ''
  const detail = watcher.detail ? `: ${escape(clip(watcher.detail, DETAIL_MAX))}` : ''
  return `<p class="watcher">見張り（chore-hub-watch）: ${WATCHER_LABELS[watcher.state] ?? ''}${detail}</p>`
}

export function renderHub(model) {
  const groups = [
    renderGroup('あなたの番', model.attention, 'attention'),
    renderGroup('動いている', model.working, 'working'),
    renderGroup('待っている', model.idle, 'idle'),
    renderGroup('済んだ', model.done, 'done')
  ].join('')
  const body = groups || '<p class="empty">Claude Code のセッションはありません。</p>'
  return `<main>${body}${renderWatcher(model.watcher)}</main>`
}

export function renderLoading() {
  return '<main><p class="empty">セッションを読んでいます…</p></main>'
}
