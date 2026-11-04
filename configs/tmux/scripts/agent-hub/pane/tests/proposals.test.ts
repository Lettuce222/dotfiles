import { expect, test } from 'claude-code/testing'

import { openProposals, parseProposals, splitAttrs } from '../hooks/proposals'

test('属性はタイトルから分け、値の中の空白は残す', () => {
  expect(splitAttrs('レビューに返事する source:: https://example.com/a plan:: 文面を書いて送る')).toEqual({
    title: 'レビューに返事する',
    attrs: { source: 'https://example.com/a', plan: '文面を書いて送る' },
  })
  expect(splitAttrs('  属性なし  ')).toEqual({ title: '属性なし', attrs: {} })
})

test('提案の行だけを読み、ほかの行は無視する', () => {
  const text = [
    '# 提案',
    '- [ ] P1 一つ目 since:: 2026-11-04',
    'ただのメモ',
    '- [x] P2 決まったもの',
    '- [>] P3 あとで',
    '- [ ] 番号なし',
  ].join('\n')
  const all = parseProposals(text)
  expect(all.map(p => [p.id, p.mark, p.title])).toEqual([
    ['P1', ' ', '一つ目'],
    ['P2', 'x', '決まったもの'],
    ['P3', '>', 'あとで'],
  ])
  expect(all[0]?.attrs).toEqual({ since: '2026-11-04' })
})

test('未決を先に、あとでを後ろに並べ、決まったものは出さない', () => {
  const all = parseProposals(['- [>] P1 あとで', '- [x] P2 済み', '- [ ] P3 未決'].join('\n'))
  expect(openProposals(all).map(p => p.id)).toEqual(['P3', 'P1'])
})
