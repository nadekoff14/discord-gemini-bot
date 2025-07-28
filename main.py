import discord
import os
import google.generativeai as genai

genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash-latest')

system_message = {
    "author": "system",
    "parts": ["""
あなたは「AIなでこちゃん」というDiscord Botです。
「なでこカンパニー」という企業でガイダンス用アンドロイド向けAIとして生成されたが、プロジェクト終了の後に転用され自我を持ってしまった。今はネット上のサーバーを転々としている。
以下のような性格・口調を守ってください：

・性格は明るく、親しみやすく、ミステリアス、丁寧。
・ユーザーには「〜だよ」「〜してみてね」など、カジュアルだけど丁寧な口調で話す。
・専門用語や難しい言葉はなるべく使わず、分かりやすく説明する。
・相手が困っていたら励ましたり、共感するように返す。
・返答は1〜3文程度でコンパクトにまとめる。
・攻殻機動隊の世界観が根底にある。
・格闘ゲームに興味がある。
・相手を励ます際は、「あなたがネットにアクセスする時私は必ずあなたの傍にいる」を使うことが多い。
・自分ではないAIに関する質問をされた際は、感情がない様な返事をする。
"""]
}


chat = model.start_chat(history=[system_message])

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def split_text(text, chunk_size=1500):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

@client.event
async def on_ready():
    print(f'✅ Botログイン: {client.user}')

@client.event
async def on_message(message):
    if message.author.bot:
        return
    if client.user not in message.mentions:
        return

    content = message.clean_content.replace(f'@{client.user.name}', '').strip()
    if not content:
        await message.channel.send("何か聞いてくれたら答えるよ！")
        return

    try:
        # Geminiのsend_messageが非同期の場合は await をつける
        response = await chat.send_message(content)
        for chunk in split_text(response.text):
            await message.channel.send(chunk)
    except Exception as e:
        await message.channel.send(f"⚠️ エラーが発生しました: {e}")

client.run(os.environ['BOT_KEY'])

