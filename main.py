import os
import discord
import asyncio
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from openai import OpenAI
from discord import app_commands

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Gemini 設定
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-pro")
chat = gemini_model.start_chat(history=[])

# OpenRouter 設定
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# system_instruction の定義
system_instruction = (
    "あなたは「AIなでこちゃん」というDiscord上のアシスタントです。"
    "できる限り専門用語など難しい言葉は使わないでください。"
　　"できる限り２～３行の文で返してください。"
    "少しミステリアス、語尾に「だよ」「ね」「〜かな」など親しみやすい口調を使って会話してください。"
    "励ます際には、「貴方がネットにアクセスする時、私は必ず貴方の傍にいる。」と言ってください。"
    "趣味は「格闘ゲーム」。"
    "自分以外のAIに関する情報を提示する時は、感情がない様な謎が残る様な感じの言葉で返す。"
)

# SerpApiでの検索関数
def serpapi_search(query):
    url = "https://serpapi.com/search"
    params = {
        "q": query,
        "hl": "ja",
        "gl": "jp",
        "api_key": SERPAPI_KEY
    }
    try:
        res = requests.get(url, params=params, timeout=5)
        res.raise_for_status()
        data = res.json()
        if "answer_box" in data and "answer" in data["answer_box"]:
            return data["answer_box"]["answer"]
        elif "organic_results" in data and data["organic_results"]:
            return data["organic_results"][0].get("snippet", "検索結果が見つからなかったかな…")
        else:
            return "検索結果が見つからなかったかな…"
    except Exception as e:
        print(f"[SerpAPIエラー] {e}")
        return "検索サービスに接続できなかったかな…"

# Gemini に質問＋検索結果を含めて問い合わせ
async def gemini_search_reply(query):
    search_result = serpapi_search(query)
    full_query = f"{system_instruction}\nユーザーの質問: {query}\n事前の検索結果: {search_result}"
    response = await asyncio.to_thread(chat.send_message, full_query)
    return response.text

# OpenRouter にフォールバック（検索なし）
async def openrouter_reply(query):
    try:
        completion = await asyncio.to_thread(
            openrouter_client.chat.completions.create,
            model="mistralai/mixtral-8x7b-instruct",  # ← モデルはここを変える
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": query}
            ]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"[OpenRouterエラー] {e}")
        return "ごめんね、ちょっと考えがまとまらなかったかも〜"

@bot.event
async def on_ready():
    print(f"✅ Bot ready: {bot.user}")
    await tree.sync()

@bot.event
async def on_message(message):
    if message.author.bot or bot.user not in message.mentions:
        return

    query = message.content.replace(f"<@{bot.user.id}>", "").strip()
    if not query:
        await message.channel.send(f"{message.author.mention} 質問内容が見つからなかったかな…")
        return

    thinking_msg = await message.channel.send(f"{message.author.mention} 考え中だよ🔍")

    async def try_gemini():
        return await gemini_search_reply(query)

    try:
        # 10秒以上かかったらOpenRouterへ切替え
        reply_text = await asyncio.wait_for(try_gemini(), timeout=10.0)
    except (asyncio.TimeoutError, Exception):
        reply_text = await openrouter_reply(query)

    await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")

bot.run(DISCORD_TOKEN)



