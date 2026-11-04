import { expect, test } from 'claude-code/testing'

import { linkify, repoFromUrl } from '../hooks/links'

// チケットのリンク先は架空のもの。本物は ~/hub/pane.json にある
const JIRA = 'https://tickets.example.com/browse/'

test('GitHub の URL から owner/repo を取る', () => {
  expect(repoFromUrl('https://github.com/octo/demo/pull/12')).toBe('octo/demo')
  expect(repoFromUrl('https://github.com/octo/demo/issues/3#x')).toBe('octo/demo')
  expect(repoFromUrl('https://example.com/a')).toBeUndefined()
  expect(repoFromUrl(undefined)).toBeUndefined()
})

test('URL は短い表示名のリンクにする', () => {
  expect(linkify('見る https://github.com/octo/demo/pull/12', {})).toBe(
    '見る [demo#12](https://github.com/octo/demo/pull/12)',
  )
  expect(linkify('https://example.com/x/y', {})).toBe('[example.com](https://example.com/x/y)')
})

test('#123 はリポジトリが分かるときだけ PR へのリンクにする', () => {
  expect(linkify('#5 を直す', { repo: 'octo/demo' })).toBe('[#5](https://github.com/octo/demo/pull/5) を直す')
  expect(linkify('#5 を直す', {})).toBe('#5 を直す')
})

test('チケット ID は pane.json の URL があるときだけリンクにする', () => {
  expect(linkify('ABC-12 の件', { jira: JIRA })).toBe(`[ABC-12](${JIRA}ABC-12) の件`)
  expect(linkify('ABC-12 の件', {})).toBe('ABC-12 の件')
})

test('リンク以外の markdown の記号はエスケープする', () => {
  expect(linkify('a_b *c* [d]', {})).toBe('a\\_b \\*c\\* \\[d\\]')
})
