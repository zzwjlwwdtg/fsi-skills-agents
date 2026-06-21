# A+B 改动清单 — Claude 目标价 → paper_trader 限价执行

**实施日期**：2026-06-19
**快照位置**：`backups/agents_backup_YYYYMMDD_HHMMSS_with_AB.zip`

如需回滚 A+B（恢复"立即吃单 + 仅 trailing stop"行为），按以下清单逐项删除：

## decision_agent.py

**删除**：[_compute_buy_stop_ref](f:/fsi-skills/agents/decision_agent.py) 函数（约 30 行，紧邻 `_apply_trump_override` 之前）

```python
def _compute_buy_stop_ref(market: dict) -> float | None:
    """BUY/WATCH_BUY 时算保护性 stop_ref（broker 端 SELL STOP 用）。..."""
    ...
```

**改回**：两处 `stop_ref` 字段
1. `_etf_rules` 看涨评分路径（约 line 471）
   ```python
   # 现在
   "stop_ref": _compute_buy_stop_ref(market),
   # 改回
   "stop_ref": None,
   ```
2. V 反弹分支（约 line 412）
   ```python
   # 现在
   v_stop = _compute_buy_stop_ref(market)
   ...
   "stop_ref": v_stop,
   # 改回（删掉 v_stop 行）
   "stop_ref": None,
   ```

## ai_prompt.py

**删除**：函数 `_extract_targets_block` / `_normalize_target` / `_save_ai_targets` / `load_ai_target` 及 `_TARGETS_JSON_RE` / `_AI_TARGETS_PATH_PREFIX` / `import json as _json_mod`（一整块，约 100 行，在 `auto_analyze` 后面）

**改回**：`auto_analyze` 返回的 dict
```python
# 现在
if output:
    analysis_path.write_text(...)
    try:
        targets_path = _save_ai_targets(output, today)
    except Exception:
        targets_path = None
return {
    ...,
    "targets_path": targets_path if output else None,
    ...,
}
# 改回（删除 try/except + dict 里的 targets_path 项）
if output:
    analysis_path.write_text(...)
return {...}
```

**改回**：morning prompt 模板（zh + ja）末尾的 `⚠ 结构化目标输出` 整段删掉（zh 大约 35 行，ja 类似）。保留前面的 ⑪ 期权风险特别说明 + 格式要求。

## paper_trader.py

**删除**：`_load_ai_target_safe` 函数（紧邻 "AI target loader" 注释，约 10 行）

**改回**：`execute()` BUY 路径里 AI 限价覆盖逻辑（约 line 693-712）
```python
# 现在
if size_usd <= 0:
    return
ai_t = _load_ai_target_safe(ticker)
ai_price = float(price)
ai_use_limit = False
ai_stop_override = None
if ai_t and ai_t.get("action") in ("watch_buy", "buy"):
    ...
qty  = int(size_usd // ai_price)
side = TrdSide.BUY
stop = ai_stop_override or decision.get("stop_ref")

# 改回
if size_usd <= 0:
    return
qty  = int(size_usd // price)
side = TrdSide.BUY
stop = decision.get("stop_ref")
```

**改回**：_place 调用前的 AI 限价分支（约 line 725-735）
```python
# 现在
place_price = float(price)
place_buffer = win_cfg.get("buffer", 0.005)
place_tag = f"[{action} conf={conf} win={window} ...]"
if side == TrdSide.BUY and 'ai_use_limit' in locals() and ai_use_limit:
    place_price = ai_price
    place_buffer = 0.001
    place_tag = f"[{action} conf={conf} ... AI-LIMIT@${ai_price:.2f} ...]"
oid = _place(ticker, side, qty, place_price, tag=place_tag, buffer=place_buffer, ...)

# 改回
oid = _place(
    ticker, side, qty, float(price),
    tag=f"[{action} conf={conf} win={window} {'core' if is_core else 'sat'}]",
    buffer=win_cfg.get("buffer", 0.005),
    fill_outside_rth=win_cfg.get("fill_outside_rth", False),
)
```

## 数据文件（可选清理）

回滚后这些文件不再使用，可删：
- `signals/ai_targets_*.json`（Claude 输出的目标位 JSON）

## 验证回滚

回滚后跑：
1. `python _backtest_modules_accuracy.py` — 准确率应与 A+B 前一致（5d/10d/20d）
2. `python _snapshot_today.py` — decision 输出的 dict 里 `stop_ref: None`（V 反弹 + 看涨评分两条都是）
3. paper_trader 下单 log 不再出现 `AI-LIMIT@$X.XX` tag

## 重新应用 A+B

如果回滚后又想用，从快照 zip 里恢复 `decision_agent.py`/`ai_prompt.py`/`paper_trader.py` 三个文件即可。
