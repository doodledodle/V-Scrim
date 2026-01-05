import streamlit as st
from supabase import create_client, Client
import requests
import pandas as pd
import time

# --- Configuration & Setup ---
st.set_page_config(page_title="발로란트 내전 관리자", layout="wide")

# Initialize Supabase Client
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Supabase 설정 오류. secrets.toml 파일을 확인해주세요.")
    st.stop()

# Discord Config
try:
    DISCORD_TOKEN_RAW = st.secrets["DISCORD_TOKEN_RAW"]
    GUILD_ID = st.secrets["GUILD_ID"]
    DISCORD_HEADER = {"Authorization": f"Bot {DISCORD_TOKEN_RAW}"} 
except Exception as e:
    st.error("Discord 설정 오류. secrets.toml 파일을 확인해주세요.")
    st.stop()

# --- Functions ---

def sync_discord_members():
    """Fetches members and roles from Discord API and updates the Supabase 'users' table."""
    
    # 1. Fetch Roles
    roles_url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/roles"
    roles_resp = requests.get(roles_url, headers=DISCORD_HEADER)
    
    role_map = {}
    if roles_resp.status_code == 200:
        roles_data = roles_resp.json()
        for r in roles_data:
            role_map[r['id']] = r['name']
    else:
        st.warning(f"역할 정보를 가져오지 못했습니다. (Status: {roles_resp.status_code})")

    # 2. Fetch Members
    members_url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members?limit=1000"
    response = requests.get(members_url, headers=DISCORD_HEADER)
    
    if response.status_code == 200:
        members = response.json()
        users_data = []
        for member in members:
            user = member.get('user', {})
            if user:
                user_id = int(user['id'])
                username = user.get('username')
                display_name = member.get('nick') or user.get('global_name') or username
                
                # Role Logic
                member_role_ids = member.get('roles', [])
                # Map IDs to Names and join
                role_names = [role_map.get(rid, "") for rid in member_role_ids if rid in role_map]
                # Filter out @everyone if present (usually not in the list but good to check)
                role_names = [r for r in role_names if r != "@everyone"]
                
                # Simple display: Join all roles or pick top one? User asked to show role. 
                # Comma separated might be long. Let's just join them for now.
                roles_str = ", ".join(role_names)
                
                users_data.append({
                    "id": user_id,
                    "name": username,
                    "display_name": display_name,
                    "roles": roles_str
                })
        
        # Perform Upsert
        if users_data:
            try:
                # Upserting with returning=minimal to check success
                data = supabase.table("users").upsert(users_data).execute()
                return len(users_data), "성공적으로 동기화되었습니다."
            except Exception as e:
                return 0, str(e)
        else:
             return 0, "멤버를 찾을 수 없습니다."

    else:
        return 0, f"오류 발생 {response.status_code}: {response.text}"

def get_all_users():
    """Retrieves all users from Supabase."""
    response = supabase.table("users").select("*").execute()
    return response.data

def record_match(team_a_ids, team_b_ids, winning_team):
    """Records a match result."""
    try:
        # 1. Create Match
        match_res = supabase.table("matches").insert({"winning_team": winning_team}).execute()
        
        if not match_res.data:
            return False, "매치 생성 실패."
        
        match_id = match_res.data[0]['id']
        
        # 2. Participants & 3. Stats Update
        participants_data = []
        all_ids = team_a_ids + team_b_ids
        
        # Fetch current stats
        users_res = supabase.table("users").select("id, wins, total_games").in_("id", all_ids).execute()
        user_map = {u['id']: u for u in users_res.data}
        
        updated_users = []
        
        # Helper to process team
        def process_team(team_ids, team_name, is_winner):
            for uid in team_ids:
                participants_data.append({"match_id": match_id, "user_id": uid, "team": team_name})
                user = user_map.get(uid)
                if user:
                    new_wins = user['wins'] + 1 if is_winner else user['wins']
                    new_total = user['total_games'] + 1
                    updated_users.append({"id": uid, "wins": new_wins, "total_games": new_total})

        process_team(team_a_ids, "A", winning_team == "A")
        process_team(team_b_ids, "B", winning_team == "B")
                
        # Insert Participants
        supabase.table("match_participants").insert(participants_data).execute()
        
        # Update User Stats
        supabase.table("users").upsert(updated_users).execute()
        
        return True, "매치 기록이 저장되었습니다!"
        
    except Exception as e:
        return False, str(e)


# --- UI Layout ---

st.title("🔫 발로란트 내전 관리자")

# Initialize Session State for Team Selection
if 'team_a' not in st.session_state:
    st.session_state.team_a = []
if 'team_b' not in st.session_state:
    st.session_state.team_b = []

def add_to_team(user_id, team):
    if team == 'A':
        if user_id not in st.session_state.team_a:
            # Remove from B if exists
            if user_id in st.session_state.team_b:
                st.session_state.team_b.remove(user_id)
            st.session_state.team_a.append(user_id)
    elif team == 'B':
        if user_id not in st.session_state.team_b:
             # Remove from A if exists
            if user_id in st.session_state.team_a:
                st.session_state.team_a.remove(user_id)
            st.session_state.team_b.append(user_id)

def remove_from_team(user_id, team):
    if team == 'A' and user_id in st.session_state.team_a:
        st.session_state.team_a.remove(user_id)
    elif team == 'B' and user_id in st.session_state.team_b:
        st.session_state.team_b.remove(user_id)

# Sidebar: Sync
with st.sidebar:
    st.header("설정 (Settings)")
    if st.button("디스코드 멤버 동기화"):
        with st.spinner("동기화 중..."):
            count, msg = sync_discord_members()
            if count > 0:
                st.success(f"{count}명 동기화 완료!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"실패: {msg}")

# Main Data Fetch
users = get_all_users()
df = pd.DataFrame(users)

if not df.empty:
    # Calculate Win Rate
    df['win_rate'] = df.apply(lambda row: (row['wins'] / row['total_games'] * 100) if row['total_games'] > 0 else 0.0, axis=1)
    
    # Leaderboard Sorting
    df_sorted = df.sort_values(by=['win_rate', 'wins'], ascending=False)
    
    # Map ID to Info
    id_map = {row['id']: row for _, row in df.iterrows()}
    
    tab1, tab2 = st.tabs(["🏆 리더보드", "📝 매치 기록"])
    
    with tab1:
        st.subheader("📊 순위표")
        st.dataframe(
            df_sorted[['display_name', 'roles', 'tier', 'wins', 'total_games', 'win_rate']],
            column_config={
                "display_name": "플레이어",
                "roles": "역할",
                "tier": "티어",
                "wins": "승리",
                "total_games": "전체 게임",
                "win_rate": st.column_config.NumberColumn(
                    "승률 (%)",
                    format="%.1f %%"
                )
            },
            hide_index=True,
            use_container_width=True
        )

    with tab2:
        st.subheader("새로운 내전 기록")
        
        # Display Selected Teams
        col_team_a, col_vs, col_team_b = st.columns([4, 1, 4])
        
        with col_team_a:
            st.markdown("### 🅰️ A팀")
            if st.session_state.team_a:
                for uid in st.session_state.team_a:
                    u = id_map.get(uid)
                    if u is not None:
                        st.button(f"{u['display_name']} ❌", key=f"del_a_{uid}", on_click=remove_from_team, args=(uid, 'A'))
            else:
                st.info("선택된 플레이어 없음")

        with col_vs:
            st.markdown("<h3 style='text-align: center;'>VS</h3>", unsafe_allow_html=True)

        with col_team_b:
             st.markdown("### 🅱️ B팀")
             if st.session_state.team_b:
                for uid in st.session_state.team_b:
                    u = id_map.get(uid)
                    if u is not None:
                        st.button(f"{u['display_name']} ❌", key=f"del_b_{uid}", on_click=remove_from_team, args=(uid, 'B'))
             else:
                st.info("선택된 플레이어 없음")

        st.divider()
        
        # Match Result Submission
        st.write("#### 결과 제출")
        winning_team = st.radio("승리 팀", ("A팀", "B팀"), horizontal=True)
        
        if st.button("결과 저장하기", type="primary"):
            if not st.session_state.team_a or not st.session_state.team_b:
                st.toast("⚠️ 양 팀에 최소 한 명 이상의 플레이어가 있어야 합니다.", icon="⚠️")
            else:
                mapped_winner = "A" if winning_team == "A팀" else "B"
                success, msg = record_match(st.session_state.team_a, st.session_state.team_b, mapped_winner)
                
                if success:
                    st.success(msg)
                    # Reset teams
                    st.session_state.team_a = []
                    st.session_state.team_b = []
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(f"오류: {msg}")
        
        st.divider()
        
        # Player Selection List (Button Style)
        st.write("#### 플레이어 목록")
        st.caption("아래 목록에서 플레이어를 선택하여 팀에 추가하세요.")
        
        # Search/Filter
        search_query = st.text_input("검색 (이름)", "")
        
        # Determine who is already selected to disable or hide them? 
        # Or just show them and allow moving?
        # Let's show all, but maybe highlight if selected? 
        # Simplest: Just list them. If clicked, add to team.
        
        filtered_df = df_sorted
        if search_query:
            filtered_df = df_sorted[df_sorted['display_name'].str.contains(search_query, case=False) | df_sorted['name'].str.contains(search_query, case=False)]

        # Display as a table with actions
        # We can use st.columns for each row
        
        # Header
        h1, h2, h3, h4 = st.columns([3, 2, 1, 1])
        h1.markdown("**이름**")
        h2.markdown("**역할**")
        h3.markdown("**A팀**")
        h4.markdown("**B팀**")
        
        for _, row in filtered_df.iterrows():
            uid = row['id']
            # Skip if already in a team? No, maybe we want to switch.
            # But let's look at the UI cleaniness.
            
            c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
            c1.write(f"{row['display_name']} ({row['name']})")
            c2.write(row.get('roles', '-')) # Handle missing roles safely
            
            # Buttons
            # We use callbacks to update session state
            c3.button("➕ A", key=f"add_a_{uid}", on_click=add_to_team, args=(uid, 'A'))
            c4.button("➕ B", key=f"add_b_{uid}", on_click=add_to_team, args=(uid, 'B'))
            
else:
    st.info("등록된 멤버가 없습니다. 왼쪽 사이드바에서 '디스코드 멤버 동기화'를 눌러주세요.")

