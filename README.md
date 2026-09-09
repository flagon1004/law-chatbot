# 법령 AI 챗봇 (law-chatbot)

법제처 Open API와 연동하여 실제 법령 원문·판례를 근거로 답변하는 대한민국 법률 AI 챗봇입니다.
FastAPI + Vanilla JS(빌드 없음)로 구성되어 있으며, [Render](https://render.com)에 무료 배포되어 있습니다.

## 주요 기능

- **법제처 Open API 실시간 연동**
  - 법률·시행령·시행규칙(`target=law`)뿐 아니라 훈령·예규·고시 같은 행정규칙(`target=admrul`)까지 조회
  - 판례 검색(`target=prec`)
  - 질문에서 법령명을 추출해 검색하고, 원본 질문의 핵심 단어로 관련 조문을 우선 선별
- **"법적 근거 원문" ↔ "AI 해석" 분리 표시**
  - 법제처에서 가져온 조문·판례 원문은 AI를 거치지 않고 그대로 화면에 표시
  - AI는 원문을 베끼지 않고 해석·요약만 작성 → 원문 왜곡 위험 차단
- **인용 조문 자동 검증**
  - AI 답변에 등장하는 "제O조" 번호를 실제 조회된 원문과 대조
  - 불일치하거나, 애초에 법제처 데이터 없이 AI 지식만으로 생성된 경우 경고 문구 자동 표시
- **AI 모델 선택 (NVIDIA Nemotron / Gemini)**
  - 기본값은 NVIDIA Nemotron Ultra (무료·공개)
  - Gemini는 관리자 비밀번호 인증 시에만 사용 가능 (서버 측에서 매 요청마다 재검증)
- **마크다운 렌더링**
  - AI 해석 답변을 `marked.js` + `DOMPurify`로 렌더링해 제목·굵게·표·인용 등이 실제 서식으로 표시
- **대화 세션 관리**
  - 대화 내용은 브라우저 `localStorage`에 저장, 세션 생성/삭제 지원
- **모바일 반응형 UI**

## 기술 스택

| 구분 | 사용 기술 |
|---|---|
| 백엔드 | FastAPI, httpx (비동기), Uvicorn |
| AI 모델 | NVIDIA Nemotron Ultra (OpenAI 호환 API), Google Gemini |
| 데이터 소스 | 법제처 Open API (law.go.kr) |
| 프론트엔드 | HTML / CSS / Vanilla JS (빌드 없음) |
| 배포 | Render (Blueprint, `render.yaml`) |

## 프로젝트 구조

```
app/
├── main.py                 # FastAPI 엔트리포인트
├── routers/
│   └── chat.py              # /api/chat, /api/admin/verify
├── services/
│   ├── gemini.py            # Gemini 호출
│   ├── nvidia.py            # NVIDIA Nemotron 호출
│   ├── intent.py            # 질문에서 검색 키워드 추출
│   ├── law_api.py           # 법제처 Open API 연동 (법령/행정규칙/판례)
│   └── verifier.py          # 인용 조문 교차 검증
└── static/
    ├── index.html
    ├── app.js
    └── style.css
render.yaml                  # Render 배포 설정
requirements.txt
```

## 로컬 실행

### 1. 사전 준비

- Python 3.12
- API 키 발급
  - Google Gemini: https://aistudio.google.com/app/apikey
  - 법제처 Open API: https://www.data.go.kr (공공데이터포털 → "법제처 오픈API" 활용신청)
  - NVIDIA: https://build.nvidia.com

### 2. 환경 설정

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

프로젝트 루트에 `.env` 파일 생성:

```env
GEMINI_API_KEY=발급받은_키
LAW_API_KEY=발급받은_키
NVIDIA_API_KEY=발급받은_키

# Gemini 모델 접근 제한용 (비워두면 제한 없음 — 배포 시 반드시 설정)
ADMIN_PASSWORD=원하는_비밀번호
```

`.env`는 `.gitignore`에 포함되어 Git에 올라가지 않습니다.

### 3. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

브라우저에서 `http://localhost:8000` 접속.

## 배포 (Render)

이 저장소에는 `render.yaml`이 포함되어 있어 Render의 **Blueprint** 기능으로 바로 배포할 수 있습니다.

1. Render 대시보드 → **New +** → **Blueprint** → 이 저장소 선택
2. 환경변수(`GEMINI_API_KEY`, `LAW_API_KEY`, `NVIDIA_API_KEY`, `ADMIN_PASSWORD`) 입력
3. Deploy

무료 티어는 일정 시간 무활동 시 슬립되며, 다음 요청 시 재기동에 시간이 걸릴 수 있습니다.

## 주의사항

- AI 답변은 참고용이며 법적 효력이 없습니다. 실제 법률 문제는 반드시 전문가(변호사 등)와 상담하시기 바랍니다.
- 법제처 API에서 조문을 찾지 못한 질문은 AI 자체 지식으로 답변하며, 이 경우 화면에 검증되지 않았다는 경고가 표시됩니다.
