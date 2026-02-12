import os
from dotenv import load_dotenv

load_dotenv()

USER_ID = os.getenv("USER_ID")
USER_PW = os.getenv("USER_PW")

BASE_URL = "https://www.kpbma-cpedu.com"
LOGIN_URL = f"{BASE_URL}/userMain/goLogin"
MYPAGE_URL = f"{BASE_URL}/sub/myPage/goMyPage"

# 텔레그램
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 구글 스프레드시트 Web App
GSHEET_WEB_APP_URL = os.getenv("GSHEET_WEB_APP_URL", "")
GSHEET_SECRET_TOKEN = os.getenv("GSHEET_SECRET_TOKEN", "")
GSHEET_ENCRYPT_KEY = os.getenv("GSHEET_ENCRYPT_KEY", "")
