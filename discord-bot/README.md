# 多機能管理Bot (discord.py)

Sticky message / 強化ログ / bump・up リマインダー / anti-nuke・anti-raid・anti-mention-spam・
外部アプリ(User Install App含む)スパム対策などのセキュリティ機能をまとめた多機能Discord管理botです。
GitHub + Render（Web Service）/ Railway での運用を想定しています。

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

### ⏰ Bump/Up リマインダー(メッセージ学習方式)
以前のバージョンはBotのIDやキーワードを決め打ちで検知していたため、環境によっては通知が来ない
問題がありました。**今のバージョンは実際の成功メッセージをBotに学習させる方式**に変更しています。

**セットアップ手順**
1. Disboardの`/bump`（またはディス速等の`/up`）を実行し、成功メッセージが送信されるのを待つ
2. その成功メッセージの上で右クリック（スマホは長押し）→ **アプリ** → **「Bumpメッセージに設定」**
   （upの場合は「Upメッセージに設定」）を実行
   → これでBotがそのメッセージの送信者(Bot)と内容の形式（メンションや数字部分は自動で無視）を覚えます
3. `/bump-mantion min:<何分前> M:<通知したいロール>` を実行（`/up-mantion`も同様）
   → コマンドの形式は変更していません

以後、学習した形式と一致するメッセージが送信されると、そのメッセージが**送信された時刻**を基準に
120分後のクールダウンタイマーを開始し、指定分前にロール通知を送ります。

**RTA計測**
成功メッセージを検知すると、直前のクールダウンが明けた時刻からの経過秒数を
`🏁 /bump RTA: 12.345678秒` のようにユーザーメンション付きで自動送信します（`/up`も同様）。

**レベル付与との連動**
- `/bump`成功時: 成功メッセージ内でメンションされているユーザーのレベルが自動で+1されます
- `/up`成功時: メンションが含まれないため、コマンドを実行した本人（インタラクション情報から特定）のレベルが自動で+1されます

> 学習前（コンテキストメニューでの登録前）は検知が行われません。まずは上記の手順1〜3を必ず行ってください。

### 🛡️ セキュリティ機能(`/security setup` `/security setup-content` `/security setup-advanced`)
**基本 (`/security setup`)**
- **anti-mention-spam**: 1メッセージ内のメンション数が閾値を超えたら削除＋処罰(**権限保持者も対象**＝乗っ取り対策)
- **anti-invite**: 他サーバーへの招待リンク投稿を自動削除
- **anti-phishing**: 既知の詐欺/フィッシングサイトのドメインパターン・短縮URL(bit.ly等)を自動削除
- **anti-spam(連投荒らし)**: 短時間の連続投稿を検知して削除＋処罰
- **anti-raid**: 短時間の大量参加を検知してアラート＋サーバー認証レベルを自動引き上げ
- **anti-alt(捨てアカウント制限)**: アカウント作成から指定時間未満のユーザーの参加を自動キック
- **anti-nuke**: 同一ユーザーによるチャンネル/ロールの短時間大量作成・削除、webhook作成、大量BAN・大量キックを検知し自動でBAN

**コンテンツフィルター (`/security setup-content`)**
- **URL一律ブロック**: `/security urlwhitelist-add` で許可したドメイン以外のURLをすべて削除
- **NGワードフィルター**: `/security addword` `/security removeword` `/security wordlist`
- **anti-caps**: 大文字だらけの「叫び」メッセージを自動削除
- **anti-emoji**: 絵文字の過剰投稿を自動削除
- **anti-duplicate**: 同一内容メッセージの連続投稿(コピペ荒らし)を自動削除
- **Zalgoフィルター**: 結合文字を悪用した崩し文字荒らしを自動削除
- **@everyone/@here濫用検知**: **権限保持者を含めて**例外なく検知(アカウント乗っ取り対策)

**高度な設定 (`/security setup-advanced`)**
- **外部アプリ/Bot(User Install App含む)スパム対策**: サーバーに投稿されたメッセージが
  外部アプリ・Bot・User Install App経由と判定された場合、専用の頻度しきい値で監視します。
  違反を検知すると該当メッセージを削除し、**そのアプリを実行(インストール)した人物をDiscordの
  インタラクション情報から特定してログに記録**、その人物を処罰します(アプリ自体はタイムアウトできないため)。
- **権限昇格の自動監視**: ロールに管理者権限が不正に付与されたのを検知すると自動的に取り消し、
  オーナーにDM通知(モデレーターアカウント乗っ取り対策)
- **ストライク制(累積タイムアウト→警告→BAN)**: スパム系の理由でタイムアウトされた回数をユーザーごとに
  記録し、**9回に達すると「次は警告なしでBANされます」という警告DMを送信**、**10回目のタイムアウトに
  該当する行為が検知されると自動的にBAN**します(`/warn`と同様のトーンの警告文)。回数は
  `/security strikes` `/security strikes-reset` で確認・リセット可能です。
- `/security whitelist-add` `/security whitelist-remove` でanti-nuke対象外ユーザーを管理

**チャンネル制御**
- `/lockdown` `/unlock`: 現在のチャンネルで@everyoneの発言を即座に禁止/再許可
- `/lockdown-all`: サーバー全体のテキストチャンネルを緊急一斉ロックダウン

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

### 4. Renderでのデプロイ(Web Serviceとして運用する場合)
RenderのWeb Serviceは常時ポートへの応答(ヘルスチェック)を要求するため、`main.py`は起動時に
軽量なHTTPサーバー(`aiohttp`)を`$PORT`で自動的に立ち上げるようになっています。追加の設定は不要です。

1. Render ダッシュボードで `New` → `Web Service` を選択し、GitHubリポジトリを連携
   (リポジトリ直下に `render.yaml` があるので "Blueprint" からまとめてデプロイも可能です)
2. 設定項目
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Health Check Path**: `/health`
3. `Environment` タブで環境変数を設定
   - `DISCORD_TOKEN`
   - `GUILD_ID`（任意）
   - `UP_BOT_ID`（必要に応じて変更）
   - `PORT` は Render が自動的に注入するため通常は設定不要です（`main.py`が`$PORT`を自動で読み取ります。未設定時は`10000`番を使用）
4. **データ永続化について**: RenderのFreeプランはファイルシステムが永続化されないため、
   再デプロイ・再起動のたびに`bot.db`がリセットされます。設定を永続化したい場合は
   Renderの **Persistent Disk**（有料）を追加し、`utils/database.py`の`DB_PATH`を
   そのディスクのマウントパス（例: `/var/data/bot.db`）に変更してください。

### 5. Railwayでのデプロイ（引き続き利用可能）
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

## ファイルの配置場所(図)

GitHubリポジトリの**ルート**（＝RenderやRailwayがそのままビルドする場所）は、以下の構成にしてください。
`discord-bot`というフォルダをもう一段挟んではいけません。フォルダの中身をそのままリポジトリ直下に置きます。

```
（GitHubリポジトリのルート）
│
├── main.py                   ← 起動ファイル
├── requirements.txt
├── Procfile                  ← Railway用
├── railway.json               ← Railway用
├── render.yaml                 ← Render用(Blueprintデプロイに使用)
├── .env.example
├── .gitignore
├── README.md
│
├── cogs/                      ← このフォルダを作って中に入れる
│   ├── sticky.py               # /stick /unstick (プレーンテキスト)
│   ├── logging_cog.py          # /log 強化ログ
│   ├── bump_reminder.py        # /bump-mantion /up-mantion
│   ├── security.py             # /security /lockdown /unlock 等
│   ├── moderation.py           # kick/ban/timeout/warn/purge
│   ├── utility.py              # ping/userinfo/serverinfo/avatar
│   ├── presence.py             # ステータス10秒ごとローテーション
│   ├── embed_builder.py        # /embed カスタムEmbed送信
│   ├── welcome.py              # 参加/退出メッセージ・自動ロール
│   ├── info.py                  # /info user 詳細情報
│   ├── extras.py                # afk/remind/poll/suggest/snipe
│   ├── reaction_roles.py        # /reactionrole
│   ├── giveaway.py              # /giveaway
│   └── tickets.py               # /ticket チケットシステム
│
└── utils/                     ← このフォルダを作って中に入れる
    ├── database.py             # SQLite (aiosqlite) ラッパー
    └── checks.py               # 権限チェック共通処理
```

**手順**
1. 空フォルダを作り、上記の`main.py`など直下のファイルをそのまま置く
2. `cogs`という名前のフォルダを作り、`cogs/`以下の`.py`ファイルをすべてその中に入れる
3. `utils`という名前のフォルダを作り、`database.py`と`checks.py`をその中に入れる
4. フォルダ名・ファイル名は上記と完全に一致させる（`main.py`が`import cogs.sticky`のように
   名前で読み込んでいるため、ズレると起動エラーになります）
5. GitHubにpushしたら、Render/Railway側の「Root Directory」設定は**空欄のまま**でOKです
   （最初からリポジトリ直下にファイルがあるため）

## 注意事項
- `/log` `/bump-mantion` `/up-mantion` `/security setup*` は `管理者` または該当の管理権限を
  持つメンバーのみ実行できます。
- **管理者権限保持者のバイパス範囲**: NGワード・URL遮断・caps・絵文字・重複投稿・Zalgo・招待リンク・
  フィッシング検知は誤検知防止のため管理者を対象外にしていますが、**メンションスパムと@everyone/@here濫用
  検知は管理者・モデレーターアカウントでも例外なく検知します**（アカウント乗っ取り対策のため）。
- anti-nuke機能はサーバーオーナーには作動しません（誤BAN防止のため）。信頼できる運営メンバーは
  `/security whitelist-add` で明示的に除外してください。
- メッセージ内容を取得するために `MESSAGE CONTENT INTENT` が必須です。オンライン状況取得には
  `PRESENCE INTENT` も必須です。未設定だと一部機能が正しく動作しません。
- 外部アプリ/User Install Appのスパム対策は、Discordの`interaction_metadata`（discord.py 2.4以降で
  利用可能）を用いて実行者を特定します。古いdiscord.pyバージョンでは実行者情報が取得できない場合があります。

## `/stick`がembedのまま/文言が付いて届く場合のチェックリスト
現在のコード（`cogs/sticky.py`）は完全にプレーンテキスト送信（`channel.send(msg)`）のみで、
embedも「自動で下に移動します」等の文言も一切含まれていません。それでも古い挙動のまま届く場合は、
以下を順番に確認してください。
1. **デプロイ環境に最新のファイルが反映されているか**: 特に`cogs/sticky.py`が今回配布したものと
   一致しているか、Render/Railwayのビルドログでファイルの更新日時を確認してください。
2. **ビルドキャッシュが古い**: Render/Railwayの管理画面から「Clear build cache」→ 再デプロイを行ってください。
3. **既存のスティックメッセージは自動で変わらない**: 修正前のコードで送信済みのスティックメッセージ
   (embed版)は、コードを直しただけでは自動的に書き換わりません。該当チャンネルで一度 `/unstick` →
   `/stick msg:<内容>` を実行し、新しいプレーンテキスト版を作り直してください。
4. 上記を行っても改善しない場合は、`cogs/sticky.py`の内容をそのまま貼り付けて教えてください。
