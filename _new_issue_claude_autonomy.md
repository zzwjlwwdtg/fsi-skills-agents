# Discuss: Claude autonomy for order triggering (currently gated by rule engine)

## Background

The system currently has 3-layer decision chain:
1. **decision_agent (rule-based)** — the boss, ONLY trigger for new orders (BUY/WATCH_BUY/SELL/REDUCE actions)
2. **claude_gate** — pre-trade risk gate, can only DOWNGRADE (BUY→HOLD), never UPGRADE
3. **Claude ai_targets JSON** — execution refinement only (entry_ref → LIMIT price, stop_ref → broker SELL STOP)

This means Claude cannot trigger a position on its own. If `decision_agent` says HOLD but Claude says `watch_buy @ $72.50`, the $72.50 order will never be placed.

## Rationale for current design (from `memory/`)

- `feedback_technical_only_mode.md`: TECHNICAL_ONLY=1 default ON — 决策只看技术面，消息面/AI 仅参考
- `feedback_oos_required.md`: Claude autonomous decisions have no OOS backtest (each prompt varies), N≤5 samples ≠ statistically valid
- Fail-safe: if Claude quota exhausted or CLI down, rule engine still works

## Question

Should we ever allow Claude to influence position triggering, and if so how?

## 3 candidate approaches (risk ascending)

### A — Conflict alert only (safest)
- When Claude `watch_buy` + rule engine `HOLD` → Discord alert: "Conflict on TICKER: rules HOLD but Claude BUY @ $X (stop $Y)"
- No auto-execution, human decides
- Zero risk to fail-safe

### B — Feature-flagged Claude probe (medium)
- New env `CLAUDE_AUTONOMY=1`
- New action `WATCH_BUY_CLAUDE` (30% position + strict stop_ref from Claude)
- Requires backtest before flip (like `CRISIS_VBOUNCE_ENABLED` pattern)
- Preserves rule engine as primary, Claude as override

### C — Peer decision (aggressive)
- Claude and rule engine equal weight
- **NOT recommended** given `feedback_oos_required` (5-sample bans)
- Effectively hands system to Claude

## Recommendation

Start with **A** — non-invasive, doesn't lose signal (get notified), preserves fail-safe. Later consider B after live A observations show cases where Claude was systematically right/wrong.

## Tasks (if A chosen)

- [ ] Add conflict detection in `paper_trader.execute` when `_load_ai_target_safe` returns `watch_buy/buy` but `decision.action` is not in ORDER_ACTIONS
- [ ] Send Discord alert via `notifications.send_alert(level="conflict")`
- [ ] Add stat tracking (weekly rollup: X conflicts, Y that user acted on manually)
- [ ] Dashboard: red badge on Claude ai_targets card if today has active conflict
