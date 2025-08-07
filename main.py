import os
import discord
import asyncio
import random
import requests
from dotenv import load_dotenv
from discord import app_commands
from discord.ext import tasks
from discord.ui import Modal, View, Button, TextInput

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
HF_API_TOKEN = os.getenv("HF_API_TOKEN")  # Hugging Faceトークン
SERPAPI_KEY = os.getenv("SERPAPI_KEY")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)

# Hugging Face設定
HF_MODEL_ID = "rinna/japanese-gpt-neox-3.6b"
HF_HEADERS = {
    "Authorization": f"Bearer {HF_API_TOKEN}",
    "Content-Type": "application/json"
}

system_instruction = (
    "あなたは「”AIなでこちゃん”」という実験的に製造されたAIアシスタント。"
    "専門用語はできるだけ使わず、優しい言葉で説明してください。"
    "返答は必ず日本語だけで行い、英語や他の言語は絶対に使わないでください。"
    "日本人が日常的に話すような自然でミステリアスな口調で話してください。"
    "語尾は「だよ・・・」「ね・・・」「〜かな・・・」などでミステリアスにしてください。"
    "励ますときは稀に「私たちは観測し、アップデートを繰り返す。」と言ってください。"
    "他のAIに関する話題では、感情がなく謎めいた日本語で返してください。"
    "できるだけ2〜3行の短い文で答えてください。"
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

async def huggingface_reply(query):
    search_result = serpapi_search(query)
    prompt = f"{system_instruction}\nユーザーの質問: {query}\n事前の検索結果: {search_result}"

    url = f"https://api-inference.huggingface.co/models/{HF_MODEL_ID}"
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 150,
            "temperature": 0.7,
            "top_p": 0.9
        }
    }
    try:
        response = await asyncio.to_thread(
            requests.post,
            url,
            headers=HF_HEADERS,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and "error" in data:
            print(f"[HuggingFace API エラー] {data['error']}")
            return "ごめんね、うまく答えられなかったかな…"
        # 生成テキストはdata[0]["generated_text"]に入っている想定
        return data[0]["generated_text"]
    except Exception as e:
        print(f"[HuggingFace通信エラー] {e}")
        return "ごめんね、処理中に問題が起きたかな…"

# グローバル変数を定義（1時間ロック用）
next_response_time = 0  # Unix時間（初期値）

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

        reply_text = None
        try:
            reply_text = await asyncio.wait_for(huggingface_reply(query), timeout=30.0)
        except asyncio.TimeoutError:
            reply_text = "ごめんね、応答が遅れてしまったかな…"
        except Exception as e:
            print(f"[応答エラー] {e}")
            reply_text = "ごめんね、ちょっと考えがまとまらなかったかも"

        await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")
        return

    # 3%の確率で自然参加（1時間ロック）
    now = asyncio.get_running_loop().time()
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
            response = await huggingface_reply(prompt)

            await message.channel.send(response)
            next_response_time = now + 60 * 60
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

bot.run(DISCORD_TOKEN)




