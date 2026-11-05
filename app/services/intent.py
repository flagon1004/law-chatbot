# app/services/intent.py
import re

KEYWORD_EXTRACTION_PROMPT = """
당신은 대한민국 법률 검색을 돕는 키워드 추출 전문가입니다.
사용자의 질문을 분석하여 아래 두 줄만 출력하세요. 부연 설명이나 인사말은 절대 포함하지 마세요.

검색어: 법제처 API 및 판례 DB에서 검색하기 가장 적합한 '법령명·예규명·핵심 법률 용어' 1~3개 (콤마로 구분)
본문용어: 해당 법령 조문 본문에 실제로 쓰이는 법령상의 표현 3~6개 (콤마로 구분)

본문용어 작성 규칙:
- 사용자는 일상어("음주운전", "쫓아내다")로 묻지만 조문은 법령 용어("술에 취한 상태", "명도")로 씁니다. 일상어를 조문에 실제로 쓰이는 표현으로 바꿔 적으세요.
- 조문에서 그대로 찾을 수 있도록 짧은 명사구(2~8자) 위주로, 조사를 붙이지 마세요.
- 해당 법령 어디에나 나오는 지나치게 일반적인 단어("운전", "법", "규정", "사람" 등)는 제외하고, 질문의 쟁점을 가려내는 구체적인 표현만 고르세요.

예시 1:
사용자: "월세 안 내고 계속 살고 있는 세입자 어떻게 쫓아내나요?"
검색어: 주택임대차보호법, 건물명도, 차임연체
본문용어: 차임, 연체, 계약의 해지, 인도, 임차인

예시 2:
사용자: "길 가다가 개한테 물렸는데 주인이 나 몰라라 해요"
검색어: 불법행위, 손해배상, 동물의 점유자 책임
본문용어: 동물의 점유자, 손해를 배상, 책임, 과실

예시 3:
사용자: "주계약자관리방식에서 전문업체인 부계약자를 주계약자의 동의 및 합의로 공동도급계약에서 탈퇴시킬 수 있나요?"
검색어: 국가를 당사자로 하는 계약에 관한 법률 시행령, 건설산업 기본법, (계약예규)공동계약운용요령
본문용어: 탈퇴, 구성원, 공동수급체, 변경, 출자비율

예시 4:
사용자: "도로교통법 음주운전 처벌 조항 알려줘"
검색어: 도로교통법, 음주운전
본문용어: 술에 취한 상태, 혈중알코올농도, 징역, 벌금, 면허 취소

사용자: {message}
"""

_SEARCH_LINE = re.compile(r"검색어\s*[:：]\s*(.+)")
_BODY_LINE   = re.compile(r"본문용어\s*[:：]\s*(.+)")


def _split_terms(line: str) -> list:
    return [t.strip().strip('"\'') for t in line.split(",") if t.strip()]


def parse_keyword_output(raw: str, message: str) -> tuple:
    """LLM 출력을 (검색어 리스트, 본문용어 리스트)로 파싱한다.

    "검색어:" 줄이 없으면(모델이 형식을 안 지킨 경우) 출력 전체를 검색어로
    취급해 기존 동작과 동일하게 처리하고, 그것도 비어 있으면 원본 질문을 쓴다."""
    search_m = _SEARCH_LINE.search(raw)
    body_m   = _BODY_LINE.search(raw)

    if search_m:
        search_terms = _split_terms(search_m.group(1))
    else:
        search_terms = _split_terms(raw.replace("\n", " "))
    body_terms = _split_terms(body_m.group(1)) if body_m else []

    return (search_terms or [message]), body_terms


async def extract_search_keywords(message: str, ask_fn) -> tuple:
    """검색어와 본문용어를 추출한다. Returns: (search_terms, body_terms).

    - search_terms: 법령/예규 제목·판례 검색에 쓰는 용어 (어느 문서를 찾을지)
    - body_terms: 찾은 문서 안에서 관련 조문을 고르는 데 쓰는 법령상의 표현

    추출도 사용자가 선택한 모델(ask_fn)로 수행한다. 최종 답변 모델과 다른
    모델을 여기서 쓰면, 사용자가 선택하지 않은 모델(예: 관리자 잠금이 걸린
    Gemini)이 매 요청마다 조용히 호출되는 문제가 생기기 때문."""
    prompt = KEYWORD_EXTRACTION_PROMPT.format(message=message)
    try:
        raw = await ask_fn(prompt)
        return parse_keyword_output(raw.strip(), message)
    except Exception:
        # 추출 실패 시 원본 메시지를 검색어로 사용
        return [message], []
