// Opens what a pressed row points at: its Orca workspace (data-open) or a hub worker's report
// (data-report). The listener sits on the root, so it keeps working however the rows are patched.
//
// Adapted from andoshin11/orca-milestone panel/open.mjs (MIT, see ../LICENSE and ../NOTICE.md).

function targetOf(element) {
  const head = element.closest('[data-open], [data-report]')
  if (!head) return null
  return head.hasAttribute('data-open')
    ? { kind: 'workspace', path: head.getAttribute('data-open') }
    : { kind: 'report', path: head.getAttribute('data-report') }
}

export function openOnPress(root, open) {
  root.addEventListener('click', (event) => {
    const target = targetOf(event.target)
    if (target) open(target)
  })
  root.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    const target = event.target.matches?.('[data-open], [data-report]') ? targetOf(event.target) : null
    if (!target) return
    event.preventDefault()
    open(target)
  })
}
