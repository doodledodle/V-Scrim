import streamlit as st
from supabase import create_client, Client
import requests
import pandas as pd
import time

# --- Configuration & Setup ---
st.set_page_config(page_title=":Defying 내전 관리", layout="wide")

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

# --- RANK DEFINITIONS ---
# Priority Order (High index = Higher Priority for sorting, Low Index for iteration if using reversed)
# Let's map rank name to an integer priority
RANK_PRIORITY = {
    "레디언트": 10,
    "불멸": 9,
    "초월자": 8,
    "다이아몬드": 7,
    "플래티넘": 6,
    "골드": 5,
    "실버": 4,
    "브론즈": 3,
    "아이언": 2,
    "언랭": 1
}

def get_tier_from_roles(role_names):
    """Determines the highest tier from a list of role names."""
    current_tier = "언랭"
    current_priority = 0
    
    for role in role_names:
        # Check if role contains rank name (flexible matching)
        for rank_name, priority in RANK_PRIORITY.items():
            if rank_name in role:
                if priority > current_priority:
                    current_tier = rank_name
                    current_priority = priority
    return current_tier

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
        bot_ids = []

        for member in members:
            user = member.get('user', {})
            if user:
                user_id = int(user['id'])
                username = user.get('username')
                display_name = member.get('nick') or user.get('global_name') or username

                # Check for bot OR specific nickname
                if user.get('bot') or display_name == "부스터봇":
                    bot_ids.append(int(user['id']))
                    continue
                
                # Role Logic
                
                # Role Logic
                member_role_ids = member.get('roles', [])
                role_names = [role_map.get(rid, "") for rid in member_role_ids if rid in role_map]
                role_names = [r for r in role_names if r != "@everyone"]
                roles_str = ", ".join(role_names)
                
                # Tier Logic
                tier = get_tier_from_roles(role_names)
                
                users_data.append({
                    "id": user_id,
                    "name": username,
                    "display_name": display_name,
                    "roles": roles_str,
                    "tier": tier 
                })
        
        # Get existing users to check who left
        try:
            existing_users_resp = supabase.table("users").select("id").execute()
            existing_user_ids = {int(u['id']) for u in existing_users_resp.data}
        except Exception:
            existing_user_ids = set()
            
        valid_user_ids = {int(u['id']) for u in users_data}
        left_user_ids = list(existing_user_ids - valid_user_ids - set(bot_ids))

        # Perform Upsert for Real Users
        upsert_count = 0
        if users_data:
            try:
                supabase.table("users").upsert(users_data).execute()
                upsert_count = len(users_data)
            except Exception as e:
                return 0, str(e)

        # Mark left users as inactive
        if left_user_ids:
            try:
                supabase.table("users").update({"roles": "LEFT_SERVER", "tier": "Unranked"}).in_("id", left_user_ids).execute()
            except Exception as e:
                print(f"Failed to update left users: {e}")

        # Remove Bots from DB if they exist
        if bot_ids:
            try:
                supabase.table("users").delete().in_("id", bot_ids).execute()
            except Exception as e:
                # Log error but don't fail the whole sync? Or maybe we should.
                # For now let's just proceed.
                print(f"Failed to remove bots: {e}")

        if upsert_count > 0 or bot_ids or left_user_ids:
             return upsert_count, f"성공적으로 동기화되었습니다. (봇 {len(bot_ids)}명 제외, {len(left_user_ids)}명 비활성화)"
        else:
             return 0, "멤버를 찾을 수 없습니다."

    else:
        return 0, f"오류 발생 {response.status_code}: {response.text}"

def get_all_users():
    """Retrieves all active users from Supabase."""
    response = supabase.table("users").select("*").neq("roles", "LEFT_SERVER").execute()
    return response.data

# Helper for Map Management
def add_map(map_name):
    try:
        supabase.table("maps").insert({"name": map_name}).execute()
        return True, "맵이 추가되었습니다."
    except Exception as e:
        return False, str(e)

def delete_map(map_id):
    try:
        supabase.table("maps").delete().eq("id", map_id).execute()
        return True, "맵이 삭제되었습니다."
    except Exception as e:
        return False, str(e)

def get_all_maps():
    try:
        res = supabase.table("maps").select("*").order("name").execute()
        return res.data
    except:
        return []

def record_match(team_a_ids, team_b_ids, winning_team, map_name):
    """Records a match result and updates user stats."""
    # ... (Stats update logic same as before, skipped for brevity but ensure arguments match) ...
    # Wait. I need to replace the WHOLE function if I change the signature.
    # Let me include the full logic to be safe.
    if not team_a_ids or not team_b_ids:
        return False, "팀 구성원이 부족합니다."
    
    try:
        # 1. Create Match with Map Name
        match_data = {
            "winning_team": winning_team,
            "map_name": map_name
        }
        res = supabase.table("matches").insert(match_data).execute()
        if not res.data:
            return False, "매치 생성 실패"
        
        match_id = res.data[0]['id']
        
        # 2. Add Participants
        participants = []
        for uid in team_a_ids:
            participants.append({"match_id": match_id, "user_id": uid, "team": "A"})
        for uid in team_b_ids:
            participants.append({"match_id": match_id, "user_id": uid, "team": "B"})
            
        supabase.table("match_participants").insert(participants).execute()
        
        # 3. Update User Stats (Wins & Total Games)
        # Fetch current stats
        all_ids = team_a_ids + team_b_ids
        users_res = supabase.table("users").select("id, wins, total_games").in_("id", all_ids).execute()
        user_map = {u['id']: u for u in users_res.data}
        
        updated_users = []
        for uid in all_ids:
            user = user_map.get(uid)
            if user:
                current_wins = user.get('wins', 0)
                current_total = user.get('total_games', 0)
                
                # Determine if user won
                is_team_a = uid in team_a_ids
                user_won = (is_team_a and winning_team == 'A') or (not is_team_a and winning_team == 'B')
                
                new_wins = current_wins + (1 if user_won else 0)
                new_total = current_total + 1
                
                updated_users.append({
                    "id": uid,
                    "wins": new_wins,
                    "total_games": new_total
                })
        
        if updated_users:
            supabase.table("users").upsert(updated_users).execute()
            
        return True, "매치 결과가 저장되었습니다!"
        
    except Exception as e:
        return False, str(e)


# --- UI Layout ---

st.title("🔫 :Defying 내전 관리")

# Initialize Session State
if 'team_a' not in st.session_state:
    st.session_state.team_a = []
if 'team_b' not in st.session_state:
    st.session_state.team_b = []
if 'participants' not in st.session_state:
    st.session_state.participants = set()

def toggle_participation(user_id):
    if user_id in st.session_state.participants:
        st.session_state.participants.remove(user_id)
        # Also remove from teams if present
        if user_id in st.session_state.team_a:
            st.session_state.team_a.remove(user_id)
        if user_id in st.session_state.team_b:
            st.session_state.team_b.remove(user_id)
    else:
        st.session_state.participants.add(user_id)

def add_to_team(user_id, team):
    # Ensure participant
    st.session_state.participants.add(user_id)
    
    if team == 'A':
        if user_id not in st.session_state.team_a:
            if user_id in st.session_state.team_b:
                st.session_state.team_b.remove(user_id)
            st.session_state.team_a.append(user_id)
    elif team == 'B':
        if user_id not in st.session_state.team_b:
            if user_id in st.session_state.team_a:
                st.session_state.team_a.remove(user_id)
            st.session_state.team_b.append(user_id)

def remove_from_team_to_lobby(user_id, team):
    """Removes from specific team but keeps in lobby (participants)"""
    if team == 'A' and user_id in st.session_state.team_a:
        st.session_state.team_a.remove(user_id)
    elif team == 'B' and user_id in st.session_state.team_b:
        st.session_state.team_b.remove(user_id)

# Helper for Team Win Rate
def calculate_team_avg_win_rate(team_ids, user_map):
    if not team_ids:
        return 0.0
    total_wr = 0.0
    valid_members = 0
    for uid in team_ids:
        user = user_map.get(uid)
        if user is not None:
             # Calculate WR safely
             games = user.get('total_games', 0)
             wins = user.get('wins', 0)
             wr = (wins / games * 100) if games > 0 else 0.0
             total_wr += wr
             valid_members += 1
    
    return total_wr / valid_members if valid_members > 0 else 0.0

def delete_match(match_id):
    """Deletes a match and reverts user stats."""
    try:
        # 1. Fetch Match Info to know who won
        match_res = supabase.table("matches").select("*").eq("id", match_id).single().execute()
        if not match_res.data:
            return False, "매치를 찾을 수 없습니다."
        
        match_data = match_res.data
        winning_team = match_data['winning_team'] # 'A' or 'B'
        
        # 2. Fetch Participants to know who played
        parts_res = supabase.table("match_participants").select("*").eq("match_id", match_id).execute()
        participants = parts_res.data
        
        # 3. Prepare User Stats Reversion
        user_ids = [p['user_id'] for p in participants]
        if user_ids:
            users_res = supabase.table("users").select("id, wins, total_games").in_("id", user_ids).execute()
            user_map = {u['id']: u for u in users_res.data}
            
            updated_users = []
            for p in participants:
                uid = p['user_id']
                team = p['team'] # 'A' or 'B'
                
                user = user_map.get(uid)
                if user:
                    # Revert Stats
                    current_wins = user['wins']
                    current_total = user['total_games']
                    
                    # Logic: If they were on winning team, decrement win. Always decrement total.
                    # Safety check: don't go below 0
                    new_wins = current_wins
                    if team == winning_team:
                        new_wins = max(0, current_wins - 1)
                    
                    new_total = max(0, current_total - 1)
                    
                    updated_users.append({
                        "id": uid,
                        "wins": new_wins,
                        "total_games": new_total
                    })
            
            # Update Users
            if updated_users:
                 supabase.table("users").upsert(updated_users).execute()
        
        # 4. Delete Participants (Must be done before deleting match if no CASCADE)
        supabase.table("match_participants").delete().eq("match_id", match_id).execute()
        
        # 5. Delete Match
        supabase.table("matches").delete().eq("id", match_id).execute()
        
        return True, "매치가 취소(삭제)되었습니다."
        
    except Exception as e:
        return False, str(e)

def get_recent_matches(limit=10):
    """Fetches recent matches with participant info."""
    # This is a bit complex with standard supabase client without joins.
    # We'll fetch matches, then fetch participants for them.
    try:
        matches_res = supabase.table("matches").select("*").order("created_at", desc=True).limit(limit).execute()
        matches = matches_res.data
        if not matches:
            return []
            
        match_ids = [m['id'] for m in matches]
        
        # Fetch participants
        parts_res = supabase.table("match_participants").select("match_id, team, user_id").in_("match_id", match_ids).execute()
        parts = parts_res.data
        
        # Fetch user names
        all_user_ids = list(set([p['user_id'] for p in parts]))
        if all_user_ids:
            users_res = supabase.table("users").select("id, display_name").in_("id", all_user_ids).execute()
            user_map = {u['id']: u['display_name'] for u in users_res.data}
        else:
            user_map = {}
            
        # Group participants by match
        # Structure: {match_id: {'A': [names], 'B': [names]}}
        match_details = {}
        for p in parts:
            mid = p['match_id']
            if mid not in match_details:
                match_details[mid] = {'A': [], 'B': []}
            
            u_name = user_map.get(p['user_id'], "Unknown")
            match_details[mid][p['team']].append(u_name)
            
        # Combine
        full_history = []
        for m in matches:
            mid = m['id']
            details = match_details.get(mid, {'A': [], 'B': []})
            full_history.append({
                "id": mid,
                "created_at": m['created_at'],
                "winning_team": m['winning_team'],
                "map_name": m.get('map_name'), # Include map_name
                "team_a": ", ".join(details['A']),
                "team_b": ", ".join(details['B'])
            })
            
        return full_history
    except Exception as e:
        st.error(f"기록 불러오기 실패: {str(e)}")
        return []

@st.dialog("맵 관리 (Map Management)")
def add_map_dialog():
    st.write("### 🆕 맵 추가")
    new_map_name = st.text_input("맵 이름", placeholder="예: 어센트")
    if st.button("추가하기", type="primary", use_container_width=True):
        if new_map_name:
            s, m = add_map(new_map_name)
            if s:
                st.success(m)
                time.sleep(1)
                st.rerun()
            else:
                st.error(m)
    
    st.divider()
    
    st.write("### 📋 등록된 맵 목록")
    maps = get_all_maps()
    if maps:
        for m in maps:
            c1, c2 = st.columns([4, 1])
            c1.write(f"- {m['name']}")
            # Simple 'x' button for delete
            if c2.button("x", key=f"del_map_{m['id']}", help="삭제"):
                delete_map(m['id'])
                st.rerun()
    else:
        st.info("등록된 맵이 없습니다.")

@st.dialog("고급 설정 (Advanced Settings)")
def advanced_settings_dialog():
    st.write("### ⚙️ 표시 설정")
    st.caption("변경 사항을 적용하려면 하단의 확인 버튼을 눌러주세요.")
    
    # Use local keys for form-like behavior
    # We initialize them with current session state
    
    new_show_individual = st.checkbox("개인 승률 표시 (Player Win Rate)", value=st.session_state.show_individual_wr)
    new_show_team = st.checkbox("팀 평균 승률 표시 (Team Avg Win Rate)", value=st.session_state.show_team_wr)
    
    st.divider()
    
    if st.button("확인 (Apply)", type="primary", use_container_width=True):
        st.session_state.show_individual_wr = new_show_individual
        st.session_state.show_team_wr = new_show_team
        st.rerun()

# Sidebar: Sync & Maps
with st.sidebar:
    st.header("설정 (Settings)")
    
    # Advanced Settings Button
    if st.button("⚙️ 고급 설정", use_container_width=True):
        advanced_settings_dialog()
        
    if st.button("디스코드 멤버 동기화", use_container_width=True):
        with st.spinner("동기화 중..."):
            count, msg = sync_discord_members()
            if count > 0:
                st.success(f"{count}명 동기화 완료!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"실패: {msg}")
    
    st.divider()
    
    st.header("맵 관리 (Maps)")
    
    if st.button("🗺️ 맵 관리하기", use_container_width=True):
        add_map_dialog()



# Main Data Fetch
users = get_all_users()
df = pd.DataFrame(users)

if not df.empty:
    df['win_rate'] = df.apply(lambda row: (row['wins'] / row['total_games'] * 100) if row['total_games'] > 0 else 0.0, axis=1)
    df_sorted = df.sort_values(by=['win_rate', 'wins'], ascending=False)
    id_map = {row['id']: row for _, row in df.iterrows()}
    
    # Initialize Settings State
    if 'show_individual_wr' not in st.session_state:
        st.session_state.show_individual_wr = True
    if 'show_team_wr' not in st.session_state:
        st.session_state.show_team_wr = True
    
    # Tabs
    tab1, tab2, tab3 = st.tabs(["🏆 리더보드", "📝 매치 생성", "📜 최근 기록"])
    
    with tab1:
        st.subheader("📊 순위표")
        
        # Select columns based on settings
        lb_cols = ['display_name', 'tier', 'wins', 'total_games']
        lb_config = {
            "display_name": "플레이어",
            "tier": "티어",
            "wins": "승리",
            "total_games": "전체 게임"
        }
        
        if st.session_state.show_individual_wr:
            lb_cols.append('win_rate')
            lb_config["win_rate"] = st.column_config.NumberColumn("승률 (%)", format="%.1f %%")
            
        st.dataframe(
            df_sorted[lb_cols],
            column_config=lb_config,
            hide_index=True,
            use_container_width=True
        )

    with tab2:
        
        # Calculate Team Stats
        team_a_avg = calculate_team_avg_win_rate(st.session_state.team_a, id_map)
        team_b_avg = calculate_team_avg_win_rate(st.session_state.team_b, id_map)
        
        # Initialize Attack Team State
        if 'attack_team' not in st.session_state:
            st.session_state.attack_team = None
            
        # Determine Headers based on side
        header_a = "🅰️ A팀"
        header_b = "🅱️ B팀"
        
        if st.session_state.attack_team == 'A':
            header_a += " (⚔️ 공격)"
            header_b += " (🛡️ 수비)"
        elif st.session_state.attack_team == 'B':
            header_a += " (🛡️ 수비)"
            header_b += " (⚔️ 공격)"
        
        # Display Selected Teams
        col_team_a, col_vs, col_team_b = st.columns([4, 1, 4])
        
        with col_team_a:
            header_text = header_a
            if st.session_state.show_team_wr:
                header_text += f" (평균 승률: {team_a_avg:.1f}%)"
            
            st.markdown(f"### {header_text}")
            
            if st.session_state.team_a:
                for uid in st.session_state.team_a:
                    u = id_map.get(uid)
                    if u is not None:
                         # Calculate individual WR for display
                        g = u.get('total_games', 0)
                        w = u.get('wins', 0)
                        wr = (w / g * 100) if g > 0 else 0.0
                        
                        display_text = f"{u['display_name']} ({u.get('tier', '-')})"
                        if st.session_state.show_individual_wr:
                            display_text += f", {wr:.1f}%"
                        
                        st.button(f"{display_text} ❌", key=f"del_a_{uid}", on_click=remove_from_team_to_lobby, args=(uid, 'A'))
            else:
                st.info("플레이어를 배치하세요 (Lobby)")

        with col_vs:
            st.markdown("<h3 style='text-align: center; margin-top: 20px;'>VS</h3>", unsafe_allow_html=True)
            if st.session_state.show_team_wr:
                diff = abs(team_a_avg - team_b_avg)
                st.markdown(f"<div style='text-align: center; color: gray; font-size: 0.8em;'>차이: {diff:.1f}%</div>", unsafe_allow_html=True)

        with col_team_b:
            header_text = header_b
            if st.session_state.show_team_wr:
                header_text += f" (평균 승률: {team_b_avg:.1f}%)"
            
            st.markdown(f"### {header_text}")
             
            if st.session_state.team_b:
                for uid in st.session_state.team_b:
                    u = id_map.get(uid)
                    if u is not None:
                        g = u.get('total_games', 0)
                        w = u.get('wins', 0)
                        wr = (w / g * 100) if g > 0 else 0.0
                        
                        display_text = f"{u['display_name']} ({u.get('tier', '-')})"
                        if st.session_state.show_individual_wr:
                            display_text += f", {wr:.1f}%"
                        
                        st.button(f"{display_text} ❌", key=f"del_b_{uid}", on_click=remove_from_team_to_lobby, args=(uid, 'B'))
            else:
                st.info("플레이어를 배치하세요 (Lobby)")

        st.divider()

        # --- LOBBY SECTION (New) ---
        st.markdown("### 🏟️ 대기실 (Lobby) / 팀 배정")
        st.caption("아래 플레이어 목록에서 참여(Join)시킨 인원이 여기 표시됩니다. A/B 팀으로 배정하세요.")
        
        # Filter participants who are NOT in a team
        lobby_users = []
        for uid in st.session_state.participants:
            if uid not in st.session_state.team_a and uid not in st.session_state.team_b:
                lobby_users.append(uid)
        
        if lobby_users:
            # Sort by rank priority (Descending) then Name
            lobby_users_data = [id_map.get(uid) for uid in lobby_users if uid in id_map]
            
            lobby_users_data.sort(key=lambda x: ( -RANK_PRIORITY.get(x.get('tier', '언랭'), 0), x['display_name'] ))

            # Display as list with buttons
            for u in lobby_users_data:
                c1, c2, c3, c4 = st.columns([4, 2, 2, 2])
                with c1:
                    display_str = f"**{u['display_name']}** ({u.get('tier', '-')})"
                    if st.session_state.show_individual_wr:
                        # Calculate WR
                        g = u.get('total_games', 0)
                        w = u.get('wins', 0)
                        wr = (w / g * 100) if g > 0 else 0.0
                        display_str += f" | {wr:.1f}%"
                        
                    st.write(display_str)
                with c2:
                    st.button("A팀으로", key=f"to_a_{u['id']}", on_click=add_to_team, args=(u['id'], 'A'), use_container_width=True)
                with c3:
                    st.button("B팀으로", key=f"to_b_{u['id']}", on_click=add_to_team, args=(u['id'], 'B'), use_container_width=True)
                with c4:
                    st.button("제외", key=f"out_{u['id']}", on_click=toggle_participation, args=(u['id'],))
        else:
            st.info("대기 중인 인원이 없습니다. 하단에서 '참여'를 눌러주세요.")
        
        st.divider()
        
        # --- Random Map Selector ---
        all_maps = get_all_maps()
        map_names = [m['name'] for m in all_maps] if all_maps else []
        
        # Remove Header "#### 🗺️ 맵 선택" as requested
        
        # Container for Map Display
        map_container = st.container(border=True)
        
        # Helper to render map box
        def render_map_box(text, color="#f0f2f6"):
            return f"""
            <div style='
                background-color: {color}; 
                padding: 20px; 
                border-radius: 10px; 
                text-align: center; 
                margin-bottom: 10px;
                border: 2px solid #ddd;
            '>
                <h2 style='margin: 0; color: #333;'>{text}</h2>
            </div>
            """

        # Initialize or Get Session State
        if 'selected_map' not in st.session_state:
            st.session_state.selected_map = None

        # Display Area (Always visible)
        map_slot = map_container.empty()
        
        if st.session_state.selected_map:
            map_slot.markdown(render_map_box(f"📍 {st.session_state.selected_map}", "#d4edda"), unsafe_allow_html=True)
        else:
            map_slot.markdown(render_map_box("❓ 맵을 돌려주세요", "#f0f2f6"), unsafe_allow_html=True)

        # Spin Button Area
        col_spin, _ = st.columns([1, 2]) # Adjust width if needed, or use full width
        spin = st.button("🎰 랜덤 맵 돌리기 (Spin!)", type="primary", use_container_width=True)
        
        if spin:
            if not map_names:
                 st.toast("⚠️ 등록된 맵이 없습니다. 사이드바에서 맵을 추가해주세요.", icon="⚠️")
            else:
                # Animation Logic
                import random
                import time
                
                # Fast spin
                for _ in range(10):
                    temp_map = random.choice(map_names)
                    map_slot.markdown(render_map_box(f"🎲 {temp_map}", "#fff3cd"), unsafe_allow_html=True)
                    time.sleep(0.08)
                
                # Slow down (Suspense)
                for i in range(5):
                    temp_map = random.choice(map_names)
                    map_slot.markdown(render_map_box(f"🎲 {temp_map} ...", "#fff3cd"), unsafe_allow_html=True)
                    time.sleep(0.1 + (i * 0.1)) # 0.1, 0.2, 0.3, 0.4, 0.5
                
                # Final Result
                final_map = random.choice(map_names)
                st.session_state.selected_map = final_map
                map_slot.markdown(render_map_box(f"📍 {final_map}", "#d4edda"), unsafe_allow_html=True) 
                st.balloons() # Optional celebration

        st.divider()
        
        # --- Bottom Section: Side Select & Result Submit ---
        c_side, c_submit = st.columns(2)
        
        with c_side:
            st.markdown("### ⚔️ 공수 결정 (Coin Toss)")
            if st.button("🪙 공격/수비 랜덤 추첨", use_container_width=True):
                import random
                sides = ['A', 'B']
                picked = random.choice(sides)
                st.session_state.attack_team = picked
                st.rerun()
            
            # Display current side status
            if st.session_state.attack_team:
                if st.session_state.attack_team == 'A':
                    st.success("**A팀**이 공격(Attack) 입니다!")
                else:
                    st.success("**B팀**이 공격(Attack) 입니다!")
            else:
                st.info("버튼을 눌러 공격 팀을 정하세요.")

        with c_submit:
            st.markdown("### 🏆 승리 팀 선택") 
            winning_team = st.radio("승리 팀", ("A팀", "B팀"), horizontal=True, label_visibility="collapsed")
            
            if st.button("결과 저장하기", type="primary", use_container_width=True):
                if not st.session_state.team_a or not st.session_state.team_b:
                    st.toast("⚠️ 양 팀에 최소 한 명 이상의 플레이어가 있어야 합니다.", icon="⚠️")
                elif not st.session_state.selected_map:
                    st.toast("⚠️ 맵이 선택되지 않았습니다. 맵을 돌려주세요!", icon="⚠️")
                else:
                    mapped_winner = "A" if winning_team == "A팀" else "B"
                    success, msg = record_match(st.session_state.team_a, st.session_state.team_b, mapped_winner, st.session_state.selected_map)
                    if success:
                        st.success(msg)
                        # Reset map and attack side, keep teams? Or reset teams too?
                        # Usually keep teams matches often happen in series. 
                        # But maybe we should remove from Lobby but keep in Participants?
                        # For now keep as is.
                        st.session_state.selected_map = None 
                        st.session_state.attack_team = None
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"오류: {msg}")
        
        st.divider()
        
        # Player Selection (Grouped by Tier)
        st.write("#### 플레이어 목록")
        st.caption("참여(Join) 버튼을 눌러 대기실로 이동시키세요.")
        
        search_query = st.text_input("검색 (이름)", "")
        
        filtered_df = df_sorted
        if search_query:
            filtered_df = df_sorted[filtered_df['display_name'].str.contains(search_query, case=False) | filtered_df['name'].str.contains(search_query, case=False)]

        # Ordered Rank List for Display
        RANK_ORDER = ["레디언트", "불멸", "초월자", "다이아몬드", "플래티넘", "골드", "실버", "브론즈", "아이언", "언랭"]
        
        for rank in RANK_ORDER:
            # Filter users in this rank
            rank_users = filtered_df[filtered_df['tier'] == rank]
            
            if not rank_users.empty:
                with st.expander(f"💠 {rank} ({len(rank_users)}명)", expanded=True):
                    # Grid Layout: 3 columns per row
                    cols = st.columns(3)
                    for idx, (_, row) in enumerate(rank_users.iterrows()):
                        uid = row['id']
                        with cols[idx % 3]:
                            is_participating = uid in st.session_state.participants
                            
                            # Always use a standard container for layout stability
                            with st.container(border=True):
                                # Name Display with Background Color for Participants
                                display_name = row['display_name']
                                if is_participating:
                                    # Use Streamlit's colored background syntax for pastel effect
                                    st.markdown(f":green-background[**{display_name}**]")
                                else:
                                    st.markdown(f"**{display_name}**")
                                
                                info_text = f"{rank}"
                                if st.session_state.show_individual_wr:
                                    info_text += f" | 승률: {row['win_rate']:.1f}%"
                                st.caption(info_text)
                                
                                if is_participating:
                                    if st.button("참여 취소", key=f"cancel_{uid}", use_container_width=True):
                                        toggle_participation(uid)
                                        st.rerun()
                                else:
                                    if st.button("참여 (Join)", key=f"join_{uid}", use_container_width=True):
                                        toggle_participation(uid)
                                        st.rerun()

    with tab3:
        st.subheader("📜 최근 매치 기록")
        st.caption("최근 20개의 매치를 보여줍니다. 잘못 기록된 매치는 삭제(취소)할 수 있습니다.")
        
        history = get_recent_matches(limit=20)
        
        if history:
            for match in history:
                with st.container():
                    # Parse timestamp (optional formatting)
                    created_at = match['created_at'][:16].replace("T", " ")
                    map_display = match.get('map_name') or "알 수 없음"
                    
                    c1, c2, c3 = st.columns([5, 1, 1])
                    with c1:
                        st.markdown(f"**매치 #{match['id']}** ({created_at}) | 🗺️ **{map_display}**")
                        st.markdown(f"{'🏆' if match['winning_team'] == 'A' else ''} **A팀**: {match['team_a']}")
                        st.markdown(f"{'🏆' if match['winning_team'] == 'B' else ''} **B팀**: {match['team_b']}")
                    
                    with c3:
                        # Use a callback to delete
                        if st.button("🗑️ 삭제", key=f"del_match_{match['id']}"):
                            success, msg = delete_match(match['id'])
                            if success:
                                st.success(msg)
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(f"실패: {msg}")
                    st.divider()
        else:
            st.info("아직 기록된 매치가 없습니다.")



else:
    st.info("등록된 멤버가 없습니다. 왼쪽 사이드바에서 '디스코드 멤버 동기화'를 눌러주세요.")

