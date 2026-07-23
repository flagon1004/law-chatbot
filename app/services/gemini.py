import os
import asyncio
from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

_client = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(".env 파일에 GEMINI_API_KEY가 설정되지 않았습니다.")
        _client = genai.Client(api_key=api_key)
    return _client

async def ask_gemini(prompt: str, retry: int = 3) -> str:
    for attempt in range(retry):
        try:
            client = _get_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=prompt,
            )
            return response.text
        except Exception as e:
            if "429" in str(e):
                if attempt < retry - 1:
                    await asyncio.sleep(5 * (attempt + 1))  # 5초, 10초, 15초 간격
                    continue
                return "⚠️ 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
            return f"[AI 오류] {str(e)}"
