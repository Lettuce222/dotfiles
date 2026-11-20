// Renders the Hub model to the HTML of the panel's body. It carries no clock, so the same model gives
// the same bytes and the worker posts only real changes. The styles are in panel/style.css.
//
// The focused workspace, its cards and the row and task markup are adapted from
// andoshin11/orca-milestone src/render.mjs (MIT, see ../LICENSE and ../NOTICE.md). Left out: the
// restart card and the list of what "the rest of this turn" allowed.

import { CHOICES, latestAction } from './case-actions.mjs'
import { plainText, renderInline, renderMarkdown } from './markdown.mjs'

const GOAL_MAX = 160
const DETAIL_MAX = 160
const FULL_MAX = 2000
// A said line longer than this may need scrolling, so the pointer can enter the expansion.
const LONG_SAID = 400
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
  // What the session says, never cut: in full on a row that needs the user, in at most two lines on
  // the others, whose expansion then shows it in full.
  const sub = row.step
    ? `<div class="sub">▶ ${escape(clip(row.step, FULL_MAX))}</div>`
    : row.detail
      ? row.state === 'attention'
        ? `<div class="sub md-sub">${renderMarkdown(cut(row.detail, FULL_MAX))}</div>`
        : `<div class="sub">${escape(clip(plainText(row.detail), FULL_MAX))}</div>`
      : ''
  const say = row.say ? `<button type="button" class="say" data-say="${escape(row.say)}" data-name="${escape(row.name)}" title="指示を書く">✎</button>` : ''
  const head = `<div class="top">${mark}<span class="name" title="${escape(row.name)}">${escape(row.name)}</span>${kind}${STATE_BADGES[row.state] ?? ''}${of}${say}</div>${sub}${bar}`
  const key = escape(`${row.key}\n${clip(row.goal ?? '', GOAL_MAX)}`)
  const open = target(row)
  const button = open
    ? `<div class="head" role="button" tabindex="0"${open}>${head}</div>`
    : `<div class="head">${head}</div>`
  const where = row.where && row.where !== row.name ? `<p class="where">${escape(row.where)}</p>` : ''
  // A step hides what the session last said, and a clamped line may hide its end.
  const said = row.detail && (row.step || row.state !== 'attention') ? `<div class="said">${renderMarkdown(cut(row.detail, FULL_MAX))}</div>` : ''
  const goal = row.goal ? `<p class="goal">${escape(clip(row.goal, GOAL_MAX))}</p>` : ''
  const tasks = row.tasks.length > 0 ? `<ol>${row.tasks.map(renderTask).join('')}</ol>` : ''
  const ask = row.card ? renderRowCard(row.card, row.name) : row.state === 'attention' ? renderNoAsk(row) : ''
  if (!where && !said && !goal && !tasks) return `<li class="row ${row.state}${focused}" data-key="${key}">${button}${ask}</li>`
  const long = row.tasks.length > ROW_TASKS_SHORT || said.length > LONG_SAID ? ' long' : ''
  return `<li class="row ${row.state}${focused} has-detail${long}" data-key="${key}">${button}${ask}
<div class="detail"><div class="inner">${where}${said}${goal}${tasks}</div></div></li>`
}

/** At most `max` characters, the lines kept: Markdown is rendered from what is left. */
function cut(text, max) {
  const value = String(text).trim()
  return value.length > max ? `${value.slice(0, max - 1)}…` : value
}

function dueLabel(item) {
  if (!item.due) return ''
  const [, month, day] = item.due.split('-').map(Number)
  const kind = item.overdue ? ' overdue' : item.today ? ' today' : ''
  const word = item.overdue ? '過ぎた ' : item.today ? '今日 ' : ''
  return `<span class="due${kind}">${word}${month}/${day}</span>`
}

function renderTodo(item) {
  const bang = item.bang ? '<span class="bang">!</span>' : ''
  return `<li class="todo"><span class="mark">○</span><span class="text">${dueLabel(item)}${bang}${renderInline(item.text)}</span></li>`
}

function renderWaiting(item) {
  const next = item.next ? `<span class="then"> → ${renderInline(item.next)}</span>` : ''
  return `<li class="waiting"><span class="mark">…</span><span class="text">${renderInline(item.text)}${next}</span></li>`
}

export const ORCHESTRATOR_FAILURES = {
  busy: '窓口が応答中のまま、3 分待っても終わりませんでした。',
  covered: '窓口のターミナルでエディタなど別の画面が開いたまま、3 分待っても閉じませんでした。',
  asking: '窓口が問いや確認の途中です。窓口の画面で答えてからにしてください。',
  'no-orchestrator': '窓口（名前が orchestrator の claude）が動いていません。',
  'many-orchestrators': '名前が orchestrator の claude が 2 つ以上あり、どれが窓口か決められません。',
  'not-in-orca': '窓口が Orca のターミナルの中に見つかりません。',
  'not-in-hub': '窓口のターミナルが hub のワークスペースに無いか、書き込めません。',
  refused: '窓口のターミナルが受け取りませんでした。',
  failed: '届けるときに失敗しました。'
}

const ACTION_FAILURES = {
  ...ORCHESTRATOR_FAILURES,
  stale: 'このアクションは変わりました。出し直したものを見てください。',
  invalid: '届けられない指示です。'
}

/** The latest action in full, with what the orchestrator can be asked to do about it. */
function renderLatest(project, action) {
  const key = escape(`latest\n${project.slug}\n${action.kind}\n${action.text}`)
  const mark = action.kind === 'todo' ? `${dueLabel(action)}${action.bang ? '<span class="bang">!</span>' : ''}` : '<span class="wait-mark">待ち</span>'
  const then = action.kind === 'waiting' && action.next ? `<span class="then"> → ${renderInline(action.next)}</span>` : ''
  const text = `<p class="latest-text">${mark}${renderInline(action.text)}${then}</p>`
  if (project.sending) {
    return `<div class="latest next sending" data-key="${key}">${text}<div class="action sent"><span class="label">${escape(project.sending)}</span><span class="detail">窓口に届けています…</span></div></div>`
  }
  const data = `data-case="${escape(project.slug)}" data-kind="${action.kind}" data-text="${escape(action.text)}"`
  const choices = CHOICES[action.kind]
    .map((c) => `<li><button type="button" class="chip" data-case-act ${data} data-choice="${c.id}" title="${c.detail}"><span class="label">${c.label}</span></button></li>`)
    .join('')
  const write = `<li><button type="button" class="chip other" data-case-write ${data} data-name="${escape(project.short)}" title="こうしてほしい、を窓口に届ける"><span class="label">指示を書く…</span></button></li>`
  const failure = project.failure ? `<p class="status">届けられませんでした: ${ACTION_FAILURES[project.failure] ?? ACTION_FAILURES.failed}</p>` : ''
  return `<div class="latest next" data-key="${key}">${text}<ol class="choices">${choices}${write}</ol>${failure}</div>`
}

/** A project: its name, its latest action in full, the rest folded, and the workers on it. */
function renderProject(project) {
  const attention = project.rows.filter((row) => row.state === 'attention').length
  const badge = attention > 0 ? `<span class="badge">あなたの番 ${attention}</span>` : ''
  const open = project.path ? ` role="button" tabindex="0" data-report="${escape(project.path)}"` : ''
  const head = `<div class="project-head"${open}><span class="name">${escape(project.short)}</span><span class="title">${escape(project.title)}</span>${badge}</div>`
  const action = latestAction(project)
  const latest = action ? renderLatest(project, action) : ''
  const restTodo = action?.kind === 'todo' ? project.todo.slice(1) : []
  const restWaiting = action?.kind === 'waiting' ? project.waiting.slice(1) : project.waiting
  const restCount = restTodo.length + restWaiting.length
  const rest = restCount > 0
    ? `<button type="button" class="more" data-more="${escape(project.slug)}">ほか ${restCount} 件（TODO ${restTodo.length}・待ち ${restWaiting.length}）</button><ol class="items rest">${restTodo.map(renderTodo).join('')}${restWaiting.map(renderWaiting).join('')}</ol>`
    : ''
  const rows = project.rows.length > 0 ? `<ol class="rows">${project.rows.map(renderRow).join('')}</ol>` : ''
  const empty = !latest && !rows ? '<p class="quiet">TODO も待ちもありません</p>' : ''
  return `<li class="project${attention > 0 ? ' attention' : ''}" data-project="${escape(project.slug)}" data-key="${escape(`project\n${project.slug}`)}">${head}${latest}${rest}${rows}${empty}</li>`
}

function renderProjects(projects) {
  if (!projects || projects.length === 0) return ''
  return `<div class="group projects"><h2><span>プロジェクト</span><span class="n">${projects.length}</span></h2>
<ol class="project-list">${projects.map(renderProject).join('')}</ol></div>`
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

function lineSpans(lines) {
  return lines.filter(([, text]) => text).map(([kind, text]) => `<span class="${kind}">${renderMarkdown(text)}</span>`).join('')
}

function answerButton(card, choice, label, lines, recommended) {
  const disabled = card.pressed ? ' disabled' : ''
  const mark = recommended ? '<span class="recommended">推奨</span>' : ''
  return `<button type="button" class="action answer" data-answer data-id="${escape(card.id)}" data-sha="${escape(card.sha)}" data-choice="${choice}"${disabled}><span class="label">${choice}. ${escape(label)}${mark}</span>${lineSpans(lines)}</button>`
}

function plainOption(choice, label, lines) {
  return `<div class="action plain"><span class="label">${choice}. ${escape(label)}</span>${lineSpans(lines)}</div>`
}

// The question in full, each option as a card of the focused agent: what it makes the worker do is
// written in the card, under its label.
function cardBody(card) {
  const item = (choice, label, lines, recommended) =>
    `<li>${card.check.ok ? answerButton(card, choice, label, lines, recommended) : plainOption(choice, label, lines)}</li>`
  if (card.kind === 'decide') {
    const options = card.options.map((option, index) => item(index + 1, option.label, [['detail', option.description]], card.recommended === index + 1)).join('')
    return `<div class="ask">${renderMarkdown(card.question)}</div><ol class="actions">${options}</ol>`
  }
  const steps = card.suggestions.map((step, index) => item(index + 1, step.label, [['reason', step.reason], ['detail', step.prompt]], false)).join('')
  return `<ol class="actions">${steps}</ol>`
}

/** What another answer button opens: the composer, which sends its text as the answer to this ask. */
function otherAnswer(card, name) {
  if (!card.check.ok || card.kind !== 'decide') return ''
  const disabled = card.pressed ? ' disabled' : ''
  return `<li><button type="button" class="action other" data-say="${escape(card.sessionId)}" data-name="${escape(name)}" data-ask="${escape(card.id)}" data-sha="${escape(card.sha)}"${disabled}><span class="label">ほかの答えを書く</span><span class="detail">選択肢に無い答えや補足を、そのまま worker に送ります</span></button></li>`
}

/** The ask inside its worker's row: the question in full and its answers, as orca-milestone's cards. */
// Why an answer did not reach the worker, said in its row.
const FAILURES = {
  busy: 'worker が作業を終えないので、届けられませんでした。もう一度押してください。',
  stale: 'この依頼は、カードを出したあとに変わりました。出し直した選択肢を見てください。',
  answered: 'ほかの場所（窓口）でもう答えています。',
  unverified: '依頼した worker を確かめられないので、届けませんでした。',
  gone: '届け先の worker が見つかりません。',
  'not-worker': '届け先が worker ではありません。',
  'stop-failed': 'worker を止められず、届けられませんでした。',
  'resume-failed': 'worker を続けられず、届けられませんでした。',
  invalid: '届けられない答えです。',
  expired: '期限が過ぎました。窓口のターミナルの確認で答えてください。',
  failed: '届けるときに失敗しました。'
}

/**
 * A row that needs the user but has no ask: a worker stopped under the older rules, or waiting for
 * an approval, which the orchestrator asks. The panel offers no options it does not have; a worker
 * can be written to, and where to answer otherwise is said.
 */
function renderNoAsk(row) {
  if (row.say) {
    return `<div class="row-card next"><ol class="actions"><li><button type="button" class="action other" data-say="${escape(row.say)}" data-name="${escape(row.name)}"><span class="label">指示を書く</span><span class="detail">この判断の選択肢はパネルに出ていません（承認が要るものは窓口で聞きます）。書いた文を、そのまま worker に届けます</span></button></li></ol></div>`
  }
  const where = row.open ? 'そのワークスペースのターミナルで答えてください' : 'そのセッションの画面で答えてください'
  return `<p class="hint answer-elsewhere">${where}</p>`
}

function renderRowCard(card, name) {
  const key = escape(`card\n${card.id}\n${card.sha}`)
  // Pressed: the options give way to the answer, until it reaches the worker or fails.
  if (card.pressed !== null && card.pressed !== undefined) {
    const answer = card.pressed ? `<span class="label">${escape(card.pressed)}</span>` : ''
    return `<div class="row-card next sending" data-key="${key}"><div class="ask">${renderMarkdown(card.question ?? '')}</div><div class="action sent">${answer}<span class="detail">届けています…（worker が今の作業を終えるのを待ってから届けます）</span></div></div>`
  }
  const note = card.check.ok ? '' : `<p class="note">${CHECK_NOTES[card.check.reason] ?? ''}</p>`
  const body = card.check.reason === 'level' ? '' : cardBody(card).replace(/<\/ol>$/, `${otherAnswer(card, name)}</ol>`)
  const failure = card.failure ? `<p class="status">${FAILURES[card.failure] ?? FAILURES.failed}</p>` : ''
  return `<div class="row-card next" data-key="${key}">${note}${body}${failure}</div>`
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
  const body = lineSpans(lines)
  return `<li><button type="button" class="action" data-next="${escape(offerId)}" data-index="${index}"${extra}><span class="label">${escape(label)}</span>${body}</button></li>`
}

function renderForm(offer) {
  const questions = offer.questions.map((question, position) => {
    const options = question.options.map((option, index) =>
      `<li><button type="button" class="action option" data-form="${escape(offer.id)}" data-question="${position}" data-option="${index}" data-multi="${question.multiSelect ? '1' : '0'}"><span class="label">${escape(option.label)}</span>${option.detail ? `<span class="detail">${renderMarkdown(option.detail)}</span>` : ''}</button></li>`
    )
    const hint = question.multiSelect ? '<p class="hint">複数選択できます</p>' : ''
    return `<div class="question"><div class="ask">${renderMarkdown(question.question)}</div>${hint}<ol class="actions">${options.join('')}</ol></div>`
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
    body = `<div class="ask">${renderMarkdown(offer.question)}</div><ol class="actions">${cards.join('')}</ol>`
  } else if (offer.kind === 'permission') {
    const risk = offer.dangerous ? '<span class="danger">危険なコマンド</span>' : RISK_LABELS[offer.risk] ? `<span class="risk ${escape(offer.risk)}">${RISK_LABELS[offer.risk]}</span>` : ''
    heading = `<h2>許可の確認${risk}</h2>`
    const cards = offer.suggestions.map((s, index) =>
      offerCard(offer.id, index, s.label, [['detail', s.detail]], s.action === 'allow' && offer.dangerous ? ' data-dangerous="1"' : '')
    )
    const where = offer.where ? `<p class="where">場所: ${escape(offer.where)}</p>` : ''
    const only = offer.terminalOnly ? '<p class="hint">外に出る操作です。許可は、ターミナルの確認で中身を全部読んでから押してください。</p>' : ''
    body = `<div class="ask">${renderMarkdown(offer.question)}</div>${where}${only}<ol class="actions">${cards.join('')}</ol>`
  } else {
    heading = '<h2>次の作業<span>選ばなくても構いません</span></h2>'
    const cards = offer.suggestions.map((s, index) => offerCard(offer.id, index, s.label, [['reason', s.reason], ['prompt', cut(s.prompt, PROMPT_LINES_MAX)]]))
    body = `<ol class="actions">${cards.join('')}</ol>`
  }
  // Another offer is another set of cards: it replaces the old one without a transition.
  return `<div class="next ${escape(offer.kind)}" data-key="${escape(`next\n${offer.id}`)}">${heading}${body}</div>`
}

// Characters that do not show, or turn text around, shown by their code point so nothing in a
// question the user approves is hidden.
const HIDDEN = /[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\u00ad]/g

function reveal(html) {
  return html.replace(HIDDEN, (c) => `<span class="hidden-char">⟨U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}⟩</span>`)
}

function visible(value) {
  return reveal(escape(value))
}

/** Markdown, with every character that does not show made visible. */
function visibleMarkdown(value) {
  return reveal(renderMarkdown(value))
}

function optionBody(option) {
  const description = option.description ? `<span class="detail full">${visibleMarkdown(option.description)}</span>` : ''
  const preview = option.preview ? `<pre class="preview">${visible(option.preview)}</pre>` : ''
  return `<span class="label">${visible(option.label)}</span>${description}${preview}`
}

/**
 * The question the orchestrator asks the user, in full: every question, every option's label and
 * description, every preview, nothing cut. Pressing here answers the terminal's menu with the same
 * keys, so the card shows everything that menu shows. Other (a written answer) stays at the terminal.
 */
function renderOrchestratorQuestion(offer) {
  if (!offer) return ''
  const single = offer.questions.length === 1 && !offer.questions[0].multiSelect
  const body = offer.questions
    .map((q, position) => {
      const header = q.header ? `<span class="q-header">${visible(q.header)}</span>` : ''
      const hint = q.multiSelect ? '<p class="hint">複数選択できます</p>' : ''
      const options = q.options
        .map((option, index) =>
          single
            ? `<li><button type="button" class="action full" data-next="${escape(offer.id)}" data-index="${index}">${optionBody(option)}</button></li>`
            : `<li><button type="button" class="action option full" data-form="${escape(offer.id)}" data-question="${position}" data-option="${index}" data-multi="${q.multiSelect ? '1' : '0'}">${optionBody(option)}</button></li>`
        )
        .join('')
      return `<div class="question">${header}<div class="ask full">${visibleMarkdown(q.question)}</div>${hint}<ol class="actions">${options}</ol></div>`
    })
    .join('')
  const submit = single ? '' : `<button type="button" class="submit" data-submit="${escape(offer.id)}" data-count="${offer.questions.length}" disabled>回答を送信</button>`
  const other = '<p class="hint">選択肢に無い答え（Other）や、話して決めたいときは、窓口のターミナルで答えてください。</p>'
  return `<div class="next orchestrator-question" data-key="${escape(`orchestrator\n${offer.id}`)}"><h2>窓口の問い<span>ターミナルで押すのと同じです</span></h2>${body}${submit}${other}</div>`
}

/**
 * The orchestrator's question written for the panel (panel-mode): the question, its whole body as
 * one text, and the real answers. Pressing writes the answer, which the orchestrator reads itself.
 */
function renderOrchestratorAsk(card) {
  if (card.kind === 'permission') return renderPermissionAsk(card)
  const key = escape(`orchestrator-ask\n${card.id}\n${card.sha}`)
  const badge = card.approval ? '<span class="q-header">承認の問い</span>' : ''
  if (card.kept) return renderKeptAnswer(card, key)
  const body = card.body ? `<div class="body">${visibleMarkdown(card.body)}</div>` : ''
  const head = `<h2>窓口の問い<span>パネルで答えると、窓口が受け取ります</span></h2>${badge}<div class="ask full">${visibleMarkdown(card.question)}</div>${body}`
  if (card.pressed !== null && card.pressed !== undefined) {
    return `<div class="next orchestrator-question sending" data-key="${key}">${head}<div class="action sent"><span class="label">${escape(card.pressed)}</span><span class="detail">窓口に届けています…</span></div></div>`
  }
  if (!card.check.ok) {
    return `<div class="next orchestrator-question" data-key="${key}">${head}<p class="note">${CHECK_NOTES[card.check.reason] ?? ''}</p></div>`
  }
  const options = card.options
    .map((option, index) => {
      const mark = card.recommended === index + 1 ? '<span class="recommended">推奨</span>' : ''
      const description = option.description ? `<span class="detail full">${visibleMarkdown(option.description)}</span>` : ''
      return `<li><button type="button" class="action full" data-answer data-id="${escape(card.id)}" data-sha="${escape(card.sha)}" data-choice="${index + 1}"><span class="label">${visible(option.label)}${mark}</span>${description}</button></li>`
    })
    .join('')
  const other = `<li><button type="button" class="action other" data-say="${escape(card.sessionId)}" data-name="窓口" data-ask="${escape(card.id)}" data-sha="${escape(card.sha)}"><span class="label">ほかの答えを書く</span><span class="detail">選択肢に無い答えや補足を、そのまま窓口に渡します</span></button></li>`
  const failure = card.failure ? `<p class="status">${FAILURES[card.failure] ?? FAILURES.failed}</p>` : ''
  return `<div class="next orchestrator-question" data-key="${key}">${head}<ol class="actions">${options}${other}</ol>${failure}</div>`
}

const PERMISSION_NOTES = {
  identity: '窓口のセッションを確かめられないので、ボタンは出しません。窓口のターミナルで答えてください。',
  expired: '期限が過ぎました。窓口のターミナルの確認で答えてください。'
}

/** HH:MM:SS of a time, local. */
function clock(ms) {
  const date = new Date(ms)
  return [date.getHours(), date.getMinutes(), date.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':')
}

/** The whole text of a call, never cut, with every character that does not show made visible. */
function callBlock(label, value) {
  if (typeof value !== 'string' || value === '') return ''
  return `<p class="hint">${escape(label)}</p><pre class="preview">${visible(value)}</pre>`
}

/** What the call would do, in full: what a person reads before allowing it in place of the dialog. */
function permissionBody(card) {
  const input = card.input
  if (card.toolName === 'Bash' && typeof input.command === 'string') {
    const description = typeof input.description === 'string' && input.description.trim() ? `<div class="ask full">${visible(input.description)}</div>` : ''
    const rest = Object.fromEntries(Object.entries(input).filter(([name]) => !['command', 'description'].includes(name)))
    return `${description}${callBlock('コマンド', input.command)}${Object.keys(rest).length ? callBlock('ほかの引数', JSON.stringify(rest, null, 2)) : ''}`
  }
  if (typeof input.file_path === 'string' && ['Write', 'Edit', 'MultiEdit', 'NotebookEdit'].includes(card.toolName)) {
    const rest = Object.fromEntries(Object.entries(input).filter(([name]) => !['file_path', 'content', 'old_string', 'new_string'].includes(name)))
    return `${callBlock('ファイル', input.file_path)}${callBlock('書く中身', input.content)}${callBlock('置き換える前', input.old_string)}${callBlock('置き換えたあと', input.new_string)}${Object.keys(rest).length ? callBlock('ほかの引数', JSON.stringify(rest, null, 2)) : ''}`
  }
  return callBlock('引数', JSON.stringify(input, null, 2))
}

/**
 * A permission dialog of the orchestrator that approval-gate.py holds back while the panel answers:
 * the call in full, and allow (this once), deny, deny with a reason, or the terminal's dialog now.
 * A call that reaches past this machine gets no allow button, and a dangerous one is pressed twice.
 */
function renderPermissionAsk(card) {
  const key = escape(`orchestrator-permission\n${card.id}\n${card.sha}`)
  const risk = card.dangerous ? '<span class="danger">危険なコマンド</span>' : RISK_LABELS[card.risk] ? `<span class="risk ${escape(card.risk)}">${RISK_LABELS[card.risk]}</span>` : ''
  const agent = card.agentType ? `（サブエージェント ${visible(card.agentType)}）` : ''
  const where = card.where || card.cwd ? `<p class="where">場所: ${visible(card.where || card.cwd)}</p>` : ''
  const head = `<h2>許可の確認${risk}<span>パネルで答えると、窓口の確認ダイアログの代わりになります</span></h2><div class="ask full">窓口の ${visible(card.toolName)}${agent} を実行してよいですか</div>${permissionBody(card)}${where}`
  if (card.pressed !== null && card.pressed !== undefined) {
    return `<div class="next orchestrator-question permission sending" data-key="${key}">${head}<div class="action sent"><span class="label">${escape(card.pressed)}</span><span class="detail">窓口に返しています…</span></div></div>`
  }
  if (!card.check.ok) {
    return `<div class="next orchestrator-question permission" data-key="${key}">${head}<p class="note">${PERMISSION_NOTES[card.check.reason] ?? CHECK_NOTES[card.check.reason] ?? ''}</p></div>`
  }
  const button = (choice, label, detail, extra = '') =>
    `<li><button type="button" class="action full" data-answer data-permission data-id="${escape(card.id)}" data-sha="${escape(card.sha)}" data-choice="${choice}"${extra}><span class="label">${label}</span><span class="detail full">${detail}</span></button></li>`
  const allow = card.risk === 'outside' ? '' : button('allow', '許可（今回だけ）', 'この 1 回だけ実行します。許可のルールは足しません', card.dangerous ? ' data-dangerous="1"' : '')
  const only = card.risk === 'outside' ? '<p class="hint">外に出る操作です。許可は、窓口のターミナルの確認で中身を全部読んでから押してください。</p>' : ''
  const reason = `<li><button type="button" class="action other" data-say="${escape(card.sessionId)}" data-name="許可の確認" data-to="許可の確認を拒否する理由" data-ask="${escape(card.id)}" data-sha="${escape(card.sha)}"><span class="label">理由を書いて拒否</span><span class="detail">書いた理由を添えて拒否し、窓口の Claude に返します</span></button></li>`
  const options = `${allow}${button('deny', '拒否', '実行しません。窓口の Claude には、パネルで拒否されたと返します')}${reason}${button('terminal', 'ターミナルで確かめる', '待たずに、窓口のターミナルに確認ダイアログを出します')}`
  const deadline = `<p class="hint">${clock(card.expiresAt)} までに答えないと、窓口のターミナルに確認ダイアログが出ます。</p>`
  const failure = card.failure ? `<p class="status">${FAILURES[card.failure] ?? FAILURES.failed}</p>` : ''
  return `<div class="next orchestrator-question permission" data-key="${key}">${head}${only}<ol class="actions">${options}</ol>${deadline}${failure}</div>`
}

/**
 * An answer to the orchestrator's question that is written, but that the orchestrator was not told
 * of yet: what was answered, why it did not reach the orchestrator, and that the panel tries again.
 */
function renderKeptAnswer(card, key) {
  const why = ORCHESTRATOR_FAILURES[card.reason] ?? ORCHESTRATOR_FAILURES.failed
  const head = `<h2>窓口の問い<span>答えは残してあります</span></h2><div class="ask full">${visibleMarkdown(card.question)}</div>`
  return `<div class="next orchestrator-question kept" data-key="${key}">${head}<div class="action sent"><span class="label">${escape(card.label)}</span><span class="detail">まだ窓口に知らせられていません: ${why} 窓口が受け取れるようになったら、パネルが自動で知らせます。</span></div></div>`
}

function renderFocused(focused) {
  if (!focused || focused.kind === 'no-workspace') return ''
  const agent = AGENT_LABELS[focused.agent] ?? ''
  const header = `<header><h1>${escape(focused.workspace)}</h1><span class="agent ${escape(focused.agent)}">${agent}</span></header>`
  const body = focused.kind === 'no-tasks'
    ? '<p class="empty">このワークスペースのエージェントはまだタスクを作っていません。</p>'
    : focused.sessions.map(renderSession).join('')
  return `<div class="focus">${header}${body}${renderNext(focused.next)}</div>`
}

function renderWatcher(watcher) {
  if (!watcher) return ''
  const detail = watcher.detail ? `: ${escape(clip(watcher.detail, DETAIL_MAX))}` : ''
  return `<p class="watcher">見張り（chore-hub-watch）: ${WATCHER_LABELS[watcher.state] ?? ''}${detail}</p>`
}

export function renderHub(model) {
  const groups = [
    ...(model.orchestratorAsks ?? []).map(renderOrchestratorAsk),
    renderOrchestratorQuestion(model.orchestratorQuestion),
    renderFocused(model.focused),
    renderCards(model.cards),
    renderProjects(model.projects),
    renderGroup('あなたの番（プロジェクトの外）', model.attention, 'attention'),
    renderGroup('動いている（プロジェクトの外）', model.working, 'working'),
    renderGroup('待っている', model.idle, 'idle')
  ].join('')
  const body = groups || '<p class="empty">Claude Code のセッションはありません。</p>'
  return `<main>${body}${renderWatcher(model.watcher)}</main>`
}

export function renderLoading() {
  return '<main><p class="empty">セッションを読んでいます…</p></main>'
}
