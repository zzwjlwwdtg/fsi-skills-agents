"""
HMM Regime Detection — 用 Hidden Markov Model 自动学习市场 regime。

不预设 regime 数，让数据自己说话：用 K=4 个隐状态 + Gaussian 发射，
特征 = [SPY 日收益, SPY 20日波动率, VIX, ΔVIX]。

输出：每天处于哪个 regime + 转移概率。给规则版 regime_today 一个对照。

调用：
  python hmm_regime.py            # 训练 + 当日推断 + 显示
  detect_today() → {state, prob, label, characteristics}

缓存：hmm_state.json (每天 pre-open 刷新)。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from config import SIGNALS_DIR
from notifier import logger


N_STATES        = 4         # 4 个隐状态
TRAIN_DAYS      = 500       # 训练窗口
HMM_STATE_PATH  = Path(SIGNALS_DIR) / "hmm_state.json"


def _fetch_features(days: int = 500) -> pd.DataFrame | None:
    """构造特征矩阵: [SPY 收益, SPY 20日年化波动, VIX 水平, VIX 1日变化]。"""
    try:
        import yfinance as yf
        spy = yf.Ticker("SPY").history(period=f"{days}d", interval="1d", auto_adjust=True)
        vix = yf.Ticker("^VIX").history(period=f"{days}d", interval="1d")
        if spy.empty or vix.empty:
            return None
        spy_ret = spy["Close"].pct_change()
        spy_vol = spy_ret.rolling(20).std() * np.sqrt(252)   # 年化波动
        vix_close = vix["Close"]
        vix_chg = vix_close.pct_change()
        # 对齐时区 + index
        for s in (spy_ret, spy_vol, vix_close, vix_chg):
            s.index = s.index.tz_localize(None) if s.index.tz else s.index
        df = pd.DataFrame({
            "spy_ret":   spy_ret,
            "spy_vol":   spy_vol,
            "vix":       vix_close,
            "vix_chg":   vix_chg,
        }).dropna()
        return df
    except Exception as e:
        logger.warning(f"[hmm] fetch_features 失败: {e}")
        return None


def _label_state(stats: dict) -> str:
    """根据各状态的均值/方差给个人类可读名字。"""
    ret  = stats["spy_ret"]
    vol  = stats["spy_vol"]
    vix  = stats["vix"]
    # 简单分类
    if vix > 28 and ret < 0:    return "crisis"
    if vix > 22:                return "volatile_uncertain"
    if ret > 0.0008 and vol < 0.18:  return "bull_low_vol"   # 平均日涨 + 低波动
    if ret > 0.0005:            return "bull_normal"
    if ret < -0.0005:           return "bear_or_correction"
    return "neutral_chop"


def train_and_detect() -> dict:
    """训练 HMM + 推断当前状态。返回 {state, label, prob, characteristics}。"""
    from hmmlearn import hmm
    df = _fetch_features(TRAIN_DAYS)
    if df is None or len(df) < 100:
        return {"error": "no_data"}
    X = df.values
    # Gaussian HMM K=4, full covariance
    model = hmm.GaussianHMM(n_components=N_STATES, covariance_type="full",
                            n_iter=50, random_state=42)
    try:
        model.fit(X)
    except Exception as e:
        return {"error": f"hmm fit: {e}"}
    states = model.predict(X)
    # 计算每个状态的特征均值
    state_stats = {}
    for k in range(N_STATES):
        mask = states == k
        if mask.sum() == 0: continue
        Xk = X[mask]
        state_stats[k] = {
            "spy_ret":   float(Xk[:,0].mean()),
            "spy_vol":   float(Xk[:,1].mean()),
            "vix":       float(Xk[:,2].mean()),
            "vix_chg":   float(Xk[:,3].mean()),
            "n_days":    int(mask.sum()),
            "label":     "",   # 填充下面
        }
    for k, s in state_stats.items():
        s["label"] = _label_state(s)
    # 当前状态 + 概率
    cur_state = int(states[-1])
    posterior = model.predict_proba(X)
    cur_prob = posterior[-1]
    # 转移矩阵: 从 cur_state 转去其他的概率
    trans_row = model.transmat_[cur_state].tolist()

    return {
        "ts":              datetime.now().isoformat(),
        "current_state":   cur_state,
        "current_label":   state_stats[cur_state]["label"],
        "current_prob":    round(float(cur_prob[cur_state]), 3),
        "all_state_probs": {int(k): round(float(p), 3) for k, p in enumerate(cur_prob)},
        "state_stats":     {int(k): s for k, s in state_stats.items()},
        "transition_from_current": {int(k): round(float(p), 3) for k, p in enumerate(trans_row)},
        "n_train_days":    len(df),
    }


def save(info: dict) -> None:
    try:
        HMM_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        HMM_STATE_PATH.write_text(
            json.dumps(info, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"[hmm] save 失败: {e}")


def load() -> Optional[dict]:
    if not HMM_STATE_PATH.exists():
        return None
    try:
        return json.loads(HMM_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def detect_today() -> dict:
    """pre-open 调用：训练 + 推断 + 写文件。"""
    info = train_and_detect()
    if "error" not in info:
        save(info)
    return info


def format_report(info: dict) -> list[str]:
    W = 76
    lines = ["+" + "="*(W-2) + "+",
             f"|  HMM 自动 Regime 检测 (4 隐状态, 500 天训练)".ljust(W-1) + "|",
             "+" + "="*(W-2) + "+"]
    if info.get("error"):
        lines.append(f"  ❌ {info['error']}")
        return lines + ["="*W]
    cur = info["current_state"]
    label = info["current_label"]
    prob = info["current_prob"]
    lines.append(f"  当前状态: state {cur} = 「{label}」  概率 {prob*100:.0f}%")
    lines.append("")
    lines.append(f"  各状态概率分布: " + "  ".join(
        f"S{k}={p*100:.0f}%" for k, p in info["all_state_probs"].items()))
    lines.append("")
    lines.append(f"  {'状态':<6} {'标签':<22} {'平均日收益':>10} {'年化波动':>9} {'VIX 均值':>8} {'天数':>5}")
    lines.append(f"  {'-'*6} {'-'*22} {'-'*10} {'-'*9} {'-'*8} {'-'*5}")
    for k, s in info["state_stats"].items():
        mark = "★ ←" if k == cur else ""
        lines.append(
            f"  S{k:<5} {s['label']:<22} {s['spy_ret']*100:>+9.3f}% "
            f"{s['spy_vol']*100:>8.1f}% {s['vix']:>7.1f}  {s['n_days']:>5}  {mark}"
        )
    lines.append("")
    lines.append(f"  从 state {cur} 转出概率:")
    for k, p in info["transition_from_current"].items():
        bar = "█" * int(p * 30)
        lines.append(f"    → S{k} ({info['state_stats'].get(k,{}).get('label','?'):<22}) {p*100:>5.1f}% {bar}")
    lines.append("="*W)
    return lines


if __name__ == "__main__":
    info = detect_today()
    for line in format_report(info):
        print(line)
