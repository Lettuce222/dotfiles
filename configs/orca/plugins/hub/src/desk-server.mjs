// Serves the desk (desk/index.html) to Orca's built-in browser from the plugin's worker, on
// 127.0.0.1 only, at a port the system picks, with a token made at each start. The HTTP layer only:
// what each call does is in the handlers (src/desk.mjs).
//
// Guards, since any page in any browser on this computer can reach 127.0.0.1:
// - every API call needs the token (the X-Desk-Token header; the event stream, which cannot send a
//   header, takes it as ?t=), compared in constant time;
// - the Host header must name this server (a DNS rebinding page has its own host name);
// - a write must be a POST of application/json (a form of another site cannot send that without a
//   preflight, which this server never answers) and its Origin, when sent, must be this server;
// - no CORS headers, a strict Content-Security-Policy, and request bodies of at most 64 KiB.
import { randomBytes, timingSafeEqual } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { createServer } from 'node:http'
import { join } from 'node:path'

const BODY_MAX = 64 * 1024
const HEARTBEAT_MS = 25_000
const TYPES = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8' }
const CSP = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
// The page for the desk's address without the right token: what to do, and no token. Titled デスク
// like the desk, so that opening the desk finds this tab and loads it anew (src/desk-tab.mjs).
// desk/reopen.mjs asks again with the token the tab keeps, which is all a reload needs.
const STALE_PAGE = `<!doctype html>
<html lang="ja">
<head><meta charset="utf-8"><title>デスク</title>
<style>body{font:15px/1.7 -apple-system,BlinkMacSystemFont,sans-serif;margin:3em auto;max-width:36em;padding:0 1em}</style>
<script type="module" src="/reopen.mjs"></script>
</head>
<body><h1>デスク</h1><p>鍵が古くなりました。Orca のステータスバーの「デスク」を押して開き直してください。</p></body>
</html>
`
export const POSTS = ['add', 'move', 'done', 'open', 'focus', 'from-case', 'case-project', 'answer']

export class DeskError extends Error {
  constructor(status, message) {
    super(message)
    this.status = status
  }
}

/** The files the page loads, by URL path, from the plugin's folder. */
export function deskFiles(pluginDir) {
  return {
    '/': join(pluginDir, 'desk', 'index.html'),
    '/desk.css': join(pluginDir, 'desk', 'desk.css'),
    '/desk.mjs': join(pluginDir, 'desk', 'desk.mjs'),
    '/keys.mjs': join(pluginDir, 'desk', 'keys.mjs'),
    '/reopen.mjs': join(pluginDir, 'desk', 'reopen.mjs'),
    '/markdown.mjs': join(pluginDir, 'src', 'markdown.mjs')
  }
}

function sameToken(given, token) {
  if (typeof given !== 'string') return false
  const a = Buffer.from(given)
  const b = Buffer.from(token)
  return a.length === b.length && timingSafeEqual(a, b)
}

function send(res, status, body, headers = {}) {
  const data = typeof body === 'string' || Buffer.isBuffer(body) ? body : JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': typeof body === 'string' || Buffer.isBuffer(body) ? 'text/plain; charset=utf-8' : 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    ...headers
  })
  res.end(data)
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > BODY_MAX) {
        reject(new DeskError(413, '本文が大きすぎる'))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => {
      try {
        const parsed = chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {}
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('object')
        resolve(parsed)
      } catch {
        reject(new DeskError(400, 'JSON でない'))
      }
    })
    req.on('error', reject)
  })
}

/**
 * @param handlers { state(): Promise<object>, add(body), move(body), done(body), open(body),
 *   focus(body), 'from-case'(body), 'case-project'(body), answer(body) }; a handler throws a
 *   DeskError (or an error with a numeric `status`) for an answer other than 500.
 */
export function createDeskServer({ pluginDir, handlers, token = randomBytes(24).toString('base64url'), files = deskFiles(pluginDir), log = () => {} }) {
  const clients = new Set()
  let server = null
  let port = null
  let rev = 0
  let heartbeat = null

  const origin = () => `http://127.0.0.1:${port}`
  const hostOk = (host) => host === `127.0.0.1:${port}` || host === `localhost:${port}`

  async function handle(req, res) {
    const url = new URL(req.url, origin())
    if (!hostOk(req.headers.host)) return send(res, 421, 'misdirected')
    if (req.method === 'GET' && Object.hasOwn(files, url.pathname)) {
      // The page itself only with the token, so that another page cannot frame or read it.
      if (url.pathname === '/' && !sameToken(url.searchParams.get('t'), token)) {
        return send(res, 403, STALE_PAGE, { 'Content-Type': TYPES['.html'], 'Content-Security-Policy': CSP })
      }
      const path = files[url.pathname]
      const type = TYPES[path.slice(path.lastIndexOf('.'))] ?? 'application/octet-stream'
      try {
        return send(res, 200, await readFile(path), { 'Content-Type': type, 'Content-Security-Policy': CSP })
      } catch {
        return send(res, 404, 'not found')
      }
    }
    if (!url.pathname.startsWith('/api/')) return send(res, 404, 'not found')
    if (url.pathname === '/api/events' && req.method === 'GET') {
      if (!sameToken(url.searchParams.get('t'), token)) return send(res, 403, { ok: false, error: 'トークンが違う' })
      res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', Connection: 'keep-alive', 'X-Content-Type-Options': 'nosniff' })
      res.write(`retry: 5000\nevent: change\ndata: ${JSON.stringify({ rev })}\n\n`)
      clients.add(res)
      req.on('close', () => clients.delete(res))
      return
    }
    if (!sameToken(req.headers['x-desk-token'], token)) return send(res, 403, { ok: false, error: 'トークンが違う（デスクを開き直してください）' })
    if (url.pathname === '/api/state' && req.method === 'GET') {
      return send(res, 200, { ok: true, rev, ...(await handlers.state()) })
    }
    const name = url.pathname.slice('/api/'.length)
    if (!POSTS.includes(name)) return send(res, 404, { ok: false, error: 'not found' })
    if (req.method !== 'POST') return send(res, 405, { ok: false, error: 'POST だけ' }, { Allow: 'POST' })
    if (!String(req.headers['content-type'] ?? '').startsWith('application/json')) return send(res, 415, { ok: false, error: 'application/json だけ' })
    if (req.headers.origin && req.headers.origin !== origin() && req.headers.origin !== `http://localhost:${port}`) return send(res, 403, { ok: false, error: 'ほかのページからは書けない' })
    const body = await readBody(req)
    const result = await handlers[name](body)
    return send(res, 200, { ok: true, ...(result ?? {}) })
  }

  function onRequest(req, res) {
    handle(req, res).catch((error) => {
      const status = Number.isInteger(error?.status) ? error.status : 500
      if (status === 500) log(`desk: ${req.method} ${req.url?.split('?')[0]} failed: ${error?.stack ?? error}`)
      if (!res.headersSent) send(res, status, { ok: false, error: status === 500 ? `デスクの中でエラー: ${error?.message ?? error}` : error.message })
    })
  }

  /** Tells every open page that the items or the cases changed. */
  function notify() {
    rev += 1
    for (const res of clients) res.write(`event: change\ndata: ${JSON.stringify({ rev })}\n\n`)
  }

  /**
   * Listens on 127.0.0.1 at listenPort, or at a port the system picks when it is 0 or taken. A port
   * that stays the same from one start to the next keeps an open desk tab pointed at this server.
   */
  async function start(listenPort = 0) {
    if (server) return { port, url: `${origin()}/?t=${token}` }
    try {
      return await listenOn(listenPort)
    } catch (error) {
      if (listenPort === 0 || error?.code !== 'EADDRINUSE') throw error
      log(`desk: 127.0.0.1:${listenPort} is taken; serving on a port the system picks`)
      return listenOn(0)
    }
  }

  function listenOn(listenPort) {
    return new Promise((resolve, reject) => {
      const created = createServer(onRequest)
      created.on('error', reject)
      created.listen(listenPort, '127.0.0.1', () => {
        server = created
        port = created.address().port
        heartbeat = setInterval(() => {
          for (const res of clients) res.write(': keep\n\n')
        }, HEARTBEAT_MS)
        heartbeat.unref?.()
        resolve({ port, url: `${origin()}/?t=${token}` })
      })
    })
  }

  function close() {
    clearInterval(heartbeat)
    for (const res of clients) res.end()
    clients.clear()
    const closing = server
    server = null
    return new Promise((resolve) => (closing ? closing.close(() => resolve()) : resolve()))
  }

  return {
    start,
    close,
    notify,
    get port() {
      return port
    },
    get url() {
      return port ? `${origin()}/?t=${token}` : null
    },
    get origin() {
      return port ? origin() : null
    },
    get clients() {
      return clients.size
    }
  }
}
