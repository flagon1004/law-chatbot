import os
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")

_client = None

def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError(".env 파일에 NVIDIA_API_KEY가 설정되지 않았습니다.")
        _client = AsyncOpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)
    return _client

async def ask_nvidia(prompt: str) -> str:
    try:
        client = _get_client()
        completion = await client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=1,
            top_p=0.95,
            max_tokens=16384,
            extra_body={"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget": 16384},
        )
        return completion.choices[0].message.content
    except ValueError as e:
        return f"⚠️ {str(e)}"
    except Exception as e:
        if "429" in str(e):
            return "⚠️ 요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
        return f"[AI 오류] {str(e)}"
