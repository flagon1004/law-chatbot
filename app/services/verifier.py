import re

# "2014다26187", "2023도1234", "63다131" 같은 대법원 사건번호
_CASE_NO = re.compile(r"(?<!\d)(\d{2,4}[가나다라마바사아자차카타파하도두누노오고구합단허재초]{1,3}\d{1,7})(?!\d)")


def _verify_case_numbers(reply: str, precedents: list) -> str:
    """답변이 언급한 사건번호가 실제 조회된 판례에 없으면 경고 문구를 반환."""
    cited = set(_CASE_NO.findall(reply))
    if not cited:
        return ""
    # 하급심 사건번호는 "수원지방법원-2021-가단-540557"처럼 오므로 "2021가단540557"로 정규화
    known = set()
    for p in (precedents or []):
        raw = p.get("case_no", "")
        known.add(raw)
        known.update(_CASE_NO.findall(raw.replace("-", "")))
    unknown = sorted(n for n in cited if not any(n in k for k in known))
    if not unknown:
        return ""
    return (
        "\n\n⚠️ **검증 안내**: 답변에 언급된 판례번호 "
        f"({', '.join(unknown)})는 법제처에서 조회된 판례 목록에 없어 확인되지 않았습니다. "
        "국가법령정보센터(law.go.kr)에서 직접 확인하세요."
    )


async def verify_citations(reply: str, legal_basis: list, precedents: list = None) -> str:
    """
    AI 답변의 조문 번호·판례번호를 실제 조회 결과와 교차 검증.
    조회 결과에 없는 번호가 인용되면 경고 문구 추가.
    """
    case_warning = _verify_case_numbers(reply, precedents)

    # 답변에서 "제XX조" 패턴 추출
    cited = re.findall(r"제(\d+)조", reply)
    if not cited:
        return reply + case_warning

    if not legal_basis:
        # 법제처 데이터를 전혀 조회하지 못한 상태에서 조문 번호를 인용한 경우
        # (AI의 사전 지식만으로 생성된 것이므로 반드시 별도 확인이 필요함)
        warning = (
            "\n\n⚠️ **검증 안내**: 이 답변은 법제처 원문 데이터 없이 AI 자체 지식으로 "
            "생성되어 인용된 조문 번호가 전혀 검증되지 않았습니다. "
            "국가법령정보센터(law.go.kr)에서 반드시 직접 확인하세요."
        )
        return reply + warning + case_warning

    # 실제 조문 리스트에 존재하는 조문 번호 목록
    actual = {str(item["article_no"]) for item in legal_basis}

    # 불일치 조문 탐지
    unverified = [n for n in cited if n not in actual]

    if unverified:
        warning = (
            "\n\n⚠️ **검증 안내**: "
            f"제{'·'.join(sorted(set(unverified)))}조 번호는 법제처 데이터와 "
            "일치 여부를 확인하지 못했습니다. "
            "국가법령정보센터(law.go.kr)에서 직접 확인하세요."
        )
        return reply + warning + case_warning

    return reply + case_warning
