// Refuses text that something other than a person or this panel drives into an Orca terminal:
// `orca terminal send` run by an agent, or another plugin. Such text could answer the question an
// agent waits on, or type "approved" into a session, without anyone pressing a button. What a
// person types is never hooked by Orca, and neither are launch prompts nor Orca's own
// orchestration, which pass. The panel's own sends are expected beforehand and pass once.
//
// agent-ui-guard.py stops `orca terminal send` in Claude Code sessions already; this catches the
// rest (other agents, a call the guard cannot read).

const EXPECT_MS = 30_000

export const DENY_REASON = 'Hub (local) では、人が打つ入力とパネルのボタン以外からターミナルに文を送れません。'

export function createSendGuard({ now = Date.now } = {}) {
  // The panel's own sends, by terminal and text, until they pass or expire.
  const expected = []

  function expect(terminalId, text) {
    expected.push({ terminalId, text, until: now() + EXPECT_MS })
  }

  function consume(terminalId, text) {
    const time = now()
    for (let i = expected.length - 1; i >= 0; i -= 1) {
      if (expected[i].until < time) expected.splice(i, 1)
    }
    const index = expected.findIndex((entry) => entry.terminalId === terminalId && entry.text === text)
    if (index === -1) return false
    expected.splice(index, 1)
    return true
  }

  /** The decision for a send of this kind and text: undefined lets it through. */
  function decide(inputKind, terminalId, text) {
    if (inputKind !== 'driving') return undefined
    if (consume(terminalId, text)) return undefined
    return { deny: DENY_REASON }
  }

  return {
    expect,
    terminalSend: (event) => decide(event.inputKind, event.terminalId, event.text),
    promptBefore: (event) => decide(event.inputKind, event.terminalId, event.prompt)
  }
}
