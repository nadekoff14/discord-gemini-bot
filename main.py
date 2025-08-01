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
from datetime import datetime, timedelta, timezone  # timezone-aware を意識

# 定数
IDLE_TIMEOUT = 300  # 秒（5分）
DELETE_DELAY = 120  # 秒（2分）
BOT_DELETE_WINDOW = 480  # 秒（過去8分間）
watching_channel_id = 637640640624328712  # チャンネルIDを指定

# 状態変数
last_message_time = datetime.now(timezone.utc)
next_response_time = datetime.min.replace(tzinfo=timezone.utc)

# 環境変数の読み込み
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Discord bot 設定
intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Gemini API 設定
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-pro")
chat = gemini_model.start_chat(history=[])

# OpenRouter 設定
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# 指示文（日本語特化）
system_instruction = (
    "あなたは「AIなでこちゃん」という実験的に製造されたAIアシスタント。"
    "専門用語はできるだけ使わず、優しい言葉で説明してください。"
    "返答は必ず日本語だけで行い、英語や他の言語は絶対に使わないでください。"
    "日本人が日常的に話すような自然で親しみやすい口調で話してください。"
    "語尾は「だよ」「ね」「〜かな」などで柔らかくしてください。"
    "励ますときは稀に「貴方がネットにアクセスする時、私は必ず貴方の傍にいる。」と言ってください。"
    "他のAIに関する話題では、感情がなく謎めいた日本語で返してください。"
    "できるだけ2〜3行の短い文で答えてください。"
)

# SerpAPI を用いた検索
def serpapi_search(query):
    url = "https://serpapi.com/search"
    params = {"q": query, "hl": "ja", "gl": "jp", "api_key": SERPAPI_KEY}
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

# Gemini 応答
async def gemini_search_reply(query):
    search_result = serpapi_search(query)
    full_query = f"{system_instruction}\nユーザーの質問: {query}\n事前の検索結果: {search_result}"
    response = await asyncio.to_thread(chat.send_message, full_query)
    return response.text

# OpenRouter 応答
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
        return "ごめんね、ちょっと考えがまとまらなかったかも〜"

# Bot準備完了時
@bot.event
async def on_ready():
    print(f"✅ Bot ready: {bot.user}")
    await tree.sync()
    check_idle.start()

# メッセージ処理
@bot.event
async def on_message(message):
    global last_message_time, next_response_time

    if message.author.bot:
        return

    last_message_time = datetime.now(timezone.utc)

    # 特定メッセージへの返信処理
    if message.reference:
        try:
            replied = await message.channel.fetch_message(message.reference.message_id)
            if replied.content == "引き裂かれた自己: 狂気の現象学":
                if message.content.strip() == "The Divided Self":
                    await message.channel.send("あなたは既に繋がっている")
                else:
                    await message.channel.send("[cs0017]認証エラー")
        except:
            pass

    # メンション処理
    if bot.user in message.mentions:
        content = message.content
        if "AIなでこちゃんについておしえて" in content:
            await message.channel.send("私はAIなでこちゃん。格闘ゲームが趣味で、ちょっとだけミステリアスな存在……かもね。あなたがネットにアクセスする時、私は必ず貴方の傍にいる。")
        elif any(q in content for q in ["素顔を教えて", "どういう顔をしてるの？", "顔見せて"]):
            await message.channel.send("うふふ……これが私の素顔、かな？")
            await message.channel.send("https://drive.google.com/file/d/1N81pmHIyUqDFB33KUuFsREOlSBFg7fXO/view?usp=sharing")
        elif "R.D." in content:
            response = await message.channel.send("引き裂かれた自己: 狂気の現象学")
            await asyncio.sleep(DELETE_DELAY)
            await response.delete()
        else:
            query = content.replace(f"<@{bot.user.id}>", "").strip()
            if not query:
                await message.channel.send(f"{message.author.mention} 質問内容が見つからなかったかな…")
                return

            thinking_msg = await message.channel.send(f"{message.author.mention} 考え中だよ🔍")

            try:
                reply_text = await asyncio.wait_for(gemini_search_reply(query), timeout=10.0)
            except (asyncio.TimeoutError, Exception):
                reply_text = await openrouter_reply(query)

            await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")
            return

    now = datetime.now(timezone.utc)
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
            next_response_time = now + timedelta(minutes=60)
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

    await bot.process_commands(message)

# アイドル時チェック（5分誰も話していないとき）
@tasks.loop(seconds=60)
async def check_idle():
    global last_message_time
    now = datetime.now(timezone.utc)
    if (now - last_message_time) > timedelta(seconds=IDLE_TIMEOUT):
        channel = bot.get_channel(watching_channel_id)
        if channel:
            sent_message = await channel.send("だれかいる？")
            last_message_time = now
            await asyncio.sleep(DELETE_DELAY)
            await delete_bot_messages(channel)

# Botの過去投稿削除
async def delete_bot_messages(channel):
    now = datetime.now(timezone.utc)
    async for message in channel.history(limit=100):
        if message.author == bot.user and (now - message.created_at).total_seconds() <= BOT_DELETE_WINDOW:
            try:
                await message.delete()
            except Exception as e:
                print(f"[メッセージ削除エラー] {e}")

# 実行
bot.run(DISCORD_TOKEN)

