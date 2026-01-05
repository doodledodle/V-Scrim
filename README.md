# Valorant Scrim Manager (Streamlit + Supabase)

발로란트 내전 관리 및 승률 추적을 위한 Streamlit 웹 애플리케이션입니다.

## 배포 방법 (Streamlit Community Cloud)

1. [Streamlit Community Cloud](https://share.streamlit.io/)에 이 저장소를 연결하여 앱을 배포합니다.
2. **App Settings** -> **Secrets** 메뉴로 이동하여 다음 내용을 붙여넣으세요.
   (Supabase 프로젝트 설정 및 Discord 개발자 포털 정보를 확인하여 값을 채워넣어야 합니다)

```toml
# .streamlit/secrets.toml

# Supabase 설정 (Project Settings -> API)
SUPABASE_URL = "your_supabase_project_url"
SUPABASE_KEY = "your_supabase_anon_key"

# Discord 설정 (Developer Portal)
DISCORD_TOKEN = "Bot your_bot_token_here" 
# 주의: 토큰 앞에 'Bot ' 접두사를 꼭 붙여야 하거나, 코드에서 붙여주어야 합니다.
# 이 코드에서는 secrets에 'Bot '을 포함해서 넣거나, 코드에서 f"Bot {token}" 처리를 확인하세요.
# 가이드: 그냥 토큰 값만 넣으세요. 코드에서 처리하겠습니다.
DISCORD_TOKEN_RAW = "your_raw_bot_token"
GUILD_ID = "your_discord_server_id"
```

## 데이터베이스 설정 (Supabase)

1. Supabase 대시보드에서 **SQL Editor**로 이동합니다.
2. `schema.sql` 파일의 내용을 복사하여 실행합니다.

## 기능

- **디스코드 멤버 동기화**: 서버의 멤버 정보를 가져와 DB에 저장합니다.
- **내전 매치 기록**: A팀/B팀 멤버와 승리 팀을 선택하여 기록하면 승률이 자동 계산됩니다.
- **리더보드**: 승률 및 티어 정보를 확인합니다.
