// Scrolling for a row's expanded tasks. The wheel works from the row's head too, so a long list can
// be read without moving the pointer. Listeners sit on the root, so they survive patches.

const CONTEXT_PX = 24

function tasksOf(head) {
  return head.parentElement.querySelector('.inner')
}

export function scrollExpandedRows(root) {
  // Opening a long list starts at what is left, not at the finished tasks.
  root.addEventListener('mouseover', (event) => {
    const head = event.target.closest('.head')
    if (!head || head.parentElement.contains(event.relatedTarget)) return
    const inner = tasksOf(head)
    const next = inner?.querySelector('li:not(.completed)')
    if (!next) return
    const offset = next.getBoundingClientRect().top - inner.getBoundingClientRect().top
    inner.scrollTop += offset - CONTEXT_PX
  })
  root.addEventListener('wheel', (event) => {
    const head = event.target.closest('.head')
    const inner = head && tasksOf(head)
    if (inner) inner.scrollTop += event.deltaY
  })
}
