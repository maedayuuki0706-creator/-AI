# Discord 質問Bot セットアップ

## 目的
専用の「質問」チャンネルで、競艇AIナビの予想・用語・買い目について質問するとBotが回答します。

対応例:
- `PT3って何？`
- `1-234-234って何点？`
- `若松10Rの4号艇を入れた理由は？`
- 予想メッセージのDiscordリンクを貼って `これって何？`
- 質問チャンネル内でメッセージに返信して質問

## 1. Discord側
1. サーバーに `質問` チャンネルを作る。
2. Discord Developer PortalでBotを用意する。
3. Bot設定で **Message Content Intent** をONにする。
4. Botをサーバーへ招待する。
5. 最低限の権限:
   - View Channels
   - Send Messages
   - Read Message History
   - Embed Links
6. 予想元メッセージのリンクを読む場合、対象の予想チャンネルもBotから閲覧可能にする。

## 2. Render側
別Web Serviceとして動かす場合:

- Repository: `https://github.com/maedayuuki0706-creator/-AI`
- Branch: `main`
- Runtime: Python
- Build Command: `pip install -r requirements-question-bot.txt`
- Start Command: `python question_bot.py`

環境変数:
- `DISCORD_BOT_TOKEN` = Discord Bot Token
- `OPENAI_API_KEY` = OpenAI API Key（AI回答を使う場合）
- `OPENAI_MODEL` = `gpt-5.6-luna`
- `DISCORD_QUESTION_CHANNEL_NAME` = `質問`

任意:
- `DISCORD_QUESTION_CHANNEL_ID` = 質問チャンネルID。設定時はチャンネル名より優先。
- `DISCORD_PREDICTION_CHANNEL_NAMES` = 予想チャンネル名の検索キーワードをカンマ区切りで設定。

## 3. 挙動
優先順位:
1. 質問メッセージの返信先
2. 質問文に含まれるDiscordメッセージリンク
3. 質問文の場名・R番号から同一サーバー内の最近の予想を検索
4. 用語辞典・フォーメーション解析
5. 参照元不足なら、予想文またはメッセージリンクを求める

OpenAI APIが未設定・一時失敗でも、主要用語とフォーメーション説明はローカル処理で回答します。

## 4. テスト
起動後に質問チャンネルで:
- `PT3って何？`
- `1-234-234って何点？`

次に予想メッセージのリンクを貼って:
- `これって何？`
- `なんで4号艇入ってる？`

AIは参照できない根拠を勝手に作らず、材料不足の場合はその旨を返します。
