// A project's latest action, and what the panel can ask the orchestrator to do about it.
//
// The latest action is the first TODO in the order cases.py gives (a date, the soonest first, then
// `!`, then the rest in the file's order); without a TODO, the first Waiting. A project with
// neither has none.

export const CHOICES = {
  todo: [
    { id: 'go', label: '進めて', detail: '窓口が worker を起こすか自分で進める' },
    { id: 'later', label: '後回し', detail: 'Later に移す' },
    { id: 'done', label: '済んだ', detail: 'TODO から消す' }
  ],
  waiting: [
    { id: 'resolved', label: '待ちが解けた', detail: '消して、→ のあとを TODO に移す' },
    { id: 'check', label: '確かめて', detail: '待ちの相手や状態を調べ、必要なら催促の下書きを作る' }
  ]
}

const WHAT = { todo: 'TODO', waiting: 'Waiting' }

export function latestAction(project) {
  if (project.todo.length > 0) return { kind: 'todo', ...project.todo[0] }
  if (project.waiting.length > 0) return { kind: 'waiting', ...project.waiting[0] }
  return null
}

/**
 * The line the orchestrator gets for a choice or a written note, or null when neither fits.
 * The case and the item are named in full, so the orchestrator finds them in the case file.
 */
export function actionText(project, action, { choice, note }) {
  const head = `案件「${project.short}」（${project.slug}.md）の${WHAT[action.kind]}「${action.text}」について、ユーザーの指示:`
  if (typeof note === 'string') return `${head} ${note}`
  const picked = CHOICES[action.kind].find((c) => c.id === choice)
  return picked ? `${head} ${picked.label}（${picked.detail}）` : null
}
