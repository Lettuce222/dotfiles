// The small Markdown renderer of src/markdown.mjs: escaped first, then marked up.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { test } from 'node:test'
import { plainText, renderInline, renderMarkdown } from '../src/markdown.mjs'

const item = (marker, body) => `<div class="md-item"><span class="md-marker">${marker}</span><div class="md-body">${body}</div></div>`
const p = (...lines) => `<div class="md-p">${lines.map((line) => `<div class="md-line">${line}</div>`).join('')}</div>`

test('nothing in the text becomes a tag or an attribute', () => {
  const html = renderMarkdown('<img src=x onerror=alert(1)>\n- <script>x</script>\n[<b>a</b>](javascript:alert(1)) `<i>` **"q"**')
  assert.ok(!/<(img|script|b|i|a)[\s>]/.test(html), html)
  assert.ok(!html.includes('href'))
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'))
  assert.ok(html.includes('<span class="md-link">&lt;b&gt;a&lt;/b&gt;</span>'), 'a link shows its label only')
  assert.ok(html.includes('<code>&lt;i&gt;</code>'))
  assert.ok(html.includes('<strong>&quot;q&quot;</strong>'))
  assert.ok(!renderMarkdown('a\u0000b').includes('\u0000'))
})

test('a list item is its marker and its body side by side, so wrapped lines start under the body', () => {
  assert.equal(
    renderMarkdown('- とても長い文字列\n  続き\n- 二つ目\n  - 入れ子'),
    `<div class="md"><div class="md-list">${item('・', p('とても長い文字列', '続き'))}${item('・', `${p('二つ目')}<div class="md-list">${item('・', p('入れ子'))}</div>`)}</div></div>`
  )
  assert.equal(renderMarkdown('3. 三\n4. 四'), `<div class="md"><div class="md-list md-ordered">${item('3.', p('三'))}${item('4.', p('四'))}</div></div>`)
  assert.equal(renderMarkdown('- [ ] まだ\n- [x] 済み'), `<div class="md"><div class="md-list">${item('☐', p('まだ'))}${item('☑', p('済み'))}</div></div>`)
  assert.equal(renderMarkdown('1. 一\n\n   段落\n2. 二'), `<div class="md"><div class="md-list md-ordered">${item('1.', `${p('一')}${p('段落')}`)}${item('2.', p('二'))}</div></div>`, 'a blank line inside an item')
  assert.equal(renderMarkdown('- a\n1. b'), `<div class="md"><div class="md-list">${item('・', p('a'))}</div><div class="md-list md-ordered">${item('1.', p('b'))}</div></div>`)
})

test('each line of a paragraph stays a line, paragraphs and other blocks apart', () => {
  assert.equal(renderMarkdown('一行目\n二行目\n\n次の段落'), `<div class="md">${p('一行目', '二行目')}${p('次の段落')}</div>`)
  assert.equal(renderMarkdown('## 見出し\n本文'), `<div class="md"><div class="md-h md-h2">見出し</div>${p('本文')}</div>`)
  assert.equal(renderMarkdown('> 引用\n> 続き'), `<div class="md"><div class="md-quote">${p('引用', '続き')}</div></div>`)
  assert.equal(renderMarkdown('```sh\nls <x>\n  y\n```\n後'), `<div class="md"><pre class="md-code">ls &lt;x&gt;\n  y</pre>${p('後')}</div>`)
  assert.equal(renderMarkdown('a\n\n---\n\nb'), `<div class="md">${p('a')}<hr class="md-rule">${p('b')}</div>`)
  assert.equal(
    renderMarkdown('| 名前 | 値 |\n|---|:-:|\n| `a` | 1 |'),
    '<div class="md"><table class="md-table"><thead><tr><th>名前</th><th>値</th></tr></thead><tbody><tr><td><code>a</code></td><td>1</td></tr></tbody></table></div>'
  )
})

test('inline marks, and what is not one stays as written', () => {
  assert.equal(renderInline('**太字** と *斜体* と ~~消し~~'), '<strong>太字</strong> と <em>斜体</em> と <s>消し</s>')
  assert.equal(renderInline('snake_case_name と a*b*c と 2 * 3'), 'snake_case_name と a*b*c と 2 * 3')
  assert.equal(renderInline('`**` は記号'), '<code>**</code> は記号')
  assert.equal(renderInline('[11/19] の期日'), '[11/19] の期日')
})

test('plain text for the lines shown short', () => {
  assert.equal(plainText('## 見出し\n- [資料](https://x) を **読む**'), '見出し\n資料 を 読む')
})

test('the panel has the styles of the hanging indent and the wrap', () => {
  const css = readFileSync(join(import.meta.dirname, '..', 'panel', 'style.css'), 'utf8')
  assert.match(css, /\.md-item \{[^}]*grid-template-columns: auto minmax\(0, 1fr\)/)
  assert.match(css, /\.md \{[^}]*overflow-wrap: anywhere/)
  assert.match(css, /\.md-p \{[^}]*gap: 3px/)
  assert.doesNotMatch(css, /preview\.body/, 'no unwrapped body is left')
})
