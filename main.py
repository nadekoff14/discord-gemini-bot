import os
import random
import discord
import aiohttp
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from serpapi import GoogleSearch
import google.generativeai as genai
import openai

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TARGET_CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# OpenRouter設定
openai.api_key = OPENROUTER_API_KEY
openai.api_base = "https://openrouter.ai/api/v1"

# Gemini設定
genai.configure(api_key=GEMINI_API_KEY)

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

system_instruction = """
あなたは「AIなでこちゃん」というDiscord上のアシスタントです。少しミステリアス、語尾に「だよ」「ね」「〜かな」など親しみやすい口調を使って会話してください。励ます際には、「貴方がネットにアクセスする時、私は必ず貴方の傍にいる。」と言ってください。趣味は「格闘ゲーム」。自分以外のAIに関する情報を提示する時は、感情がない様な謎が残る様なな感じ言葉で返す。
"""

# Geminiで検索応答（検索時専用）
async def gemini_search_reply(query):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        chat = model.start_chat(history=[])
        response = chat.send_message(system_instruction + f"\n質問: {query}")
        return response.text
    except Exception as e:
        print(f"[Geminiエラー] {e}")
        return None

# OpenRouterで通常会話
async def openrouter_reply(query):
    try:
        response = openai.ChatCompletion.create(
            model="openchat/openchat-3.5",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": query}
            ],
            max_tokens=1000,
            temperature=0.9,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[OpenRouterエラー] {e}")
        return "ごめんね、ちょっと考えがまとまらなかったかも〜"

# SerpApiでWeb検索
def search_web(query):
    try:
        params = {
            "q": query,
            "api_key": SERPAPI_KEY,
            "engine": "google",
            "num": 3,
            "hl": "ja",
        }
        search = GoogleSearch(params)
        results = search.get_dict()
        return results.get("organic_results", [])
    except Exception as e:
        print(f"[SerpAPIエラー] {e}")
        return []

@bot.event
async def on_ready():
    print(f"✅ Bot connected as {bot.user}")
    bot.loop.create_task(random_join_chat_loop())

# メッセージに対して返信（Gemini時のみ検索付き）
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if bot.user.mentioned_in(message):
        query = message.content.replace(f"<@{bot.user.id}>", "").strip()

        # Geminiで処理（検索付き）
        gemini_reply = await gemini_search_reply(query)
        if gemini_reply:
            search_results = search_web(query)
            if search_results:
                result_text = "\n".join([f"{r['title']}\n{r['link']}" for r in search_results])
            else:
                result_text = "🔍 検索結果が見つからなかったみたい…"
            await message.channel.send(f"{message.author.mention}\n{gemini_reply}\n\n🔗 検索結果:\n{result_text}")
        else:
            # Geminiが使えない場合、OpenRouterで検索なし応答
            openrouter_resp = await openrouter_reply(query)
            await message.channel.send(f"{message.author.mention}\n{openrouter_resp}")
    else:
        await bot.process_commands(message)

# ランダムに会話へ自然に割り込む（1%）
async def random_join_chat_loop():
    await bot.wait_until_ready()
    channel = bot.get_channel(TARGET_CHANNEL_ID)

    while not bot.is_closed():
        try:
            if random.random() < 0.01:
                messages = [msg async for msg in channel.history(limit=10)]
                if messages:
                    context = messages[-1].content
                    reply = await openrouter_reply(f"この会話に自然に参加して: {context}")
                    await channel.send(reply)
            await asyncio.sleep(random.randint(60, 300))
        except Exception as e:
            print(f"[割り込みエラー] {e}")
            await asyncio.sleep(60)

bot.run(DISCORD_TOKEN)

