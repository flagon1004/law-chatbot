import re

async def verify_citations(reply: str, legal_basis: list) -> str:
    """
    AI 답변의 조문 번호를 실제 조문 리스트(legal_basis)와 교차 검증.
    조문 리스트에 없는 번호가 인용되면 경고 문구 추가.
    """
    # 답변에서 "제XX조" 패턴 추출
    cited = re.findall(r"제(\d+)조", reply)
    if not cited:
        return reply

    if not legal_basis:
        # 법제처 데이터를 전혀 조회하지 못한 상태에서 조문 번호를 인용한 경우
        # (AI의 사전 지식만으로 생성된 것이므로 반드시 별도 확인이 필요함)
        warning = (
            "\n\n⚠️ **검증 안내**: 이 답변은 법제처 원문 데이터 없이 AI 자체 지식으로 "
            "생성되어 인용된 조문 번호가 전혀 검증되지 않았습니다. "
            "국가법령정보센터(law.go.kr)에서 반드시 직접 확인하세요."
        )
        return reply + warning

    # 실제 조문 리스트에 존재하는 조문 번호 목록
    actual = {str(item["article_no"]) for item in legal_basis}

    # 불일치 조문 탐지
    unverified = [n for n in cited if n not in actual]

    if unverified:
        warning = (
            "\n\n⚠️ **검증 안내**: "
            f"제{'·'.join(set(unverified))}조 번호는 법제처 데이터와 "
            "일치 여부를 확인하지 못했습니다. "
            "국가법령정보센터(law.go.kr)에서 직접 확인하세요."
        )
        return reply + warning

    return reply
