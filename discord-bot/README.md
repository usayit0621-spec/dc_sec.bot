# 多機能管理Bot (discord.py)

Sticky message / 強化ログ / bump・up リマインダー / anti-nuke・anti-raid・anti-mention-spam などの
セキュリティ機能をまとめた多機能Discord管理botです。GitHub + Railway での運用を想定しています。

## 実装済み機能

### 📌 `/stick msg:<内容>`
実行したチャンネルの下部に指定メッセージを **embedなし・そのままのプレーンテキストで** 固定表示します。
新しいメッセージが投稿されると自動で古い固定メッセージを削除し、最新の位置に再送信します（連投時は2秒デバウンス）。
`/unstick` で解除できます。

### 🎨 `/embed title:<> discussion:<> image:<任意> color:<>`
タイトル・本文・画像・色を指定してカスタムEmbedを送信できます。`color`はプリセット名(red/blue/green等)か
`#RRGGBB`形式のカラーコードに対応（入力補完あり）。`footer`・`thumbnail`も任意で指定可能です。

### 🔎 `/info user user:<メンション>`
指定ユーザーの詳細情報を表示します。オンライン状況、デバイス種別（デスクトップ/モバイル/Web）、
現在のアクティビティ（ゲーム・Spotify再生中・カスタムステータス）、ボイスチャンネル接続状況、
ロール、ブースト開始日、タイムアウト状況などをまとめて確認できます。
**この機能を使うには Developer Portal で `PRESENCE INTENT` を有効にする必要があります。**

### 📝 `/log ch:<チャンネル>`
指定チャンネルに以下をembedで記録します。
- メッセージ削除（元の内容・添付ファイル・削除実行者の推定）
- メッセージ編集（編集前後の内容）
- メッセージ一括削除
- メンバー参加（使用された招待リンクの特定、アカウント作成日、新規アカウント警告）
- メンバー退出／キック検知
- BAN／BAN解除（理由・実行者）
- ニックネーム変更・ロール付与剥奪・タイムアウト設定
- チャンネル作成／削除／更新
- ロール作成／削除／更新
- 招待リンクの作成／削除
- ボイスチャンネルの入退室・移動

### ⏰ `/bump-mantion min:<分> M:<ロール>` / `/up-mantion min:<分> M:<ロール>`
Disboardの`/bump`が成功したメッセージを検知し、120分後の使用可能時刻から逆算して
指定分前に指定ロールへ通知します。`/up-mantion`も同様の仕組みで、監視するbotとメッセージが
異なるだけです。

> **重要な設計上の注意**
> Discordの仕様上、botは「他のユーザーが実行したスラッシュコマンドのInteraction」を直接検知できません。
> そのため本botはご要望のロジックと同等の効果を得るために、**Disboard等のbumpコマンド成功時に
> 送られてくるメッセージ（embed）を検知する方式**で実装しています。これは実在の bump リマインダーbotが
> 採用している標準的な方式です。
> `/up-mantion`側で監視するbotのIDは `.env` の `UP_BOT_ID` で設定してください
> （デフォルトはディス速を想定した値ですが、**必ずご自身の環境で使っているbotのIDに書き換えて確認**してください）。

### 🛡️ セキュリティ機能 `/security setup`
- **anti-mention-spam**: 1メッセージ内のメンション数が閾値を超えたら削除＋タイムアウト
- **anti-invite**: 他サーバーへの招待リンク投稿を自動削除
- **anti-phishing**: 既知の詐欺/フィッシングサイトの典型的なドメインパターンを自動削除
- **NGワードフィルター**: `/security addword` `/security removeword` `/security wordlist` で単語を管理し、該当メッセージを自動削除
- **anti-spam(連投荒らし)**: 短時間の連続投稿を検知して削除＋タイムアウト
- **anti-raid**: 短時間の大量参加を検知してアラート＋サーバー認証レベルを自動引き上げ
- **anti-alt(捨てアカウント制限)**: アカウント作成から指定時間未満のユーザーの参加を自動キック
- **anti-nuke**: 同一ユーザーによるチャンネル/ロールの短時間大量作成・削除、webhook作成、大量BANを検知し、
  自動でBANまたはロール剥奪
- **`/lockdown` `/unlock`**: 現在のチャンネルで@everyoneの発言を即座に禁止/再許可
- `/security whitelist-add` `/security whitelist-remove` でanti-nuke対象外ユーザーを管理

### 🎫 チケットシステム `/ticket setup`
指定チャンネルにボタン付きパネルを設置し、ユーザーがボタンを押すと専用のプライベートチャンネルが
自動作成されます。`/ticket close`またはチケット内のボタンでチャンネルを閉じられます。

### 🎉 ギブアウェイ `/giveaway`
リアクション(🎉)形式の景品抽選を開催できます。`/giveaway-end`で即時終了・抽選も可能です。

### 🎭 リアクションロール `/reactionrole add`
指定メッセージへの絵文字リアクションでロールを自動付与/剥奪します。

### 💤 便利機能いろいろ
- `/afk` : 離席中に設定。メンションされると自動でお知らせし、発言すると自動解除
- `/remind minutes:<> content:<>` : 指定分後にリマインド通知
- `/poll question:<> options:<カンマ区切り>` : リアクション投票を作成
- `/suggest setup` `/suggest new` : 提案システム(👍👎リアクション付き)
- `/snipe` `/editsnipe` : 直近削除/編集されたメッセージをチャンネルごとに確認
- `/welcome setup` `/welcome leave-setup` : 参加/退出メッセージ・自動ロール付与を設定

### 🔄 起動通知
Botが起動(再起動)すると、設定済みの全サーバーのログチャンネルへ「Dc_Sec Botが再起動しました。」という
embedを自動送信します。

### 🔨 モデレーション
`/kick` `/ban` `/unban` `/timeout` `/untimeout` `/warn` `/warnings` `/clearwarnings`
`/purge` `/slowmode`

### 🔧 ユーティリティ
`/ping` `/userinfo` `/serverinfo` `/avatar`

### 🔄 ステータス自動ローテーション
Botのアクティビティ表示（「〜を見ています」欄）を **10秒ごと** に自動で切り替えます。
- `Ping: {ms}ms`
- `{サーバー数} サーバー`
- `{メンバー数} 人のメンバー`
- コマンド案内
- 見守りメッセージ

`cogs/presence.py` の `_build_statuses()` 内のリストを編集すれば表示内容や順番、間隔（`@tasks.loop(seconds=10)`）を自由に変更できます。

---

## セットアップ

### 1. Discord Developer Portal
1. https://discord.com/developers/applications で新規アプリケーションを作成
2. Bot タブでBotを作成し、トークンを取得
3. **Privileged Gateway Intents** で以下を必ずON
   - `PRESENCE INTENT`（/info user のオンライン状況・デバイス表示に必須）
   - `SERVER MEMBERS INTENT`
   - `MESSAGE CONTENT INTENT`
4. OAuth2 > URL Generator で `bot` と `applications.commands` にチェックし、
   必要な権限（Administrator推奨、最低でも Manage Roles / Manage Channels / Kick Members /
   Ban Members / Moderate Members / Manage Messages / View Audit Log / Manage Guild）
   を選択して招待リンクを発行し、botをサーバーに招待

### 2. ローカルでの準備
```bash
git clone <このリポジトリ>
cd discord-bot
python -m venv venv
source venv/bin/activate  # Windowsは venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```
`.env` を開き `DISCORD_TOKEN` を設定してください。開発中は `GUILD_ID` にテストサーバーの
IDを入れるとコマンドが即座に反映されます（本番では空欄でOK、グローバル反映は最大1時間程度）。

```bash
python main.py
```

### 3. GitHubへpush
```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin <あなたのリポジトリURL>
git push -u origin main
```
`.env` は `.gitignore` 済みなのでpushされません。

### 4. Railwayでのデプロイ
1. Railway で `New Project` → `Deploy from GitHub repo` を選択し、このリポジトリを指定
2. `Variables` タブで環境変数を設定
   - `DISCORD_TOKEN`
   - `GUILD_ID`（任意）
   - `UP_BOT_ID`（必要に応じて変更）
3. 自動的に `Procfile` / `railway.json` を検出して起動します（起動コマンド: `python main.py`）
4. **データ永続化について**: SQLite（`bot.db`）はコンテナのローカルファイルに保存されるため、
   再デプロイ時にリセットされる可能性があります。設定を確実に保持したい場合は Railway の
   **Volume** 機能を追加し、`bot.db` の保存先をそのボリューム上のパスに変更することを推奨します
   （`utils/database.py` の `DB_PATH` を変更してください）。

---

## ディレクトリ構成
```
discord-bot/
├── main.py                  # エントリーポイント
├── requirements.txt
├── Procfile
├── railway.json
├── .env.example
├── cogs/
│   ├── sticky.py             # /stick /unstick (プレーンテキスト)
│   ├── logging_cog.py        # /log 強化ログ
│   ├── bump_reminder.py      # /bump-mantion /up-mantion
│   ├── security.py           # /security /lockdown /unlock 等
│   ├── moderation.py         # kick/ban/timeout/warn/purge
│   ├── utility.py            # ping/userinfo/serverinfo/avatar
│   ├── presence.py           # ステータス10秒ごとローテーション
│   ├── embed_builder.py      # /embed カスタムEmbed送信
│   ├── welcome.py            # 参加/退出メッセージ・自動ロール
│   ├── info.py                # /info user 詳細情報
│   ├── extras.py              # afk/remind/poll/suggest/snipe
│   ├── reaction_roles.py      # /reactionrole
│   ├── giveaway.py            # /giveaway
│   └── tickets.py             # /ticket チケットシステム
└── utils/
    ├── database.py           # SQLite (aiosqlite) ラッパー
    └── checks.py             # 権限チェック共通処理
```

## 注意事項
- `/log` `/bump-mantion` `/up-mantion` `/security setup` は `管理者` または該当の管理権限を
  持つメンバーのみ実行できます。
- anti-nuke機能はサーバーオーナー・管理者権限保持者には作動しません（誤BAN防止のため）。
  信頼できる運営メンバーは `/security whitelist-add` で明示的に除外してください。
- メッセージ内容を取得するために `MESSAGE CONTENT INTENT` が必須です。未設定だとsticky機能や
  ログ機能の一部が正しく動作しません。
