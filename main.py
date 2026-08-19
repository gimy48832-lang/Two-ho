import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import math
from flask import Flask
from threading import Thread

# --------------------------------------------------
# [Flask 웹 서버 설정 (렌더 24시간 유지용 - 수정본)]
# --------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "I am alive!", 200

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.daemon = True
    t.start()

# --------------------------------------------------
# [디스코드 봇 권한(Intents) 설정]
# --------------------------------------------------
intents = discord.Intents.default()
intents.members = True          # 멤버 정보 및 입장/퇴장 감지용
intents.message_content = True  # 메시지 내용 감지용

bot = commands.Bot(command_prefix="!", intents=intents)

# --------------------------------------------------
# [설정 영역] 환경 변수 또는 직접 입력
# --------------------------------------------------
RANKING_CHANNEL_ID = int(os.getenv("RANKING_CHANNEL_ID", "1538549157738979338"))  
DATA_FILE = "scores.json"               
BOT_TOKEN = os.getenv("BOT_TOKEN", "여기에_봇_토큰을_입력하세요")      

ranking_message_id = None
user_scores = {}

# 예외 처리 대상 역할 목록
EXCLUDED_ROLES = ["오락실 점장", "오락실 부점장", "테스트"]

# --------------------------------------------------
# [레벨 계산 함수 (0레벨 시작 및 상세 정보 반환)]
# --------------------------------------------------
def calculate_level_info(score):
    if score < 100:
        return 0, score, 100 - score

    LVL100_SCORE = 505000       
    FIXED_EXP_AFTER_100 = 10000 

    if score < LVL100_SCORE:
        level = int((1 + math.sqrt(1 + 8 * score / 100)) / 2) - 1
        next_level = level + 1
        next_level_score = int(50 * (next_level + 1) * next_level)
        needed_score = next_level_score - score
        return level, score, needed_score
    else:
        extra_score = score - LVL100_SCORE
        level = 100 + (extra_score // FIXED_EXP_AFTER_100)
        needed_score = FIXED_EXP_AFTER_100 - (extra_score % FIXED_EXP_AFTER_100)
        return level, score, needed_score

# --------------------------------------------------
# [데이터 파일 관리 함수]
# --------------------------------------------------
def load_scores():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception as e:
            print(f"⚠️ 데이터 파일 읽기 오류: {e}")
            return {}
    return {}

def save_scores():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(user_scores, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"❌ 데이터 저장 중 에러 발생: {e}")

# --------------------------------------------------
# [주기적 자동 저장 태스크] (3분마다 디스크 저장)
# --------------------------------------------------
@tasks.loop(minutes=3)
async def auto_save_task():
    save_scores()

# --------------------------------------------------
# [레벨별 역할 지급 및 랭커 역할 연동 함수]
# --------------------------------------------------
async def check_and_grant_level_roles(member, level, is_ranker=False):
    is_excluded = any(role.name in EXCLUDED_ROLES for role in member.roles)
    if is_excluded:
        return

    guest_role = discord.utils.get(member.guild.roles, name="손님")
    role_25 = discord.utils.get(member.guild.roles, name="단골 손님")
    role_50 = discord.utils.get(member.guild.roles, name="고인물")

    # 1. 랭커(TOP 5)인 경우: 레벨 역할(손님, 단골 손님, 고인물) 모두 회수
    if is_ranker:
        for role in [guest_role, role_25, role_50]:
            if role and role in member.roles:
                try:
                    await member.remove_roles(role)
                    print(f"👑 랭커 등극으로 인해 {member.display_name}님의 '{role.name}' 역할을 회수했습니다.")
                except Exception as e:
                    print(f"⚠️ 역할 회수 실패 ({role.name}): {e}")
        return

    # 2. 랭커가 아닌 경우: 본인 레벨에 맞는 역할 부여 및 나머지 레벨 역할 회수
    if level >= 50:
        if guest_role and guest_role in member.roles:
            await member.remove_roles(guest_role)
        if role_25 and role_25 in member.roles:
            await member.remove_roles(role_25)
        if role_50 and role_50 not in member.roles:
            try:
                await member.add_roles(role_50)
                print(f"🔥 {member.display_name}님이 50레벨 달성으로 '고인물' 역할을 부여받았습니다.")
            except Exception as e:
                print(f"⚠️ 역할 부여 실패 (고인물): {e}")

    elif level >= 25:
        if role_50 and role_50 in member.roles:
            await member.remove_roles(role_50)
        if guest_role and guest_role in member.roles:
            await member.remove_roles(guest_role)
        if role_25 and role_25 not in member.roles:
            try:
                await member.add_roles(role_25)
                print(f"🎉 {member.display_name}님이 25레벨을 달성하여 '단골 손님' 역할을 부여받았습니다.")
            except Exception as e:
                print(f"⚠️ 역할 부여 실패 (단골 손님): {e}")

    else:
        if role_50 and role_50 in member.roles:
            await member.remove_roles(role_50)
        if role_25 and role_25 in member.roles:
            await member.remove_roles(role_25)
        if guest_role and guest_role not in member.roles:
            try:
                await member.add_roles(guest_role)
                print(f"👤 {member.display_name}님에게 '손님' 역할을 부여했습니다.")
            except Exception as e:
                print(f"⚠️ 역할 부여 실패 (손님): {e}")

# --------------------------------------------------
# [이벤트 처리]
# --------------------------------------------------
@bot.event
async def on_ready():
    global user_scores, ranking_message_id
    user_scores = load_scores()
    
    if not auto_save_task.is_running():
        auto_save_task.start()

    channel = bot.get_channel(RANKING_CHANNEL_ID)
    if channel:
        try:
            async for message in channel.history(limit=10):
                if message.author == bot.user and message.embeds:
                    ranking_message_id = message.id
                    break
        except Exception as e:
            print(f"⚠️ 기존 전광판 메시지 검색 오류: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"✅ 슬래시 명령어 동기화 완료: {len(synced)}개")
    except Exception as e:
        print(f"⚠️ 슬래시 명령어 동기화 실패: {e}")

    print(f"🎮 렌더 백그라운드 봇 가동 완료: {bot.user.name}")

# [기능: /레벨 비공개 슬래시 명령어]
@bot.tree.command(name="레벨", description="내 현재 레벨과 경험치 상태를 비공개로 확인합니다.")
async def my_level(interaction: discord.Interaction):
    user_id = interaction.user.id
    score = user_scores.get(user_id, 0)
    
    level, current_score, needed_score = calculate_level_info(score)

    embed = discord.Embed(
        title="📊 내 정보 및 레벨 현황",
        color=discord.Color.blue()
    )
    embed.add_field(name="현재 레벨", value=f"`Lv.{level}`", inline=True)
    embed.add_field(name="누적 점수", value=f"`{current_score} P`", inline=True)
    
    if level >= 100:
        embed.add_field(name="진행 상황", value="만렙(MAX) 구간에 도달했습니다!", inline=False)
    else:
        embed.add_field(name="다음 레벨까지", value=f"약 `{needed_score} P` 남음", inline=False)

    embed.set_footer(text=f"{interaction.user.display_name}님의 정보 (이 메시지는 본인에게만 보입니다.)")

    await interaction.response.send_message(embed=embed, ephemeral=True)

# [기능 1] 신규 멤버 입장 시 '손님' 역할 자동 부여
@bot.event
async def on_member_join(member):
    role = discord.utils.get(member.guild.roles, name="손님")
    if role:
        try:
            await member.add_roles(role)
            print(f"👤 {member.name}님에게 '손님' 역할을 부여했습니다.")
        except Exception as e:
            print(f"⚠️ 역할 부여 실패: {e}")

# [기능 2] 멤버 퇴장 시 점수 즉시 초기화 (삭제)
@bot.event
async def on_member_remove(member):
    if member.id in user_scores:
        del user_scores[member.id]
        save_scores()
        print(f"🚪 {member.display_name}님이 퇴장하여 점수 데이터를 삭제했습니다.")
        await update_ranking_board(member.guild)

# [기능 3] 부스트 감지
@bot.event
async def on_member_update(before, after):
    vip_role = discord.utils.get(after.guild.roles, name="VIP")
    if not vip_role:
        return

    if before.premium_since is None and after.premium_since is not None:
        try:
            await after.add_roles(vip_role)
            print(f"🚀 {after.name}님이 서버를 부스트하여 'VIP' 역할을 부여했습니다.")
        except Exception as e:
            print(f"⚠️ VIP 부여 실패: {e}")

    elif before.premium_since is not None and after.premium_since is None:
        if vip_role in after.roles:
            try:
                await after.remove_roles(vip_role)
                print(f"📉 {after.name}님의 부스트가 종료되어 'VIP' 역할을 회수했습니다.")
            except Exception as e:
                print(f"⚠️ VIP 회수 실패: {e}")

# [기능 4] 채팅 감지 및 점수 갱신
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    user_id = message.author.id
    user_scores[user_id] = user_scores.get(user_id, 0) + 10

    # 채팅마다 실시간 랭킹 및 역할 연동 업데이트
    await update_ranking_board(message.guild)
    await bot.process_commands(message)

# --------------------------------------------------
# [실시간 랭킹 전광판 메시지 및 랭커/레벨 역할 통합 갱신 함수]
# --------------------------------------------------
async def update_ranking_board(guild):
    global ranking_message_id

    channel = guild.get_channel(RANKING_CHANNEL_ID)
    if not channel:
        return

    filtered_scores = []
    
    for uid, score in list(user_scores.items()):
        member = guild.get_member(uid)
        
        if member:
            is_excluded = any(role.name in EXCLUDED_ROLES for role in member.roles)
            if not is_excluded:
                filtered_scores.append((uid, score))
        else:
            del user_scores[uid]

    all_sorted_scores = sorted(filtered_scores, key=lambda x: x[1], reverse=True)
    top_5_uids = {uid for uid, _ in all_sorted_scores[:5]}
    
    ranker_role = discord.utils.get(guild.roles, name="랭커")

    # 전체 사용자의 랭커 및 레벨 역할 실시간 동기화
    for uid, score in all_sorted_scores:
        member = guild.get_member(uid)
        if not member:
            continue

        level, _, _ = calculate_level_info(score)

        if uid in top_5_uids:
            # TOP 5 진입자: '랭커' 역할 부여 & (손님, 단골 손님, 고인물) 역할 모두 회수
            if ranker_role and ranker_role not in member.roles:
                try:
                    await member.add_roles(ranker_role)
                    print(f"👑 {member.display_name}님이 TOP 5 진입으로 '랭커' 역할을 부여받았습니다.")
                except Exception as e:
                    print(f"⚠️ 랭커 역할 부여 실패: {e}")
            
            await check_and_grant_level_roles(member, level, is_ranker=True)

        else:
            # TOP 5 탈락/미진입자: '랭커' 역할 회수 & 현재 레벨에 맞는 역할 복구
            if ranker_role and ranker_role in member.roles:
                try:
                    await member.remove_roles(ranker_role)
                    print(f"🔻 {member.display_name}님이 순위 하락으로 '랭커' 역할이 회수되었습니다.")
                except Exception as e:
                    print(f"⚠️ 랭커 역할 회수 실패: {e}")

            await check_and_grant_level_roles(member, level, is_ranker=False)

    sorted_scores = all_sorted_scores[:5]

    embed = discord.Embed(
        title="🕹️ 오락실 HIGH SCORE (실시간 랭킹)",
        description="가장 활동적인 명예의 전당 멤버입니다!",
        color=discord.Color.from_rgb(255, 214, 0)
    )

    rank_text = ""
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    for i, (uid, score) in enumerate(sorted_scores):
        member = guild.get_member(uid)
        name = member.display_name if member else "알 수 없음"
        level, _, _ = calculate_level_info(score)
        rank_text += f"{medals[i]} **{name}** - `Lv.{level}` (`{score} P`)\n"

    if not rank_text:
        rank_text = "아직 기록된 점수가 없습니다."

    embed.add_field(name="🏆 TOP 5 랭커", value=rank_text, inline=False)

    try:
        if ranking_message_id is None:
            msg = await channel.send(embed=embed)
            ranking_message_id = msg.id
        else:
            try:
                msg = await channel.fetch_message(ranking_message_id)
                await msg.edit(embed=embed)
            except discord.NotFound:
                msg = await channel.send(embed=embed)
                ranking_message_id = msg.id
    except Exception as e:
        print(f"⚠️ 전광판 갱신 오류: {e}")

# --------------------------------------------------
# [실행 및 종료 처리]
# --------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    try:
        bot.run(BOT_TOKEN)
    finally:
        save_scores()
        print("💾 봇 종료 시점 점수 저장 완료.")
