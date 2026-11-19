// What a person presses in the panel besides opening a row: an answer on a card, and the line they
// write to a worker from its row (✎). Both go to the worker of the plugin, which checks them again
// and hands the text to the worker session; the panel only says how it went. The composer and the
// notice sit outside the patched view, so an update never drops what is being typed.

const MESSAGES = {
  ok: '送りました。',
  busy: 'worker が動いているので送れません。止まってから、もう一度押してください。',
  stale: 'カードを出したあとに依頼が変わりました。出し直したカードを見てください。',
  answered: 'ほかの場所でもう答えています。',
  pressed: '送っています。',
  unverified: '依頼した worker を確かめられないので、送りませんでした。',
  gone: '送り先の worker が見つかりません。',
  'not-worker': '窓口と見張りには、それぞれの画面で話してください。',
  'stop-failed': 'worker を止められず、届けられませんでした。',
  'resume-failed': 'worker に届けられませんでした。',
  invalid: '送れない内容です（空、長すぎる、見えない文字がある）。',
  asking: '窓口が問いや確認の途中なので、届けませんでした。',
  'no-orchestrator': '窓口が見つかりません。',
  refused: '窓口のターミナルが受け取りませんでした。'
}

export function messageOf(result) {
  if (result?.ok) return MESSAGES.ok
  return MESSAGES[result?.reason] ?? `送れませんでした（${result?.reason ?? '不明'}）。`
}

export function setUpActions({ view, notice, composer, request }) {
  const textarea = composer.querySelector('textarea')
  const to = composer.querySelector('.to')
  let target = null
  // A note for a project's latest action, when the composer was opened from one.
  let caseAction = null
  // Projects whose folded items are open, put back after every patch.
  const opened = new Set()

  function restore() {
    for (const project of view.querySelectorAll('[data-project]')) project.classList.toggle('open', opened.has(project.dataset.project))
  }
  // The ask a written answer is for, when the composer was opened from a card.
  let ask = null

  function say(text) {
    notice.textContent = text
    notice.hidden = false
  }

  async function call(name, params) {
    try {
      say(messageOf(await request(name, params)))
    } catch (error) {
      say(`送れませんでした（${error.code ?? error.message}）。`)
    }
  }

  view.addEventListener('click', (event) => {
    const more = event.target.closest('button[data-more]')
    if (more) {
      event.stopPropagation()
      const slug = more.dataset.more
      if (opened.has(slug)) opened.delete(slug)
      else opened.add(slug)
      restore()
      return
    }
    const act = event.target.closest('button[data-case-act]')
    if (act) {
      event.stopPropagation()
      const latest = act.closest('.latest')
      latest.classList.add('sending')
      act.classList.add('chosen')
      for (const button of latest.querySelectorAll('button')) button.disabled = true
      void call('case.act', { slug: act.dataset.case, kind: act.dataset.kind, text: act.dataset.text, choice: act.dataset.choice })
      return
    }
    const write = event.target.closest('button[data-case-write]')
    if (write) {
      event.stopPropagation()
      target = null
      caseAction = { slug: write.dataset.case, kind: write.dataset.kind, text: write.dataset.text }
      to.textContent = `窓口への指示（${write.dataset.name}）`
      composer.hidden = false
      textarea.focus()
      return
    }
    const answer = event.target.closest('button[data-answer]')
    if (answer) {
      event.stopPropagation()
      // The options give way to the pressed one at once; the worker's next body says how it went.
      const card = answer.closest('.card, .row-card')
      card.classList.add('sending')
      answer.classList.add('chosen')
      for (const button of card.querySelectorAll('button')) button.disabled = true
      void call('ask.answer', { id: answer.dataset.id, sha: answer.dataset.sha, choice: Number(answer.dataset.choice) })
      return
    }
    const open = event.target.closest('button[data-say]')
    if (open) {
      event.stopPropagation()
      target = open.dataset.say
      ask = open.dataset.ask ? { id: open.dataset.ask, sha: open.dataset.sha } : null
      to.textContent = ask ? `${open.dataset.name} の判断への答え` : `${open.dataset.name} への指示`
      composer.hidden = false
      textarea.focus()
    }
  })

  composer.addEventListener('submit', (event) => {
    event.preventDefault()
    const text = textarea.value.trim()
    if (caseAction && text) {
      const action = caseAction
      composer.hidden = true
      textarea.value = ''
      caseAction = null
      void call('case.act', { ...action, note: text })
      return
    }
    if (!target || !text) return
    const sessionId = target
    const answering = ask
    composer.hidden = true
    textarea.value = ''
    target = null
    ask = null
    if (answering) void call('ask.answer', { id: answering.id, sha: answering.sha, text })
    else void call('session.send', { sessionId, text })
  })

  composer.querySelector('.cancel').addEventListener('click', () => {
    composer.hidden = true
    target = null
    ask = null
    caseAction = null
  })

  return { restore }
}
