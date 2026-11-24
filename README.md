# Hearthstone Battlegrounds Power.log Analyzer (`bg_review.py`)

ハースストーン バトルグラウンド（Hearthstone Battlegrounds）の `Power.log` を解析し、試合の振り返り用 **HTMLレポート** および **AI分析用の軽量Markdown（`*_ai.md`）** を生成するPythonスクリプトです。

Python標準ライブラリのみで動作するため、追加パッケージのインストールは不要です。

---

## 主な機能

- **バトルグラウンド自動抽出**: `Power.log` 内の複数試合からバトルグラウンド（`GT_BATTLEGROUNDS*`）のみを自動で切り出して解析します。
- **ターン・リロール単位の記録**:
  - 各リロールでの酒場提示ミニオン／呪文、前ターンからの凍結持ち越し、購入したカード
  - 各行動前後の所持金・最大所持金
  - ターン開始／終了時の酒場グレードおよび開始時のアップグレード費用
  - 「悪夢の恵み（Dark Gifts）」の発見選択肢と選択結果、ミニオンへの付与効果
- **盤面・戦闘・ロビー情報の可視化**:
  - ターン終了時の自分の盤面（配置順・スタッツ・ゴールデン・各種キーワード能力・悪夢の恵み）および手札
  - 戦闘結果（勝利／敗北／引き分け・ダメージ・ライフ推移）と対戦相手の盤面・ヒーロー情報
  - ロビー全員（自分＋対戦相手7人）のリーダーボード（順位・ヒーロー・グレード推移・HP／アーマー・トリプル数・下級／上級装飾品）
  - 開始時のヒーロー選択肢と出現／BAN種族の自動判定
- **日本語カード情報・画像連携**:
  - [HearthstoneJSON](https://hearthstonejson.com/) の日本語カードマスタ（`jaJP/cards.json`）からカード名・テキスト・スタッツ・種族・装飾品・ヒーローパワー・悪夢の恵みを自動取得します（取得できない場合は CardID で表示）。
- **AI分析用Markdown出力（`--ai-text` / `--ai-only`）**:
  - HTMLと同等の試合情報をCSSやHTMLタグを含まない軽量なMarkdownへ出力し、末尾にその試合に登場したカードのみの「登場カード辞書」を付与します。ChatGPTやClaude、GeminiなどのAIに読み込ませてプレイングの振り返り・コーチングを行う用途に適しています。

---

## 必要環境

- **Python 3.x**（標準ライブラリのみ使用：`argparse`, `glob`, `gzip`, `html`, `json`, `os`, `re`, `sys`, `urllib.request`）
- **インターネット接続**（任意：HearthstoneJSON からのカードマスタ・カード画像取得に使用。オフライン時でも CardID ベースで解析・出力可能）

---

## 事前準備（`Power.log` について）

Hearthstone で `Power.log` を出力するには、Hearthstone の設定ファイル `log.config` で `[Power]` ログを有効化しておく必要があります。

スクリプトは以下の順でログファイルを探索します。

1. コマンドライン引数で指定された `log_file`
2. Windows 標準インストール先の最新ログ（`C:\Program Files (x86)\Hearthstone\Logs\Hearthstone_*\Power.log`）
3. カレントディレクトリの `Power.log`

---

## 使い方

```bash
python bg_review.py [log_file] [オプション]
```

### オプション一覧

| オプション | 短縮形 | 説明 |
| --- | --- | --- |
| `log_file` | - | 解析対象の `Power.log` パス（省略時は自動検出） |
| `--output` | `-o` | 出力ベースファイル名（デフォルト: `bg_review_rolls.html`） |
| `--split` | `-s` | 試合ごとに個別ファイルへ分割出力（HTML・AIテキスト両方に適用） |
| `--game` | `-g` | 出力する試合番号を指定（1始まり、複数指定可。例: `-g 1 3`） |
| `--ai-text` | `-a` | HTMLに加えて、AI読み込み用の軽量Markdown（`*_ai.md`）も出力 |
| `--ai-only` | - | HTMLを生成せず、AI用Markdownのみ出力 |

### 実行例

```bash
# 最新の Power.log を自動検出して bg_review_rolls.html を生成
python bg_review.py

# 指定した Power.log を解析し、HTML と AI用Markdown の両方を出力
python bg_review.py Power.log --ai-text

# 試合ごとにファイルを分割して出力（例: bg_review_rolls_game1.html など）
python bg_review.py Power.log --split

# 1試合目と3試合目だけを抽出して出力
python bg_review.py Power.log --game 1 3

# AI分析用の軽量Markdownのみを指定ファイル名で出力
python bg_review.py Power.log --ai-only -o review.md
```

---

## 出力ファイル

- **HTMLレポート（デフォルト: `bg_review_rolls.html`）**
  - ブラウザで開いて、ターンごとのリロール履歴・盤面・戦闘結果・ロビー状況を視覚的に振り返ることができます。
  - `--split` 指定時は `<ベース名>_game1.html`, `<ベース名>_game2.html` ... として出力されます。
- **AI用Markdown（`*_ai.md`）**
  - `--ai-text` 指定時は `<ベース名>_ai.md`（分割時は `<ベース名>_game1_ai.md`）として出力されます。
  - `--ai-only` で `-o` に `.md` または `.txt` を指定した場合は、そのファイル名（分割時は `<ベース名>_game1.md`）で出力されます。

---

## 注意事項

- 本スクリプトは Hearthstone の内部ログ仕様（`Power.log`）および HearthstoneJSON のAPI構造に依存しています。ゲームの大型アップデート等によりログ形式が変更された場合、一部項目が正しく抽出できなくなる可能性があります。
- `Power.log` にはプレイヤー名（BattleTag等）が含まれる場合があります。解析結果やログファイルを公開・共有する際はご注意ください。
- 作者はバトルグラウンドのソロモードのみをプレイしているため、他のゲームモードが混在した `Power.log` での動作確認およびバトルグラウンド デュオモードでの動作確認は実施していません。

---

## 謝辞

- 本ツールのカード情報（日本語カード名・テキスト・スタッツ・種族等）およびカード画像の取得には、[HearthstoneJSON](https://hearthstonejson.com/) のデータを利用させていただいております。素晴らしいAPI・データセットを公開・維持してくださっている開発者・関係者の皆様に感謝いたします。
