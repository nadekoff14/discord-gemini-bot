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

# Gemini設定
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-pro")
chat = gemini_model.start_chat(history=[])

# OpenRouter設定
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

# システムプロンプト
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

is_modal_active = False  # モーダルフラグ

class QuestionModal(Modal, title="問題に答えてね"):
    answer = TextInput(label="私の名前は？制限時間は3分間だよ。", style=discord.TextStyle.short)

    async def on_submit(self, interaction: discord.Interaction):
        global is_modal_active
        try:
            user_answer = self.answer.value.strip().lower()
            correct_answer = "968900402072387675"
            reply = "正解！すごいね・・・" if user_answer == correct_answer else "間違っているよ・・・もう一度考えてみてね・・・"
            await interaction.response.send_message(reply, ephemeral=True)
        finally:
            is_modal_active = False  # 必ず解除

class QuestionView(View):
    @discord.ui.button(label="答える…", style=discord.ButtonStyle.primary)
    async def open_modal(self, interaction: discord.Interaction, button: Button):
        global is_modal_active
        if is_modal_active:
            await interaction.response.send_message("今は回答中だよ・・・", ephemeral=True)
            return
        is_modal_active = True
        await interaction.response.send_modal(QuestionModal())

@tasks.loop(minutes=6)
async def check_online_members():
    global is_modal_active
    try:
        print("✅ オンラインチェック実行中")
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            print("Guildが見つかりません")
            return

        online = [m for m in guild.members if not m.bot and m.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd)]
        print(f"オンライン人数: {len(online)}")
        if len(online) >= 5:
            if is_modal_active:
                print("モーダル表示中のためスキップ")
                return
            channel = guild.get_channel(CHANNEL_ID)
            if not channel:
                print(f"チャンネルが見つかりません: {CHANNEL_ID}")
                return
            is_modal_active = True
            msg = await channel.send("条件を達成。ちょっと質問してもいい？", view=QuestionView())
            await asyncio.sleep(180)
            try:
                await msg.delete()
                print("✅ モーダルメッセージ削除完了")
            except Exception as e:
                print(f"[削除失敗] {e}")
            is_modal_active = False
    except Exception as e:
        print(f"[check_online_membersエラー] {e}")
        is_modal_active = False  # エラー時でも復旧させる

@bot.event
async def on_ready():
    print(f"🤖 Bot ready: {bot.user}")
    await tree.sync()
    check_online_members.start()

next_response_time = 0

@bot.event
async def on_message(message):
    global next_response_time, is_modal_active

    if message.author.bot or is_modal_active:
        return

    # メンションされたとき
    if bot.user in message.mentions:
        query = message.content.replace(f"<@{bot.user.id}>", "").strip()
        if not query:
            await message.channel.send(f"{message.author.mention} 質問内容が見つからなかったかな…")
            return
        thinking_msg = await message.channel.send(f"{message.author.mention} 考え中だよ🔍")
        try:
            reply_text = await asyncio.wait_for(gemini_search_reply(query), timeout=10.0)
        except:
            reply_text = await openrouter_reply(query)
        await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")
        return

    # 自然参加（5%）
    now = asyncio.get_event_loop().time()
    if now >= next_response_time and random.random() < 0.05:
        try:
            history = []
            async for msg in message.channel.history(limit=20):
                if not msg.author.bot and msg.content.strip():
                    history.append(f"{msg.author.display_name}: {msg.content.strip()}")
                if len(history) >= 10:
                    break
            history.reverse()
            prompt = f"{system_instruction}\n以下はDiscordのチャンネルでの最近の会話です。\nこれらを読んで自然に会話に入ってみてください。\n\n" + "\n".join(history)
            response = await openrouter_reply(prompt)
            await message.channel.send(response)
            next_response_time = now + 3600  # 1時間に1回
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

bot.run(DISCORD_TOKEN)
