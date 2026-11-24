// The page shown for the desk's address without its token (src/desk-server.mjs). The desk takes the
// token out of the address once it has it (desk/desk.mjs), so reloading the tab asks for the page
// with none. The token this tab was given is still in its sessionStorage: ask again with it, once.
// When the address had a token and it was refused anyway, the worker started again with another
// one, and only Orca can give the tab the new one: the page says so.
const TOKEN_KEY = 'desk-token'
const asked = new URLSearchParams(location.search).has('t')
const kept = sessionStorage.getItem(TOKEN_KEY)
if (!asked && kept) location.replace(`/?t=${encodeURIComponent(kept)}${location.hash}`)
else if (asked) sessionStorage.removeItem(TOKEN_KEY)
