"""텔레그램 봇 수신/응답 테스트"""
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API = f"https://api.telegram.org/bot{TOKEN}"

print(f"BOT TOKEN: {TOKEN[:10]}...{TOKEN[-5:]}")
print(f"CHAT ID: {CHAT_ID}")

# 밀린 메시지 무시
last_id = 0
try:
    r = requests.get(f"{API}/getUpdates", params={"offset": -1}, timeout=5)
    data = r.json()
    print(f"getUpdates 응답: ok={data.get('ok')}")
    if data.get("result"):
        last_id = data["result"][-1]["update_id"]
        print(f"마지막 update_id: {last_id}")
except Exception as e:
    print(f"초기화 실패: {e}")

print("\n대기 중... 텔레그램에서 아무 메시지나 보내보세요.\n")

while True:
    try:
        r = requests.get(f"{API}/getUpdates", params={
            "offset": last_id + 1,
            "timeout": 10,
        }, timeout=15)
        data = r.json()

        if not data.get("ok"):
            print(f"API 에러: {data}")
            break

        for update in data.get("result", []):
            last_id = update["update_id"]
            msg = update.get("message", {})
            text = msg.get("text", "")
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            user = msg.get("from", {}).get("first_name", "?")

            print(f"[수신] chat_id={chat_id} / from={user} / text={text}")

            # 에코 응답
            reply = f"에코: {text}"
            resp = requests.post(f"{API}/sendMessage", json={
                "chat_id": chat_id,
                "text": reply,
            }, timeout=10)
            result = resp.json()
            print(f"[응답] ok={result.get('ok')} → {reply}")

    except requests.exceptions.Timeout:
        continue
    except KeyboardInterrupt:
        print("\n종료")
        break
    except Exception as e:
        print(f"오류: {e}")
