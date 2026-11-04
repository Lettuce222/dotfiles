import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, Timer } from 'claude-code'

import type { GtdItem, HubStatus, PrEntry, Proposal, Snapshot, WorkerEntry } from '../types'
import { openProposals, parseProposals } from './proposals'
import { linkify, repoFromUrl } from './links'
import type { LinkContext } from './links'

// hub（~/hub で起動したセッション）の横に、判断待ち・worker・期限・GTD・PR を出す。
// 中身は dotfiles の dash.py の `status --json` をそのまま使い、ここでは描くだけにする。
// 答えは `dash.py answer` に渡す（worker の pane へ送り、報告のファイルに残る）。
// 提案（~/hub/proposals.md）への承認・却下・一言は、hub への発言として送る。

const PANE = 'hub-dashboard'
const TITLE = 'hub'
const REFRESH_MS = 20_000
const MIN_GAP_MS = 5_000

const snapshot = atom({ plugin: 'hub-dashboard', key: 'snapshot' } as const, null, {
  shape: 'snapshot-3',
})
const drafts = atom({ plugin: 'hub-dashboard', key: 'drafts' } as const, {}, {
  shape: 'drafts-1',
})
// ボタンを押した提案は、hub が proposals.md を書き換えるまでの間も隠す（押した時刻、10 分で忘れる）
const handled = atom({ plugin: 'hub-dashboard', key: 'handled' } as const, {}, {
  shape: 'handled-1',
})
const HANDLED_TTL_MS = 10 * 60_000
const collapsed = atom({ plugin: 'hub-dashboard', key: 'collapsed' } as const, ['next'], {
  shape: 'collapsed-2',
})

const STATUS_MARK: Record<string, string> = {
  busy: '⚙',
  idle: '⏸',
  permission: '🔴',
  no_window: '✕',
}

export function shortWorker(name: string): string {
  const dot = name.indexOf('.')
  return dot === -1 ? name : name.slice(dot + 1)
}

export function prLabel(p: PrEntry): string {
  const repo = p.repo?.split('/').pop() ?? ''
  const states = (p.states ?? [])
    .map(s => (typeof s === 'string' ? s : s.state ?? ''))
    .filter(Boolean)
    .join(',')
  return `${repo}#${p.number ?? '?'} ${states}`.trim()
}

export function dueLabel(it: GtdItem): string {
  const d = it.days_left
  if (d === undefined) return it.attrs.due ?? ''
  if (d < 0) return `${-d}日超過`
  if (d === 0) return '今日'
  return `あと${d}日`
}

export function workerLine(w: WorkerEntry): string {
  const mark = STATUS_MARK[w.status] ?? '?'
  const pr = w.pr?.number ? ` #${w.pr.number}${w.pr.ci ? ` ${w.pr.ci}` : ''}` : ''
  return `${mark} ${shortWorker(w.name)}${pr}`
}

export function parseStatus(stdout: string): HubStatus {
  const raw = JSON.parse(stdout) as Partial<HubStatus>
  return {
    generated_at: raw.generated_at,
    inbox: raw.inbox ?? [],
    workers: raw.workers ?? [],
    gtd: {
      doing: raw.gtd?.doing ?? [],
      waiting: raw.gtd?.waiting ?? [],
      next: raw.gtd?.next ?? [],
      next_total: raw.gtd?.next_total,
      due_soon: raw.gtd?.due_soon ?? [],
      inbox_total: raw.gtd?.inbox_total,
    },
    prs: {
      pending: raw.prs?.pending,
      review_requests: raw.prs?.review_requests ?? [],
      own_action: raw.prs?.own_action ?? [],
      team_requests: raw.prs?.team_requests,
    },
    errors: raw.errors ?? {},
  }
}

const ctx: {
  dashPy: string | undefined
  proposalsMd: string | undefined
  jira: string | undefined
  outbox: string | undefined
  askedSig: string | undefined
  running: boolean
  lastRun: number
} = {
  dashPy: undefined,
  proposalsMd: undefined,
  jira: undefined,
  outbox: undefined,
  askedSig: undefined,
  running: false,
  lastRun: 0,
}

async function refresh($: EngineInterface, force = false): Promise<void> {
  if (ctx.dashPy === undefined || ctx.running) return
  const now = await $.clock.now()
  if (!force && now - ctx.lastRun < MIN_GAP_MS) return
  ctx.running = true
  ctx.lastRun = now
  try {
    const proposals = await loadProposals($)
    const r = await $.process.run(['/usr/bin/env', 'python3', ctx.dashPy, 'status', '--json'])
    const loadedAt = new Date(await $.clock.now()).toISOString()
    if (r.exitCode !== 0) {
      const msg = (r.stderr || r.stdout).trim().split('\n').pop() ?? `exit ${r.exitCode}`
      await update($, snapshot, prev => ({ status: prev?.status ?? null, proposals, error: msg, loadedAt }))
      return
    }
    const status = parseStatus(r.stdout)
    await update($, snapshot, () => ({ status, proposals, error: null, loadedAt }))
    askForProposals($, status, proposals)
  } catch (err) {
    const loadedAt = new Date(await $.clock.now()).toISOString()
    await update($, snapshot, prev => ({
      status: prev?.status ?? null,
      proposals: prev?.proposals ?? [],
      error: String(err),
      loadedAt,
    }))
  } finally {
    ctx.running = false
  }
}

async function loadProposals($: EngineInterface): Promise<Proposal[]> {
  if (ctx.proposalsMd === undefined) return []
  try {
    const text = (await $.fs.read(ctx.proposalsMd)) as string
    const open = openProposals(parseProposals(text))
    const now = await $.clock.now()
    const marks = await read($, handled)
    const stillOpen = new Set(open.map(p => p.id))
    // 決まった（ファイルで閉じた）ものと、古くなった印は捨てる
    const kept: Record<string, number> = {}
    for (const [id, at] of Object.entries(marks)) {
      if (stillOpen.has(id) && now - at < HANDLED_TTL_MS) kept[id] = at
    }
    if (Object.keys(kept).length !== Object.keys(marks).length) await update($, handled, () => kept)
    return open.filter(p => kept[p.id] === undefined)
  } catch {
    return []
  }
}

// ターンの終わりを待たない（押下のフックには 10 秒の上限がある）
function say($: EngineInterface, text: string): void {
  void $.prompt.submit({ text, asUser: true }).catch(() => undefined)
  $.ui.toast('hub に送りました')
}

async function openUrl($: EngineInterface, href: string): Promise<void> {
  if (!/^https?:\/\//.test(href)) return
  await $.process.run(['/usr/bin/open', href])
}

// 承認の印は、ユーザーがボタンを押したこの時点で mod が書く（モデルには書かせない）。
// 送る文面（outbox/<ID>.md）がある提案だけ。hook が文面と送信先、30 分の期限を照合して送信を通す。
async function markApproved($: EngineInterface, id: string): Promise<void> {
  if (ctx.outbox === undefined || !/^P\d+$/.test(id)) return
  try {
    await $.fs.stat(`${ctx.outbox}/${id}.md`)
  } catch {
    return
  }
  const at = new Date(await $.clock.now()).toISOString()
  await $.fs.write(`${ctx.outbox}/${id}.approved`, `${at}\n`)
}

async function decide($: EngineInterface, id: string, verdict: string, fb: string): Promise<void> {
  if (verdict === '承認します') await markApproved($, id).catch(() => undefined)
  // 一言だけのときは提案を残す。承認・却下・あとでは、押した時点でペインから消す
  if (verdict !== 'について一言') {
    const now = await $.clock.now()
    await update($, handled, h => ({ ...h, [id]: now }))
    await update($, snapshot, prev =>
      prev === null ? prev : { ...prev, proposals: prev.proposals.filter(p => p.id !== id) },
    )
  }
  const note = fb.trim() === '' ? '' : ` 一言: ${fb.trim()}`
  say($, `提案 ${id} を${verdict}。${note}`)
  await update($, drafts, d => {
    const next = { ...d }
    delete next[id]
    return next
  })
}

// 提案が空なのに次にやること・inbox が残っていたら、hub に提案を作るよう頼む。
// 同じ中身のままなら頼み直さない（全部が人待ちのときに繰り返さないため）
function askForProposals($: EngineInterface, status: HubStatus, proposals: Proposal[]): void {
  if (proposals.length > 0) return
  const nextCount = status.gtd.next_total ?? status.gtd.next.length
  const inboxCount = status.gtd.inbox_total ?? 0
  if (nextCount === 0 && inboxCount === 0) return
  const sig = JSON.stringify([status.gtd.next.map(i => i.body), inboxCount])
  if (sig === ctx.askedSig) return
  ctx.askedSig = sig
  const parts = [] as string[]
  if (nextCount > 0) parts.push(`次にやることが ${nextCount} 件`)
  if (inboxCount > 0) parts.push(`inbox が ${inboxCount} 件`)
  say(
    $,
    `［ペインから自動］提案が 0 件ですが、${parts.join('、')}あります。そこから次の提案を作ってください（inbox があれば整理の提案を先に）。人待ちで動かせないものは提案にせず、理由を 1 行で返してください。`,
  )
}

// hub-dash（ブラウザのダッシュボード）を開く。動いていなければ裏で起動する
async function openHubDash($: EngineInterface): Promise<void> {
  if (ctx.dashPy === undefined) return
  const cmd = `nohup /usr/bin/env python3 '${ctx.dashPy}' --open >/dev/null 2>&1 &`
  await $.process.run(['/bin/sh', '-c', cmd])
  $.ui.toast('hub-dash を開きます')
}

async function answer(
  $: EngineInterface,
  worker: string,
  ref: string,
  text: string | null,
): Promise<void> {
  if (ctx.dashPy === undefined) return
  const argv = ['/usr/bin/env', 'python3', ctx.dashPy, 'answer', worker, ref]
  if (text === null) argv.push('--done')
  else argv.push(text)
  const r = await $.process.run(argv)
  const line = (r.stdout || r.stderr).trim().split('\n').pop() ?? ''
  $.ui.toast(r.exitCode === 0 ? `送りました: ${shortWorker(worker)}` : `送れませんでした: ${line}`)
  await refresh($, true)
}

export const register: Register = on => {
  let timer: Timer | undefined

  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const home = await $.env.get('HOME')
    const root = await $.session.root()
    if (home === undefined || root !== `${home}/hub`) return result

    ctx.dashPy = `${home}/.config/tmux/scripts/agent-hub/dash.py`
    ctx.proposalsMd = `${root}/proposals.md`
    ctx.outbox = `${root}/outbox`
    try {
      const conf = JSON.parse((await $.fs.read(`${root}/pane.json`)) as string) as { jira?: string }
      ctx.jira = conf.jira
    } catch {
      ctx.jira = undefined
    }
    await refresh($, true)
    timer?.cancel()
    timer = $.clock.every(REFRESH_MS, () => void refresh($, true))
    await $.command.register({
      name: 'gtd-dashboard',
      description: 'hub の状況ペイン（判断待ち・worker・GTD・PR）を開く',
    })
    void $.ui.open({ id: PANE, title: TITLE })

    return result
  })

  on('command.run', { command: 'gtd-dashboard' }, async $ => {
    await refresh($, true)
    await $.ui.open({ id: PANE, title: TITLE })
    return { text: 'hub の状況ペインを開きました。' }
  })

  // gtd/ や worker の状態を変えうるツールの直後に読み直す
  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (ctx.dashPy !== undefined && ['Write', 'Edit', 'Bash', 'SendMessage'].includes(e.tool)) {
      await refresh($).catch(() => undefined)
    }
    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const ui = $.ui.resolve(e)
    const { Box, Button, Text } = ui
    const Input = 'Input' in ui ? ui.Input : undefined
    const Markdown = 'Markdown' in ui ? ui.Markdown : undefined
    let mdSeq = 0
    // リンクを含む 1 行。クリックで既定のブラウザを開く。Markdown の無い面では素の文字
    const md = (text: string, linkCtx: Omit<LinkContext, 'jira'>, prefix = '') => {
      if (Markdown === undefined) return <Text wrap="wrap">{prefix}{text}</Text>
      mdSeq += 1
      return (
        <Markdown
          key={`md-${mdSeq}`}
          text={`${prefix}${linkify(text, { ...linkCtx, jira: ctx.jira })}`}
          onLinkPress={link => void openUrl($, link.href)}
        />
      )
    }
    const snap = await read($, snapshot)
    const draft = await read($, drafts)
    const closed = await read($, collapsed)

    if (snap === null) return <Text dimColor>状況を読み込んでいます…</Text>

    const s = snap.status
    const loaded = new Date(snap.loadedAt)
    const hhmm = `${String(loaded.getHours()).padStart(2, '0')}:${String(loaded.getMinutes()).padStart(2, '0')}`
    const toggle = (id: string) =>
      update($, collapsed, list => (list.includes(id) ? list.filter(x => x !== id) : [...list, id]))
    const head = (id: string, label: string, count: number, color?: string) => (
      <Button key={`head-${id}`} plain onPress={() => toggle(id)}>
        {closed.includes(id) ? '▶' : '▼'} <Text bold color={color}>{label}</Text>{' '}
        <Text dimColor>{count}</Text>
      </Button>
    )
    const open = (id: string) => !closed.includes(id)

    if (s === null) {
      return (
        <Box flexDirection="column">
          <Text color="red">読み込めませんでした: {snap.error ?? ''}</Text>
        </Box>
      )
    }

    const errKeys = Object.keys(s.errors)

    return (
      <Box flexDirection="column">
        <Box flexDirection="row">
          <Button key="open-dash" plain onPress={() => void openHubDash($)}>
            <Text color="cyan">[hub-dash を開く ↗]</Text>
          </Button>
        </Box>
        <Text dimColor>
          更新 {hhmm}
          {snap.error ? <Text color="yellow"> （前回の値。{snap.error}）</Text> : null}
          {errKeys.length > 0 ? <Text color="yellow"> 取れなかった: {errKeys.join(', ')}</Text> : null}
        </Text>

        <Box flexDirection="column" marginTop={1}>
          {head('proposals', '提案', snap.proposals.length, snap.proposals.length > 0 ? 'cyan' : undefined)}
          {open('proposals') && snap.proposals.length === 0 && <Text dimColor>  なし</Text>}
          {open('proposals') &&
            snap.proposals.map(p => (
              <Box key={`p-${p.id}`} flexDirection="column" marginBottom={1}>
                {md(
                  `${p.title}${p.mark === '>' ? '（あとで）' : ''}`,
                  { repo: repoFromUrl(p.attrs.source) ?? p.attrs.repo },
                  `**${p.id}** `,
                )}
                {p.attrs.plan ? md(p.attrs.plan, { repo: repoFromUrl(p.attrs.source) ?? p.attrs.repo }, '→ ') : null}
                {p.attrs.source ? md(p.attrs.source, {}, 'きっかけ: ') : null}
                <Box flexDirection="row">
                  <Text>{'     '}</Text>
                  <Button key={`ok-${p.id}`} onPress={() => decide($, p.id, '承認します', draft[p.id] ?? '')}>
                    承認
                  </Button>
                  <Text> </Text>
                  <Button key={`ng-${p.id}`} onPress={() => decide($, p.id, '却下します', draft[p.id] ?? '')}>
                    却下
                  </Button>
                  <Text> </Text>
                  <Button key={`later-${p.id}`} onPress={() => decide($, p.id, 'あとにします', draft[p.id] ?? '')}>
                    あとで
                  </Button>
                </Box>
                {Input !== undefined && (<Input
                  key={`fb-${p.id}`}
                  label="     一言 "
                  placeholder="承認・却下に添える一言（Enter で一言だけ送る）"
                  value={draft[p.id] ?? ''}
                  submitLabel="送る"
                  onInput={(v: string) => void update($, drafts, d => ({ ...d, [p.id]: v }))}
                  onSubmit={(v: string) => void decide($, p.id, 'について一言', v)}
                />)}
              </Box>
            ))}
          {Input !== undefined && (<Input
            key="say"
            label="  hub へ "
            placeholder="フィードバックや頼みごと（Enter で送る）"
            submitLabel="送る"
            onSubmit={(v: string) => {
              if (v.trim() !== '') say($, v.trim())
            }}
          />)}
        </Box>

        <Box flexDirection="column" marginTop={1}>
          {head('inbox', '判断待ち', s.inbox.length, s.inbox.length > 0 ? 'red' : undefined)}
          {open('inbox') && s.inbox.length === 0 && <Text dimColor>  なし</Text>}
          {open('inbox') &&
            s.inbox.map((r, i) => (
              <Box key={`q-${r.worker}-${r.ref}`} flexDirection="column">
                <Text wrap="truncate-end">
                  {'  '}
                  <Text bold>Q{i + 1}</Text> [{r.kind}] {shortWorker(r.worker)}
                  {r.dialog ? <Text color="red"> 🔴確認画面</Text> : null}
                </Text>
                {md(r.summary, {})}
                {r.choices.map((c, j) => (
                  <Button
                    key={`c-${r.worker}-${r.ref}-${j}`}
                    plain
                    onPress={() => answer($, r.worker, r.ref, c)}
                  >
                    {'     '}
                    <Text color="cyan">[{String.fromCharCode(97 + j)}]</Text> {c}
                  </Button>
                ))}
                <Button key={`d-${r.worker}-${r.ref}`} plain onPress={() => answer($, r.worker, r.ref, null)}>
                  {'     '}
                  <Text dimColor>[済] 送らずに対応済みにする</Text>
                </Button>
              </Box>
            ))}
        </Box>

        <Box flexDirection="column" marginTop={1}>
          {head('workers', 'worker', s.workers.length)}
          {open('workers') && s.workers.length === 0 && <Text dimColor>  なし</Text>}
          {open('workers') &&
            s.workers.map(w => (
              <Box key={`w-${w.name}`} flexDirection="column">
                <Text wrap="truncate-end" color={w.status === 'permission' ? 'red' : undefined}>
                  {'  '}
                  {workerLine(w)}
                  {w.open_reports ? <Text color="red"> 未回答{w.open_reports}</Text> : null}
                </Text>
                {w.item ? md(w.item.body, { repo: w.item.attrs.repo }, '↳ ') : null}
              </Box>
            ))}
        </Box>

        {s.gtd.due_soon.length > 0 && (
          <Box flexDirection="column" marginTop={1}>
            {head('due', '期限が近い', s.gtd.due_soon.length, 'yellow')}
            {open('due') &&
              s.gtd.due_soon.map((it, i) => (
                <Box key={`due-${i}`}>{md(it.body, { repo: it.attrs.repo }, `**${dueLabel(it)}** `)}</Box>
              ))}
          </Box>
        )}

        <Box flexDirection="column" marginTop={1}>
          {head('doing', 'DOING', s.gtd.doing.length)}
          {open('doing') &&
            s.gtd.doing.map((it, i) => (
              <Box key={`doing-${i}`}>{md(it.body, { repo: it.attrs.repo }, '▸ ')}</Box>
            ))}
        </Box>

        <Box flexDirection="column" marginTop={1}>
          {head('waiting', '待ち', s.gtd.waiting.length)}
          {open('waiting') &&
            s.gtd.waiting.map((it, i) => (
              <Box key={`wait-${i}`}>
                {md(it.body, { repo: it.attrs.repo }, it.attrs.worker ? '🤖 ' : it.attrs.reported ? '✅ ' : '・')}
              </Box>
            ))}
        </Box>

        <Box flexDirection="column" marginTop={1}>
          {head('next', '次にやること', s.gtd.next_total ?? s.gtd.next.length)}
          {open('next') &&
            s.gtd.next.map((it, i) => (
              <Box key={`next-${i}`}>{md(it.body, { repo: it.attrs.repo }, `${i + 1}\\. `)}</Box>
            ))}
        </Box>

        <Box flexDirection="column" marginTop={1}>
          {head('prs', 'PR', s.prs.review_requests.length + s.prs.own_action.length)}
          {open('prs') && s.prs.pending && <Text dimColor>  取得中…</Text>}
          {open('prs') &&
            s.prs.review_requests.map((p, i) => (
              <Box key={`rr-${i}`}>{md(`${p.url ?? ''} ${p.title ?? ''}`, {}, '👀 ')}</Box>
            ))}
          {open('prs') &&
            s.prs.own_action.map((p, i) => (
              <Box key={`own-${i}`}>{md(`${p.url ?? ''} ${prLabel(p).split(' ').slice(1).join(' ')} ${p.title ?? ''}`, {}, '⚑ ')}</Box>
            ))}
          {open('prs') && (s.prs.team_requests ?? 0) > 0 && (
            <Text dimColor>  チーム宛ての依頼 {s.prs.team_requests}</Text>
          )}
        </Box>
      </Box>
    )
  })
}
