from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")
HORIZONS = (1, 3, 5, 20, 60)


@dataclass
class PriceMove:
    code: str
    yfinance_code: str
    prediction_day: str
    baseline_date: str = ""
    baseline_close: float | None = None
    latest_date: str = ""
    latest_price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    price_source: str = ""
    status: str = "missing"
    horizons: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "yfinance_code": self.yfinance_code,
            "prediction_day": self.prediction_day,
            "baseline_date": self.baseline_date,
            "baseline_close": self.baseline_close,
            "latest_date": self.latest_date,
            "latest_price": self.latest_price,
            "change": self.change,
            "change_pct": self.change_pct,
            "price_source": self.price_source,
            "status": self.status,
            "horizons": self.horizons,
        }


def _parse_day(value: str) -> date | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        try:
            return date.fromisoformat(str(value)[:10])
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST).date()


def _clean_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if hasattr(value, "item"):
            value = value.item()
        f = float(value)
        if f != f:
            return None
        return f
    except Exception:
        return None


def _latest_from_fast_info(ticker: Any) -> tuple[float | None, str]:
    try:
        fast = getattr(ticker, "fast_info", None)
        if not fast:
            return None, ""
        for key in ("last_price", "regular_market_price", "lastPrice"):
            try:
                price = _clean_float(fast.get(key) if hasattr(fast, "get") else getattr(fast, key))
            except Exception:
                price = None
            if price:
                return price, key
    except Exception:
        pass
    return None, ""


def _direction_for_side(side: str) -> int:
    s = (side or "").strip().lower()
    if s in {"sell", "avoid", "short", "bearish"}:
        return -1
    return 1


def _outcome_for_change(side: str, change_pct: float | None) -> str:
    if change_pct is None:
        return "pending"
    direction = _direction_for_side(side)
    if direction > 0:
        return "success" if change_pct > 0 else "fail"
    # sell/avoid are reverse predictions: falling price is a hit.
    return "success" if change_pct < 0 else "fail"


def _horizon_scope(horizon: str) -> str:
    h = (horizon or "").strip().lower()
    if any(k in h for k in ("long", "长期", "长线", "中长期", "中线", "medium")):
        return "long"
    if any(k in h for k in ("short", "短线", "短期", "波段", "swing")):
        return "short"
    return "unspecified"


def _eligible_windows_for_scope(scope: str) -> list[int]:
    if scope == "long":
        return [20, 60]
    return [1, 3, 5]


def _opinion_status(side: str, horizon: str, horizon_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    scope = _horizon_scope(horizon)
    windows = _eligible_windows_for_scope(scope)
    outcomes = [horizon_results.get(f"{w}d", {}).get("outcome", "pending") for w in windows]
    successes = outcomes.count("success")
    fails = outcomes.count("fail")
    pending = outcomes.count("pending")
    if scope == "long":
        if successes >= 1:
            status = "success"
        elif pending:
            status = "pending"
        else:
            status = "fail"
    else:
        # For short/unspecified views, require two positive horizon hits.
        if successes >= 2:
            status = "success"
        elif fails >= 2:
            status = "fail"
        else:
            status = "pending"
    return {
        "status": status,
        "scope": scope,
        "eligible_windows": [f"{w}d" for w in windows],
        "success_count": successes,
        "fail_count": fails,
        "pending_count": pending,
        "rule": "windows are actual trading days. long: 20d/60d, any hit succeeds; short/unspecified: 1d/3d/5d, two hits succeed",
    }


def _history_move(code: str, prediction_day: date, *, now_day: date) -> PriceMove:
    symbol = f"{code}.T"
    move = PriceMove(code=code, yfinance_code=symbol, prediction_day=prediction_day.isoformat())
    try:
        import yfinance as yf
    except Exception as exc:
        move.status = f"yfinance_import_error: {exc}"
        return move

    start = prediction_day - timedelta(days=20)
    end = max(now_day + timedelta(days=2), prediction_day + timedelta(days=100))
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(
            start=start.isoformat(),
            end=end.isoformat(),
            auto_adjust=False,
            actions=False,
            timeout=12,
        )
    except Exception as exc:
        move.status = f"history_error: {exc}"
        return move
    if hist is None or hist.empty or "Close" not in hist:
        move.status = "history_empty"
        return move

    rows = hist.copy()
    try:
        rows = rows.dropna(subset=["Close"])
    except Exception:
        pass
    if rows.empty:
        move.status = "close_empty"
        return move

    dated_rows: list[tuple[date, float]] = []
    for idx, row in rows.iterrows():
        try:
            row_day = idx.date()
        except Exception:
            row_day = _parse_day(str(idx))
        close = _clean_float(row.get("Close"))
        if row_day and close:
            dated_rows.append((row_day, close))
    dated_rows.sort(key=lambda x: x[0])
    if not dated_rows:
        move.status = "no_dated_close"
        return move

    baseline_index = -1
    for i, (row_day, _close) in enumerate(dated_rows):
        if row_day <= prediction_day:
            baseline_index = i
    if baseline_index < 0:
        move.status = "no_baseline_close"
        return move
    baseline_date, baseline_close = dated_rows[baseline_index]

    latest_price, price_source = _latest_from_fast_info(ticker)
    latest_date = now_day
    if not latest_price:
        latest_date, latest_price = dated_rows[-1]
        price_source = "latest_history_close"

    move.baseline_date = baseline_date.isoformat()
    move.baseline_close = round(float(baseline_close), 4)
    move.latest_date = latest_date.isoformat()
    move.latest_price = round(float(latest_price), 4) if latest_price else None
    move.price_source = price_source
    if latest_price and baseline_close:
        move.change = round(float(latest_price - baseline_close), 4)
        move.change_pct = round(float((latest_price / baseline_close - 1.0) * 100.0), 2)
        move.status = "ok"
    else:
        move.status = "missing_price"

    for horizon in HORIZONS:
        key = f"{horizon}d"
        target_idx = baseline_index + horizon
        if target_idx >= len(dated_rows):
            move.horizons[key] = {
                "horizon_days": horizon,
                "horizon_trading_days": horizon,
                "status": "pending",
                "target_date": "",
                "target_price": None,
                "change": None,
                "change_pct": None,
            }
            continue
        target_date, target_close = dated_rows[target_idx]
        # Daily history may include an in-progress current-day bar; keep it as the
        # best available mark, consistent with the latest-price check.
        change = float(target_close - baseline_close)
        change_pct = float((target_close / baseline_close - 1.0) * 100.0)
        move.horizons[key] = {
            "horizon_days": horizon,
            "horizon_trading_days": horizon,
            "status": "ok",
            "target_date": target_date.isoformat(),
            "target_price": round(float(target_close), 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 2),
        }
    return move


def _rec_key(idx: int, rec: dict[str, Any]) -> str:
    code = str(rec.get("code") or "").strip()
    return f"{idx}|{code}|{rec.get('published_at') or ''}|{rec.get('item_id') or ''}"


def _with_direction_outcomes(rec: dict[str, Any], move: PriceMove) -> dict[str, Any]:
    side = str(rec.get("side") or "")
    horizon = str(rec.get("horizon") or "")
    out = move.to_dict()
    horizon_results: dict[str, dict[str, Any]] = {}
    for key, row in (out.get("horizons") or {}).items():
        row = dict(row)
        row["outcome"] = _outcome_for_change(side, row.get("change_pct"))
        horizon_results[key] = row
    out["horizons"] = horizon_results
    out["direction"] = "down" if _direction_for_side(side) < 0 else "up"
    out["horizon_scope"] = _horizon_scope(horizon)
    out["opinion_status"] = _opinion_status(side, horizon, horizon_results)
    if out.get("change_pct") is not None:
        out["latest_outcome"] = _outcome_for_change(side, out.get("change_pct"))
    else:
        out["latest_outcome"] = "pending"
    return out


def summarize_creator_accuracy(recommendations_by_date: list[dict[str, Any]]) -> dict[str, Any]:
    by_creator: dict[str, dict[str, Any]] = {}
    for rec in recommendations_by_date:
        creator = rec.get("creator") or "unknown"
        row = by_creator.setdefault(creator, {
            "creator": creator,
            "total_opinions": 0,
            "overall": {"success": 0, "pending": 0, "fail": 0, "total": 0},
            "horizons": {
                f"{h}d": {"success": 0, "pending": 0, "fail": 0, "total": 0}
                for h in HORIZONS
            },
        })
        row["total_opinions"] += 1
        chk = rec.get("price_check") or {}
        overall_status = (chk.get("opinion_status") or {}).get("status", "pending")
        row["overall"][overall_status] = row["overall"].get(overall_status, 0) + 1
        row["overall"]["total"] += 1
        for horizon in HORIZONS:
            key = f"{horizon}d"
            outcome = ((chk.get("horizons") or {}).get(key) or {}).get("outcome", "pending")
            if outcome not in {"success", "pending", "fail"}:
                outcome = "pending"
            row["horizons"][key][outcome] += 1
            row["horizons"][key]["total"] += 1

    def enrich_counts(counts: dict[str, int]) -> dict[str, Any]:
        success = int(counts.get("success") or 0)
        fail = int(counts.get("fail") or 0)
        pending = int(counts.get("pending") or 0)
        total = int(counts.get("total") or success + fail + pending)
        judged = success + fail
        return {
            "success": success,
            "pending": pending,
            "fail": fail,
            "total": total,
            "judged": judged,
            "accuracy_pct": round(success / judged * 100.0, 2) if judged else None,
            "cumulative_pct": round(success / total * 100.0, 2) if total else None,
            "n_over_m": f"{success}/{judged}" if judged else f"0/0",
            "success_pending_fail_total": f"{success}/{pending}/{fail}/{total}",
        }

    rows = []
    for creator, row in by_creator.items():
        enriched = {
            "creator": creator,
            "total_opinions": row["total_opinions"],
            "overall": enrich_counts(row["overall"]),
            "horizons": {
                key: enrich_counts(counts)
                for key, counts in row["horizons"].items()
            },
        }
        rows.append(enriched)
    rows.sort(key=lambda r: (r["overall"]["success"], -r["overall"]["pending"], r["total_opinions"]), reverse=True)
    return {
        "rule": "1d/3d/5d/20d/60d are actual trading-day windows. Non-trading days are skipped. sell/avoid count as successful if the stock falls. Short or unspecified views use 1d/3d/5d and require at least two hits. Long/medium views use 20d/60d and remain pending until those windows mature.",
        "horizons": [f"{h}d" for h in HORIZONS],
        "creators": rows,
    }


def price_moves_for_recommendations(recommendations: list[dict[str, Any]],
                                    *,
                                    max_checks: int = 80) -> dict[str, dict[str, Any]]:
    """Return price checks keyed by recommendation identity.

    Baseline is the close on the creator's publication day. If that day was not
    a trading day, the latest trading close before that day is used. For
    sell/avoid opinions, falling prices are counted as hits.
    """
    now_day = datetime.now(timezone.utc).astimezone(JST).date()
    unique: dict[tuple[str, date], PriceMove] = {}
    keys: dict[str, tuple[str, date]] = {}

    for idx, rec in enumerate(recommendations[:max_checks]):
        code = str(rec.get("code") or "").strip()
        if not (len(code) == 4 and code.isdigit()):
            continue
        pred_day = _parse_day(str(rec.get("published_at") or ""))
        if not pred_day:
            continue
        key = (code, pred_day)
        keys[_rec_key(idx, rec)] = key
        unique.setdefault(key, PriceMove(code=code, yfinance_code=f"{code}.T", prediction_day=pred_day.isoformat()))

    checked: dict[tuple[str, date], PriceMove] = {}
    for code, pred_day in list(unique.keys())[:max_checks]:
        checked[(code, pred_day)] = _history_move(code, pred_day, now_day=now_day)

    out: dict[str, dict[str, Any]] = {}
    for idx, rec in enumerate(recommendations[:max_checks]):
        key = keys.get(_rec_key(idx, rec))
        if not key:
            continue
        out[_rec_key(idx, rec)] = _with_direction_outcomes(rec, checked.get(key, unique[key]))
    return out
