// Sends what is picked in the cards under the focused workspace. A pressed card turns to show it and
// the others stop taking presses; the worker's next body, once the agent moves on, takes the cards
// away. When nothing was sent, a line under the cards says why and they take presses again.
// - A form's options are ticked here and sent together with its button. The worker's bodies would
//   drop the ticks, so they are kept per form and put back after every patch (`restore`).
// - Allowing a dangerous command takes two presses: the first only asks for the second.
// - Cards that just came take no presses for a moment (`settling`). Answering one permission often
//   puts the next in the same place, and a quick second click would answer that one unread.
// Listeners sit on the root, so they keep working however the cards are patched.
//
// Copied from andoshin11/orca-milestone panel/next.mjs (MIT, see ../LICENSE and ../NOTICE.md).

export const SETTLE_MS = 1500

const MESSAGES = {
  stale: 'この選択肢はもう使えません。エージェントが先に進んだか、すでに押されています。',
  typing: 'Codex の入力欄に書きかけの文字があるため、送りませんでした。',
  draft: '入力欄に書きかけの文字があるため、再開しませんでした。',
  confirm: '危険なコマンドです。実行してよければ、もう一度押してください。',
  failed: '送信に失敗しました。'
}

function showStatus(within, text) {
  const next = within.closest('.next')
  if (!next) return
  let status = next.querySelector('.status')
  if (!status) {
    status = next.ownerDocument.createElement('p')
    status.className = 'status'
    next.appendChild(status)
  }
  status.textContent = text
}

/** The offer a card, an option or a form's button belongs to. */
function offerOf(element) {
  return element.getAttribute('data-next') ?? element.getAttribute('data-form') ?? element.getAttribute('data-submit')
}

export function sendOnPress(root, send, { now = () => Date.now(), settleMs = SETTLE_MS, later = setTimeout } = {}) {
  // Ticks per form, by offer: an array of option sets, one per question.
  const picks = new Map()
  // When each offer on screen first showed.
  const arrived = new Map()
  let busy = false

  const settling = (offer) => now() - (arrived.get(offer) ?? -Infinity) < settleMs
  // Cards already there when this starts listening did not just come.
  for (const element of root.querySelectorAll('[data-next], [data-form], [data-submit]')) arrived.set(offerOf(element), -Infinity)

  /** Notes the offers that just came, and marks their cards while they take no presses. */
  function settle() {
    const shown = new Set([...root.querySelectorAll('[data-next], [data-form], [data-submit]')].map(offerOf))
    for (const offer of arrived.keys()) if (!shown.has(offer)) arrived.delete(offer)
    for (const offer of shown) {
      if (arrived.has(offer)) continue
      arrived.set(offer, now())
      later(settle, settleMs + 50)
    }
    for (const next of root.querySelectorAll('.next')) {
      const offers = [...next.querySelectorAll('[data-next], [data-form], [data-submit]')].map(offerOf)
      next.classList.toggle('settling', offers.some(settling))
    }
  }

  async function deliver(element, request) {
    busy = true
    const next = element.closest('.next')
    next?.classList.add('busy')
    element.classList.add('sending')
    let result
    try {
      result = await send(request)
    } catch {
      result = { sent: false, reason: 'failed' }
    }
    busy = false
    if (result?.sent) {
      picks.delete(request.offer)
      return
    }
    element.classList.remove('sending')
    next?.classList.remove('busy')
    if (result?.reason === 'confirm') element.classList.add('armed')
    showStatus(element, MESSAGES[result?.reason] ?? MESSAGES.failed)
  }

  function restore() {
    settle()
    for (const button of root.querySelectorAll('[data-option]')) {
      const chosen = picks.get(button.getAttribute('data-form'))?.[Number(button.getAttribute('data-question'))]
      button.classList.toggle('chosen', Boolean(chosen?.has(Number(button.getAttribute('data-option')))))
    }
    for (const submit of root.querySelectorAll('[data-submit]')) {
      const chosen = picks.get(submit.getAttribute('data-submit')) ?? []
      const count = Number(submit.getAttribute('data-count'))
      submit.disabled = busy || chosen.filter((set) => set?.size > 0).length !== count
    }
  }

  function pick(option) {
    const offer = option.getAttribute('data-form')
    const position = Number(option.getAttribute('data-question'))
    const index = Number(option.getAttribute('data-option'))
    const chosen = picks.get(offer) ?? []
    const set = option.getAttribute('data-multi') === '1' ? new Set(chosen[position]) : new Set()
    if (set.has(index)) set.delete(index)
    else set.add(index)
    chosen[position] = set
    picks.set(offer, chosen)
    restore()
  }

  root.addEventListener('click', (event) => {
    if (busy) return
    const pressed = event.target.closest('[data-next], [data-form], [data-submit]')
    if (pressed && settling(offerOf(pressed))) return
    const option = event.target.closest('[data-option]')
    if (option) {
      pick(option)
      return
    }
    const submit = event.target.closest('[data-submit]')
    if (submit) {
      if (submit.disabled) return
      const offer = submit.getAttribute('data-submit')
      const answers = (picks.get(offer) ?? []).map((set) => [...set].sort((a, b) => a - b))
      void deliver(submit, { offer, answers }).then(restore)
      return
    }
    const card = event.target.closest('[data-next]')
    if (!card) return
    const dangerous = card.getAttribute('data-dangerous') === '1'
    if (dangerous && !card.classList.contains('armed')) {
      card.classList.add('armed')
      showStatus(card, MESSAGES.confirm)
      return
    }
    void deliver(card, { offer: card.getAttribute('data-next'), index: Number(card.getAttribute('data-index')), ...(dangerous ? { confirmed: true } : {}) })
  })

  return { restore }
}
