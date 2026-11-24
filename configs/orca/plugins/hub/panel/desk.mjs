// The panel's way into the desk: the button asks the plugin's worker to open the desk in a browser
// tab of Orca, and the other button shows or hides the view from before hub v2. Listeners sit on the
// root, so they keep working however the body is patched; whether the old view shows is a class of
// the document's body, which patches never touch.

const SHOW_LEGACY = 'show-legacy'
const KEY = 'hub.showLegacy'

function remembered() {
  try {
    return window.localStorage?.getItem(KEY) === '1'
  } catch {
    return false
  }
}

function remember(on) {
  try {
    window.localStorage?.setItem(KEY, on ? '1' : '0')
  } catch {
    // A frame without storage forgets it on the next open.
  }
}

export function setUpDesk({ view, notice, request }) {
  document.body.classList.toggle(SHOW_LEGACY, remembered())
  view.addEventListener('click', async (event) => {
    if (event.target.closest('[data-legacy-toggle]')) {
      const on = document.body.classList.toggle(SHOW_LEGACY)
      remember(on)
      return
    }
    const open = event.target.closest('[data-desk-open]')
    if (!open || open.disabled) return
    open.disabled = true
    try {
      const result = await request('desk.open')
      if (!result?.opened) {
        notice.textContent = `デスクを開けませんでした（${result?.reason ?? '不明'}）。`
        notice.hidden = false
      }
    } catch (error) {
      notice.textContent = `デスクを開けませんでした（${error.code ?? error.message}）。`
      notice.hidden = false
    } finally {
      open.disabled = false
    }
  })
}
