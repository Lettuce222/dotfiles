// A small Markdown renderer for the text the panel shows: questions, bodies, what a session says,
// the lines of a case. No library: the panel takes no outside code.
//
// Safe by construction: every piece of the text is HTML-escaped before any tag is put around it,
// and no tag carries an attribute taken from the text. A link shows its label only (the panel opens
// nothing the text points at), and an image its alt text.
//
// The blocks are what the texts use: paragraphs (a newline inside one is kept as a line break),
// headings, lists (bulleted, numbered, tasks, nested), quotes, fenced code, tables and rules. A list
// item is a marker and a body side by side, so a wrapped line starts under the body, not under the
// marker; the styles are in panel/style.css (`.md`).

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
}

// Characters that do not show, or turn text around, shown by their code point so nothing in a
// question the user approves is hidden (the panel's cards and the desk's).
const HIDDEN = /[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\u00ad]/g

/** HTML with every character that does not show made visible. */
export function reveal(html) {
  return html.replace(HIDDEN, (c) => `<span class="hidden-char">⟨U+${c.codePointAt(0).toString(16).toUpperCase().padStart(4, '0')}⟩</span>`)
}

const FENCE = /^ {0,3}(`{3,}|~{3,})/
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/
const RULE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/
const QUOTE = /^ {0,3}> ?/
const ITEM = /^( *)([-*+]|\d{1,9}[.)])(?: +(.*)|$)/
const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/
const TASK = /^\[([ xX])\] +/

// Placeholders for code spans while the rest of a line is marked up; NUL never stays in the text.
const SLOT = '\u0000'

/** Inline Markdown of one line of text, escaped. */
export function renderInline(text) {
  const codes = []
  let line = String(text).replaceAll(SLOT, '')
  line = line.replace(/(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g, (_, _ticks, code) => {
    codes.push(`<code>${escapeHtml(code.trim() || code)}</code>`)
    return `${SLOT}${codes.length - 1}${SLOT}`
  })
  line = escapeHtml(line)
  // Images and links: the label (or alt text) only.
  line = line.replace(/!?\[([^\]]*)\]\([^)\s]*(?:\s+&quot;[^&]*&quot;)?\)/g, (_, label) => `<span class="md-link">${label}</span>`)
  line = line.replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>')
  line = line.replace(/(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)/g, '$1<strong>$2</strong>')
  line = line.replace(/~~(?=\S)([\s\S]*?\S)~~/g, '<s>$1</s>')
  line = line.replace(/(^|[^*\w])\*(?=[^\s*])([^*]*?[^\s*])\*(?!\*)/g, '$1<em>$2</em>')
  return line.replace(new RegExp(`${SLOT}(\\d+)${SLOT}`, 'g'), (_, index) => codes[Number(index)])
}

function indentOf(line) {
  return line.match(/^ */)[0].length
}

function isBlank(line) {
  return line.trim() === ''
}

function startsBlock(line, next) {
  return FENCE.test(line) || HEADING.test(line) || RULE.test(line) || QUOTE.test(line) || ITEM.test(line) || isTableStart(line, next)
}

function isTableStart(line, next) {
  return line.includes('|') && next !== undefined && TABLE_RULE.test(next)
}

function cells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((cell) => cell.trim())
}

function renderTable(lines) {
  const [head, , ...body] = lines
  const row = (line, tag) => `<tr>${cells(line).map((cell) => `<${tag}>${renderInline(cell)}</${tag}>`).join('')}</tr>`
  return `<table class="md-table"><thead>${row(head, 'th')}</thead><tbody>${body.map((line) => row(line, 'td')).join('')}</tbody></table>`
}

/** The lines of one list: its items, each with the lines of its body (dedented). */
function readList(lines, start) {
  const first = lines[start].match(ITEM)
  const base = first[1].length
  const ordered = /\d/.test(first[2])
  const items = []
  let i = start
  while (i < lines.length) {
    const match = lines[i].match(ITEM)
    if (!match || match[1].length !== base || /\d/.test(match[2]) !== ordered) break
    const content = match[3] ?? ''
    // The body starts where the text after the marker starts.
    const inner = base + match[2].length + 1
    const body = [content]
    i += 1
    while (i < lines.length) {
      const line = lines[i]
      if (isBlank(line)) {
        // A blank line ends the item unless the text goes on, indented, under it.
        let j = i
        while (j < lines.length && isBlank(lines[j])) j += 1
        if (j < lines.length && indentOf(lines[j]) >= inner) {
          for (; i < j; i += 1) body.push('')
          continue
        }
        break
      }
      const indent = indentOf(line)
      if (indent >= inner || (indent > base && ITEM.test(line))) {
        body.push(line.slice(Math.min(indent, inner)))
      } else if (indent <= base && (ITEM.test(line) || startsBlock(line, lines[i + 1]))) {
        break
      } else {
        // A line that only goes on with the item's text.
        body.push(line.trim())
      }
      i += 1
    }
    items.push({ number: ordered ? Number(match[2].slice(0, -1)) : null, body })
  }
  return { ordered, items, end: i }
}

function renderList({ ordered, items }) {
  const start = items[0].number ?? 1
  const rows = items
    .map((item, index) => {
      const lines = [...item.body]
      let marker = ordered ? `${start + index}.` : '・'
      const task = lines[0].match(TASK)
      if (task) {
        marker = task[1] === ' ' ? '☐' : '☑'
        lines[0] = lines[0].slice(task[0].length)
      }
      return `<div class="md-item"><span class="md-marker">${marker}</span><div class="md-body">${renderBlocks(lines)}</div></div>`
    })
    .join('')
  return `<div class="md-list${ordered ? ' md-ordered' : ''}">${rows}</div>`
}

function renderBlocks(lines) {
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (isBlank(line)) {
      i += 1
      continue
    }
    const fence = line.match(FENCE)
    if (fence) {
      const code = []
      i += 1
      while (i < lines.length && !(lines[i].trim().startsWith(fence[1][0].repeat(fence[1].length)) && lines[i].trim().replace(/[`~]/g, '') === '')) {
        code.push(lines[i])
        i += 1
      }
      i += 1
      out.push(`<pre class="md-code">${escapeHtml(code.join('\n'))}</pre>`)
      continue
    }
    const heading = line.match(HEADING)
    if (heading) {
      out.push(`<div class="md-h md-h${heading[1].length}">${renderInline(heading[2])}</div>`)
      i += 1
      continue
    }
    if (RULE.test(line)) {
      out.push('<hr class="md-rule">')
      i += 1
      continue
    }
    if (QUOTE.test(line)) {
      const quoted = []
      // Quoted lines, and the lines that only go on with the quoted text.
      while (i < lines.length && (QUOTE.test(lines[i]) || (!isBlank(lines[i]) && !startsBlock(lines[i], lines[i + 1])))) {
        quoted.push(lines[i].replace(QUOTE, ''))
        i += 1
      }
      out.push(`<div class="md-quote">${renderBlocks(quoted)}</div>`)
      continue
    }
    if (ITEM.test(line)) {
      const list = readList(lines, i)
      out.push(renderList(list))
      i = list.end
      continue
    }
    if (isTableStart(line, lines[i + 1])) {
      const rows = [line, lines[i + 1]]
      i += 2
      while (i < lines.length && lines[i].includes('|') && !isBlank(lines[i])) {
        rows.push(lines[i])
        i += 1
      }
      out.push(renderTable(rows))
      continue
    }
    const paragraph = [line.trim()]
    i += 1
    while (i < lines.length && !isBlank(lines[i]) && !startsBlock(lines[i], lines[i + 1])) {
      paragraph.push(lines[i].trim())
      i += 1
    }
    // Each line of the text its own line, set apart a little: a newline then looks unlike a wrap.
    out.push(`<div class="md-p">${paragraph.map((text) => `<div class="md-line">${renderInline(text)}</div>`).join('')}</div>`)
  }
  return out.join('')
}

/** Markdown text as HTML: a `<div class="md">` of blocks. */
export function renderMarkdown(text) {
  const lines = String(text ?? '').replaceAll(SLOT, '').replace(/\r\n?/g, '\n').replace(/\t/g, '    ').split('\n')
  return `<div class="md">${renderBlocks(lines)}</div>`
}

/** Markdown text as one line of plain text, for the places that show a line or two of it. */
export function plainText(text) {
  return String(text ?? '')
    .replace(/!?\[([^\]]*)\]\([^)\s]*\)/g, '$1')
    .replace(/^ {0,3}(#{1,6}|>|[-*+]|\d{1,9}[.)])\s+/gm, '')
    .replace(/(\*\*|__|~~|`)/g, '')
}
