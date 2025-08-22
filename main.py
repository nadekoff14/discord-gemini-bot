import os
import discord
import asyncio
import random
import requests
import google.generativeai as genai
import aiohttp
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
NEWS_API_KEY = os.getenv("NEWS_API_KEY")

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

# ---------------------
# 謎解きイベント用の状態管理
# ---------------------
event_active = False              # 謎解き全体のオン/オフ
event_channel_id = CHANNEL_ID     # 実行対象チャンネル（環境変数）
event_start_ts = 0                # イベント開始時のループ時間 (asyncio loop time)
event_end_ts = 0                  # イベント終了予定時刻（開始 + 3600）
event_stage = 0                   # 0=待機 1=問いかけ済→待メンション 2=名前受付→待指定名 3=モニター段階 ... etc
event_messages = []               # イベント中に生成したメッセージオブジェクト（botの投稿）を保存
participant_messages = []         # イベント中に参加者が送ったメッセージ（botにメンションしているもの）を記録
count_cooldown_until = 0          # オンラインカウントのクールダウン（1時間停止させる時に使用）
ONLINE_THRESHOLD = 6              # 起動条件の閾値
NAME_KEYWORDS = [
    "よるのは","yorunoha","えび","えヴぃ","なでこ","いずれ","izure",
    "lufe","macomo","まこも","ちる","れいちる","チル","レイチル",
    "ロイ","ロイズ","ろいず","えび","えヴぃ"
]
CIPHER_TEXT = "XHAJRVETKOU"       # 出題するヴィジュネル暗号文（先に作ったもの）
CIPHER_KEY = "JGIFAAEACAHCDIHGHF" # 指定のキー（ユーザー提供）
ANSWER = "OBSERVATION"            # 正解（大文字比較）
MONITOR_CODE = "XHAJRVETKOU"

# ---------------------
# 既存機能ラッパー（Web検索・OpenRouter等）を残すが、イベント中は無効にする
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
    # イベント中は無効化
    if event_active:
        return "今はちょっと静かにするね・・・"
    if not chat:
        return "Gemini が利用できないよ・・・"
    search_result = serpapi_search(query)
    full_query = f"{system_instruction}\nユーザーの質問: {query}\n事前の検索結果: {search_result}"
    response = await asyncio.to_thread(chat.send_message, full_query)
    return response.text

async def openrouter_reply(query):
    # イベント中は無効化
    if event_active:
        return "今はちょっと静かにするね・・・"
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
# ヴィジュネル暗号の暗号化/復号ユーティリティ（必要なら）
# ---------------------
def vigenere_encrypt(plaintext, key):
    result = []
    key = key.upper()
    key_indices = [ord(c) - ord('A') for c in key if c.isalpha()]
    if not key_indices:
        return plaintext
    ki = 0
    for ch in plaintext.upper():
        if ch.isalpha():
            p = ord(ch) - ord('A')
            k = key_indices[ki % len(key_indices)]
            c = (p + k) % 26
            result.append(chr(c + ord('A')))
            ki += 1
        else:
            result.append(ch)
    return "".join(result)

def vigenere_decrypt(ciphertext, key):
    result = []
    key = key.upper()
    key_indices = [ord(c) - ord('A') for c in key if c.isalpha()]
    if not key_indices:
        return ciphertext
    ki = 0
    for ch in ciphertext.upper():
        if ch.isalpha():
            c = ord(ch) - ord('A')
            k = key_indices[ki % len(key_indices)]
            p = (c - k) % 26
            result.append(chr(p + ord('A')))
            ki += 1
        else:
            result.append(ch)
    return "".join(result)


# 非同期でオンライン人数カウント
async def count_online_members(guild: discord.Guild):
    await guild.chunk()
    count = 0
    for m in guild.members:
        if m.bot:
            continue
        if m.status in (discord.Status.online, discord.Status.idle, discord.Status.dnd):
            count += 1
    return count

@tasks.loop(minutes=60)
async def hourly_online_check():
    global count_cooldown_until, event_active
    await bot.wait_until_ready()
    now = asyncio.get_event_loop().time()
    if now < count_cooldown_until:
        print(f"[DEBUG] クールダウン中: count_cooldown_until={count_cooldown_until}, now={now}")
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("[DEBUG] ギルドが取得できていません。")
        return

    online = await count_online_members(guild)
    print(f"[DEBUG] Online members: {online}")

    channel = bot.get_channel(event_channel_id)
    print(f"[DEBUG] event_active={event_active}, channel={channel}")

    if online >= ONLINE_THRESHOLD and not event_active and channel:
        print("[DEBUG] イベント開始条件を満たしました。start_eventを呼びます。")
        await start_event(channel, reason="auto")
    else:
        print("[DEBUG] イベント開始条件を満たしていません。")




# ---------------------
# イベントオーケストレーション
# ---------------------
async def start_event(channel: discord.abc.GuildChannel, reason="manual"):
    """
    イベント開始。reasonは "auto"（60分チェック）か "manual"（Open Lain）など
    """
    global event_active, event_start_ts, event_end_ts, event_stage, event_messages, participant_messages, count_cooldown_until

    if event_active:
        return
    event_active = True
    event_stage = 1
    event_messages = []
    participant_messages = []
    loop_now = asyncio.get_event_loop().time()
    event_start_ts = loop_now
    event_end_ts = loop_now + 3600  # 1時間
    # Post initial message (①)
    initial = await channel.send("ねえ・・・誰かいる・・・？")
    event_messages.append(initial)
    # start waiting for mentions (stage 1 -> stage2 when mention received)
    # 同時に「1時間後」の削除スケジュールはイベント終了側で管理（ただし最終解答による早期終了でも削除は実行）
    # 59分タイマー：到達しない場合の睡眠メッセージ
    asyncio.create_task(stage_59min_check(channel, event_start_ts))
    return

async def stage_59min_check(channel: discord.abc.GuildChannel, start_ts):
    """
    イベント開始から59分経過してもFINALに到達していなければ
    BOT が寝るメッセージを出して、メンション受け付けを停止（削除されるまで）
    """
    await asyncio.sleep(59 * 60)  # 59分
    global event_active, event_stage
    # もし既にイベント終了していたら何もしない
    if not event_active:
        return
    # まだFINALに到達していない（つまり event_stage < 4 ）なら眠る
    if event_stage < 4:
        msg1 = await channel.send("眠くなってきちゃった・・・。少し眠るね。")
        msg2 = await channel.send("---謎時イベント終了。システムを終了します。---")
        event_messages.extend([msg1, msg2])
        # 以降、メンションは削除されるまで受け付けない（実装上 event_active True の間は受け付けないので既に無効）
        # 削除実行は通常通り event_end または final 解答による早期削除で行う
    return

# ---------------------
# イベント終了処理：投稿の削除とカウント休止セット
# ---------------------
async def finalize_and_delete_event(channel: discord.abc.GuildChannel, force_now=False):
    """
    イベント終了時に実行。仕様により：
    - 初投稿から1時間分の投稿を削除（ここでは bot 投稿 + bot をメンションしたユーザー投稿を削除）
    - 削除後、1時間はオンライン人数のカウントを停止
    """
    global event_active, event_stage, event_messages, participant_messages, count_cooldown_until

    # collect window
    start_dt = event_start_ts
    end_dt = event_start_ts + 3600

    # Delete bot messages saved in event_messages
    # and delete participant_messages (user posts that mention bot during event)
    # Note: we only stored objects while running; fallback: search history in window.
    to_delete = []
    try:
        for m in event_messages:
            try:
                to_delete.append(m)
            except Exception:
                continue
        for m in participant_messages:
            try:
                to_delete.append(m)
            except Exception:
                continue
    except Exception as e:
        print(f"[収集エラー] {e}")

    # As fallback, try to find recent messages in channel mentioning bot in the time window
    try:
        async for msg in channel.history(limit=1000, after=datetime.now(timezone.utc) - timedelta(hours=2)):
            # if msg is within our event window (approx): check timestamp
            ts = msg.created_at.replace(tzinfo=timezone.utc).timestamp()
            if ts >= start_dt - 5 and ts <= end_dt + 5:
                if msg.author == bot.user or (bot.user in msg.mentions):
                    if msg not in to_delete:
                        to_delete.append(msg)
    except Exception as e:
        print(f"[履歴取得エラー] {e}")

    # Perform deletions (bulk if possible; otherwise single)
    deleted = 0
    for m in to_delete:
        try:
            await m.delete()
            deleted += 1
        except Exception:
            continue

    # set cooldown for counting
    count_cooldown_until = asyncio.get_event_loop().time() + 3600  # 1時間カウント停止

    # reset event flags
    event_active = False
    event_stage = 0
    event_messages = []
    participant_messages = []

    # Optionally announce in channel (but event messages were deleted)
    try:
        await channel.send("--- 謎解きは終了しました。---")
    except Exception:
        pass

    print(f"[イベント削除] deleted {deleted} messages; counting paused for 1 hour.")
    return

# ---------------------
# メッセージイベントハンドラ（中心）
# ---------------------
@bot.event
async def on_ready():
    print(f'Bot {bot.user} is ready.')
    # 60分ごとのチェック開始
    hourly_online_check.start()
    # Summarize daily loop should still be running but must check event_active before doing work
    summarize_previous_day.start()

@bot.event
async def on_message(message):
    global next_response_time, event_active, event_stage, event_messages, participant_messages, event_end_ts

    if message.author.bot:
        return

    channel = message.channel
    content = message.content or ""
    content_stripped = content.strip()

    now = asyncio.get_event_loop().time()  # ←ここを追加、printで使うため

    print(f"[DEBUG] event_active={event_active}, cooldown_until={count_cooldown_until}, now={now}, channel={channel}")

    # 強制開始トリガー ("Open Lain" — case-insensitive, exact phrase anywhere)
    if content_stripped.lower() == "open lain":
        if not event_active:
            await channel.send("トリガーとして受け取りました・・・")
            await start_event(channel, reason="manual")
        else:
            await channel.send("もう謎解きは始まっているよ・・・")
        return channel.send("もう謎解きは始まっているよ・・・")
        return


    # If event is active, only handle event-specific interactions and ignore all other features
    if event_active:
        # record participant messages if they mention the bot or are relevant to puzzle flow
        if bot.user in message.mentions:
            participant_messages.append(message)

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
                return

        # If event_active but message does not mention bot, ignore (no other features)
        return

    # ここからは event_active == False の通常処理
    # 強制まとめトリガー
    if content_stripped == "できごとまとめ":
        await summarize_logs(channel)
        return

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
            async for msg in channel.history(limit=30, oldest_first=False):
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
            next_response_time = now + 60 * 45
        except Exception as e:
            print(f"[履歴会話エラー] {e}")

# ---------------------
# 既存の summarize_previous_day は event_active をチェックするように改修
# ---------------------
@tasks.loop(time=time(7, 0, tzinfo=timezone(timedelta(hours=9))))
async def daily_summary():
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

@bot.event
async def on_message(message: discord.Message):
    # BOT自身のメッセージは無視
    if message.author.bot:
        return

    # 「日報」AIにメンションされた場合に強制起動
    if bot.user in message.mentions and "AI日報" in message.content:
        channel = message.channel
        await channel.send("昨日の会話ログをまとめるね・・・")
        await summarize_logs(channel)
        return  # 他の処理に流さない場合はここでreturn

    # 既存のコマンド処理なども動かすため
    await bot.process_commands(message)


# 取得するGoogleニュースRSSフィード（ジャンル別）
RSS_FEEDS = {
    "政治": "https://news.google.com/rss/search?q=政治&hl=ja&gl=JP&ceid=JP:ja",
    "経済": "https://news.google.com/rss/search?q=経済&hl=ja&gl=JP&ceid=JP:ja",
    "eスポーツ": "https://news.google.com/rss/search?q=eスポーツ&hl=ja&gl=JP&ceid=JP:ja",
    "ゲーム": "https://news.google.com/rss/search?q=ゲーム&hl=ja&gl=JP&ceid=JP:ja",
    "日本国内": "https://news.google.com/rss/search?q=日本&hl=ja&gl=JP&ceid=JP:ja",
}

# Geminiでまとめ & 問題提起
async def summarize_all_topics(entries_by_topic) -> str:
    text = ""
    for topic, entries in entries_by_topic.items():
        for entry in entries[:3]:  # 各ジャンル2〜3件
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            text += f"- [{topic}] {title}\n{summary}\n\n"

    prompt = (
        "以下は各ジャンルの主要ニュースです。\n"
        "2〜3件ずつまとめて全体を簡潔に要約してください。\n"
        "その後、ニュース全体を踏まえて問題提起や意見を1〜2文でまとめてください。\n\n"
        f"{text}"
    )

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"[Gemini要約エラー] {e}")
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

    # 全ジャンルをまとめてGeminiに投げる
    summary = await summarize_all_topics(entries_by_topic)
    await channel.send(summary)


# 毎日19:00(JST)に投稿
@tasks.loop(minutes=1)
async def scheduled_news():
    JST = timezone(timedelta(hours=9))
    now = datetime.now(JST)
    if now.hour == 19 and now.minute == 0:
        await post_daily_news()


@bot.event
async def on_ready():
    print(f"ログインしました: {bot.user}")
    scheduled_news.start()


# メンションで強制実行
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if bot.user in message.mentions and "ニュースまとめ" in message.content:
        await message.channel.send("📰 強制的にニュースをまとめるね・・・")
        await post_daily_news()



# ---------------------
# ボット起動
# ---------------------
bot.run(DISCORD_TOKEN)












