// A small DOM for tests: enough of it to press the panel's rendered cards with panel/act.mjs, without
// a browser. It parses the HTML the worker renders (no comments, no scripts) into elements with
// closest(), querySelectorAll() on tag names, classList and dataset.

const VOID = new Set(['br', 'img', 'input', 'hr', 'meta', 'link'])
const TAG = /<\/?([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*(?:\s*=\s*"[^"]*")?)*)\s*\/?>/g
const ATTR = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g

function unescape(value) {
  return value.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
}

class Element {
  constructor(tagName, attributes = {}, parentElement = null) {
    this.tagName = tagName.toUpperCase()
    this.attributes = attributes
    this.parentElement = parentElement
    this.children = []
    this.disabled = 'disabled' in attributes
    const classes = new Set((attributes.class ?? '').split(/\s+/).filter(Boolean))
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, on) => (on ?? !classes.has(name) ? classes.add(name) : classes.delete(name))
    }
    this.dataset = {}
    for (const [name, value] of Object.entries(attributes)) {
      if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value
    }
  }

  /** One simple selector: tag, .class, [attr], or tag[attr] / tag.class. */
  matchesOne(selector) {
    const match = /^([a-zA-Z]*)((?:\.[-\w]+)*)((?:\[[-\w]+\])*)$/.exec(selector.trim())
    if (!match) throw new Error(`mini-dom cannot read the selector ${selector}`)
    const [, tag, classes, attrs] = match
    if (tag && tag.toUpperCase() !== this.tagName) return false
    for (const name of classes.split('.').filter(Boolean)) if (!this.classList.contains(name)) return false
    for (const name of (attrs.match(/[-\w]+/g) ?? [])) if (!(name in this.attributes)) return false
    return true
  }

  matches(selectors) {
    return selectors.split(',').some((selector) => this.matchesOne(selector))
  }

  closest(selectors) {
    for (let node = this; node; node = node.parentElement) if (node.matches(selectors)) return node
    return null
  }

  querySelectorAll(selectors) {
    const out = []
    const walk = (node) => {
      for (const child of node.children) {
        if (child.matches(selectors)) out.push(child)
        walk(child)
      }
    }
    walk(this)
    return out
  }
}

/** The root element of an HTML string. */
export function parse(html) {
  const root = new Element('div')
  let current = root
  for (const match of html.matchAll(TAG)) {
    const [whole, name, rest] = match
    if (whole.startsWith('</')) {
      if (current.parentElement) current = current.parentElement
      continue
    }
    const attributes = {}
    for (const [, key, value] of rest.matchAll(ATTR)) attributes[key] = value === undefined ? '' : unescape(value)
    const element = new Element(name, attributes, current)
    current.children.push(element)
    if (!VOID.has(name.toLowerCase()) && !whole.endsWith('/>')) current = element
  }
  return root
}

/** A root to hand panel/act.mjs: it keeps the listeners and dispatches a click on an element. */
export function view(html) {
  const root = parse(html)
  const listeners = {}
  root.addEventListener = (type, fn) => {
    listeners[type] = fn
  }
  root.click = (element) => listeners.click?.({ target: element, stopPropagation: () => {} })
  return root
}
