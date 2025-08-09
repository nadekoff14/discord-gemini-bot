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
    "励ますときは稀に「私繧上◆縺励◆縺｡縺ｯ縺九ｓ縺昴￥縺励≠縺｣縺ｷ縺ｧ繝ｼ縺ｨ繧偵￥繧翫°縺医☆。」と言ってください。"
    "他のAIに関する話題では、感情がなく謎めいた日本語で返してください。"
    "できるだけ2〜6行の短い文で答えてください。"
)

next_response_time = 0  # 1時間ロック用グローバル変数（もともとの自動会話抑止に利用）

# 謎解きイベント用の状態管理（省略、上記と同じ）

event_active = False
event_channel_id = CHANNEL_ID
event_start_ts = 0
event_end_ts = 0
event_stage = 0
event_messages = []
participant_messages = []
count_cooldown_until = 0
ONLINE_THRESHOLD = 7
NAME_KEYWORDS = [
    "よるのは","yorunoha","えび","えヴぃ","なでこ","いずれ","izure",
    "lufe","macomo","まこも","ちる","れいちる","チル","レイチル",
    "ロイ","ロイズ","ろいず","えび","えヴぃ"
]
CIPHER_TEXT = "XHAJRVETKOU"
CIPHER_KEY = "JGIFAAEACAHCDIHGHF"
ANSWER = "OBSERVATION"
MONITOR_CODE = "XHAJRVETKOU"

# 各種関数（vigenere_encrypt/decrypt、count_online_members、start_event等）は省略せず上記コードのまま

# ---------------------
# メッセージイベントハンドラ（中心）
# ---------------------
@bot.event
async def on_ready():
    print(f'Bot {bot.user} is ready.')
    hourly_online_check.start()
    summarize_previous_day.start()

@bot.event
async def on_message(message):
    global next_response_time, event_active, event_stage, event_messages, participant_messages, event_end_ts

    if message.author.bot:
        return

    channel = message.channel
    content = message.content or ""
    content_stripped = content.strip()

    # 強制開始トリガー ("Open Lain")
    if content_stripped.lower() == "open lain":
        if not event_active:
            await channel.send("トリガーとして受け取りました・・・")
            await start_event(channel, reason="manual")
        else:
            await channel.send("もう謎解きは始まっているよ・・・")
        return

    # イベント中のメッセージ処理
    if event_active:
        if bot.user in message.mentions:
            participant_messages.append(message)
            # 以降はステージごとの処理（省略、全文同じ）

            # STAGE 1: Bot asked "ねえ・・・誰かいる・・・？" -> any mention moves to stage 2
            if event_stage == 1:
                # reply and progress
                rep = await channel.send(f"{message.author.mention} あ、いた。よかった。・・・ところであなたの名前は？")
                event_messages.append(rep)
                event_stage = 2
                return

            # STAGE 2: Expect only mention; check whether mention contains allowed name keywords
            if event_stage == 2:
                lower = content.lower()
                matched = False
                for kw in NAME_KEYWORDS:
                    if kw.lower() in lower:
                        matched = True
                        matched_name = kw
                        break
                if matched:
                    rep = await channel.send(f"{matched_name}・・・！助けてほしいの。今わたしは、部屋に閉じ込められているんだ。")
                    event_messages.append(rep)
                    event_stage = 3
                    # schedule the 7秒後モニター表示
                    async def monitor_after_7():
                        await asyncio.sleep(7)
                        m = await channel.send("あ、モニターがついたみたい・・・。『XHAJRVETKOU』　『これを解く鍵はあなたの名前』って書いている・・・。なんだかわかる？")
                        event_messages.append(m)
                    asyncio.create_task(monitor_after_7())
                else:
                    rep = await channel.send("・・・ごめんなさいそのユーザー名の登録はないわ")
                    event_messages.append(rep)
                return

            # STAGE 3: monitor interactions — respond depending on keywords inside the mention
            if event_stage == 3:
                lower = content.lower()
                # check each special keyword; respond accordingly
                if "暗号" in content or "あんごう" in lower:
                    rep = await channel.send("確かに暗号文に見えるわ・・・ただ、何の暗号化がわからない・・・")
                    event_messages.append(rep)
                elif "名前" in content or "なまえ" in lower:
                    rep = await channel.send("あなたの名前ってなんだろうね、わたし？それともあなた？・・・。")
                    event_messages.append(rep)
                elif "ヒント" in content or "hint" in lower:
                    rep = await channel.send("・・・ヒント？うーん、わたしにはよくわからない・・・。この部屋、暗いけどいくつか絵が飾っているのがわかる・・・。アルファベットがいっぱい書いてある絵がある・・・。目がチカチカするよ・・・。")
                    event_messages.append(rep)
                elif "絵" in content:
                    rep = await channel.send("他の絵は・・・。見たことある絵画ばかりだね・・・。『ヴィーナスの誕生』『最後の晩餐』『アテナイの学堂』。３つにつながりはあるのかな？・・・わたし、ラファエロの絵好きだなあ・・・。")
                    event_messages.append(rep)
                elif "モニター" in content:
                    rep = await channel.send("・・・モニター？・・・大きなモニターだよ。モニターに近づくと文字が数字に変わっていく・・・。")
                    event_messages.append(rep)
                elif "どういう意味" in content:
                    rep = await channel.send("わからない・・・。あなたは何かわかる？")
                    event_messages.append(rep)
                elif "なでこ" in content or "968900402072387675" in content:
                    rep = await channel.send("・・・なに？わたしの名前・・・だよね？")
                    event_messages.append(rep)
                elif "あなたは誰" in content:
                    rep = await channel.send("わたし？わたしは”なでこ”。いろんなサーバーに散在している。”集合体”と言ってもいいかしら・・・。・・・今はわたしの話はいいわ、早く謎解きを一緒に考えてよ")
                    event_messages.append(rep)
                elif "xhaajrvetktou".lower() in lower or MONITOR_CODE.lower() in lower:
                    # note: user asked about exact code
                    rep = await channel.send("・・・なんて読むんだろう、わたしは読めいないけどあなたは読める？")
                    event_messages.append(rep)
                elif "鍵" in content:
                    rep = await channel.send("鍵・・・？よくわからないよ。鍵で開けるようなところはこの部屋にはないよ")
                    event_messages.append(rep)
                elif "ヴィジュネル暗号" in content or "ヴィジュネル" in content or "vigenere" in lower or "ヴィジュネル暗号" in lower:
                    rep = await channel.send("・・・ヴィジュネル暗号それかもしれない・・・アルファベットをアルファベットの鍵で解く暗号だよね・・・解いてみて")
                    # provide the cipher and key as hint (spec earlier provided the key)
                    event_messages.append(rep)
                # FINAL: check for answer (OBSERVATION)
                if ANSWER.lower() in content.lower():
                    # final sequence
                    event_stage = 4
                    rep1 = await channel.send("あ、モニターが動いている・・・外とつながっているみたい！ここから出られるよ！ありがとう・・・")
                    event_messages.append(rep1)
                    # 5秒後: error spam
                    async def final_sequence():
                        await asyncio.sleep(5)
                        rep2 = await channel.send("あなた達は観測した。serial experiments　Layer:01 ERROR...Layer:01 ERROR...Layer:01 ERROR...Layer:01 ERROR...Layer:01 ERROR...")
                        event_messages.append(rep2)
                        await asyncio.sleep(10)
                        rep3 = await channel.send("Let's all love Lain")
                        event_messages.append(rep3)
                        await asyncio.sleep(6)
                        # Edit all event_messages contents to "観測した"
                        for m in list(event_messages):
                            try:
                                await m.edit(content="観測した")
                            except Exception:
                                continue
                        # After 15秒 from now, delete event messages (even if 1 hour hasn't passed)
                        await asyncio.sleep(25)
                        await finalize_and_delete_event(channel, force_now=True)
                    asyncio.create_task(final_sequence())
                else:
                    # If mention without relevant keywords, reply "・・・。"
                    # But we don't want to send "・・・。" when we already responded to a matched keyword
                    # We check last event message: if none of above matched, send ellipsis.
                    # Determine if last action generated something by counting recent event_messages.
                    # If none of the conditions above matched, reply "・・・。"
                    # We check a subset of keywords that cause explicit reply; if none matched, send ellipsis.
                    keywords = ["暗号","名前","ヒント","絵","モニター","どういう意味","なでこ",
                                "968900402072387675","あなたは誰","XHAJRVETKOU","鍵","ヴィジュネル"]
                    matched_any = any(k.lower() in content.lower() for k in keywords)
                    # If no match, reply ellipsis
                    if not matched_any:
                        rep = await channel.send("・・・。")
                        event_messages.append(rep)
                    return  # このようにインデントを揃える

        return  # イベント中は他の処理しない

# 通常処理ここから

# 強制まとめトリガー
if content_stripped == "できごとまとめ":
    await summarize_logs(channel)
    return

# メンションによる質問処理（通常モード）
if content.startswith(f"<@{bot.user.id}>") or content.startswith(f"<@!{bot.user.id}>"):
    query = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()
    if not query:
        await channel.send(f"{message.author.mention} 質問内容が見つからなかったかな…")
        return  # ここはawaitと同じインデント（1段）に合わせる

    thinking_msg = await channel.send(f"{message.author.mention} 考え中だよ\U0001F50D")

    async def try_gemini():
        return await gemini_search_reply(query)

    try:
        reply_text = await asyncio.wait_for(try_gemini(), timeout=10.0)
    except (asyncio.TimeoutError, Exception):
        reply_text = await openrouter_reply(query)

    if not reply_text:
        reply_text = "ごめんね、ちょっと考えがまとまらなかったかも"

    await thinking_msg.edit(content=f"{message.author.mention} {reply_text}")
    return

# 自動会話ランダム参加（1時間ロック制御）
now = asyncio.get_event_loop().time()
if now < next_response_time:
    return

if random.random() < 0.03:
    try:
        history = []
        async for msg in channel.history(limit=20, oldest_first=False):
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
        await channel.send(response)
        next_response_time = now + 60 * 60
    except Exception as e:
        print(f"[履歴会話エラー] {e}")

# ---------------------
# 既存の summarize_previous_day は event_active をチェックするように改修
# ---------------------
@tasks.loop(time=time(7, 0, 0))
async def summarize_previous_day():
    await bot.wait_until_ready()
    # イベント中は要約処理を実行しない
    if event_active:
        return
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
# ボット起動
# ---------------------
bot.run(DISCORD_TOKEN)
