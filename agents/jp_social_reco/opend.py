from __future__ import annotations

import json
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from config import OPEND_HOST, OPEND_PORT
except Exception:
    OPEND_HOST, OPEND_PORT = "127.0.0.1", 11111


@dataclass
class QuoteCheck:
    code: str
    ok: bool
    last_price: float | None = None
    volume: float | None = None
    turnover: float | None = None
    error: str = ""
    raw: dict[str, Any] | None = None


def to_moomoo(code: str) -> str:
    code = str(code).replace("JP.", "").replace(".T", "").strip()
    return f"JP.{code}"


def _fail_all(codes: list[str], error: str) -> dict[str, QuoteCheck]:
    return {c: QuoteCheck(code=c, ok=False, error=error) for c in codes}


def _port_open(timeout: float = 0.7) -> bool:
    try:
        with socket.create_connection((OPEND_HOST, int(OPEND_PORT)), timeout=timeout):
            return True
    except Exception:
        return False


def verify_with_opend(codes: list[str], timeout: int = 6) -> dict[str, QuoteCheck]:
    """Verify JP tickers through moomoo OpenD.

    It returns soft failures instead of raising, so the scanner can still run
    when OpenD is closed or JP quotes are not subscribed.
    """
    clean = []
    for code in codes:
        c = str(code).replace("JP.", "").replace(".T", "").strip()
        if len(c) == 4 and c.isdigit():
            clean.append(c)
    if not clean:
        return {}

    if not _port_open():
        return _fail_all(clean, f"opend_unreachable: {OPEND_HOST}:{OPEND_PORT}")

    agents_dir = Path(__file__).resolve().parents[1]
    script = r'''
import json, sys
from config import OPEND_HOST, OPEND_PORT
MARKER = "__JP_SOCIAL_RECO_JSON__"
try:
    from moomoo import OpenQuoteContext, RET_OK
except Exception as exc:
    print(MARKER + json.dumps({"error": "moomoo_import_failed: " + str(exc)}))
    raise SystemExit(0)
codes = json.loads(sys.argv[1])
out = {}
ctx = None
try:
    ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_PORT)
    ret, data = ctx.get_market_snapshot(["JP." + c for c in codes])
    if ret != RET_OK or data is None or data.empty:
        print(MARKER + json.dumps({"error": "snapshot_failed: " + str(data)}))
        raise SystemExit(0)
    for _, row in data.iterrows():
        full = str(row.get("code", ""))
        code = full.split(".", 1)[-1]
        def f(name):
            try:
                value = row.get(name)
                return float(value) if value is not None else None
            except Exception:
                return None
        last_price = f("last_price")
        out[code] = {
            "ok": bool(last_price and last_price > 0),
            "last_price": last_price,
            "volume": f("volume"),
            "turnover": f("turnover"),
            "error": "" if last_price else "no_last_price",
        }
    print(MARKER + json.dumps({"items": out}, ensure_ascii=False))
finally:
    if ctx is not None:
        try:
            ctx.close()
        except Exception:
            pass
'''
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", script, json.dumps(clean)],
            cwd=str(agents_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return _fail_all(clean, f"opend_timeout: >{timeout}s")
    except Exception as exc:
        return _fail_all(clean, f"opend_error: {exc}")

    text = (proc.stdout or "").strip()
    if not text:
        err = (proc.stderr or "").strip()[:200]
        return _fail_all(clean, f"opend_subprocess_failed: {err}")
    marker = "__JP_SOCIAL_RECO_JSON__"
    payload_line = ""
    for line in text.splitlines():
        if marker in line:
            payload_line = line.split(marker, 1)[1].strip()
    if not payload_line:
        return _fail_all(clean, f"opend_no_json_marker: {text[:160]}")
    try:
        payload = json.loads(payload_line)
    except Exception:
        return _fail_all(clean, f"opend_bad_json: {text[:160]}")
    if payload.get("error"):
        return _fail_all(clean, payload["error"])

    items = payload.get("items") or {}
    result: dict[str, QuoteCheck] = {}
    for c in clean:
        row = items.get(c) or {}
        result[c] = QuoteCheck(
            code=c,
            ok=bool(row.get("ok")),
            last_price=row.get("last_price"),
            volume=row.get("volume"),
            turnover=row.get("turnover"),
            error=row.get("error") or ("" if row.get("ok") else "not_returned"),
            raw=row,
        )
    return result
