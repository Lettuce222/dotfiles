// Renders the panel model to the HTML of the panel's body. It carries no clock, so the same model
// gives the same bytes and the worker posts only real changes. The styles are in panel/style.css.
//
// Adapted from andoshin11/orca-milestone src/render.mjs (MIT, see ../LICENSE and ../NOTICE.md).
// Left out: the cards for next steps, questions and permissions, which typed into the session.

const GOAL_MAX = 160
const SUBJECT_MAX = 200
// A row with more tasks than this may need scrolling, so the pointer can enter its expansion.
const ROW_TASKS_SHORT = 8
function escape(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  )
}

function clip(text, max) {
  const oneLine = text.replace(/\s+/g, ' ').trim()
  return oneLine.length > max ? `${oneLine.slice(0, max - 1)}…` : oneLine
}

const AGENT_LABELS = {
  working: '作業中',
  waiting: '入力待ち',
  idle: '待機中',
  // Waiting for the user while shells it started in the background run.
  background: '待機中（裏で実行中）',
  none: ''
}

const MARKS = { completed: '✓', in_progress: '●', pending: '○' }

function renderTask(task) {
  const subject = task.status === 'in_progress' && task.activeForm ? task.activeForm : task.subject
  const status = MARKS[task.status] ? task.status : 'pending'
  return `<li class="${status}"><span class="mark">${MARKS[status]}</span><span class="subject"><span class="strike">${escape(clip(subject, SUBJECT_MAX))}</span></span></li>`
}

function renderSession(session) {
  const percent = session.total === 0 ? 0 : Math.round((session.done / session.total) * 100)
  const goal = session.goal ? `<p class="goal">${escape(clip(session.goal, GOAL_MAX))}</p>` : ''
  // The key tells the panel this is another list, which it shows at once instead of animating.
  const key = escape(`${session.listId}\n${clip(session.goal ?? '', GOAL_MAX)}`)
  return `<section data-key="${key}">${goal}<div class="count"><span>マイルストーン</span><strong>${session.done} / ${session.total}</strong></div>
<div class="bar"><div style="width:${percent}%"></div></div>
<ol>${session.tasks.map(renderTask).join('')}</ol></section>`
}

function renderRow(row) {
  const percent = row.total === 0 ? 0 : Math.round((row.done / row.total) * 100)
  const badge = row.kind === 'attention'
    ? '<span class="badge">要確認</span>'
    : row.working
      ? `<span class="working">${AGENT_LABELS.working}</span>`
      : row.background
        ? '<span class="background">裏で実行中</span>'
        : ''
  const of = row.total > 0 ? `<span class="of">${row.done} / ${row.total}</span>` : ''
  const bar = row.total > 0 ? `<div class="bar"><div style="width:${percent}%"></div></div>` : ''
  const repo = row.repo ? `<span class="repo">${escape(row.repo)}</span>` : ''
  // Every task done, nothing asked of the user: a check instead of the dot. A task in
  // progress turns the dot orange, like its mark in the list.
  const finished = row.kind !== 'attention' && row.total > 0 && row.done === row.total
  const running = row.kind !== 'attention' && row.tasks.some((task) => task.status === 'in_progress')
  const mark = finished
    ? '<span class="check">✓</span>'
    : running
      ? '<span class="dot running"></span>'
      : '<span class="dot"></span>'
  const head = `<div class="top">${mark}<span class="name">${escape(row.workspace)}${repo}</span>${badge}${of}</div>${bar}`
  const key = escape(`${row.workspace}\n${row.repo ?? ''}\n${clip(row.goal ?? '', GOAL_MAX)}`)
  const button = `<div class="head" role="button" tabindex="0" data-open="${escape(row.path)}">${head}</div>`
  if (row.total === 0) return `<li class="row ${row.kind}" data-key="${key}">${button}</li>`
  // Hovering a row's head expands its goal and tasks; plain CSS, so it needs no script.
  const goal = row.goal ? `<p class="goal">${escape(clip(row.goal, GOAL_MAX))}</p>` : ''
  const long = row.tasks.length > ROW_TASKS_SHORT ? ' long' : ''
  return `<li class="row ${row.kind} has-detail${long}" data-key="${key}">${button}
<div class="detail"><div class="inner">${goal}<ol>${row.tasks.map(renderTask).join('')}</ol></div></div></li>`
}

function renderOthers(others) {
  if (!others || others.rows.length === 0) return ''
  const attention = others.attention > 0 ? `<span class="attention">要確認 ${others.attention}</span>` : ''
  return `<div class="others"><h2><span>ほかのワークスペース</span>${attention}</h2>
<ol class="rows">${others.rows.map(renderRow).join('')}</ol></div>`
}

export function renderBody(model) {
  // The focused workspace sits at the top and the others at the bottom edge, apart.
  return `<main>${renderFocused(model)}</main>${renderOthers(model.others)}`
}

function renderFocused(model) {
  if (model.kind === 'no-workspace') {
    return '<p class="empty">ワークスペースを開くと、エージェントの進捗をここに表示します。</p>'
  }
  const agent = AGENT_LABELS[model.agent] ?? ''
  const header = `<header><h1>${escape(model.workspace)}</h1><span class="agent ${model.agent}">${agent}</span></header>`
  if (model.kind === 'no-tasks') {
    return `${header}<p class="empty">このワークスペースのエージェントはまだタスクを作っていません。</p>`
  }
  return header + model.sessions.map(renderSession).join('')
}
