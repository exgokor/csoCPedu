import os
from dotenv import load_dotenv

load_dotenv()

USER_ID = os.getenv("USER_ID")
USER_PW = os.getenv("USER_PW")

BASE_URL = "https://www.kpbma-cpedu.com"
LOGIN_URL = f"{BASE_URL}/userMain/goLogin"
MYPAGE_URL = f"{BASE_URL}/sub/myPage/goMyPage"
