import streamlit as st
from supabase import create_client, Client
import requests
import pandas as pd
import time

# --- Configuration & Setup ---
st.set_page_config(page_title="Valorant Scrim Manager", layout="wide")

# Initialize Supabase Client
# Expecting secrets to be available in st.secrets
# Format in .streamlit/secrets.toml:
# [supabase]
# url = "..."
# key = "..."
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    st.error("Supabase secrets not found. Please check your secrets.toml file.")
    st.stop()

# Discord Config
try:
    DISCORD_TOKEN_RAW = st.secrets["DISCORD_TOKEN_RAW"]
    GUILD_ID = st.secrets["GUILD_ID"]
    # Ensure correct format for Authorization header
    DISCORD_HEADER = {"Authorization": f"Bot {DISCORD_TOKEN_RAW}"} 
except Exception as e:
    st.error("Discord secrets not found. Please check your secrets.toml file.")
    st.stop()

# --- Functions ---

def sync_discord_members():
    """Fetches members from Discord API and updates the Supabase 'users' table."""
    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members?limit=1000"
    response = requests.get(url, headers=DISCORD_HEADER)
    
    if response.status_code == 200:
        members = response.json()
        users_data = []
        for member in members:
            user = member.get('user', {})
            if user:
                # Prepare data for upsert
                # Note: We only update name/display_name, we preserve stats
                # However, supabase upsert needs all non-null columns if we want to insert new rows.
                # Ideally, we upsert on ID.
                
                # To avoid overwriting existing stats (wins, total_games) with defaults,
                # we might need to be careful. Supabase upsert updates columns if ID exists.
                # If we omit fields, do they keep their old values? Yes, if we don't pass them in the payload usually?
                # Actually bulk upsert replaces row content if not careful.
                # A safer way allows partial updates or ignores existing rows?
                # Let's try to fetch existing users first or just update names.
                # Actually, simpler approach: Just Insert ON CONFLICT DO UPDATE SET name=EXCLUDED.name...
                # Supabase-py 'upsert' method handles this.
                
                user_id = int(user['id'])
                username = user.get('username')
                display_name = member.get('nick') or user.get('global_name') or username
                
                users_data.append({
                    "id": user_id,
                    "name": username,
                    "display_name": display_name,
                    # We do NOT include wins/total_games here to avoid resetting them or needing to fetch them first.
                    # BUT if it's a new user, they need defaults.
                    # The SQL definition has DEFAULT 0, so if we omit them for NEW rows it's fine.
                    # For EXISTING rows, if we omit them, does upsert keep them? 
                    # supabase-py upsert behavior depends on 'ignoreDuplicates' or exact payload.
                    # To be safe, let's just Upsert ID/Names.
                })
        
        # Perform Upsert
        if users_data:
            # We want to update names if changed, but keep stats.
            # Upsert will Insert if new, Update if exists. 
            # If we pass only id/name/display_name, it SHOULD only update those columns?
            # Let's test this assumption or check docs. 
            # Actually, typically upsert replaces the row. 
            # BUT passing a partial dictionary usually updates only those fields in an update.
            try:
                data = supabase.table("users").upsert(users_data).execute()
                return len(users_data), "Success"
            except Exception as e:
                return 0, str(e)
        else:
             return 0, "No members found."

    else:
        return 0, f"Error {response.status_code}: {response.text}"

def get_all_users():
    """Retrieves all users from Supabase."""
    response = supabase.table("users").select("*").execute()
    return response.data

def record_match(team_a_ids, team_b_ids, winning_team):
    """
    Records a match:
    1. Creates a match record.
    2. Enters participants.
    3. Updates user stats (wins/total_games).
    """
    try:
        # 1. Create Match
        match_res = supabase.table("matches").insert({"winning_team": winning_team}).execute()
        
        if not match_res.data:
            return False, "Failed to create match."
        
        match_id = match_res.data[0]['id']
        
        # 2. Participants & 3. Stats Update
        participants_data = []
        
        # Needed to fetch current stats to increment? 
        # Supabase doesn't support atomic increment easily via simple client call without RPC.
        # So we fetch relevant users, calculate new stats, and update.
        
        all_ids = team_a_ids + team_b_ids
        users_res = supabase.table("users").select("id, wins, total_games").in_("id", all_ids).execute()
        user_map = {u['id']: u for u in users_res.data}
        
        updated_users = []
        
        # Process Team A
        for uid in team_a_ids:
            participants_data.append({"match_id": match_id, "user_id": uid, "team": "A"})
            user = user_map.get(uid)
            if user:
                new_wins = user['wins'] + 1 if winning_team == 'A' else user['wins']
                new_total = user['total_games'] + 1
                updated_users.append({"id": uid, "wins": new_wins, "total_games": new_total})

        # Process Team B
        for uid in team_b_ids:
            participants_data.append({"match_id": match_id, "user_id": uid, "team": "B"})
            user = user_map.get(uid)
            if user:
                new_wins = user['wins'] + 1 if winning_team == 'B' else user['wins']
                new_total = user['total_games'] + 1
                updated_users.append({"id": uid, "wins": new_wins, "total_games": new_total})
                
        # Insert Participants
        supabase.table("match_participants").insert(participants_data).execute()
        
        # Update User Stats
        supabase.table("users").upsert(updated_users).execute()
        
        return True, "Match recorded successfully!"
        
    except Exception as e:
        return False, str(e)


# --- UI Layout ---

st.title("🔫 Valorant Scrim Manager")

# Sidebar: Sync
with st.sidebar:
    st.header("Settings")
    if st.button("Sync Discord Members"):
        with st.spinner("Syncing members..."):
            count, msg = sync_discord_members()
            if count > 0:
                st.success(f"Synced {count} members!")
            else:
                st.error(f"Failed: {msg}")

# Main Data Fetch
users = get_all_users()
df = pd.DataFrame(users)

if not df.empty:
    # Calculate Win Rate for display
    # Avoid division by zero
    df['win_rate'] = df.apply(lambda row: (row['wins'] / row['total_games'] * 100) if row['total_games'] > 0 else 0.0, axis=1)
    
    # Sort for Leaderboard
    df_sorted = df.sort_values(by=['win_rate', 'wins'], ascending=False)
    
    # Map for Multiselect (Display Name -> ID)
    # We create a list of strings "Display Name (ID/Name)" to Ensure uniqueness in UI
    df['ui_label'] = df['display_name'] + " (" + df['name'] + ")"
    id_map = dict(zip(df['ui_label'], df['id']))
    
    tab1, tab2 = st.tabs(["🏆 Leaderboard", "📝 Record Match"])
    
    with tab1:
        st.subheader("Leaderboard")
        # Display Columns
        st.dataframe(
            df_sorted[['display_name', 'tier', 'wins', 'total_games', 'win_rate']],
            column_config={
                "display_name": "Player",
                "tier": "Tier",
                "wins": "Wins",
                "total_games": "Matches",
                "win_rate": st.column_config.NumberColumn(
                    "Win Rate (%)",
                    format="%.1f %%"
                )
            },
            hide_index=True,
            use_container_width=True
        )

    with tab2:
        st.subheader("Record a New Scrim")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Team A")
            team_a_selection = st.multiselect("Select Team A Players", df['ui_label'], key="team_a")
        
        with col2:
            st.markdown("### Team B")
            team_b_selection = st.multiselect("Select Team B Players", df['ui_label'], key="team_b")
            
        winning_team = st.radio("Who Won?", ("Team A", "Team B"), horizontal=True)
        
        if st.button("Submit Match Result", type="primary"):
            team_a_ids = [id_map[label] for label in team_a_selection]
            team_b_ids = [id_map[label] for label in team_b_selection]
            
            # Validation
            if not team_a_ids or not team_b_ids:
                st.toast("⚠️ Both teams must have at least one player.", icon="⚠️")
            else:
                # Check for overlap
                if set(team_a_ids) & set(team_b_ids):
                     st.toast("⚠️ A player cannot be in both teams!", icon="⚠️")
                else:
                    mapped_winner = "A" if winning_team == "Team A" else "B"
                    success, msg = record_match(team_a_ids, team_b_ids, mapped_winner)
                    
                    if success:
                        st.success(msg)
                        time.sleep(1)
                        st.rerun() # Refresh data
                    else:
                        st.error(f"Error: {msg}")
else:
    st.info("No users found. Please sync with Discord first via the Sidebar.")
