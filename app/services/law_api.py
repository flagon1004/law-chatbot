import os
import httpx
from dotenv import load_dotenv

load_dotenv()

LAW_API_BASE = "https://www.law.go.kr/DRF"


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
                "query": query,
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

async def search_precedent(query: str) -> str:
    """법제처 Open API로 실제 판례 검색 (최대 3개)"""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            params = {
                "OC": _get_api_key(),
                "target": "prec",      # 판례 검색
                "type": "JSON",
                "query": query,
                "display": 3,
                "page": 1,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
            resp.raise_for_status()
            data = resp.json()

            precs = _as_list(data.get("PrecSearch", {}).get("prec"))
            if not precs:
                return ""

            results = []
            for p in precs[:3]:
                court   = p.get("법원명", "")
                date    = p.get("선고일자", "")
                num     = p.get("사건번호", "")
                name    = p.get("사건명", "")
                summary = p.get("판시사항", "")[:100] if p.get("판시사항") else ""
                if num:
                    results.append(
                        f"[{court} {date} {num}] {name}"
                        + (f" — {summary}..." if summary else "")
                    )

            return "\n".join(results)

    except Exception:
        return ""
    
async def get_law_full_text(law_id: str) -> str:
    """법령 ID로 실제 조문 전문 조회"""
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
                return ""

            results = []
            for article in articles[:10]:  # 최대 10개 조문
                if not isinstance(article, dict):
                    continue
                jo_num  = article.get("조문번호", "")
                jo_cont = article.get("조문내용", "")
                if jo_num and jo_cont:
                    results.append(f"제{jo_num}조 {jo_cont[:200]}")

            return "\n".join(results)

    except Exception:
        return ""

async def search_and_fetch_law(query: str) -> str:
    """검색 → 상위 법령의 실제 조문까지 조회"""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # 1단계: 법령 검색
            params = {
                "OC": _get_api_key(),
                "target": "law",
                "type": "JSON",
                "query": query,
                "display": 2,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
            resp.raise_for_status()
            data = resp.json()
            laws = _as_list(data.get("LawSearch", {}).get("law"))
            if not laws:
                return ""

            # 2단계: 상위 2개 법령의 조문 전문 조회
            full_texts = []
            for law in laws[:2]:
                law_id   = law.get("법령ID", "")
                law_name = law.get("법령명한글", "")
                date     = law.get("시행일자", "")
                if law_id:
                    text = await get_law_full_text(law_id)
                    if text:
                        full_texts.append(
                            f"[{law_name} / 시행: {date}]\n{text}"
                        )

            return "\n\n".join(full_texts)

    except Exception:
        return ""    