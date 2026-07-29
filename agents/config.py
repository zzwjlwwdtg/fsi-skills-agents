import json
import os
from datetime import datetime as _dt
from pathlib import Path

# ── 本地敏感配置（不入 git）─────────────────────────────────────────────
# 优先级：环境变量 > secrets.local.json > secrets.example.json（占位） > 空
# secrets.local.json 应放在 agents/ 目录下，被 .gitignore 排除
_BASE = Path(__file__).parent
_SECRETS: dict = {}
# 先加载 example（占位/默认），再 local 覆盖（real values）
for _name in ("secrets.example.json", "secrets.local.json"):
    _p = _BASE / _name
    if _p.exists():
        try:
            _SECRETS = {**_SECRETS, **json.loads(_p.read_text(encoding="utf-8"))}
        except Exception:
            pass


def _cfg(key: str, default=""):
    """优先环境变量；缺则读 secrets.local.json；最后默认值。"""
    v = os.environ.get(key)
    if v:
        return v
    return _SECRETS.get(key, default)


# --- Tickers ---
# DRAM/存储板块（2026-06-17/18 加）：
#   US.DRAM = Roundhill Memory ETF（存储芯片板块 ETF，1x）
#   US.MULL = 2x MU 杠杆 ETF（Micron 单股杠杆暴露）
# LEVERAGED_PAIRS 配置防止 MU↔MULL 同时持仓叠杠杆（见 paper_trader.py）
TICKERS = ["US.TQQQ", "US.SOXL", "US.DRAM", "US.MULL"]

# WATCH-only：只 scan 信号 + 供 dashboard 展示，不触发 trade_execute
# 用于关注但不打算持仓的板块风向标（比如 NVDA 是半导体链条领头，看它就知道 SOXL/DRAM 方向）
WATCH_ONLY_TICKERS = ["US.NVDA"]

# --- Leverage Factors ---
# 杠杆 ETF 单日波动是标的的 N 倍 → 各种"暴跌/暴涨"绝对阈值要按倍数缩放
# 否则 SOXL 一天 -5% (正常 1σ 波动) 就误触发 crisis
LEVERAGE_FACTORS = {
    "US.TQQQ": 3.0, "US.SOXL": 3.0, "US.TECL": 3.0, "US.UPRO": 3.0,
    "US.MULL": 2.0, "US.NVDU": 2.0, "US.NVDX": 2.0,
    "US.TSLL": 1.5, "US.AAPU": 2.0, "US.GGLL": 2.0,
    # 反向杠杆（绝对值看波动幅度一样）
    "US.SQQQ": 3.0, "US.SOXS": 3.0, "US.SPXU": 3.0,
    "US.NVDD": 1.5, "US.TSLZ": 2.0, "US.TSLQ": 2.0,
    # 默认 1x（正常股票/ETF）
}

# --- moomoo OpenD ---
OPEND_HOST = "127.0.0.1"
OPEND_PORT = 11111
MOOMOO_ACC_ID = int(_cfg("MOOMOO_ACC_ID", "0"))   # SIMULATE 账户 ID
MOOMOO_ACC_ID_JP = int(_cfg("MOOMOO_ACC_ID_JP", "0"))   # 日股 SIMULATE 账户

# --- OpenAI ---
OPENAI_API_KEY = _cfg("OPENAI_API_KEY", "")
DECISION_MODEL = "gpt-4o-mini"

# --- FRED (Federal Reserve Economic Data) ---
# 免费申请: https://fred.stlouisfed.org/docs/api/api_key.html
FRED_API_KEY = _cfg("FRED_API_KEY", "")

# --- Scheduler (日K交易者模式) ---
# 每天 5 个 ET 时间窗口；trader 只在 TRADE_WINDOWS 里的几个下单
# pre-open 仅做"选股 + evolver"不下单；pre-market 仅紧急减仓 (严门槛)
DAILY_WINDOWS_ET = [
    (8*60+30,  8*60+45,  "pre-market"), # 08:30-08:45 ET  盘前 (严门槛 + 大 buffer + RTH 外撮合)
    (9*60+20,  9*60+35,  "pre-open"),   # 09:20-09:35 ET  开盘前扫描 (选 picks 不交易)
    (10*60,    10*60+15, "post-open"),  # 10:00-10:15 ET  开盘后跟踪
    (12*60,    12*60+15, "midday"),     # 12:00-12:15 ET  午盘跟踪
    (15*60+45, 16*60,    "pre-close"),  # 15:45-16:00 ET  收盘前确认
]

# --- Technical thresholds ---
RSI_OVERBOUGHT = 78       # REDUCE_RISK trigger
RSI_EXTREME_OB = 82       # Strong REDUCE_RISK
RSI_OVERSOLD = 38

VOL_DIVERGE_WARN = 0.78   # new high but vol < this ratio = divergence
VOL_DIVERGE_STRONG = 0.70 # strong divergence threshold

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_DIR = os.path.join(BASE_DIR, "signals")
# 按日切割的 log（UTF-8，由 Python 的 FileHandler 直接写，避免 PowerShell 双写导致编码错乱）
_LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

def get_today_log_path():
    """返回当前 UTC/本地日期对应的 log 文件路径，跨午夜自动切换。"""
    return os.path.join(_LOG_DIR, f"run_{_dt.now().strftime('%Y%m%d')}.log")

# 保留 LOG_PATH 作为启动时刻快照，仅用于向后兼容旧代码；
# 真正写入应使用 get_today_log_path() 或 notifier 里的 _DailyLogHandler
LOG_PATH = get_today_log_path()
