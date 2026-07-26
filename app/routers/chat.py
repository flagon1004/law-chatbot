import hmac
import os
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Optional
import asyncio
from app.services.intent import extract_search_keywords
from app.services.gemini import ask_gemini
from app.services.nvidia import ask_nvidia
from app.services.law_api import (
    search_and_fetch_law, search_precedent,
    format_legal_basis, format_precedents,
)
from app.services.verifier import verify_citations

router = APIRouter()

MODEL_PROVIDERS = {
    "gemini": ask_gemini,
    "nvidia": ask_nvidia,
}

ADMIN_ONLY_MODELS = {"gemini"}


def _check_admin_password(password: Optional[str]) -> bool:
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    if not admin_password:
        # 관리자 비밀번호가 설정되지 않은 환경(로컬 개발 등)에서는 제한하지 않음
        return True
    if not password:
        return False
    return hmac.compare_digest(password, admin_password)

SYSTEM_PROMPT = """당신은 대한민국 법령 전문 AI 어시스턴트입니다.

[답변 원칙]
1. 법령 조문 인용 시 반드시 법령명과 조문 번호를 명시하세요.
2. 판례는 반드시 아래 [법제처 실제 판례] 섹션에 제공된 것만 인용하세요.
3. 제공된 판례가 없으면 "관련 판례를 찾지 못했습니다"라고 명시하세요.
4. 판례번호, 선고일자, 법원명을 절대 임의로 생성하지 마세요.
5. 모르는 내용은 추측하지 말고 법령 확인을 권고하세요.
6. [법제처 법령 데이터]에 제공된 조문 원문은 화면에 별도로 표시되므로, 답변에 원문을 그대로 옮겨 적지 마세요.
   대신 "제O조에 따르면 ~하다"처럼 조문 번호를 근거로 그 의미와 적용 결과를 해설·요약하세요."""

class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: List[Message] = []
    model: str = "nvidia"
    admin_password: Optional[str] = None


class LegalBasisItem(BaseModel):
    law_name: str
    date: str
    article_no: str
    text: str


class PrecedentItem(BaseModel):
    court: str
    date: str
    case_no: str
    case_name: str
    summary: str = ""


class ChatResponse(BaseModel):
    reply: str
    law_context_used: bool = False
    denied: bool = False
    legal_basis: List[LegalBasisItem] = []
    precedents: List[PrecedentItem] = []


class AdminVerifyRequest(BaseModel):
    password: str


class AdminVerifyResponse(BaseModel):
    ok: bool


def build_prompt(message: str, history: List[Message],
                 law_context: str, prec_context: str) -> str:
    parts = [SYSTEM_PROMPT]

    for h in history[-6:]:
        role = "사용자" if h.role == "user" else "어시스턴트"
        parts.append(f"\n{role}: {h.content}")

    if law_context:
        parts.append(f"\n\n[법제처 법령 데이터]\n{law_context}")

    if prec_context:
        parts.append(f"\n\n[법제처 실제 판례 — 아래 판례만 인용할 것]\n{prec_context}")

    parts.append(f"\n\n사용자: {message}\n어시스턴트:")
    return "".join(parts)


@router.post("/admin/verify", response_model=AdminVerifyResponse)
async def admin_verify(req: AdminVerifyRequest):
    return AdminVerifyResponse(ok=_check_admin_password(req.password))


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    if req.model in ADMIN_ONLY_MODELS and not _check_admin_password(req.admin_password):
        return ChatResponse(
            reply="🔒 이 모델은 관리자 전용입니다. 관리자 비밀번호를 확인해 주세요.",
            law_context_used=False,
            denied=True,
        )

    await asyncio.sleep(1)
    # [신규] 의도 파악 및 검색 키워드 정제
    search_query = await extract_search_keywords(req.message)
    
    # 법령 키워드 유무와 무관하게 항상 조회를 시도한다.
    # (민법/상법 관련 질문 등은 "법", "조" 같은 키워드 없이도 들어올 수 있고,
    #  검색 실패 시 빈 리스트를 반환하므로 항상 시도해도 안전하다.)
   
    # [수정] 원본 req.message 대신 정제된 search_query로 API 검색 시도
    legal_basis, precedents = await asyncio.gather(
        search_and_fetch_law(search_query),
        search_precedent(search_query),
    )
    law_used = bool(legal_basis or precedents)

    prompt = build_prompt(
        req.message, req.history,
        format_legal_basis(legal_basis), format_precedents(precedents),
    )
    ask_model = MODEL_PROVIDERS.get(req.model, ask_gemini)
    reply  = await ask_model(prompt)

    # 인용 검증 — 조문 번호 오류 탐지
    reply = await verify_citations(reply, legal_basis)

    return ChatResponse(
        reply=reply,
        law_context_used=law_used,
        legal_basis=legal_basis,
        precedents=precedents,
    )
