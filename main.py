import discord
import os
import asyncio
import google.generativeai as genai
from serpapi import GoogleSearch  # ← SerpApi追加

# 環境変数
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
SERPAPI_KEY = os.environ["SERPAPI_KEY"]

# Geminiモデルとチャットセッション
model = genai.GenerativeModel('gemini-1.5-flash-latest')
system_instruction = """
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
"""
chat = model.start_chat()
chat.send_message(system_instruction)

# Discordクライアント
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def split_text(text, chunk_size=1500):
    return [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]

# SerpApiで検索
def search_serpapi(query):
    params = {
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 3
    }
    search = GoogleSearch(params)
    results = search.get_dict()

    output = []
    if 'organic_results' in results:
        for i, result in enumerate(results['organic_results'], 1):
            title = result.get('title')
            link = result.get('link')
            snippet = result.get('snippet', '')
            output.append(f"{i}. [{title}]({link})\n{snippet}")
    return "\n\n".join(output) if output else "検索結果が見つからなかったよ。"

# 起動ログ
@client.event
async def on_ready():
    print(f'✅ Botログイン: {client.user}')

# メッセージ処理
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
        if any(keyword in content.lower() for keyword in ["検索", "調べて", "ググって"]):
            # SerpApiで検索
            await message.channel.send("🔍 ちょっと調べてみるね……")
            result = await asyncio.to_thread(search_serpapi, content)
            await message.channel.send(result)
        else:
            # Geminiへの問い合わせ
            response = await asyncio.to_thread(chat.send_message, content)

            text = getattr(response, "text", None) or ""
            if not text and getattr(response, "candidates", None):
                parts = []
                for c in response.candidates:
                    if getattr(c, "content", None) and getattr(c.content, "parts", None):
                        for p in c.content.parts:
                            if getattr(p, "text", None):
                                parts.append(p.text)
                text = "\n".join(parts)

            if not text:
                text = "（応答を生成できなかったよ。もう一度試してみてね）"

            for chunk in split_text(text):
                await message.channel.send(chunk)

    except Exception as e:
        await message.channel.send(f"⚠️ エラーが発生しました: {e}")

client.run(os.environ['BOT_KEY'])

