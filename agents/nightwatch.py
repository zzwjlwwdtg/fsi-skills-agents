"""
Nightwatch — 夜盘期货监控。

美股期货 23 小时交易（周日 18:00 ET 至周五 17:00 ET，每天停 1h 维护），
是夜间预判第二天 ETF 开盘方向的最佳代理：

  NQ → TQQQ 方向参考（领先 8-12h）
  ES → SPY/QQQ 整体方向
  GC → GLD 方向参考
  YM → 道指方向
  CL → 能源板块

数据源优先级：
  1. moomoo OpenD（需要美股期货数据订阅；多数账号默认无权限）
  2. yfinance（免费 fallback，~15min 延迟）

调用入口:
  get_nightwatch_snapshot()  → 拉所有夜盘合约的实时价 + 涨跌
  format_nightwatch_lines()  → 格式化成 logger 可输出的多行
"""

from __future__ import annotations

from datetime import datetime

from moomoo import RET_OK
from moomoo_pool import get_quote_ctx
from i18n import t


# (moomoo_code, yf_symbol, short_name, full_name, etf_ref)
# full_name 中日双语：(zh, ja)
def _name(zh: str, ja: str) -> str:
    return t(zh, ja)

_FUTURES_MAP = [
    ("US.NQmain",  "NQ=F", _name("NQ 期货", "NQ 先物"), _name("Nasdaq 100", "ナスダック100"),  "TQQQ"),
    ("US.ESmain",  "ES=F", _name("ES 期货", "ES 先物"), _name("S&P 500",    "S&P 500"),       "QQQ/SPY"),
    ("US.GCmain",  "GC=F", _name("GC 期货", "GC 先物"), _name("黄金",        "金"),            "GLD"),
    ("US.YMmain",  "YM=F", _name("YM 期货", "YM 先物"), _name("Dow 30",      "ダウ30"),        "DIA"),
    ("US.CLmain",  "CL=F", _name("CL 期货", "CL 先物"), _name("WTI 原油",    "WTI 原油"),      "USO/XLE"),
]


def _fetch_via_moomoo() -> tuple[list[dict], str]:
    """返回 (results, error_message)。错误时 results 为空。"""
    try:
        ctx = get_quote_ctx()
    except Exception as e:
        return [], f"moomoo 未连接: {e}"
    tickers = [f[0] for f in _FUTURES_MAP]
    try:
        ret, snap = ctx.get_market_snapshot(tickers)
    except Exception as e:
        return [], f"moomoo 调用失败: {e}"
    if ret != RET_OK:
        # 这里 snap 通常是错误字符串
        return [], f"moomoo 拒绝（多半是期货行情权限不足）: {str(snap)[:100]}"
    if snap is None or snap.empty:
        return [], "moomoo 返回空数据"

    results = []
    by_code = {row["code"]: row for _, row in snap.iterrows()}
    for code, _yf, short_name, full_name, etf_ref in _FUTURES_MAP:
        row = by_code.get(code)
        if row is None:
            continue
        try:
            price   = float(row["last_price"])
            prev_cl = float(row["prev_close_price"])
            pct     = (price - prev_cl) / prev_cl * 100 if prev_cl else 0
        except (TypeError, ValueError, KeyError):
            continue
        results.append({
            "code": code, "short_name": short_name, "full_name": full_name,
            "etf_ref": etf_ref, "price": round(price, 2),
            "prev_close": round(prev_cl, 2), "pct_chg": round(pct, 2),
        })
    return results, ""


def _fetch_via_yfinance() -> tuple[list[dict], str]:
    """yfinance 免费 fallback。拉 5 日历史确保至少 2 根日K（夜盘期货+周末）。"""
    try:
        import yfinance as yf
    except ImportError:
        return [], "yfinance 未安装"
    results = []
    for _moomoo, yf_sym, short_name, full_name, etf_ref in _FUTURES_MAP:
        try:
            t = yf.Ticker(yf_sym)
            # 拉 5 天确保跨周末也有 ≥2 根
            hist = t.history(period="5d", interval="1d")
            if len(hist) < 2:
                continue
            price = float(hist["Close"].iloc[-1])
            prev  = float(hist["Close"].iloc[-2])
            pct = (price - prev) / prev * 100 if prev else 0
        except Exception:
            continue
        results.append({
            "code": yf_sym, "short_name": short_name, "full_name": full_name,
            "etf_ref": etf_ref, "price": round(price, 2),
            "prev_close": round(prev, 2), "pct_chg": round(pct, 2),
        })
    return results, ("yfinance 拉取失败" if not results else "")


def get_nightwatch_snapshot() -> dict:
    """
    返回 {data: list, source: str, error: str}

    优先 yfinance（多数用户都能用，稳定）。
    moomoo 期货行情需要付费订阅，无权限时 OpenD 会 hang 死而非干净失败，
    所以默认不再尝试 moomoo。
    """
    data, err = _fetch_via_yfinance()
    if data:
        return {"data": data, "source": "yfinance(~15min延迟)", "error": ""}
    return {"data": [], "source": "", "error": err or "all sources failed"}


def _zh_zone(pct: float) -> tuple[str, str]:
    if   pct >=  2:   return t("强势上行", "強い上昇"),   "▲▲"
    if   pct >=  0.5: return t("上行",     "上昇"),       "▲"
    if   pct <= -2:   return t("强势下行", "強い下落"),   "▼▼"
    if   pct <= -0.5: return t("下行",     "下落"),       "▼"
    return t("震荡", "もみ合い"), "─"


def format_nightwatch_lines() -> list[str]:
    """返回多行夜盘速览（带数据源标注）。"""
    res = get_nightwatch_snapshot()
    snap = res["data"]
    src  = res["source"]
    err  = res["error"]
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")

    title = t("夜盘速览", "ナイトセッション速報")

    if not snap:
        return [
            f"+{'=' * 70}+",
            f"|  {title}  |  {now}".ljust(71) + "|",
            f"+{'=' * 70}+",
            t(f"  数据不可用：{err}", f"  データ取得不可：{err}"),
            t("  ⚠ 美股期货行情通常需要 moomoo 单独订阅。建议:",
              "  ⚠ 米株先物データは通常 moomoo の別途契約が必要。推奨:"),
            t("     pip install yfinance  (已装则忽略)",
              "     pip install yfinance  (インストール済なら無視)"),
            t("     或在 moomoo 申请 CME 行情权限",
              "     または moomoo で CME データ権限を申請"),
            "=" * 72,
        ]

    W = 72
    src_label = t("数据源", "データソース")
    hdr_contract = t("合约", "銘柄")
    hdr_target   = t("标的", "対象")
    hdr_ref_etf  = t("参考 ETF", "参考 ETF")
    hdr_price    = t("价格", "価格")
    hdr_pct      = t("涨跌", "騰落")
    hdr_dir      = t("方向", "方向")

    lines = [
        "+" + "=" * (W - 2) + "+",
        f"|  {title}  |  {now}  |  {src_label}: {src}".ljust(W - 1) + "|",
        "+" + "=" * (W - 2) + "+",
        f"  {hdr_contract:<9} {hdr_target:<14} {hdr_ref_etf:<12} "
        f"{hdr_price:>10} {hdr_pct:>7}  {hdr_dir}",
        f"  {'-'*9} {'-'*14} {'-'*12} {'-'*10} {'-'*7}  ----",
    ]
    for r in snap:
        zone, arrow = _zh_zone(r["pct_chg"])
        lines.append(
            f"  {r['short_name']:<9} {r['full_name']:<14} {r['etf_ref']:<12} "
            f"{r['price']:>10.2f} {r['pct_chg']:>+6.2f}%  {arrow} {zone}"
        )

    nq = next((r for r in snap if "NQ" in r["short_name"]), None)
    es = next((r for r in snap if "ES" in r["short_name"]), None)
    gc = next((r for r in snap if "GC" in r["short_name"]), None)
    if nq and es:
        avg = (nq["pct_chg"] + es["pct_chg"]) / 2
        if abs(avg) >= 1.0:
            direction_zh = "高开" if avg > 0 else "低开"
            direction_ja = "高寄り" if avg > 0 else "安寄り"
            mag_zh = "大幅" if abs(avg) >= 2 else ""
            mag_ja = "大幅な" if abs(avg) >= 2 else ""
            lines.append("")
            lines.append(t(
                f"  解读: NQ {nq['pct_chg']:+.2f}% / ES {es['pct_chg']:+.2f}%  "
                f"→  美股大概率 {mag_zh}{direction_zh}（TQQQ 关联度高）",
                f"  解説: NQ {nq['pct_chg']:+.2f}% / ES {es['pct_chg']:+.2f}%  "
                f"→  米株は{mag_ja}{direction_ja}の確度高（TQQQ 相関高）",
            ))
        elif abs(avg) >= 0.3:
            mood_zh = "多" if avg > 0 else "空"
            mood_ja = "強気寄り" if avg > 0 else "弱気寄り"
            dir_zh = "高开" if avg > 0 else "低开"
            dir_ja = "高寄り" if avg > 0 else "安寄り"
            lines.append("")
            lines.append(t(
                f"  解读: 夜盘震荡偏{mood_zh}，开盘小幅{dir_zh}",
                f"  解説: ナイトセッションは{mood_ja}でもみ合い、寄付き小幅{dir_ja}",
            ))
    if gc and abs(gc["pct_chg"]) >= 0.8:
        up_zh = "上涨" if gc["pct_chg"] > 0 else "下跌"
        up_ja = "上昇" if gc["pct_chg"] > 0 else "下落"
        lines.append(t(
            f"  黄金: GC {gc['pct_chg']:+.2f}%  → GLD 开盘可能{up_zh}",
            f"  金: GC {gc['pct_chg']:+.2f}%  → GLD 寄付き{up_ja}の可能性",
        ))

    lines.append("=" * W)
    return lines


if __name__ == "__main__":
    for line in format_nightwatch_lines():
        print(line)
