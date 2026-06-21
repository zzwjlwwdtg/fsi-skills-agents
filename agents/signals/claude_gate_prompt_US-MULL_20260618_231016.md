You are the final pre-trade risk gate for this local trading system.

Task:
- Review ONLY the rule_decision below. Do not create a new trade idea.
- Return APPROVE only if the proposed action is internally consistent, timely,
  and risk is acceptable for the current window.
- Return HOLD if data is stale, conflicted, weak, or the proposed order should
  not be sent.
- Return CAUTION if the signal is notable but should be recorded as no-order.
- Be conservative. If unsure, choose HOLD.

Output JSON only, with this schema:
{"verdict":"APPROVE|HOLD|CAUTION","confidence":1-10,"reason":"short reason","risk_flags":["..."]}

Decision packet:
{
  "timestamp_local": "2026-06-18T23:10:16",
  "ticker": "US.MULL",
  "window": "post-open",
  "market": {
    "ticker": "MULL",
    "ts": "2026-06-18 23:10",
    "price": 901.83,
    "pct_chg": 12.36,
    "rsi_14": 59.0,
    "cci_20": 120.1,
    "cci_zone": "overbought",
    "ma20": 692.75,
    "ma50": 447.91,
    "vol_ratio": 0.23,
    "is_new_52w_high": false,
    "dist_from_high": -4.37,
    "trend": "up",
    "ma_stack": "bull",
    "rsi_zone": "neutral",
    "vol_zone": "shrink",
    "pct_chg_zone": "surge",
    "pre_price": 906.0,
    "pre_pct": 12.883,
    "pre_volume": 10934.0,
    "pre_date": "2026-06-18",
    "pre_label": "今日盘前(已结束)",
    "after_price": 856.0,
    "after_pct": 6.653,
    "after_volume": 12023.0,
    "after_date": "2026-06-17",
    "after_label": "昨日盘后(已结束)",
    "overnight_price": 869.98,
    "overnight_pct": 8.395,
    "overnight_volume": 24287.0,
    "overnight_date": "2026-06-17",
    "overnight_label": "昨夜夜盘(已结束)",
    "now_et": "2026-06-18 10:10 ET",
    "prev_session": {
      "date": "2026-06-15",
      "open": 837.6,
      "close": 881.85,
      "high": 893.56,
      "low": 828.91,
      "pct": 5.28
    },
    "prev_pct": 5.28,
    "today_session": {
      "date": "2026-06-18",
      "open": 900.49,
      "current": 901.83,
      "pct": 0.15,
      "status": "盘中进行中"
    },
    "today_not_yet_opened": null,
    "ma_cross": "none",
    "rsi_cross": "none",
    "cci_cross": "up_100",
    "bb_pct": 0.827,
    "bb_zone": "normal",
    "bb_upper": 1012.53,
    "bb_lower": 372.98,
    "psar_trend": 1,
    "psar_signal": "none",
    "macd_dif": 102.341,
    "macd_dea": 101.331,
    "macd_hist": 1.01,
    "macd_zone": "bull",
    "macd_signal": "golden",
    "adx_14": 26.0,
    "adx_zone": "strong"
  },
  "events": {
    "ts": "2026-06-18 23:08",
    "next_event": "NFP Release (2026-07-03)",
    "next_event_name": "NFP Release",
    "next_event_date": "2026-07-03",
    "next_event_impact": "critical",
    "event_verify_src": "",
    "days_to_event": 15,
    "breaking_news": false,
    "breaking_evidence": "",
    "top_headlines": [
      {
        "title": "Stock Market Today: Dow Brushes Off Fed, Rises After Jobless Claims; Trump Spurs Intel Shares (Live Coverage)",
        "url": "https://finance.yahoo.com/m/7d9d2b46-4a95-3f5e-8492-d6e8307ce329/stock-market-today%3A-dow.html?.tsrc=rss",
        "source": null
      },
      {
        "title": "Exchange-Traded Funds, Equity Futures Higher Pre-Bell Thursday as Interim US-Iran Deal Lifts Risk Sentiment",
        "url": "https://finance.yahoo.com/markets/stocks/articles/exchange-traded-funds-equity-futures-125723601.html?.tsrc=rss",
        "source": null
      }
    ],
    "risk_level": "normal",
    "trump_signal": {
      "direction": "bullish",
      "magnitude": "large",
      "score": 40,
      "tariff_alert": false,
      "silence_signal": false,
      "posts_count": 22,
      "n_signals_medium_plus": 2,
      "fallback": false
    },
    "options_risk": {
      "ts": "2026-06-18T23:09:46.217788",
      "witching": {
        "is_witching_day": false,
        "days_to_witching": 1,
        "phase": "adjacent",
        "next_witching_date": "2026-06-19"
      },
      "per_ticker": {
        "TQQQ": {
          "gex": {
            "direction": "positive_pin",
            "cp_oi_ratio": "1.76",
            "weighted_max_pain_pct": "-2.42",
            "strength": "medium"
          },
          "spot": 81.98,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'QQQ', 'label': 'QQQ underlying', 'proxy_spot': 736.76, 'leveraged_ticker': 'TQQQ', 'leveraged_spot': 81.98, 'leverage': 3.0, 'gex': {'direction': 'neutral', 'cp_oi_ratio': 0.76, 'weighted_max_pain_pct': -0.24, 'strength': 'weak'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 740.0, 'proxy_pct': 0.44, 'leveraged_level': 83.06, 'leveraged_pct': 1.32, 'volume': 19375}, 'put_wall': {'proxy_strike': 730.0, 'proxy_pct': -0.92, 'leveraged_level': 79.72, 'leveraged_pct': -2.75, 'volume': 19413}, 'max_pain': {'proxy_strike': 735.0, 'proxy_pct': -0.24, 'leveraged_level': 81.39, 'leveraged_pct': -0.72}, 'total_call_vol': 146599, 'total_put_vol': 197510, 'cp_ratio': 0.74}, {'expiry': '2026-06-22', 'category': 'weekly', 'days': 4, 'call_wall': {'proxy_strike': 737.0, 'proxy_pct': 0.03, 'leveraged_level': 82.06, 'leveraged_pct': 0.1, 'volume': 2586}, 'put_wall': {'proxy_strike': 737.0, 'proxy_pct': 0.03, 'leveraged_level': 82.06, 'leveraged_pct': 0.1, 'volume': 1243}, 'max_pain': {'proxy_strike': 735.0, 'proxy_pct': -0.24, 'leveraged_level': 81.39, 'leveraged_pct': -0.72}, 'total_call_vol': 17031, 'total_put_vol': 16862, 'cp_ratio': 1.01}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 733.0, 'proxy_pct': -0.51, 'leveraged_level': 80.72, 'leveraged_pct': -1.53, 'volume': 514}, 'put_wall': {'proxy_strike': 728.0, 'proxy_pct': -1.19, 'leveraged_level': 79.06, 'leveraged_pct': -3.57, 'volume': 872}, 'max_pain': {'proxy_strike': 733.0, 'proxy_pct': -0.51, 'leveraged_level': 80.72, 'leveraged_pct': -1.53}, 'total_call_vol': 5370, 'total_put_vol': 8427, 'cp_ratio': 0.64}]}"
          ]
        },
        "SOXL": {
          "gex": {
            "direction": "positive_pin",
            "cp_oi_ratio": "2.33",
            "weighted_max_pain_pct": "-8.4",
            "strength": "medium"
          },
          "spot": 272.94,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'SOXX', 'label': 'SOXX underlying', 'proxy_spot': 632.79, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 272.94, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.21, 'weighted_max_pain_pct': -6.37, 'strength': 'strong'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 622.5, 'proxy_pct': -1.63, 'leveraged_level': 259.62, 'leveraged_pct': -4.88, 'volume': 854}, 'put_wall': {'proxy_strike': 585.0, 'proxy_pct': -7.55, 'leveraged_level': 211.1, 'leveraged_pct': -22.66, 'volume': 4281}, 'max_pain': {'proxy_strike': 592.5, 'proxy_pct': -6.37, 'leveraged_level': 220.81, 'leveraged_pct': -19.1}, 'total_call_vol': 2681, 'total_put_vol': 13028, 'cp_ratio': 0.21}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 725.0, 'proxy_pct': 14.57, 'leveraged_level': 392.26, 'leveraged_pct': 43.72, 'volume': 345}, 'put_wall': {'proxy_strike': 565.0, 'proxy_pct': -10.71, 'leveraged_level': 185.22, 'leveraged_pct': -32.14, 'volume': 1772}, 'max_pain': {'proxy_strike': 600.0, 'proxy_pct': -5.18, 'leveraged_level': 230.51, 'leveraged_pct': -15.55}, 'total_call_vol': 586, 'total_put_vol': 3394, 'cp_ratio': 0.17}]}",
            "{'proxy': 'SMH', 'label': 'SMH liquid proxy', 'proxy_spot': 654.57, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 272.94, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.6, 'weighted_max_pain_pct': -6.43, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 650.0, 'proxy_pct': -0.7, 'leveraged_level': 267.22, 'leveraged_pct': -2.09, 'volume': 736}, 'put_wall': {'proxy_strike': 612.5, 'proxy_pct': -6.43, 'leveraged_level': 220.31, 'leveraged_pct': -19.28, 'volume': 2930}, 'max_pain': {'proxy_strike': 612.5, 'proxy_pct': -6.43, 'leveraged_level': 220.31, 'leveraged_pct': -19.28}, 'total_call_vol': 5080, 'total_put_vol': 8435, 'cp_ratio': 0.6}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 635.0, 'proxy_pct': -2.99, 'leveraged_level': 248.46, 'leveraged_pct': -8.97, 'volume': 2489}, 'put_wall': {'proxy_strike': 635.0, 'proxy_pct': -2.99, 'leveraged_level': 248.46, 'leveraged_pct': -8.97, 'volume': 1678}, 'max_pain': {'proxy_strike': 635.0, 'proxy_pct': -2.99, 'leveraged_level': 248.46, 'leveraged_pct': -8.97}, 'total_call_vol': 4116, 'total_put_vol': 2376, 'cp_ratio': 1.73}]}"
          ]
        },
        "DRAM": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "1.44",
            "weighted_max_pain_pct": "-5.88",
            "strength": "weak"
          },
          "spot": 75.97,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'MU', 'label': 'MU memory proxy', 'proxy_spot': 1109.12, 'leveraged_ticker': 'DRAM', 'leveraged_spot': 75.97, 'leverage': 1.0, 'gex': {'direction': 'positive_pin', 'cp_oi_ratio': 1.87, 'weighted_max_pain_pct': -5.33, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 1100.0, 'proxy_pct': -0.82, 'leveraged_level': 75.35, 'leveraged_pct': -0.82, 'volume': 3816}, 'put_wall': {'proxy_strike': 1100.0, 'proxy_pct': -0.82, 'leveraged_level': 75.35, 'leveraged_pct': -0.82, 'volume': 1878}, 'max_pain': {'proxy_strike': 1050.0, 'proxy_pct': -5.33, 'leveraged_level': 71.92, 'leveraged_pct': -5.33}, 'total_call_vol': 26699, 'total_put_vol': 14283, 'cp_ratio': 1.87}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 1100.0, 'proxy_pct': -0.82, 'leveraged_level': 75.35, 'leveraged_pct': -0.82, 'volume': 1335}, 'put_wall': {'proxy_strike': 900.0, 'proxy_pct': -18.85, 'leveraged_level': 61.65, 'leveraged_pct': -18.85, 'volume': 484}, 'max_pain': {'proxy_strike': 910.0, 'proxy_pct': -17.95, 'leveraged_level': 62.33, 'leveraged_pct': -17.95}, 'total_call_vol': 5065, 'total_put_vol': 1065, 'cp_ratio': 4.76}]}"
          ]
        },
        "SPY": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "1.31",
            "weighted_max_pain_pct": "-0.71",
            "strength": "weak"
          },
          "spot": 745.88,
          "walls_n": 3
        },
        "QQQ": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.76",
            "weighted_max_pain_pct": "-0.24",
            "strength": "weak"
          },
          "spot": 736.76,
          "walls_n": 3
        }
      },
      "summary": {
        "max_risk": "elevated",
        "reason": "三巫日前 1天"
      }
    }
  },
  "macro": {
    "vix": 16.969999313354492,
    "fg_score": 37,
    "t10y2y": 0.29,
    "t10yie": 2.26,
    "fedfunds": 3.63
  },
  "rule_decision": {
    "action": "WATCH_BUY",
    "confidence": 8,
    "reason": "bullish trend + momentum",
    "stop_ref": null,
    "score_breakdown": {
      "tech": 3,
      "macro": 0,
      "event": 0,
      "quant": 0,
      "boost": 3
    },
    "engine": "rules",
    "regime": "bull_pulling",
    "quant": {
      "buy_hits": [],
      "sell_hits": [],
      "buy_score": 0,
      "sell_score": 0,
      "n_rules": 0,
      "regime_bucket": "bull",
      "ts": null
    },
    "trump_boost": true,
    "session": "open",
    "confluence": {
      "bull_signals": [
        "价格站上MA20(价格901.83 > MA20=692.75)",
        "均线多排(MA20=692.75 > MA50=447.91)",
        "当日暴涨(+12.4%，>+5%)  ⚠超买风险"
      ],
      "bear_signals": [
        "CCI超买(CCI=120，中性区间-100~+100，当前高于+100)",
        "CCI进入超买(近3日上穿+100，当前=120)"
      ],
      "bull_count": 3,
      "bear_count": 2,
      "net": 1,
      "strength": "弱多头共振",
      "stars": "★"
    },
    "h1_context": "最新K线@17:00  趋势:向上  RSI:46.9",
    "m15_context": "[最新15m K线@2026-06-18 06:00:00] 短线无信号",
    "m15_direction": "neutral"
  }
}
