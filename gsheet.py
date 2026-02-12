"""
구글 스프레드시트 Web App 연동
- doGet: 대기 상태 계정 목록 가져오기 (XOR 암호화 → 복호화)
- doPost: 계정 상태 업데이트 (진행중/수료완료/실패)
- 요청 시 token 파라미터로 인증
"""

import base64
import requests
import config


def _enabled():
    return bool(config.GSHEET_WEB_APP_URL)


def _get_url_with_token():
    """Web App URL에 token 파라미터 추가"""
    url = config.GSHEET_WEB_APP_URL
    token = config.GSHEET_SECRET_TOKEN
    if token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={token}"
    return url


def _xor_decrypt(encrypted_b64, key):
    """XOR + Base64 복호화 (Apps Script의 xorEncrypt와 대칭)"""
    if not key or not encrypted_b64:
        return encrypted_b64
    raw = base64.b64decode(encrypted_b64)
    result = []
    for i, byte in enumerate(raw):
        result.append(chr(byte ^ ord(key[i % len(key)])))
    return "".join(result)


def fetch_pending_accounts():
    """구글시트에서 '대기' 상태 계정 목록 가져오기 (복호화 포함)

    Returns:
        list[dict]: [{"user_id": "...", "user_pw": "...", "telegram_chat_id": "..."}, ...]
        빈 리스트: 대기 계정 없음 또는 오류
    """
    if not _enabled():
        print("  [구글시트] GSHEET_WEB_APP_URL 미설정")
        return []

    try:
        resp = requests.get(_get_url_with_token(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # 에러 응답 체크
        if isinstance(data, dict) and data.get("error"):
            print(f"  [구글시트] 서버 오류: {data['error']}")
            return []

        accounts = data if isinstance(data, list) else data.get("accounts", [])

        # 암호화된 데이터 복호화
        key = config.GSHEET_ENCRYPT_KEY
        valid = []
        for acc in accounts:
            if not acc.get("user_id") or not acc.get("user_pw"):
                continue

            if acc.get("_encrypted") and key:
                acc["user_id"] = _xor_decrypt(acc["user_id"], key)
                acc["user_pw"] = _xor_decrypt(acc["user_pw"], key)

            valid.append({
                "user_id": acc["user_id"],
                "user_pw": acc["user_pw"],
                "telegram_chat_id": acc.get("telegram_chat_id", ""),
            })

        print(f"  [구글시트] 대기 계정 {len(valid)}개 로드")
        return valid

    except Exception as e:
        print(f"  [구글시트] 계정 조회 실패: {e}")
        return []


def update_status(user_id, status, message=""):
    """구글시트에 계정 상태 업데이트

    Args:
        user_id: 계정 ID (평문 - doPost에서는 user_id로 행 검색)
        status: "진행중" | "수료완료" | "실패" | "대기"
        message: 비고 메시지 (예: "6/10차시", "세션 만료")

    Returns:
        bool: 성공 여부
    """
    if not _enabled():
        return False

    try:
        resp = requests.post(_get_url_with_token(), json={
            "user_id": user_id,
            "status": status,
            "message": message,
        }, timeout=15)
        resp.raise_for_status()
        return True

    except Exception as e:
        print(f"  [구글시트] 상태 업데이트 실패 ({user_id}→{status}): {e}")
        return False
