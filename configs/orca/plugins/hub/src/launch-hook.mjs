// What the plugin adds when Orca starts Claude Code, so the panel has tasks to show without the
// user editing any settings. Claude Code leaves its task tools off on newer models and writes no
// goal unless told to, so it gets both. All of this lasts for that one session and touches no file
// of the user's.
//
// Adapted from andoshin11/orca-milestone src/launch-hook.mjs (MIT, see ../LICENSE and ../NOTICE.md).
// Left out on purpose: the `next` block instructions (buttons that type into the session), the
// `--settings` PermissionRequest hook that allowed the rest of a turn, and the Codex MCP tool.

// Kept free of single quotes, since it goes on a command line inside them.
const CLAUDE_INSTRUCTIONS = [
  'The user follows your progress in a sidebar that reads your task list, so record your work as tasks without being asked.',
  'Whenever the work takes three or more tool calls, you must first split it into about 3 to 7 steps with TaskCreate, before the first of those calls. This holds even when the work looks light, is read-only, or runs its calls in parallel. Only a question you can answer with one or two tool calls is exempt. Write each subject as a short step in the language the user writes in.',
  'Give every task metadata: {"goal": "<one line, about 40 characters, in the language of the user, saying what the current request aims for>"}. The sidebar uses it as its heading. Work out the goal from the conversation even when the request is a short reply.',
  'When you start a step, mark it in_progress with TaskUpdate, and mark it completed as soon as it is done. Update one at a time, with only one in_progress at once.',
  'If steps are added or change within the same goal, add or update tasks with the same goal, and mark tasks no longer needed as deleted.',
  'When the goal changes, first mark the tasks of the old goal completed or deleted so none stay pending or in_progress, then create new tasks with the new goal. The sidebar shows only the newest goal.',
  'If tasks exist without a goal, add one with TaskUpdate metadata. If the task tools are unavailable, carry on without them.'
].join(' ')

/** What a Claude session started now is told. */
export function claudeInstructions() {
  return CLAUDE_INSTRUCTIONS
}

/**
 * Adds the instructions to a command line that starts with claude, or with the `orca claude-teams`
 * that Orca runs for Agent Teams and that hands its arguments on to claude. Anything else is left
 * alone, and so is a command line that already appends a system prompt, since the last flag would
 * win over the other. Nothing else is added: no --settings, so the user's own hooks decide every
 * permission.
 */
export function withTaskInstructions(command) {
  const match = command.match(/^((?:\S*\/)?(?:claude|orca(?:-dev|-ide)?\s+claude-teams))(?=\s|$)/)
  if (!match || /\s--append-system-prompt(-file)?(\s|=)/.test(command)) return command
  return `${match[1]} --append-system-prompt '${CLAUDE_INSTRUCTIONS}'${command.slice(match[1].length)}`
}

export function createLaunchHook() {
  return (event, next) => {
    if (event.agent === 'claude' || event.agent === 'claude-agent-teams') {
      return next({
        ...event,
        command: withTaskInstructions(event.command),
        env: { ...event.env, CLAUDE_CODE_ENABLE_TODO_TOOLS: '1' }
      })
    }
    return undefined
  }
}
