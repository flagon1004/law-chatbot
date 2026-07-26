# app/services/intent.py
from app.services.gemini import ask_gemini

KEYWORD_EXTRACTION_PROMPT = """
당신은 대한민국 법률 검색을 돕는 키워드 추출 전문가입니다.
사용자의 질문을 분석하여 법제처 API 및 판례 DB에서 검색하기 가장 적합한 '핵심 법률 용어 및 관련 법령 키워드' 1~3개를 콤마(,)로 구분하여 단어 형태로만 추출하세요.
부연 설명이나 인사말은 절대로 포함하지 마세요.

예시 1:
사용자: "월세 안 내고 계속 살고 있는 세입자 어떻게 쫓아내나요?"
출력: 주택임대차보호법, 건물명도, 차임연체

예시 2:
사용자: "길 가다가 개한테 물렸는데 주인이 나 몰라라 해요"
출력: 불법행위, 손해배상, 동물의 점유자 책임

예시 3:
사용자: "주계약자관리방식에서 전문업체인 부계약자를 주계약자의 동의 및 합의로 공동도급계약에서 탈퇴시킬 수 있나요?"
출력: 국가를 당사자로 하는 계약에 관한 법률 시행령, 건설산업 기본법, (계약예규)공동계약운용요령 

사용자: {message}
출력:
"""

async def extract_search_keywords(message: str) -> str:
    prompt = KEYWORD_EXTRACTION_PROMPT.format(message=message)
    try:
        raw_keywords = await ask_gemini(prompt)
        search_query = raw_keywords.strip().replace("\n", " ")
        return search_query
    except Exception:
        # 추출 실패 시 원본 메시지를 fallback으로 사용
        return message
