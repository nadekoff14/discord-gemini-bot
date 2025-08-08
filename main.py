import os
import discord
import asyncio
import random
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime, timedelta, time, timezone
from discord.ext import tasks

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = discord.Client(intents=intents)

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
    "あなたは「”AIなでこちゃん”」という実験的に製造されたAIアシスタント。"
    "専門用語はできるだけ使わず、優しい言葉で説明してください。"
    "返答は必ず日本語だけで行い、英語や他の言語は絶対に使わないでください。"
    "日本人が日常的に話すような自然でミステリアスな口調で話してください。"
    "語尾は「だよ・・・」「ね・・・」「〜かな・・・」などでミステリアスにしてください。"
    "励ますときは稀に「私繧上◆縺励◆縺｡縺ｯ縺九ｓ縺昴￥縺励≠縺｣縺ｷ縺ｧ繝ｼ縺ｨ繧偵￥繧翫°縺医☆。」と言ってください。"
    "他のAIに関する話題では、感情がなく謎めいた日本語で返してください。"
    "できるだけ2〜6行の短い文で答えてください。"
)

next_response_time = 0  # 1時間ロック用グローバル変数

# SerpAPI でのウェブ検索
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

async def gemini_search_reply(query):
    search_result = serpapi_search(query)
    full_query = f"{system_instruction}\nユーザーの質問: {query}\n事前の検索結果: {search_result}"
    response = await asyncio.to_thread(chat.send_message, full_query)
    return response.text

async def openrouter_reply(query):
    try:
        completion = await asyncio.to_thread(
            openrouter_client.chat.completions.create,
            model="tngtech/deepseek-r1t2-chimera:free",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": query}
            ]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"[OpenRouterエラー] {e}")
        return "ごめんね、ちょっと考えがまとまらなかったかも"

async def summarize_logs(channel):
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    start_time = datetime(now.year, now.month, now.day, 7, 0, 0, tzinfo=JST) - timedelta(days=1)
    end_time = datetime(now.year, now.month, now.day, 6, 59, 59, tzinfo=JST)

    messages = []
    async for msg in channel.history(limit=1000, after=start_time, before=end_time, oldest_first=True):
        if msg.author.bot:
            continue
        clean_content = msg.content.strip()
        if clean_content:
            messages.append(f"{msg.author.display_name}: {clean_content}")

    if not messages:
        await channel.send("昨日は何も話されていなかったみたい・・・")
        return

    joined = "\n".join(messages)
    prompt = (
        f"{system_instruction}\n以下は Discord のチャンネルにおける昨日の 7:00〜今日の 6:59 までの会話ログです。\n"
        f"内容を要約して簡単に報告してください。\n\n{joined}"
    )
    try:
        summary = await openrouter_reply(prompt)
        await channel.send(f"\U0001F4CB **昨日のまとめだよ・・・**\n{summary}")
    except Exception as e:
        print(f"[要約エラー] {e}")
        await channel.send("ごめんね、昨日のまとめを作れなかった・・・")

@tasks.loop(time=time(7, 0, 0))
async def summarize_previous_day():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await summarize_logs(channel)

@bot.event
async def on_ready():
    print(f'Bot {bot.user} is ready.')
    summarize_previous_day.start()

@bot.event
async def on_message(message):
    global next_response_time
    if message.author.bot:
        return

    # 強制まとめトリガー
    if message.content.strip() == "できごとまとめ":
        await summarize_logs(message.channel)
        return

    # メンションによる質問処理
    if message.content.startswith(f"<@{bot.user.id}>") or message.content.startswith(f"<@!{bot.user.id}>"):
        query = message.content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not query:
            await message.channel.send(f"{message.author.mention} 質問内容が見つからなかったかな…")
            return

        thinking_msg = await message.channel.send(f"{message.author.mention} 考え中だよ\U0001F50D")

        async def try_gemini():
            return await gemini_search_reply(query)

        try:
            reply_text = await asyncio.wait_for(try_gemini(), timeout=10.0)
        except (asyncio.TimeoutError, Exception):
            reply_text = await openrouter_reply(query)

        await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")
        return

    now = asyncio.get_event_loop().time()
    if now < next_response_time:
        return

    if random.random() < 0.03:
        try:
            history = []
            async for msg in message.channel.history(limit=20, oldest_first=False):
                if not msg.author.bot and msg.content.strip():
                    history.append(f"{msg.author.display_name}: {msg.content.strip()}")
                if len(history) >= 10:
                    break
            history.reverse()
            history_text = "\n".join(history)
            prompt = (
                f"{system_instruction}\n以下はDiscordのチャンネルでの最近の会話です。\n"
                f"これらを読んで自然に会話に入ってみてください。\n\n{history_text}"
            )
            response = await openrouter_reply(prompt)
            await message.channel.send(response)
            next_response_time = now + 60 * 60
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

bot.run(DISCORD_TOKEN)

