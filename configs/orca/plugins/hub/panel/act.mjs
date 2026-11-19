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
  invalid: '送れない内容です（空、長すぎる、見えない文字がある）。'
}

export function messageOf(result) {
  if (result?.ok) return MESSAGES.ok
  return MESSAGES[result?.reason] ?? `送れませんでした（${result?.reason ?? '不明'}）。`
}

export function setUpActions({ view, notice, composer, request }) {
  const textarea = composer.querySelector('textarea')
  const to = composer.querySelector('.to')
  let target = null
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
    const answer = event.target.closest('button[data-answer]')
    if (answer) {
      event.stopPropagation()
      // Every button of the card waits for the answer, so a second press sends nothing.
      for (const button of answer.closest('.card, .row-card').querySelectorAll('button[data-answer]')) button.disabled = true
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
  })
}
