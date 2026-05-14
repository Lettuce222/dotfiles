#!/bin/bash
# Claude Code Statusline - Token & Cost tracker
input=$(cat)

# Extract values with null fallbacks
MODEL=$(echo "$input" | jq -r '.model.display_name')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
INPUT_TOKENS=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
OUTPUT_TOKENS=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')

# Colors (True Color)
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[38;2;115;218;202m'    # #73daca
GREEN='\033[38;2;158;206;106m'   # #9ece6a
YELLOW='\033[38;2;224;175;104m'  # #e0af68
RED='\033[38;2;247;118;142m'     # #f7768e
BLUE='\033[38;2;122;162;247m'    # #7aa2f7
GRAY='\033[38;2;86;95;137m'      # #565f89

# Context bar with threshold-based color
if [ "$PCT" -ge 90 ]; then BAR_COLOR="$RED"
elif [ "$PCT" -ge 70 ]; then BAR_COLOR="$YELLOW"
else BAR_COLOR="$GREEN"; fi

BAR_WIDTH=15
FILLED=$((PCT * BAR_WIDTH / 100))
EMPTY=$((BAR_WIDTH - FILLED))
BAR=""
[ "$FILLED" -gt 0 ] && printf -v FILL "%${FILLED}s" && BAR="${FILL// /█}"
[ "$EMPTY" -gt 0 ] && printf -v PAD "%${EMPTY}s" && BAR="${BAR}${PAD// /░}"

# Format tokens (K/M)
TOTAL_TOKENS=$((INPUT_TOKENS + OUTPUT_TOKENS))
if [ "$TOTAL_TOKENS" -ge 1000000 ]; then
  TOKENS_FMT=$(printf '%.1fM' "$(echo "$TOTAL_TOKENS / 1000000" | bc -l)")
elif [ "$TOTAL_TOKENS" -ge 1000 ]; then
  TOKENS_FMT=$(printf '%.1fK' "$(echo "$TOTAL_TOKENS / 1000" | bc -l)")
else
  TOKENS_FMT="${TOTAL_TOKENS}"
fi

# Format input/output tokens individually
if [ "$INPUT_TOKENS" -ge 1000000 ]; then
  IN_FMT=$(printf '%.1fM' "$(echo "$INPUT_TOKENS / 1000000" | bc -l)")
elif [ "$INPUT_TOKENS" -ge 1000 ]; then
  IN_FMT=$(printf '%.1fK' "$(echo "$INPUT_TOKENS / 1000" | bc -l)")
else
  IN_FMT="${INPUT_TOKENS}"
fi

if [ "$OUTPUT_TOKENS" -ge 1000000 ]; then
  OUT_FMT=$(printf '%.1fM' "$(echo "$OUTPUT_TOKENS / 1000000" | bc -l)")
elif [ "$OUTPUT_TOKENS" -ge 1000 ]; then
  OUT_FMT=$(printf '%.1fK' "$(echo "$OUTPUT_TOKENS / 1000" | bc -l)")
else
  OUT_FMT="${OUTPUT_TOKENS}"
fi

# Format cost with threshold color
COST_FMT=$(printf '%.2f' "$COST")
if (( $(echo "$COST > 2.00" | bc -l) )); then COST_COLOR="$RED"
elif (( $(echo "$COST > 1.00" | bc -l) )); then COST_COLOR="$YELLOW"
else COST_COLOR="$GREEN"; fi

# Output
printf "${CYAN}${BOLD}${MODEL}${RESET} ${GRAY}│${RESET} ${BAR_COLOR}${BAR} ${PCT}%%${RESET} ${GRAY}│${RESET} ${BLUE}↑${IN_FMT} ↓${OUT_FMT}${RESET} ${GRAY}│${RESET} ${COST_COLOR}\$${COST_FMT}${RESET}\n"
