// Renders the Hub model to the HTML of the panel's body. It carries no clock, so the same model gives
// the same bytes and the worker posts only real changes. The styles are in panel/style.css.
//
// The focused workspace, its cards and the row and task markup are adapted from
// andoshin11/orca-milestone src/render.mjs (MIT, see ../LICENSE and ../NOTICE.md). Left out: the
// restart card and the list of what "the rest of this turn" allowed.

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
  const say = row.say ? `<button type="button" class="say" data-say="${escape(row.say)}" data-name="${escape(row.name)}" title="指示を書く">✎</button>` : ''
  const head = `<div class="top">${mark}<span class="name">${escape(row.name)}${where}</span>${kind}${STATE_BADGES[row.state] ?? ''}${of}${say}</div>${sub}${bar}`
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

// The cards of the asks. Each shows the whole question or prompt, never cut, so a person decides
// from the card alone; what an option or a step makes the worker do is written under its button.
const CARD_KINDS = { decide: '判断', next: '次へ' }
const CHECK_NOTES = {
  identity: '依頼した worker を確かめられないので、答えのボタンは出しません。窓口で確かめてください。',
  level: 'レベル B より上の情報を含む依頼です。窓口で確かめてください。'
}

function answerButton(card, choice, label, recommended) {
  const disabled = card.pressed ? ' disabled' : ''
  const mark = recommended ? '<span class="recommended">推奨</span>' : ''
  return `<button type="button" class="answer" data-answer data-id="${escape(card.id)}" data-sha="${escape(card.sha)}" data-choice="${choice}"${disabled}>${choice}. ${escape(label)}${mark}</button>`
}

function cardBody(card) {
  if (card.kind === 'decide') {
    const options = card.options
      .map((option, index) => `<li>${card.check.ok ? answerButton(card, index + 1, option.label, card.recommended === index + 1) : `<span class="label">${index + 1}. ${escape(option.label)}</span>`}<p class="desc">${escape(option.description)}</p></li>`)
      .join('')
    return `<p class="question">${escape(card.question)}</p><ol class="options">${options}</ol>`
  }
  const steps = card.suggestions
    .map((step, index) => `<li>${card.check.ok ? answerButton(card, index + 1, step.label, false) : `<span class="label">${index + 1}. ${escape(step.label)}</span>`}<p class="desc">${escape(step.prompt)}</p><p class="reason">${escape(step.reason)}</p></li>`)
    .join('')
  return `<ol class="options">${steps}</ol>`
}

function renderCard(card) {
  const report = card.report ? ` data-report="${escape(card.report)}" role="button" tabindex="0"` : ''
  const caseName = card.case ? `<span class="case">${escape(card.case)}</span>` : ''
  const head = `<div class="card-head"${report}><span class="card-kind">${CARD_KINDS[card.kind] ?? ''}</span><span class="name">${escape(card.worker)}</span>${caseName}</div>`
  const note = card.check.ok ? '' : `<p class="note">${CHECK_NOTES[card.check.reason] ?? ''}</p>`
  const body = card.check.reason === 'level' ? '' : cardBody(card)
  const sending = card.pressed ? '<p class="note">送っています…</p>' : ''
  return `<li class="card ${escape(card.kind)}" data-key="${escape(`card\n${card.id}\n${card.sha}`)}">${head}${note}${body}${sending}</li>`
}

function renderCards(cards) {
  if (!cards || cards.length === 0) return ''
  return `<div class="group cards"><h2><span>カード</span><span class="n">${cards.length}</span></h2>
<ol class="card-list">${cards.map(renderCard).join('')}</ol></div>`
}

const PROMPT_LINES_MAX = 300
const RISK_LABELS = { read: '読むだけ', write: '書き換える', outside: '外に出る' }
const AGENT_LABELS = { working: '作業中', waiting: '入力待ち', idle: '待機中', background: '待機中（裏で実行中）', none: '' }

function renderSession(session) {
  const percent = session.total === 0 ? 0 : Math.round((session.done / session.total) * 100)
  const goal = session.goal ? `<p class="goal">${escape(clip(session.goal, GOAL_MAX))}</p>` : ''
  // The key tells the panel this is another list, which it shows at once instead of animating.
  const key = escape(`${session.listId}\n${clip(session.goal ?? '', GOAL_MAX)}`)
  return `<section data-key="${key}">${goal}<div class="count"><span>マイルストーン</span><strong>${session.done} / ${session.total}</strong></div>
<div class="bar"><div style="width:${percent}%"></div></div>
<ol>${session.tasks.map(renderTask).join('')}</ol></section>`
}

function offerCard(offerId, index, label, lines, extra = '') {
  const body = lines.filter(([, text]) => text).map(([kind, text]) => `<span class="${kind}">${escape(text)}</span>`).join('')
  return `<li><button type="button" class="action" data-next="${escape(offerId)}" data-index="${index}"${extra}><span class="label">${escape(label)}</span>${body}</button></li>`
}

function renderForm(offer) {
  const questions = offer.questions.map((question, position) => {
    const options = question.options.map((option, index) =>
      `<li><button type="button" class="action option" data-form="${escape(offer.id)}" data-question="${position}" data-option="${index}" data-multi="${question.multiSelect ? '1' : '0'}"><span class="label">${escape(option.label)}</span>${option.detail ? `<span class="detail">${escape(option.detail)}</span>` : ''}</button></li>`
    )
    const hint = question.multiSelect ? '<p class="hint">複数選択できます</p>' : ''
    return `<div class="question"><p class="ask">${escape(question.question)}</p>${hint}<ol class="actions">${options.join('')}</ol></div>`
  })
  return `${questions.join('')}<button type="button" class="submit" data-submit="${escape(offer.id)}" data-count="${offer.questions.length}" disabled>回答を送信</button>`
}

/** What the focused agent offers: its next steps, its question or a tool waiting for permission. */
function renderNext(offer) {
  if (!offer) return ''
  let heading
  let body
  if (offer.kind === 'form') {
    heading = '<h2>質問に答える</h2>'
    body = renderForm(offer)
  } else if (offer.kind === 'question') {
    heading = '<h2>質問に答える</h2>'
    const cards = offer.suggestions.map((s, index) => offerCard(offer.id, index, s.label, [['detail', s.detail]]))
    body = `<p class="ask">${escape(offer.question)}</p><ol class="actions">${cards.join('')}</ol>`
  } else if (offer.kind === 'permission') {
    const risk = offer.dangerous ? '<span class="danger">危険なコマンド</span>' : RISK_LABELS[offer.risk] ? `<span class="risk ${escape(offer.risk)}">${RISK_LABELS[offer.risk]}</span>` : ''
    heading = `<h2>許可の確認${risk}</h2>`
    const cards = offer.suggestions.map((s, index) =>
      offerCard(offer.id, index, s.label, [['detail', s.detail]], s.action === 'allow' && offer.dangerous ? ' data-dangerous="1"' : '')
    )
    const where = offer.where ? `<p class="where">場所: ${escape(offer.where)}</p>` : ''
    const only = offer.terminalOnly ? '<p class="hint">外に出る操作です。許可は、ターミナルの確認で中身を全部読んでから押してください。</p>' : ''
    body = `<p class="ask">${escape(offer.question)}</p>${where}${only}<ol class="actions">${cards.join('')}</ol>`
  } else {
    heading = '<h2>次の作業<span>選ばなくても構いません</span></h2>'
    const cards = offer.suggestions.map((s, index) => offerCard(offer.id, index, s.label, [['reason', s.reason], ['prompt', clip(s.prompt, PROMPT_LINES_MAX)]]))
    body = `<ol class="actions">${cards.join('')}</ol>`
  }
  // Another offer is another set of cards: it replaces the old one without a transition.
  return `<div class="next ${escape(offer.kind)}" data-key="${escape(`next\n${offer.id}`)}">${heading}${body}</div>`
}

function renderFocused(focused) {
  if (!focused || focused.kind === 'no-workspace') return ''
  const agent = AGENT_LABELS[focused.agent] ?? ''
  const header = `<header><h1>${escape(focused.workspace)}</h1><span class="agent ${escape(focused.agent)}">${agent}</span></header>`
  const body = focused.kind === 'no-tasks'
    ? '<p class="empty">このワークスペースのエージェントはまだタスクを作っていません。</p>'
    : focused.sessions.map(renderSession).join('')
  return `<div class="focused">${header}${body}${renderNext(focused.next)}</div>`
}

function renderWatcher(watcher) {
  if (!watcher) return ''
  const detail = watcher.detail ? `: ${escape(clip(watcher.detail, DETAIL_MAX))}` : ''
  return `<p class="watcher">見張り（chore-hub-watch）: ${WATCHER_LABELS[watcher.state] ?? ''}${detail}</p>`
}

export function renderHub(model) {
  const groups = [
    renderFocused(model.focused),
    renderCards(model.cards),
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
