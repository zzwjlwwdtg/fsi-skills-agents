# JP Social Reco

日股向けの「指定博主 / X 投稿 / 動画文字起こし → 銘柄推薦抽出 → OpenD 検証」サブシステムです。
既存の主フレームワークからは Python 関数で呼び出せます。

## Framework Interface

```python
from jp_social_reco import get_jp_social_signal_cached, format_jp_social_banner

sig = get_jp_social_signal_cached(
    lookback_hours=168,
    max_items=80,
    use_llm=True,
    verify_opend=True,
)
for line in format_jp_social_banner(sig):
    logger.info(line)
```

戻り値は JSON 化可能な dict です。OpenD や LLM が使えない場合も例外で止めず、
`extraction_status` と各 recommendation の `opend_error` に状態を入れます。

## Input Inbox

まずは `data/inbox/` に X エクスポート、動画文字起こし、手動メモを置きます。

対応形式:

- `.jsonl`: 1 行 1 JSON
- `.json`: `{"items": [...]}` または list
- `.csv`: `creator,source_type,text,published_at,url,title`
- `.txt` / `.md`: ファイル全体を 1 item として読む
- `.srt` / `.vtt`: DownSub などで落とした字幕ファイル。タイムコードは自動で除去。

JSONL 例:

```json
{"creator":"sample_creator","source_type":"x_post","published_at":"2026-06-15T08:30:00+09:00","url":"https://x.com/...","text":"今日は7203 トヨタを押し目買いで注目。円安メリットと出来高が強い。"}
```

## CLI

```bat
cd /d F:\fsi-skills\agents
C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe -X utf8 -m jp_social_reco.cli --where
C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe -X utf8 -m jp_social_reco.cli --fresh --no-llm --no-opend
```

既定の対象期間は最近 1 週間 (`168h`) です。古い動画を手動で fetch しても、
`--hours` を広げない限りスキャン対象には入りません。
CLI 実行時は既定で inbox 内の 1 週間より古い dated download を削除し、
`creator__videoid.jsonl` が既にある動画は再ダウンロードしません。

## DownSub Workflow

DownSub で字幕を手動ダウンロードした場合は、`.srt` / `.vtt` / `.txt` を
`data/inbox/` に置くだけで次回スキャン対象になります。

ファイル名を `creator__videoid.srt` にすると、creator と video id を追跡できます。

例:

```text
data/inbox/higedura24__gVvsONFzumM.srt
```

## Local YouTube Subtitle Workflow

DownSub を開かず、ローカルの `yt-dlp` で字幕を取得することもできます。

単一動画:

```bat
python -X utf8 -m jp_social_reco.cli --fetch-video "https://www.youtube.com/watch?v=VIDEO_ID" --creator higedura24 --fresh --no-opend
```

設定済み YouTube チャンネルから最近 1 週間の動画字幕を取得:

```bat
python -X utf8 -m jp_social_reco.cli --fetch-youtube-subs --fetch-max 2 --fresh --no-opend
```

既存ファイルをあえて取り直す場合だけ `--force-download` を付けます。

字幕が存在しない動画は WARN として記録され、処理は継続します。
既定では `ja,zh-Hans,zh-Hant,zh,en.*,en` の順で字幕を探します。

字幕トラック確認:

```bat
python -X utf8 -m jp_social_reco.cli --list-subs "https://www.youtube.com/watch?v=VIDEO_ID"
```

YouTube が制限する場合はブラウザ cookie を使えます:

```bat
python -X utf8 -m jp_social_reco.cli --fetch-video "https://www.youtube.com/watch?v=VIDEO_ID" --cookies-from-browser chrome --fresh --no-opend
```

字幕が無い動画は、任意でローカル Whisper fallback に回せます:

```bat
python -X utf8 -m jp_social_reco.cli --fetch-video "https://www.youtube.com/watch?v=VIDEO_ID" --whisper-fallback --quality balanced --fresh --no-opend
```

Whisper fallback には `faster-whisper` が必要です。字幕が存在する動画は Whisper を使わず高速に終わります。
精度重視なら `--quality high` を使います（CPU では遅くなります）。中国語動画は
`--whisper-language zh`、日本語動画は `--whisper-language ja` を付けると誤認識が減ります。

例:

```bat
python -X utf8 -m jp_social_reco.cli --fetch-video "https://www.youtube.com/watch?v=VIDEO_ID" --creator RhinoFinance --whisper-fallback --quality high --whisper-language zh --fresh --no-opend
```

## Weekly Creator Report

近一周博主总结可以直接输出 Markdown 和 PDF。报告会读取最近 `168h` 的荐股抽取结果，优先用 Claude CLI 生成中文摘要；如果 Claude 不可用，会回退到确定性模板。默认还会用 `yfinance` 做轻量回测：比较博主发布日期对应的收盘价和当前/最新可得价格。
报告会由 Python 自动生成 PNG 柱状图，并用 HTML `<img>` 标签嵌入 Markdown，同时写入 PDF；不需要手动作图。
回测周期包括 `1d/3d/5d/20d/60d`，全部指实际交易日，非交易日不计入。`buy/watch` 按股价上涨为命中，`sell/avoid` 按股价下跌为命中。长期/中线观点优先等待 `20d/60d`，短期或未给出期限的观点按 `1d/3d/5d`，至少两个交易周期命中才算综合成功。

```bat
cd /d F:\fsi-skills\agents
C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe -X utf8 -m jp_social_reco.cli --fresh --no-opend --report
```

连同字幕抓取一起跑：

```bat
C:\Users\masa\AppData\Local\Programs\Python\Python312\python.exe -X utf8 -m jp_social_reco.cli --fetch-youtube-subs --fetch-max 2 --fresh --no-opend --report
```

常用开关：

- `--report-dir PATH`: 指定 MD/PDF 输出目录。
- `--report-no-llm`: 不调用 Claude CLI，使用模板报告。
- `--report-no-backtest`: 不调用 yfinance。
- `--report-md-only` / `--report-pdf-only`: 只输出一种格式。

总框架也可以直接调用：

```python
from jp_social_reco import generate_jp_social_weekly_report

report = generate_jp_social_weekly_report(
    lookback_hours=168,
    max_items=80,
    use_llm=True,
    verify_opend=False,
    report_use_llm=True,
    include_backtest=True,
)
print(report["markdown_path"], report["pdf_path"])
```

## OpenD

`verify_opend=True` のとき、`moomoo_pool.get_quote_ctx()` 経由で
`JP.7203` のようなコードを `get_market_snapshot()` に投げます。
OpenD 未起動、JP quote 未契約、または銘柄不正でも scanner は停止しません。

## Next Adapters

現時点の安定入口は inbox です。X 公式 API / YouTube Captions / yt-dlp / Whisper などの
取得アダプタは、この inbox に同じ schema の item を書けば主処理側の変更なしで接続できます。
