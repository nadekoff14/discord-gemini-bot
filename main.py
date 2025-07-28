import discord
import os
import google.generativeai as genai

# Gemini API 初期化
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash-latest')
chat = model.start_chat(history=[])

# Discord Bot 初期化
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# テキストをDiscord送信用に分割
def split_text(text, chunk_size=1500):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

@client.event
async def on_ready():
    print(f'✅ Botログイン: {client.user}')

@client.event
async def on_message(message):
    if message.author.bot:
        return

    # メンションされていなければ無視
    if client.user not in message.mentions:
        return

    # メンションを除いた本文を抽出
    content = message.clean_content.replace(f'@{client.user.name}', '').strip()

    if not content:
        await message.channel.send("何か聞いてくれたら答えるよ！")
        return

    try:
        # Gemini へ送信
        response = chat.send_message(content)

        # Geminiの返答を分割して送信
        for chunk in split_text(response.text):
            await message.channel.send(chunk)
    except Exception as e:
        await message.channel.send(f"⚠️ エラーが発生しました: {e}")

# Bot起動
client.run(os.environ['BOT_KEY'])
