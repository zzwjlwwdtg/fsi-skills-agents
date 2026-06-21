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
  "timestamp_local": "2026-06-18T21:37:53",
  "ticker": "US.SOXL",
  "window": "pre-market",
  "market": {
    "ticker": "SOXL",
    "ts": "2026-06-18 21:37",
    "price": 233.86,
    "pct_chg": 3.39,
    "rsi_14": 52.3,
    "cci_20": 45.4,
    "cci_zone": "neutral",
    "ma20": 218.24,
    "ma50": 160.74,
    "vol_ratio": 0.77,
    "is_new_52w_high": false,
    "dist_from_high": -17.82,
    "trend": "up",
    "ma_stack": "bull",
    "rsi_zone": "neutral",
    "vol_zone": "shrink",
    "pct_chg_zone": "pop",
    "pre_price": 265.57,
    "pre_pct": 13.559,
    "pre_volume": 1310611.0,
    "pre_date": "2026-06-18",
    "pre_label": "今日盘前(进行中)",
    "after_price": 248.887,
    "after_pct": 6.425,
    "after_volume": 2474288.0,
    "after_date": "2026-06-17",
    "after_label": "昨日盘后(已结束)",
    "overnight_price": 255.7,
    "overnight_pct": 9.338,
    "overnight_volume": 2109890.0,
    "overnight_date": "2026-06-17",
    "overnight_label": "昨夜夜盘(已结束)",
    "now_et": "2026-06-18 08:37 ET",
    "prev_session": {
      "date": "2026-06-15",
      "open": 265.99,
      "close": 272.5,
      "high": 274.88,
      "low": 261.6,
      "pct": 2.45
    },
    "prev_pct": 2.45,
    "today_session": null,
    "today_not_yet_opened": "2026-06-18 今日尚未开盘（距 9:30 ET 还有 0h53m）",
    "ma_cross": "golden",
    "rsi_cross": "none",
    "cci_cross": "up_100",
    "bb_pct": 0.611,
    "bb_zone": "normal",
    "bb_upper": 288.82,
    "bb_lower": 147.65,
    "psar_trend": 1,
    "psar_signal": "none",
    "macd_dif": 21.094,
    "macd_dea": 22.859,
    "macd_hist": -1.765,
    "macd_zone": "bull",
    "macd_signal": "none",
    "adx_14": 16.3,
    "adx_zone": "weak"
  },
  "events": {
    "ts": "2026-06-18 21:36",
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
        "title": "Stock Market Today: Dow Brushes Off Fed, Rises Ahead Of Jobless Claims; Trump Spurs Intel Shares (Live Coverage)",
        "url": "https://finance.yahoo.com/m/7d9d2b46-4a95-3f5e-8492-d6e8307ce329/stock-market-today%3A-dow.html?.tsrc=rss",
        "source": null
      },
      {
        "title": "‘Forget AI, Fed Is The Story Now’ – 'Bond King' Jeffrey Gundlach Says Kevin Warsh Faces A 1970s-Style Inflation Challenge",
        "url": "https://stocktwits.com/news-articles/markets/equity/jeffrey-gundlach-kevin-warsh-inflation-warning/cZKjvy6R7et?.tsrc=rss",
        "source": null
      }
    ],
    "risk_level": "normal",
    "trump_signal": {
      "direction": "bullish",
      "magnitude": "medium",
      "score": 18,
      "tariff_alert": false,
      "silence_signal": false,
      "posts_count": 21,
      "n_signals_medium_plus": 1,
      "fallback": false
    },
    "options_risk": {
      "ts": "2026-06-18T21:37:51.570759",
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
            "cp_oi_ratio": "1.72",
            "weighted_max_pain_pct": "3.17",
            "strength": "medium"
          },
          "spot": 77.54,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'QQQ', 'label': 'QQQ underlying', 'proxy_spot': 722.51, 'leveraged_ticker': 'TQQQ', 'leveraged_spot': 77.54, 'leverage': 3.0, 'gex': {'direction': 'neutral', 'cp_oi_ratio': 0.76, 'weighted_max_pain_pct': 1.16, 'strength': 'weak'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 735.0, 'proxy_pct': 1.73, 'leveraged_level': 81.56, 'leveraged_pct': 5.19, 'volume': 54511}, 'put_wall': {'proxy_strike': 720.0, 'proxy_pct': -0.35, 'leveraged_level': 76.73, 'leveraged_pct': -1.04, 'volume': 67441}, 'max_pain': {'proxy_strike': 731.0, 'proxy_pct': 1.18, 'leveraged_level': 80.27, 'leveraged_pct': 3.53}, 'total_call_vol': 655902, 'total_put_vol': 868158, 'cp_ratio': 0.76}, {'expiry': '2026-06-22', 'category': 'weekly', 'days': 4, 'call_wall': {'proxy_strike': 735.0, 'proxy_pct': 1.73, 'leveraged_level': 81.56, 'leveraged_pct': 5.19, 'volume': 8034}, 'put_wall': {'proxy_strike': 728.0, 'proxy_pct': 0.76, 'leveraged_level': 79.31, 'leveraged_pct': 2.28, 'volume': 11633}, 'max_pain': {'proxy_strike': 730.0, 'proxy_pct': 1.04, 'leveraged_level': 79.95, 'leveraged_pct': 3.11}, 'total_call_vol': 98895, 'total_put_vol': 118922, 'cp_ratio': 0.83}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 733.0, 'proxy_pct': 1.45, 'leveraged_level': 80.92, 'leveraged_pct': 4.36, 'volume': 10003}, 'put_wall': {'proxy_strike': 650.0, 'proxy_pct': -10.04, 'leveraged_level': 54.19, 'leveraged_pct': -30.11, 'volume': 7057}, 'max_pain': {'proxy_strike': 732.0, 'proxy_pct': 1.31, 'leveraged_level': 80.6, 'leveraged_pct': 3.94}, 'total_call_vol': 59218, 'total_put_vol': 67365, 'cp_ratio': 0.88}]}"
          ]
        },
        "SOXL": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.75",
            "weighted_max_pain_pct": "4.76",
            "strength": "weak"
          },
          "spot": 233.86,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'SOXX', 'label': 'SOXX underlying', 'proxy_spot': 599.73, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 233.86, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.1, 'weighted_max_pain_pct': 0.05, 'strength': 'strong'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 622.5, 'proxy_pct': 3.8, 'leveraged_level': 260.5, 'leveraged_pct': 11.39, 'volume': 854}, 'put_wall': {'proxy_strike': 600.0, 'proxy_pct': 0.05, 'leveraged_level': 234.18, 'leveraged_pct': 0.14, 'volume': 22968}, 'max_pain': {'proxy_strike': 600.0, 'proxy_pct': 0.05, 'leveraged_level': 234.18, 'leveraged_pct': 0.14}, 'total_call_vol': 3934, 'total_put_vol': 39211, 'cp_ratio': 0.1}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 605.0, 'proxy_pct': 0.88, 'leveraged_level': 240.02, 'leveraged_pct': 2.64, 'volume': 1164}, 'put_wall': {'proxy_strike': 565.0, 'proxy_pct': -5.79, 'leveraged_level': 193.23, 'leveraged_pct': -17.37, 'volume': 1772}, 'max_pain': {'proxy_strike': 600.0, 'proxy_pct': 0.05, 'leveraged_level': 234.18, 'leveraged_pct': 0.14}, 'total_call_vol': 1475, 'total_put_vol': 4757, 'cp_ratio': 0.31}]}",
            "{'proxy': 'SMH', 'label': 'SMH liquid proxy', 'proxy_spot': 623.97, 'leveraged_ticker': 'SOXL', 'leveraged_spot': 233.86, 'leverage': 3.0, 'gex': {'direction': 'negative_squeeze', 'cp_oi_ratio': 0.36, 'weighted_max_pain_pct': 0.97, 'strength': 'strong'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 650.0, 'proxy_pct': 4.17, 'leveraged_level': 263.13, 'leveraged_pct': 12.52, 'volume': 3153}, 'put_wall': {'proxy_strike': 560.0, 'proxy_pct': -10.25, 'leveraged_level': 161.93, 'leveraged_pct': -30.76, 'volume': 7601}, 'max_pain': {'proxy_strike': 630.0, 'proxy_pct': 0.97, 'leveraged_level': 240.64, 'leveraged_pct': 2.9}, 'total_call_vol': 18913, 'total_put_vol': 52509, 'cp_ratio': 0.36}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 635.0, 'proxy_pct': 1.77, 'leveraged_level': 246.26, 'leveraged_pct': 5.3, 'volume': 2489}, 'put_wall': {'proxy_strike': 610.0, 'proxy_pct': -2.24, 'leveraged_level': 218.15, 'leveraged_pct': -6.72, 'volume': 6679}, 'max_pain': {'proxy_strike': 635.0, 'proxy_pct': 1.77, 'leveraged_level': 246.26, 'leveraged_pct': 5.3}, 'total_call_vol': 8760, 'total_put_vol': 24492, 'cp_ratio': 0.36}]}"
          ]
        },
        "DRAM": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.84",
            "weighted_max_pain_pct": "1.5",
            "strength": "weak"
          },
          "spot": 69.95,
          "walls_n": 2,
          "underlying_adjusted": [
            "{'proxy': 'MU', 'label': 'MU memory proxy', 'proxy_spot': 1043.19, 'leveraged_ticker': 'DRAM', 'leveraged_spot': 69.95, 'leverage': 1.0, 'gex': {'direction': 'positive_pin', 'cp_oi_ratio': 1.51, 'weighted_max_pain_pct': 0.17, 'strength': 'medium'}, 'walls': [{'expiry': '2026-06-18', 'category': '0DTE', 'days': 0, 'call_wall': {'proxy_strike': 1100.0, 'proxy_pct': 5.45, 'leveraged_level': 73.76, 'leveraged_pct': 5.45, 'volume': 31797}, 'put_wall': {'proxy_strike': 1000.0, 'proxy_pct': -4.14, 'leveraged_level': 67.05, 'leveraged_pct': -4.14, 'volume': 12477}, 'max_pain': {'proxy_strike': 1045.0, 'proxy_pct': 0.17, 'leveraged_level': 70.07, 'leveraged_pct': 0.17}, 'total_call_vol': 187167, 'total_put_vol': 123783, 'cp_ratio': 1.51}, {'expiry': '2026-07-17', 'category': 'monthly', 'days': 29, 'call_wall': {'proxy_strike': 1100.0, 'proxy_pct': 5.45, 'leveraged_level': 73.76, 'leveraged_pct': 5.45, 'volume': 7099}, 'put_wall': {'proxy_strike': 900.0, 'proxy_pct': -13.73, 'leveraged_level': 60.35, 'leveraged_pct': -13.73, 'volume': 2583}, 'max_pain': {'proxy_strike': 1000.0, 'proxy_pct': -4.14, 'leveraged_level': 67.05, 'leveraged_pct': -4.14}, 'total_call_vol': 15421, 'total_put_vol': 6849, 'cp_ratio': 2.25}]}"
          ]
        },
        "SPY": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "1.43",
            "weighted_max_pain_pct": "0.23",
            "strength": "weak"
          },
          "spot": 740.96,
          "walls_n": 3
        },
        "QQQ": {
          "gex": {
            "direction": "neutral",
            "cp_oi_ratio": "0.76",
            "weighted_max_pain_pct": "1.16",
            "strength": "weak"
          },
          "spot": 722.51,
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
    "vix": 17.290000915527344,
    "fg_score": 32,
    "t10y2y": null,
    "t10yie": 2.26,
    "fedfunds": 3.63
  },
  "rule_decision": {
    "action": "WATCH_BUY",
    "confidence": 7,
    "reason": "uptrend + positive confluence",
    "stop_ref": null,
    "score_breakdown": {
      "tech": 5,
      "macro": 0,
      "event": 0,
      "quant": 0,
      "boost": 1
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
    "session": "pre-market",
    "confluence": {
      "bull_signals": [
        "价格站上MA20(价格233.86 > MA20=218.24)",
        "均线多排(MA20=218.24 > MA50=160.74)",
        "均线金叉(MA5上穿MA20，近3日)",
        "当日上涨(+3.4%，>+2%)",
        "[2026-06-18 今日盘前(进行中)] 涨+13.56%  → 开盘大概率跳空高开"
      ],
      "bear_signals": [
        "CCI进入超买(近3日上穿+100，当前=45)"
      ],
      "bull_count": 5,
      "bear_count": 1,
      "net": 4,
      "strength": "强多头共振",
      "stars": "★★★"
    },
    "h1_context": "最新K线@17:00  趋势:向上  RSI:46.3",
    "m15_context": "[最新15m K线@2026-06-18 06:00:00] 短线信号弱(信号数 2，方向不明): 突破6h高点 $260.72 · RSI极度超买(15m RSI=82)",
    "m15_direction": "mixed"
  }
}
