import asyncio
import os
import re
from difflib import SequenceMatcher
import httpx
from dotenv import load_dotenv

load_dotenv()

LAW_API_BASE = "https://www.law.go.kr/DRF"

# 법제처 lawSearch API는 법령명 앞부분 일치(제목 검색)만 지원하므로,
# 사용자 문장 전체를 그대로 보내면 매칭되지 않는다. 문장에서 법령명 패턴만 추출한다.
# 공백을 허용하는 이유: "건설산업 기본법"처럼 띄어쓰기가 섞여 들어오면
# 공백 없는 패턴은 "기본법"처럼 너무 짧고 일반적인 조각만 잡아서
# 전혀 다른 법("건강가정기본법" 등)이 걸리는 문제가 있었다.
_LAW_NAME_PATTERN = re.compile(r"[가-힣][가-힣\s]{1,40}(?:법률|법령|시행령|시행규칙|법)")

# 법령명을 제외한 나머지 단어에서 걸러낼 의미 없는 조사/상투어
_FILLER_WORDS = {
    "알려줘", "알려주세요", "조항", "어떻게", "되나요", "되나요?", "궁금해요",
    "무엇인가요", "뭔가요", "관련", "내용", "대해", "설명해줘", "정도",
    "있나요", "있을까요", "있습니까", "할까요", "가능한가요",
}

# "제4조 삭제 <2020.4.7>"처럼 본문 없이 삭제 표시만 있는 조문
_DELETED_ARTICLE = re.compile(r"제\d+조(?:의\d+)?\s*삭제")

# 조문 1개당 프롬프트/화면에 싣는 최대 글자 수. 항·호·목까지 포함한 전체 본문을
# 매칭에는 쓰되, 출력은 이 길이로 자른다.
_ARTICLE_TEXT_LIMIT = 800
# 키워드와 일치하는 조문은 일치 키워드 수가 많은 순으로 문서당 이만큼만 싣는다.
_MATCHED_LIMIT = 8
# 키워드 일치가 없을 때 총칙 위주로 보여주는 개요 조문 수.
_OVERVIEW_LIMIT = 6


def _extract_law_query(message: str) -> str:
    # 여러 후보 중 가장 긴(=가장 구체적인) 매칭을 고른다. 예: "건설산업 기본법"에서
    # "기본법"과 "건설산업 기본법" 둘 다 매칭 가능한데, 짧은 쪽을 고르면
    # 전혀 다른 법이 검색되므로 항상 가장 긴 매칭을 우선한다.
    matches = _LAW_NAME_PATTERN.findall(message)
    if matches:
        return max(matches, key=len).strip()
    return message


def _extract_keywords(message: str, law_query: str) -> list:
    """법령명을 제외한 나머지 문장에서 조문 검색용 키워드를 뽑는다."""
    remainder = message.replace(law_query, "")
    tokens = re.split(r"[\s,\.\?!·/]+", remainder)
    return [t for t in tokens if len(t) >= 2 and t not in _FILLER_WORDS]


def _get_api_key() -> str:
    return os.getenv("LAW_API_KEY", "demo")


# 행정규칙 제목 검색은 일반 단어("보증금")도 긴 제목의 일부로 걸어버린다
# (예: "보증금 반환" → "어구보증금의 이관방법…에 관한 고시"). 검색어가 결과 제목에서
# 차지하는 비중(공통 부분 문자열 길이 / 제목 길이)이 이 값 미만이면 무관한 문서로 본다.
# 실측: 실제 규칙명 질의는 0.40~1.00(공동계약운용요령 0.67, 표준품셈 0.40~0.50),
# 일반 단어로 걸린 잡음은 0.06~0.24.
_ADMRUL_MIN_COVERAGE = 0.4


def _title_coverage(term: str, title: str) -> float:
    strip = lambda s: re.sub(r"[\s()\[\]「」·,]", "", s)
    a, b = strip(term), strip(title)
    if not a or not b:
        return 0.0
    match = SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b))
    return match.size / len(b)


# 법령 제목 검색은 부분 일치라 "민법"이 "난민법"에도 걸리고, 결과도 그 순서로 온다.
# 후보를 넉넉히 받아 아래 규칙으로 다시 고른다.
# 실제 법령이 순위 하단에 밀리는 경우가 있어(예: "상법"은 제목에 '상법'이 들어간 다른 법들 뒤)
# 후보를 최대치로 받는다.
_LAW_SEARCH_DISPLAY = 50
_LAW_PREFIX_MIN_COVERAGE = 0.25
_LAW_SUFFIXES = ("시행령", "시행규칙")


def _rank_law_candidates(term: str, laws: list, limit: int = 2) -> list:
    """검색어에 해당하는 법령을 골라 최대 limit개 반환.

    1) 제목이 검색어와 같거나(공백 무시) 그 시행령/시행규칙인 것만 우선한다.
       ("민법" → 민법, "도로교통법" → 도로교통법·시행령)
    2) 그런 게 없으면 제목이 검색어로 시작하는 것만, 제목 대비 일치 비중이 너무 낮으면 버린다."""
    norm = lambda s: re.sub(r"\s+", "", s or "")
    t = norm(term)
    if not t:
        return laws[:limit]

    exact, related, prefix = [], [], []
    for law in laws:
        name = norm(law.get("법령명한글", ""))
        if not name:
            continue
        if name == t:
            exact.append(law)
        elif any(name == t + suf for suf in _LAW_SUFFIXES):
            related.append(law)
        elif name.startswith(t):
            prefix.append(law)

    if exact or related:
        return (exact + related)[:limit]

    # 제목이 검색어로 시작하는 법령만 인정한다. 제목 중간에 검색어가 들어 있을 뿐인 법령
    # ("손해배상" → "우주손해배상법")은 무관한 경우가 대부분이라 버린다.
    fallback = [law for law in prefix
                if _title_coverage(term, law.get("법령명한글", "")) >= _LAW_PREFIX_MIN_COVERAGE]
    return fallback[:limit]


def _flatten_text(value) -> str:
    """항내용/호내용/목내용은 문자열이거나 문자열 리스트로 온다."""
    if isinstance(value, list):
        return " ".join(str(v).strip() for v in value if v)
    return str(value).strip() if value else ""


def _article_full_text(article: dict) -> str:
    """조문 제목(조문내용)에 항 → 호 → 목 본문을 이어 붙인 전체 본문.

    법령 API의 '조문내용'은 많은 조문에서 제목("제44조(술에 취한 상태에서의
    운전 금지)")뿐이고 실제 내용은 중첩된 항/호/목 필드에 들어 있다."""
    lines = [_flatten_text(article.get("조문내용"))]
    for hang in _as_list(article.get("항")):
        if not isinstance(hang, dict):
            lines.append(_flatten_text(hang))
            continue
        lines.append(_flatten_text(hang.get("항내용")))
        for ho in _as_list(hang.get("호")):
            if not isinstance(ho, dict):
                lines.append(_flatten_text(ho))
                continue
            lines.append("  " + _flatten_text(ho.get("호내용")))
            for mok in _as_list(ho.get("목")):
                text = mok.get("목내용") if isinstance(mok, dict) else mok
                lines.append("    " + _flatten_text(text))
    return "\n".join(line for line in lines if line.strip())


def _select_articles(parsed: list, keywords: list) -> tuple:
    """전체 본문(parsed[i]["text"]) 기준으로 조문을 고른다.

    Returns: (articles, matched). 키워드가 하나라도 일치하면 일치한 키워드 수가
    많은 조문부터 _MATCHED_LIMIT개, 없으면 앞쪽 _OVERVIEW_LIMIT개(개요).
    반환하는 text는 _ARTICLE_TEXT_LIMIT자로 자른다."""
    def clip(a):
        text = a["text"]
        if len(text) > _ARTICLE_TEXT_LIMIT:
            text = text[:_ARTICLE_TEXT_LIMIT] + "…"
        return {"article_no": a["article_no"], "text": text}

    if keywords:
        scored = [(sum(1 for kw in keywords if kw in a["text"]), i, a)
                  for i, a in enumerate(parsed)]
        hits = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))
        if hits:
            # 일반 단어 하나만 우연히 걸린 약한 조문이 한도를 채우지 않도록,
            # 최고 일치 수의 절반 미만인 조문은 버린다.
            floor = max(1, (hits[0][0] + 1) // 2)
            hits = [h for h in hits if h[0] >= floor]
            return [clip(a) for _, _, a in hits[:_MATCHED_LIMIT]], True

    return [clip(a) for a in parsed[:_OVERVIEW_LIMIT]], False


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

# ── 판례 검색 ────────────────────────────────────────────────────────────
# 판례 목록 검색은 '사건명' 부분 일치다. 본문에서 판시사항·판결요지는 상세 조회
# (lawService, ID=판례일련번호)로만 얻을 수 있다.
_PREC_LIST_DISPLAY = 20      # 검색어당 목록 후보 수 (사건명이 '대여금'처럼 단순한 판결이 많아 넉넉히)
_PREC_DETAIL_CANDIDATES = 10  # 상세 조회해서 관련도를 매길 후보 수
_PREC_RESULT_LIMIT = 3
_PREC_MIN_SCORE = 2          # 서로 다른 질문 키워드가 최소 이만큼 판시사항·사건명에 나와야 함
_PREC_SUMMARY_LIMIT = 250
_PREC_HOLDING_LIMIT = 400
# 검색어 전체가 법령명(민법, 도로교통법 등)인 경우. 사건명 검색에서는 그 법을 다룬
# 아무 사건이나 걸리므로 구체 용어 검색이 실패했을 때만 마지막으로 쓴다.
_BARE_LAW_TERM = re.compile(r"^[가-힣\s]{1,40}(?:법률|법령|시행령|시행규칙|법)$")


def _clean_html(value) -> str:
    text = re.sub(r"<br\s*/?>", " ", _flatten_text(value))
    return re.sub(r"\s+", " ", text).strip()


def _court_name(p: dict) -> str:
    # 일부 하급심은 법원명 필드가 비어 있고 사건번호 앞에 "서울동부지방법원-2020-…"로 온다
    return p.get("법원명") or (p.get("사건번호", "").split("-")[0] if "-" in p.get("사건번호", "") else "")


async def _prec_list(client, term: str, supreme_only: bool, body: bool = False) -> list:
    params = {
        "OC": _get_api_key(), "target": "prec", "type": "JSON",
        "query": term, "display": _PREC_LIST_DISPLAY, "page": 1,
    }
    if supreme_only:
        params["curt"] = "대법원"
    if body:
        # 사건명이 아니라 판결문 본문에서 검색한다(여러 단어는 모두 포함된 판결만).
        # 사건명이 "대여금"처럼 단순한 판결들 중 쟁점이 맞는 것을 찾는 데 쓴다.
        params["search"] = 2
    try:
        resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
        resp.raise_for_status()
        return _as_list(resp.json().get("PrecSearch", {}).get("prec"))
    except Exception:
        return []


async def _prec_detail(client, serial_no: str) -> dict:
    """판시사항·판결요지 조회. 조회되지 않는 출처(일부 하급심)는 빈 dict."""
    if not serial_no:
        return {}
    try:
        resp = await client.get(f"{LAW_API_BASE}/lawService.do", params={
            "OC": _get_api_key(), "target": "prec", "type": "JSON", "ID": serial_no})
        resp.raise_for_status()
        body = resp.json().get("PrecService")
        return body if isinstance(body, dict) else {}
    except Exception:
        return {}


def _is_bare_law(term: str) -> bool:
    return bool(_BARE_LAW_TERM.match(term.strip()))


async def _collect_precedents(terms: list, keywords: list) -> list:
    # 본문 검색은 단어가 많을수록 우연히 겹치는 잡음이 늘고 무관한 판결이 걸리므로 2어절 검색어만 쓴다
    body_terms = [t for t in terms if len(t.split()) == 2]
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 사건명 검색(대법원 한정 / 전체)과 본문 검색(대법원 한정, 여러 단어 검색어만)을 병렬 조회
        title_sup, title_all, body_sup = await asyncio.gather(
            asyncio.gather(*[_prec_list(client, t, True) for t in terms]),
            asyncio.gather(*[_prec_list(client, t, False) for t in terms]),
            asyncio.gather(*[_prec_list(client, t, True, body=True) for t in body_terms]),
        )

        def take(lists, per_list):
            return [p for lst in lists for p in lst[:per_list]]

        # 후보 구성: 사건명 일치 대법원 → 본문 일치 대법원 → 그 외(하급심 포함).
        # 사건명 후보가 목록을 다 차지하지 않도록 그룹별로 상한을 둔다.
        candidates, seen = [], set()
        body_hits = {p.get("사건번호", "") for lst in body_sup for p in lst[:4]}
        groups = [take(title_sup, 5), take(body_sup, 4), take(title_all, 20)]
        for group in groups:
            for p in group:
                num = p.get("사건번호", "")
                if not num or num in seen:
                    continue
                seen.add(num)
                candidates.append(p)
        candidates = candidates[:_PREC_DETAIL_CANDIDATES]
        details = await asyncio.gather(*[
            _prec_detail(client, p.get("판례일련번호", "")) for p in candidates])

    scored = []
    for order, (p, d) in enumerate(zip(candidates, details)):
        holding_src = _clean_html(d.get("판시사항")) + " " + _clean_html(d.get("판결요지"))
        haystack = p.get("사건명", "") + " " + holding_src
        score = sum(1 for kw in keywords if kw and kw in haystack)
        if score and p.get("사건번호") in body_hits:
            score += 1   # 쟁점어가 판결문 본문에 함께 나온 판결
        supreme = _court_name(p) == "대법원"
        scored.append((score, supreme, order, p, d))

    # 본문 관련도(키워드 일치 수) → 대법원 → 원래 순서
    scored.sort(key=lambda x: (-x[0], not x[1], x[2]))
    if keywords:
        # 일반 단어 하나(예: "책임")만 우연히 걸린 판례는 무관한 것으로 보고 버린다.
        # 무관한 판례를 보여주는 것보다 "찾지 못했다"가 낫다.
        scored = [s for s in scored if s[0] >= _PREC_MIN_SCORE]

    results = []
    for _, _, _, p, d in scored[:_PREC_RESULT_LIMIT]:
        issue = _clean_html(d.get("판시사항"))
        holding = _clean_html(d.get("판결요지"))
        results.append({
            "court": _court_name(p),
            "date": p.get("선고일자", ""),
            "case_no": p.get("사건번호", ""),
            "case_name": p.get("사건명", ""),
            "summary": issue[:_PREC_SUMMARY_LIMIT],
            "holding": holding[:_PREC_HOLDING_LIMIT],
        })
    return results


async def search_precedents(terms: list, keywords: list = None) -> list:
    """판례 검색. terms는 우선순위 순서의 후보 검색어.

    법령명만으로 된 검색어는 구체 용어로 아무것도 못 찾았을 때만 쓴다.
    후보는 대법원 판결을 우선 모으고, 판시사항·판결요지에 질문 키워드가
    얼마나 나오는지로 관련도를 매겨 상위 3건을 반환한다."""
    keywords = keywords or []
    seen, concept, bare = set(), [], []
    for t in terms:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            (bare if _is_bare_law(t) else concept).append(t)
    try:
        for group in (concept, bare):
            if group:
                results = await _collect_precedents(group, keywords)
                if results:
                    return results
    except Exception:
        pass
    return []


def format_precedents(precedents: list) -> str:
    """구조화된 판례 리스트를 프롬프트용 텍스트로 변환"""
    if not precedents:
        return ""

    lines = []
    for p in precedents:
        line = f"[{p['court']} {p['date']} {p['case_no']}] {p['case_name']}"
        if p.get("summary"):
            line += f"\n  판시사항: {p['summary']}"
        if p.get("holding"):
            line += f"\n  판결요지: {p['holding']}"
        lines.append(line)

    return "\n".join(lines)


async def get_law_articles(law_id: str, keywords: list = None) -> tuple:
    """법령 ID로 실제 조문 전문 조회.

    법령 하나가 수백 개 조문을 가질 수 있어 전부 반환할 수 없으므로,
    keywords가 주어지면 조문 내용에 키워드가 포함된 조문을 우선 반환하고
    (예: "음주운전 처벌" → 제44조·제148조의2 등 실제 관련 조문),
    일치하는 조문이 없으면 총칙 등 앞부분 조문으로 개요를 제공한다.

    Returns: (articles, matched) — matched는 keywords와 실제로 일치하는
    조문을 찾았는지 여부. False면 총칙 개요로 대체된 것이므로, 호출자는
    다른 후보(행정규칙 등)를 추가로 시도할지 판단할 수 있다.
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
                return [], False

            parsed = []
            for article in articles:
                if not isinstance(article, dict):
                    continue
                # '전문'(장·절 제목) 단위는 조문 내용이 없으므로 제외
                if article.get("조문여부", "조문") != "조문":
                    continue
                jo_num = article.get("조문번호", "")
                text   = _article_full_text(article)
                if jo_num and text and not _DELETED_ARTICLE.match(text):
                    parsed.append({"article_no": jo_num, "text": text})

            return _select_articles(parsed, keywords)

    except Exception:
        return [], False


async def search_admrul(query: str) -> list:
    """법제처 행정규칙(훈령·예규·고시) 검색.

    "계약예규 공동계약운용요령"처럼 법률/시행령/시행규칙이 아니라
    행정규칙으로 분류되는 문서는 target=law로는 절대 찾을 수 없고
    target=admrul로 검색해야 한다."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            params = {
                "OC": _get_api_key(),
                "target": "admrul",
                "type": "JSON",
                "query": query,
                # 제목 일치도로 거를 것이므로 후보를 넉넉히 받는다
                "display": 5,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
            resp.raise_for_status()
            data = resp.json()
            return _as_list(data.get("AdmRulSearch", {}).get("admrul"))
    except Exception:
        return []


async def get_admrul_articles(serial_no: str, keywords: list = None) -> tuple:
    """행정규칙일련번호로 조문 전문 조회.

    행정규칙 API는 법령 API와 응답 구조가 달라 "조문내용"이
    {"조문번호","조문내용"} 딕셔너리가 아니라 "제1조(목적) ..." 형태의
    평문 문자열 리스트로 온다. Returns: (articles, matched)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            params = {
                "OC": _get_api_key(),
                "target": "admrul",
                "type": "JSON",
                "ID": serial_no,
            }
            resp = await client.get(f"{LAW_API_BASE}/lawService.do", params=params)
            resp.raise_for_status()
            data = resp.json()

            raw_articles = _as_list(data.get("AdmRulService", {}).get("조문내용"))

            parsed = []
            for text in raw_articles:
                if not isinstance(text, str) or not text.strip():
                    continue
                m = re.match(r"제(\d+)조", text)
                parsed.append({"article_no": m.group(1) if m else "", "text": text.strip()})

            return _select_articles(parsed, keywords)

    except Exception:
        return [], False


async def _search_and_fetch_admrul(law_query: str, keywords: list) -> tuple:
    """Returns: (legal_basis, matched) — matched는 키워드와 실제 일치하는
    조문을 찾았는지 여부."""
    rules = await search_admrul(law_query)
    # 검색어와 제목이 충분히 겹치는 것만 남기고, 일치도 높은 순으로 상위 2개
    scored = [(_title_coverage(law_query, r.get("행정규칙명", "")), r) for r in rules]
    rules = [r for c, r in sorted(scored, key=lambda x: -x[0])
             if c >= _ADMRUL_MIN_COVERAGE]
    if not rules:
        return [], False

    legal_basis = []
    matched_any = False
    for rule in rules[:2]:
        serial_no = rule.get("행정규칙일련번호", "")
        rule_name = rule.get("행정규칙명", "")
        date      = rule.get("시행일자", "")
        if not serial_no:
            continue
        articles, matched = await get_admrul_articles(serial_no, keywords)
        if matched:
            matched_any = True
        for article in articles:
            legal_basis.append({
                "law_name": rule_name,
                "date": date,
                "article_no": article["article_no"],
                "text": article["text"],
            })

    return legal_basis, matched_any


async def search_and_fetch_law(query: str, concept_text: str = None,
                               body_terms: list = None) -> list:
    """검색 → 상위 법령의 실제 조문까지 조회 (구조화된 리스트로 반환)

    반환 항목: {"law_name", "date", "article_no", "text"}

    법률/시행령/시행규칙(target=law)과 행정규칙(훈령·예규·고시, target=admrul)을
    모두 시도하고, 질문 키워드와 실제로 일치하는 조문을 찾은 쪽을 우선한다.
    (예: "국가를 당사자로 하는 계약에 관한 법률 시행령"은 law target에서 바로
    찾아지지만 총칙(제1~7조)만 걸리는 반면, "공동계약운용요령"은 admrul target
    에서 실제로 관련된 조문이 걸리는 경우 — 먼저 찾아졌다는 이유만으로 총칙
    개요를 우선시하면 안 된다.)

    `query`는 "어느 법령/문서를 검색할지"를 정하는 좁은 검색어(주로 intent.py가
    뽑은 법령명 하나)이고, `concept_text`는 "그 안에서 어느 조문이 관련 있는지"
    를 가르는 키워드의 원천이다. 이 둘을 분리하지 않고 query 자체에서만
    키워드를 뽑으면(예: query가 이미 법령명 그 자체라 뺄 게 없음), 질문자가
    실제로 의도한 핵심 내용("탈퇴", "동의" 등)이 조문 선별에 전혀 반영되지
    않고 매번 총칙 개요만 나오게 된다. concept_text가 없으면 query로 대체한다.
    """
    try:
        law_query = _extract_law_query(query)
        keywords  = _extract_keywords(concept_text or query, law_query)
        # intent.py가 일상어를 조문 본문에 실제 쓰이는 법령 용어로 바꾼 것
        # (예: 음주운전 → 술에 취한 상태). 글자 매칭의 동의어 한계를 보완한다.
        for term in body_terms or []:
            if term not in keywords:
                keywords.append(term)

        # 1단계: 법령 검색 (후보 목록이 커서 동시 요청 시 간헐적으로 실패하므로 1회 재시도)
        params = {
            "OC": _get_api_key(),
            "target": "law",
            "type": "JSON",
            "query": law_query,
            "display": _LAW_SEARCH_DISPLAY,
        }
        data = {}
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=12.0) as client:
                    resp = await client.get(f"{LAW_API_BASE}/lawSearch.do", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                break
            except Exception:
                if attempt == 1:
                    raise
        laws = _rank_law_candidates(
            law_query, _as_list(data.get("LawSearch", {}).get("law")))

        law_basis, law_matched = [], False
        if laws:
            # 2단계: 고른 법령(최대 2개)의 조문 전문 조회 (키워드와 관련된 조문 우선)
            for law in laws:
                law_id   = law.get("법령ID", "")
                law_name = law.get("법령명한글", "")
                date     = law.get("시행일자", "")
                if not law_id:
                    continue
                articles, matched = await get_law_articles(law_id, keywords)
                if matched:
                    law_matched = True
                for article in articles:
                    law_basis.append({
                        "law_name": law_name,
                        "date": date,
                        "article_no": article["article_no"],
                        "text": article["text"],
                    })

        if law_matched:
            return law_basis

        # 법령에서 키워드 매칭 조문을 못 찾았으면 행정규칙(훈령·예규·고시)도 시도
        admrul_basis, admrul_matched = await _search_and_fetch_admrul(law_query, keywords)
        if admrul_matched or (admrul_basis and not law_basis):
            return admrul_basis

        # 어느 쪽도 키워드 매칭은 없지만 개요라도 있으면 법령 쪽을 우선 반환
        return law_basis or admrul_basis

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