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

# system_instruction の定義
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
            messages=[{"role": "system", "content": system_instruction}, {"role": "user", "content": query}]
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"[OpenRouterエラー] {e}")
        return "ごめんね、ちょっと考えがまとまらなかったかも"

class QuestionModal(Modal, title="ちょっと教えてほしい…"):
    answer = TextInput(label="今、どんな気分？", style=discord.TextStyle.paragraph)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"ふむふむ…「{self.answer.value}」なんだね・・・", ephemeral=True)

class QuestionView(View):
    @discord.ui.button(label="答える…", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(QuestionModal())

@tasks.loop(minutes=3)
async def check_online_members():
    try:
        print("オンラインチェック開始")
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            print("Guildが見つかりません")
            return
        online = [m for m in guild.members if not m.bot and m.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)]
        print(f"オンライン人数: {len(online)}")
        if len(online) >= 4:
            channel = guild.get_channel(CHANNEL_ID)
            if not channel:
                print(f"チャンネルが見つかりません: {CHANNEL_ID}")
                return
            await channel.send("みんな集まってるね・・・ちょっと質問してもいい？", view=QuestionView())
            print("モーダル投稿用のボタンを送信しました。")
    except Exception as e:
        print(f"[check_online_membersエラー] {e}")

@bot.event
async def on_ready():
    print(f"✅ Bot ready: {bot.user}")
    await tree.sync()
    check_online_members.start()

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
        except:
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
            prompt = f"{system_instruction}\n以下はDiscordのチャンネルでの最近の会話です。\nこれらを読んで自然に会話に入ってみてください。\n\n{history_text}"
            response = await openrouter_reply(prompt)
            await message.channel.send(response)
            next_response_time = now + 3600
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

bot.run(DISCORD_TOKEN)




