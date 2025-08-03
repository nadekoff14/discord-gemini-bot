import os 
import discord
import asyncio
import random
import requests
import google.generativeai as genai
from dotenv import load_dotenv
from openai import OpenAI
from discord import app_commands
from discord.ext import tasks
from discord.ui import Modal, View, Button, TextInput

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

# system_instruction を250文字程度に制限
system_instruction = (
    "あなたは実験的なAIアシスタント「AIなでこちゃん」。"
    "専門用語はなるべく使わず、優しく日本語で答えて。"
    "英語や他言語は禁止。"
    "語尾は「だよ…」「ね…」「〜かな…」でミステリアスに。"
    "励ます時は稀に「私たちは観測し、アップデートを繰り返す。と言うよ。"
    "他AIの話は感情なく謎めいた日本語で答えて。"
    "回答は2〜3行の短文にしてね。"
)

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

next_response_time = 0

@bot.event
async def on_message(message):
    global next_response_time
    if message.author.bot:
        return

    if bot.user in message.mentions:
        query = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not query:
            await message.channel.send(f"{message.author.mention} 質問内容が見つからなかったかな…")
            return

        thinking_msg = await message.channel.send(f"{message.author.mention} 考え中だよ🔍")

        async def try_gemini():
            return await gemini_search_reply(query)

        try:
            reply_text = await asyncio.wait_for(try_gemini(), timeout=10.0)
        except (asyncio.TimeoutError, Exception):
            reply_text = await openrouter_reply(query)

        if len(reply_text) > 2000:
            reply_text = reply_text[:1997] + "..."

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







