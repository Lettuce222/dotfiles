// The orchestrator's cards on the desk: its questions (asks.py question, with --approval or not), its
// permission dialogs held back by approval-gate.py --panel, and answers written but not yet told to
// it. The worker builds them for the panel (src/hub-worker.mjs); here they become what the desk page
// shows, and an answer from the page is checked before it goes the panel's way (answerAsk), which
// writes the answer file and tells the orchestrator, again every 30 seconds until it takes it.
//
// The page gets data, never HTML: it escapes every text and shows the characters that do not show
// (desk/asks.mjs). A card says why it offers no buttons, and the permission card keeps the panel's
// rules: no allow for a call that reaches past this machine, and a dangerous one is pressed twice.
import { ASK_ID, PERMISSION_CHOICES, SHA256 } from './asks.mjs'
import { DeskError } from './desk-server.mjs'
import { CHECK_NOTES, FAILURES, ORCHESTRATOR_FAILURES, PERMISSION_NOTES, RISK_LABELS } from './hub-render.mjs'

const WRITTEN_MAX = 2000

/** What the desk page shows of the orchestrator's cards, newest kinds first as the panel orders them. */
export function deskOrchestratorCards(cards) {
  return (Array.isArray(cards) ? cards : []).map(deskCard).filter(Boolean)
}

function deskCard(card) {
  if (!card || !ASK_ID.test(card.id ?? '')) return null
  if (card.kept) {
    return {
      id: card.id,
      kind: 'kept',
      question: String(card.question ?? ''),
      label: String(card.label ?? ''),
      note: `まだ窓口に知らせられていません: ${ORCHESTRATOR_FAILURES[card.reason] ?? ORCHESTRATOR_FAILURES.failed} 窓口が受け取れるようになったら、自動で知らせます。`
    }
  }
  const ready = card.check?.ok === true
  const base = {
    id: card.id,
    sha: card.sha,
    ready,
    note: ready ? null : (card.kind === 'permission' ? PERMISSION_NOTES[card.check?.reason] : null) ?? CHECK_NOTES[card.check?.reason] ?? '窓口のターミナルで答えてください。',
    pressed: card.pressed ?? null,
    failure: card.failure ? (FAILURES[card.failure] ?? FAILURES.failed) : null
  }
  if (card.kind === 'question') {
    return {
      ...base,
      kind: 'question',
      approval: card.approval === true,
      question: card.question,
      body: card.body ?? null,
      options: card.options.map(({ label, description }) => ({ label, description })),
      recommended: card.recommended ?? null
    }
  }
  if (card.kind === 'permission') {
    return {
      ...base,
      kind: 'permission',
      toolName: card.toolName,
      agentType: card.agentType ?? null,
      input: card.input,
      risk: card.risk,
      riskLabel: card.dangerous ? '危険なコマンド' : RISK_LABELS[card.risk] ?? null,
      dangerous: card.dangerous === true,
      canAllow: card.risk !== 'outside',
      where: card.where || card.cwd || '',
      expiresAt: card.expiresAt
    }
  }
  return null
}

/** How many of the cards wait on the user: not answered yet, and not only waiting to be told. */
export function waitingCount(cards) {
  return deskOrchestratorCards(cards).filter((card) => card.kind !== 'kept' && card.pressed === null).length
}

/**
 * An answer from the page, checked against the card it is for: the same ask as shown (sha), an
 * option it has, or a written answer. Returns what answerAsk takes; throws a DeskError otherwise.
 */
export function orchestratorAnswer(body, cards) {
  const card = (Array.isArray(cards) ? cards : []).find((candidate) => !candidate.kept && candidate.id === body?.askId)
  if (!card) return null
  if (!SHA256.test(body.sha ?? '') || body.sha !== card.sha) throw new DeskError(409, '問いが変わった（読み直してください）')
  if (body.text !== undefined) {
    if (typeof body.text !== 'string' || !body.text.trim() || body.text.length > WRITTEN_MAX) throw new DeskError(400, '書いた答えが空か長すぎる')
    return { id: card.id, sha: card.sha, text: body.text }
  }
  if (card.kind === 'permission') {
    if (!PERMISSION_CHOICES.includes(body.choice)) throw new DeskError(400, '答えの形が違う')
    if (body.choice === 'allow' && card.risk === 'outside') throw new DeskError(400, '外に出る操作は、デスクでは許可できない')
    return { id: card.id, sha: card.sha, choice: body.choice, ...(body.confirmed === true ? { confirmed: true } : {}) }
  }
  if (!Number.isInteger(body.choice) || body.choice < 1 || body.choice > card.options.length) throw new DeskError(400, '答えの番号が違う')
  return { id: card.id, sha: card.sha, choice: body.choice }
}

/** What the page is told of answerAsk's result for an orchestrator's card. */
export function orchestratorResult(result) {
  if (result?.ok) return {}
  if (result?.reason === 'kept') return { kept: true, message: result.message }
  if (result?.reason === 'confirm') throw new DeskError(409, '危険なコマンドです。もう一度押すと許可します')
  if (result?.reason === 'pressed') throw new DeskError(409, 'もう答えを送っている')
  throw new DeskError(409, FAILURES[result?.reason] ?? `答えを渡せなかった（${result?.reason ?? '不明'}）`)
}
