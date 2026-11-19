// Opens the workspace of a pressed row. The listener sits on the root, so it keeps working however
// the rows are patched. Only a row's head carries data-open, the part that keeps the row expanded.

export function openOnPress(root, open) {
  root.addEventListener('click', (event) => {
    const head = event.target.closest('[data-open]')
    if (head) open(head.getAttribute('data-open'))
  })
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    if (!event.target.hasAttribute('data-open')) return
    event.preventDefault()
    open(event.target.getAttribute('data-open'))
  })
}
