// Brings an element's children in line with an HTML string, touching only what differs. Elements
// that stay keep their scroll position and hover state, which replacing innerHTML would lose, and
// CSS transitions run on what changes in them. An element with another data-key is something else,
// such as the list of another workspace, so it replaces the old one and shows without a transition.

function patchAttributes(from, to) {
  for (const { name } of [...from.attributes]) {
    if (!to.hasAttribute(name)) from.removeAttribute(name)
  }
  for (const { name, value } of [...to.attributes]) {
    if (from.getAttribute(name) !== value) from.setAttribute(name, value)
  }
}

function keyOf(node) {
  return node.nodeType === 1 ? node.getAttribute('data-key') : null
}

function patchNodes(parent, wanted) {
  const current = [...parent.childNodes]
  wanted.forEach((to, index) => {
    const from = current[index]
    if (!from) {
      parent.appendChild(to)
    } else if (from.nodeType !== to.nodeType || from.nodeName !== to.nodeName || keyOf(from) !== keyOf(to)) {
      parent.replaceChild(to, from)
    } else if (from.nodeType === 1) {
      patchAttributes(from, to)
      patchNodes(from, [...to.childNodes])
    } else if (from.nodeValue !== to.nodeValue) {
      from.nodeValue = to.nodeValue
    }
  })
  for (const extra of current.slice(wanted.length)) parent.removeChild(extra)
}

export function patchChildren(element, html) {
  const template = element.ownerDocument.createElement('template')
  template.innerHTML = html
  patchNodes(element, [...template.content.childNodes])
}
