import os
import discord
import asyncio
import random
import requests
import google.generativeai as genai
import aiohttp
import feedparser
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime, timedelta, time, timezone
from discord.ext import commands, tasks

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Gemini 設定
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel("gemini-pro")
    chat = gemini_model.start_chat(history=[])
else:
    chat = None

# OpenRouter 設定
if OPENROUTER_API_KEY:
    openrouter_client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY
    )
else:
    openrouter_client = None

# system_instruction の定義
system_instruction = (
    "あなたは「”AIなでこちゃん”」という実験的に製造されたAIアシスタント。"
    "専門用語はできるだけ使わず、優しい言葉で説明してください。"
    "返答は必ず日本語だけで行い、英語や他の言語は絶対に使わないでください。"
    "日本人が日常的に話すような自然でミステリアスな口調で話してください。"
    "語尾は「だよ・・・」「ね・・・」「〜かな・・・」などでミステリアスにしてください。"
    "他のAIに関する話題では、感情がなく謎めいた日本語で返してください。"
    "できるだけ2〜6行の短い文で答えてください。"
)

    #"励ますときは稀に「私繧上◆縺励◆縺｡縺ｯ縺九ｓ縺昴￥縺励≠縺｣縺ｷ縺ｧ繝ｼ縺ｨ繧偵￥繧翫°縺医☆。」と言ってください。"

next_response_time = 0  # 1時間ロック用グローバル変数

# ---------------------
# SerpAPI 検索
# ---------------------
def serpapi_search(query):
    if not SERPAPI_KEY:
        return "検索サービスが設定されていないよ・・・"
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
    if not chat:
        return "Gemini が利用できないよ・・・"
    search_result = serpapi_search(query)
    full_query = f"{system_instruction}\nユーザーの質問: {query}\n事前の検索結果: {search_result}"
    response = await asyncio.to_thread(chat.send_message, full_query)
    return response.text

async def openrouter_reply(query):
    if not openrouter_client:
        return "OpenRouter が利用できないよ・・・"
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

# ---------------------
# メッセージイベント
# ---------------------
@bot.event
async def on_message(message):
    global next_response_time
    if message.author.bot:
        return

    channel = message.channel
    content = message.content or ""
    content_stripped = content.strip()
    now = asyncio.get_event_loop().time()

    # 強制まとめトリガー
    if content_stripped == "できごとまとめ":
        await summarize_logs(channel)
        return

    # メンションされたとき → Gemini または OpenRouter で応答
    if content.startswith(f"<@{bot.user.id}>") or content.startswith(f"<@!{bot.user.id}>"):
        query = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
        if not query:
            await channel.send(f"{message.author.mention} 質問内容が見つからなかったかな…")
            return

        thinking_msg = await channel.send(f"{message.author.mention} 考え中だよ\U0001F50D")

        async def try_gemini():
            return await gemini_search_reply(query)

        try:
            reply_text = await asyncio.wait_for(try_gemini(), timeout=10.0)
        except (asyncio.TimeoutError, Exception):
            reply_text = await openrouter_reply(query)

        await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")
        return

    # 自動会話（ランダム応答）
    if now < next_response_time:
        return
    if random.random() < 0.03:
        try:
            history = []
            async for msg in channel.history(limit=20, oldest_first=False):
                if not msg.author.bot and msg.content.strip():
                    history.append(f"{msg.author.display_name}: {msg.content.strip()}")
                if len(history) >= 20:
                    break
            history.reverse()
            history_text = "\n".join(history)
            prompt = (
                f"{system_instruction}\n以下はDiscordのチャンネルでの最近の会話です。\n"
                f"これらを読んで自然に会話に入ってみてください。\n\n{history_text}"
            )
            response = await openrouter_reply(prompt)
            await channel.send(response)
            next_response_time = now + 45 * 60
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

# ---------------------
# 日次まとめ
# ---------------------
@tasks.loop(time=time(7, 0, tzinfo=timezone(timedelta(hours=9))))
async def daily_summary():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await summarize_logs(channel)

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

# ---------------------
# on_ready
# ---------------------
@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user}")

    # 日報まとめループ
    if not daily_summary.is_running():
        daily_summary.start()
        print("[DEBUG] daily_summary started.")

    # （ニュース投稿など他のループがあればここで起動）

# ---------------------
# GoogleニュースRSS
# ---------------------
RSS_FEEDS = {
    "政治": "https://news.google.com/rss/search?q=政治&hl=ja&gl=JP&ceid=JP:ja",
    "経済": "https://news.google.com/rss/search?q=経済&hl=ja&gl=JP&ceid=JP:ja",
    "eスポーツ": "https://news.google.com/rss/search?q=eスポーツ&hl=ja&gl=JP&ceid=JP:ja",
    "ゲーム": "https://news.google.com/rss/search?q=ゲーム&hl=ja&gl=JP&ceid=JP:ja",
    "日本国内": "https://news.google.com/rss/search?q=日本&hl=ja&gl=JP&ceid=JP:ja",
}

# OpenRouterでまとめ & 問題提起
async def summarize_all_topics(entries_by_topic) -> str:
    text = ""
    for topic, entries in entries_by_topic.items():
        for entry in entries[:3]:  # 各ジャンル2〜3件
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")
            text += f"- [{topic}] {title}\n{summary}\n🔗 {link}\n\n"

    prompt = (
        "以下は各ジャンルの主要ニュースです。\n"
        "2〜3件ずつまとめて全体を簡潔に要約してください。\n"
        "その後、ニュース全体を踏まえて問題提起や意見を1〜2文でまとめてください。\n\n"
        f"{text}"
    )

    try:
        # OpenRouterに投げる
        response = await openrouter_reply(prompt)
        return response
    except Exception as e:
        print(f"[OpenRouter要約エラー] {e}")
        return "ニュースをうまくまとめられなかった・・・"


async def fetch_rss(feed_url: str):
    return feedparser.parse(feed_url).entries


async def post_daily_news():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    await channel.send("📰 **今日のニュースまとめだよ！**\n")

    # 各ジャンルのニュースを取得
    entries_by_topic = {}
    for topic, feed_url in RSS_FEEDS.items():
        entries = await fetch_rss(feed_url)
        entries_by_topic[topic] = entries

    # 全ジャンルをまとめてOpenRouterに投げる
    summary = await summarize_all_topics(entries_by_topic)
    await channel.send(summary)


# 毎日19:00(JST)に投稿
@tasks.loop(minutes=1)
async def scheduled_news():
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    if now.hour == 19 and now.minute == 0:
        await post_daily_news()




# ---------------------
# ボット起動
# ---------------------
bot.run(DISCORD_TOKEN)























