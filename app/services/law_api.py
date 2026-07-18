import os
import re
import httpx
from dotenv import load_dotenv

load_dotenv()

LAW_API_BASE = "https://www.law.go.kr/DRF"

# 법제처 lawSearch API는 법령명 앞부분 일치(제목 검색)만 지원하므로,
# 사용자 문장 전체를 그대로 보내면 매칭되지 않는다. 문장에서 법령명 패턴만 추출한다.
_LAW_NAME_PATTERN = re.compile(r"[가-힣]{2,15}(?:법률|법령|시행령|시행규칙|법)")

# 법령명을 제외한 나머지 단어에서 걸러낼 의미 없는 조사/상투어
_FILLER_WORDS = {
    "알려줘", "알려주세요", "조항", "어떻게", "되나요", "되나요?", "궁금해요",
    "무엇인가요", "뭔가요", "관련", "내용", "대해", "설명해줘", "정도",
}


def _extract_law_query(message: str) -> str:
    match = _LAW_NAME_PATTERN.search(message)
    return match.group() if match else message


def _extract_keywords(message: str, law_query: str) -> list:
    """법령명을 제외한 나머지 문장에서 조문 검색용 키워드를 뽑는다."""
    remainder = message.replace(law_query, "")
    tokens = re.split(r"[\s,\.\?!·/]+", remainder)
    return [t for t in tokens if len(t) >= 2 and t not in _FILLER_WORDS]


def _get_api_key() -> str:
    return os.getenv("LAW_API_KEY", "demo")


def _as_list(value):
    """법제처 API는 결과가 1건이면 list 대신 dict를 반환하므로 정규화."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


async def search_law(query: str) -> str:
    """법제처 API로 관련 법령을 검색하여 컨텍스트 문자열 반환"""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            params = {
                "OC": _get_api_key(),
                "target": "law",
                "type": "JSON",
                "query": _extract_law_query(query),
                "display": 3,
                "page": 1,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
            resp.raise_for_status()
            data = resp.json()

            laws = _as_list(data.get("LawSearch", {}).get("law"))
            if not laws:
                return ""

            results = []
            for law in laws[:3]:
                name = law.get("법령명한글", "")
                date = law.get("시행일자", "")
                law_id = law.get("법령ID", "")
                if name:
                    results.append(f"• {name} (시행: {date}, ID: {law_id})")

            return "\n".join(results)

    except httpx.TimeoutException:
        return ""
    except Exception:
        return ""


async def get_law_article(law_id: str, article: str) -> str:
    """특정 조문 전문 조회"""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            params = {
                "OC": _get_api_key(),
                "target": "law",
                "type": "JSON",
                "ID": law_id,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawService.do", params=params)
            resp.raise_for_status()
            return resp.text
    except Exception:
        return ""

async def search_precedent(query: str) -> list:
    """법제처 Open API로 실제 판례 검색 (최대 3개, 구조화된 리스트로 반환)"""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            params = {
                "OC": _get_api_key(),
                "target": "prec",      # 판례 검색
                "type": "JSON",
                "query": _extract_law_query(query),
                "display": 3,
                "page": 1,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
            resp.raise_for_status()
            data = resp.json()

            precs = _as_list(data.get("PrecSearch", {}).get("prec"))
            if not precs:
                return []

            results = []
            for p in precs[:3]:
                num = p.get("사건번호", "")
                if not num:
                    continue
                summary = p.get("판시사항", "")[:100] if p.get("판시사항") else ""
                results.append({
                    "court": p.get("법원명", ""),
                    "date": p.get("선고일자", ""),
                    "case_no": num,
                    "case_name": p.get("사건명", ""),
                    "summary": summary,
                })

            return results

    except Exception:
        return []


def format_precedents(precedents: list) -> str:
    """구조화된 판례 리스트를 프롬프트용 텍스트로 변환"""
    if not precedents:
        return ""

    lines = []
    for p in precedents:
        line = f"[{p['court']} {p['date']} {p['case_no']}] {p['case_name']}"
        if p.get("summary"):
            line += f" — {p['summary']}..."
        lines.append(line)

    return "\n".join(lines)
    
async def get_law_articles(law_id: str, keywords: list = None) -> list:
    """법령 ID로 실제 조문 전문 조회 (구조화된 리스트로 반환)

    법령 하나가 수백 개 조문을 가질 수 있어 전부 반환할 수 없으므로,
    keywords가 주어지면 조문 내용에 키워드가 포함된 조문을 우선 반환하고
    (예: "음주운전 처벌" → 제44조·제148조의2 등 실제 관련 조문),
    일치하는 조문이 없으면 총칙 등 앞부분 조문으로 개요를 제공한다.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            params = {
                "OC": _get_api_key(),
                "target": "law",
                "type": "JSON",
                "ID": law_id,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawService.do", params=params)
            resp.raise_for_status()
            data = resp.json()

            articles = _as_list(data.get("법령", {}).get("조문", {}).get("조문단위"))
            if not articles:
                return []

            parsed = []
            for article in articles:
                if not isinstance(article, dict):
                    continue
                jo_num  = article.get("조문번호", "")
                jo_cont = article.get("조문내용", "")
                if jo_num and jo_cont:
                    parsed.append({"article_no": jo_num, "text": jo_cont[:300]})

            if keywords:
                matched = [a for a in parsed if any(kw in a["text"] for kw in keywords)]
                if matched:
                    return matched[:12]

            return parsed[:10]  # 키워드 매칭이 없으면 앞부분(총칙 등)으로 개요 제공

    except Exception:
        return []


async def search_and_fetch_law(query: str) -> list:
    """검색 → 상위 법령의 실제 조문까지 조회 (구조화된 리스트로 반환)

    반환 항목: {"law_name", "date", "article_no", "text"}
    """
    try:
        law_query = _extract_law_query(query)
        keywords  = _extract_keywords(query, law_query)

        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1단계: 법령 검색
            params = {
                "OC": _get_api_key(),
                "target": "law",
                "type": "JSON",
                "query": law_query,
                "display": 2,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
            resp.raise_for_status()
            data = resp.json()
            laws = _as_list(data.get("LawSearch", {}).get("law"))
            if not laws:
                return []

            # 2단계: 상위 2개 법령의 조문 전문 조회 (키워드와 관련된 조문 우선)
            legal_basis = []
            for law in laws[:2]:
                law_id   = law.get("법령ID", "")
                law_name = law.get("법령명한글", "")
                date     = law.get("시행일자", "")
                if not law_id:
                    continue
                articles = await get_law_articles(law_id, keywords)
                for article in articles:
                    legal_basis.append({
                        "law_name": law_name,
                        "date": date,
                        "article_no": article["article_no"],
                        "text": article["text"],
                    })

            return legal_basis

    except Exception:
        return []


def format_legal_basis(legal_basis: list) -> str:
    """구조화된 조문 리스트를 프롬프트용 텍스트로 변환"""
    if not legal_basis:
        return ""

    grouped = {}
    for item in legal_basis:
        grouped.setdefault((item["law_name"], item["date"]), []).append(item)

    parts = []
    for (law_name, date), items in grouped.items():
        lines = [f"제{i['article_no']}조 {i['text']}" for i in items]
        parts.append(f"[{law_name} / 시행: {date}]\n" + "\n".join(lines))

    return "\n\n".join(parts)