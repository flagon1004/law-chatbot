import re

async def verify_citations(reply: str, legal_basis: list) -> str:
    """
    AI 답변의 조문 번호를 실제 조문 리스트(legal_basis)와 교차 검증.
    조문 리스트에 없는 번호가 인용되면 경고 문구 추가.
    """
    if not legal_basis:
        return reply

    # 답변에서 "제XX조" 패턴 추출
    cited = re.findall(r"제(\d+)조", reply)
    if not cited:
        return reply

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
