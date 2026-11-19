// Copied from andoshin11/orca-milestone src/dangerous.mjs (MIT, see ../LICENSE and ../NOTICE.md).
// Commands that ask for a second look before a card may allow them. A heuristic: it can miss one.
const DANGEROUS_COMMANDS = [
  /(^|[\s;&|(])rm(\s|$)/,
  /(^|[\s;&|(])sudo(\s|$)/,
  /\bgit\s+push\b[^;&|]*\s(--force(-with-lease)?|-f)(\s|$)/,
  /\bgit\s+reset\s+--hard\b/,
  /\bgit\s+clean\b/,
  /\bdd\s+if=/,
  /\bmkfs\b/,
  /\bchmod\s+-R\b/,
  /\bkubectl\s+delete\b/,
  /\bterraform\s+(destroy|apply)\b/,
  /\bdrop\s+(table|database)\b/i,
  /\btruncate\s+table\b/i
]

export function isDangerous(call) {
  return call.name === 'Bash' && typeof call.input?.command === 'string' && DANGEROUS_COMMANDS.some((pattern) => pattern.test(call.input.command))
}
