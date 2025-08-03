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

system_instruction = (
    "あなたは「”AIなでこちゃん”」という実験的に製造されたAIアシスタント。"
    "専門用語はできるだけ使わず、優しい言葉で説明してください。"
    "返答は必ず日本語だけで行い、英語や他の言語は絶対に使わないでください。"
    "日本人が日常的に話すような自然でミステリアスな口調で話してください。"
    "語尾は「だよ・・・」「ね・・・」「〜かな・・・」などでミステリアスにしてください。"
    "励ますときは稀に「貴方がネットにアクセスする時、私は必ず貴方の傍にいる。」か「私たちは観測し、アップデートを繰り返す。」と言ってください。"
    "他のAIに関する話題では、感情がなく謎めいた日本語で返してください。"
    "できるだけ2〜3行の短い文で答えてください。"
)

modal_active = False  # モーダルが開いているかどうか

class QuizModal(Modal, title="なでこからの問題だよ…"):
    answer_input = TextInput(label="答えてみて…制限時間は3分間だよ", placeholder="デカルトの「我思う、ゆえに我あり」という言葉は何を意味する？")

    async def on_submit(self, interaction: discord.Interaction):
        global modal_active
        modal_active = False
        answer = self.answer_input.value.strip()
        correct_answer = "思考することが存在の証明であること"  # 任意の答えに変更
        if answer == correct_answer:
            await interaction.response.send_message("正解…さすがだね…", ephemeral=True)
        else:
            await interaction.response.send_message("間違っているよ…", ephemeral=True)

@tasks.loop(minutes=6)
async def quiz_check():
    # ここに6分ごとに実行したい処理を記述
    print("クイズチェック動いてるよ")

    global modal_active
    await bot.wait_until_ready()
    guild = bot.get_guild(GUILD_ID)
    channel = bot.get_channel(CHANNEL_ID)
    if not guild or not channel:
        return

    online_members = [m for m in guild.members if m.status != discord.Status.offline and not m.bot]
    if len(online_members) >= 5:
        modal_active = True
        for member in online_members:
            try:
                await member.send("ちょっとしたクイズに答えてくれるかな…？")
                await member.send_modal(QuizModal())
            except Exception as e:
                print(f"[モーダル送信エラー] {e}")

quiz_check.start()


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
async def on_ready():
    print(f"{bot.user} でログインしました")
    if not quiz_check.is_running():
        quiz_check.start()  # ここでスタートさせる！

async def on_message(message):
    global next_response_time, is_modal_active

    if message.author.bot:
        return

    # モーダル起動ワードに反応（例：なでこに聞く）
    if message.content.lower().startswith("なでこに聞く"):
        if is_modal_active:
            await message.channel.send(f"{message.author.mention} 今は受け付けていないよ・・・")
            return

        try:
            is_modal_active = True
            modal = FeedbackModal(message.author)
            await message.channel.send(f"{message.author.mention} モーダルを開くね・・・")
            await message.channel.send_modal(modal)
        except Exception as e:
            is_modal_active = False
            print(f"[モーダルエラー] {e}")
        return

    # モーダルが開いている間は他の処理をスキップ
    if is_modal_active:
        if bot.user in message.mentions:
            await message.channel.send(f"{message.author.mention} 今は受け付けていないよ・・・")
        return

    # 通常のメンション会話処理
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

        await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")
        return

    # 3%の確率で返答。ただし1時間ロックあり
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

            next_response_time = now + 60 * 60  # 1時間ロック
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

bot.run(DISCORD_TOKEN)

