# AI Backend 개발 프로젝트 - 에이전트 지시서

## 프로젝트 개요

**목적**: AI 플레이그라운드 백엔드 개발 (OpenAI, Anthropic Claude, Google Gemini API 통합)

**환경**: 
- Windows 11
- Python 3.13
- VS Code
- FastAPI + ngrok

**목표**: 
- 프론트엔드에서 여러 AI 모델을 하나의 API로 사용
- 토큰 사용량 실시간 추적 (세션별/일일/월별/모델별)
- 비용 자동 계산
- API 키는 백엔드에서 관리 (프론트엔드 노출 X)

**MVP 개발**: 빠른 프로토타입

---

## 프로젝트 구조

```
ai_openapi_BE/
│
├── main.py                      # FastAPI 앱 + 라우터 등록
├── requirements.txt             # 패키지 목록
├── .env.example                 # 실행을 위한 환경 변수 템플릿
├── .env                         # API 키 (Git 제외)
├── .gitignore                   # Git 제외 파일
│
├── config.py                    # 설정 관리
├── database.py                  # SQLite 연결 및 모델
│
├── routers/
│   ├── __init__.py
│   ├── chat.py                  # POST /api/chat/completions
│   └── usage.py                 # GET /api/usage/*
│
├── services/
│   ├── __init__.py
│   ├── openai_service.py        # OpenAI 통합
│   ├── anthropic_service.py     # Claude 통합
│   ├── gemini_service.py        # Gemini 통합
│   ├── usage_tracker.py         # 사용량 추적
│   └── cost_calculator.py       # 비용 계산
│
├── models/
│   ├── __init__.py
│   └── schemas.py               # Pydantic 모델
│
├── utils/
│   ├── __init__.py
│   └── token_counter.py         # 토큰 카운팅
│
└── data/
    ├── usage.db                 # SQLite DB (자동 생성)
    └── models_config.json       # 모델 정보/가격
```

---

## 요구사항 및 구현 상세 (예시 변경 가능)

### 1. `requirements.txt`

```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
python-dotenv==1.0.0
sqlalchemy==2.0.23
aiosqlite==0.19.0
pydantic==2.5.0

openai==1.3.0
anthropic==0.7.0
google-generativeai==0.3.0

tiktoken==0.5.1
httpx==0.25.0
```

---

### 2. `.env` (예시)

```env
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...

DATABASE_URL=sqlite:///./data/usage.db
ALLOWED_ORIGINS=https://ai-modelhub-platform.vercel.app,http://localhost:5173

PORT=8000
DEBUG=True
```

> ℹ️ **TIP**: 저장소에는 비밀값이 제거된 `.env.example` 파일이 포함되어 있습니다. 이 파일을 복사해 `.env`로 이름을 변경한 뒤 각 API 키와 설정 값을 채워 넣으면 됩니다.

---

### 3. `.gitignore`

```
.env
__pycache__/
*.pyc
*.db
data/usage.db
venv/
.vscode/
```

---

### 4. `config.py`

**요구사항:**
- Pydantic BaseSettings 사용
- .env 파일 자동 로드
- 환경변수 타입 정의
- 기본값 설정

**필수 설정값:**
- OPENAI_API_KEY: str
- ANTHROPIC_API_KEY: str
- GOOGLE_API_KEY: str
- DATABASE_URL: str
- ALLOWED_ORIGINS: str (쉼표로 구분)
- PORT: int = 8000
- DEBUG: bool = False

---

### 5. `database.py`

**요구사항:**
- SQLAlchemy + aiosqlite 사용
- 비동기 세션 관리

**테이블 3개:**

#### 5.1. `session_usage` (세션별 요청 기록)
```sql
- id: INTEGER PRIMARY KEY
- session_id: TEXT NOT NULL
- user_id: TEXT (nullable)
- model_id: TEXT NOT NULL
- provider: TEXT NOT NULL (openai/anthropic/google)
- prompt_tokens: INTEGER NOT NULL
- completion_tokens: INTEGER NOT NULL
- total_tokens: INTEGER NOT NULL
- cost: REAL NOT NULL
- created_at: TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

#### 5.2. `daily_usage` (일일 집계)
```sql
- id: INTEGER PRIMARY KEY
- date: DATE NOT NULL
- user_id: TEXT (nullable)
- model_id: TEXT NOT NULL
- provider: TEXT NOT NULL
- total_tokens: INTEGER NOT NULL
- total_cost: REAL NOT NULL
- request_count: INTEGER NOT NULL
- UNIQUE(date, user_id, model_id)
```

#### 5.3. `monthly_usage` (월별 집계)
```sql
- id: INTEGER PRIMARY KEY
- year_month: TEXT NOT NULL (예: '2025-10')
- user_id: TEXT (nullable)
- model_id: TEXT NOT NULL
- provider: TEXT NOT NULL
- total_tokens: INTEGER NOT NULL
- total_cost: REAL NOT NULL
- request_count: INTEGER NOT NULL
- UNIQUE(year_month, user_id, model_id)
```

**필수 함수:**
- `init_db()`: 테이블 생성
- `get_session()`: DB 세션 반환 (async context manager)

---

### 6. `models/schemas.py`

**Pydantic 모델 정의:**

#### 6.1. Request 모델
- Message: role(str), content(str)
- ChatRequest: model, messages, temperature, max_tokens, stream, session_id, user_id

#### 6.2. Response 모델
- UsageInfo: prompt_tokens, completion_tokens, total_tokens
- CostInfo: input_cost, output_cost, total_cost, currency
- ChatResponse: id, model, provider, content, usage, cost, created_at

#### 6.3. Usage 모델
- ModelUsage: model_id, provider, total_tokens, total_cost, request_count
- SessionUsageResponse: session_id, requests, total_tokens, total_cost
- DailyUsageResponse: date, by_model, total_tokens, total_cost
- MonthlyUsageResponse: year_month, by_model, total_tokens, total_cost

---

### 7. `data/models_config.json`

**모델 정보 및 가격표:**

```json
{
  "gpt-4-turbo-preview": {
    "name": "GPT-4 Turbo",
    "provider": "openai",
    "context_window": 128000,
    "max_output_tokens": 4096,
    "pricing": {
      "input": 0.01,
      "output": 0.03
    }
  },
  "gpt-4": {
    "name": "GPT-4",
    "provider": "openai",
    "context_window": 8192,
    "max_output_tokens": 4096,
    "pricing": {
      "input": 0.03,
      "output": 0.06
    }
  },
  "gpt-3.5-turbo": {
    "name": "GPT-3.5 Turbo",
    "provider": "openai",
    "context_window": 16385,
    "max_output_tokens": 4096,
    "pricing": {
      "input": 0.0005,
      "output": 0.0015
    }
  },
  "claude-3-opus-20240229": {
    "name": "Claude 3 Opus",
    "provider": "anthropic",
    "context_window": 200000,
    "max_output_tokens": 4096,
    "pricing": {
      "input": 0.015,
      "output": 0.075
    }
  },
  "claude-3-sonnet-20240229": {
    "name": "Claude 3 Sonnet",
    "provider": "anthropic",
    "context_window": 200000,
    "max_output_tokens": 4096,
    "pricing": {
      "input": 0.003,
      "output": 0.015
    }
  },
  "gemini-pro": {
    "name": "Gemini Pro",
    "provider": "google",
    "context_window": 32000,
    "max_output_tokens": 2048,
    "pricing": {
      "input": 0.00025,
      "output": 0.0005
    }
  }
}
```

**참고**: 가격은 USD per 1K tokens 기준

---

### 8. `services/cost_calculator.py`

**요구사항:**
- models_config.json 로드
- 토큰 수로 비용 계산

**주요 함수:**
- `load_models_config()`: models_config.json 로드
- `calculate_cost(model_id, prompt_tokens, completion_tokens)`: 비용 계산 후 (input_cost, output_cost, total_cost) 반환

**계산 공식:**
- input_cost = (prompt_tokens / 1000) * pricing.input
- output_cost = (completion_tokens / 1000) * pricing.output
- total_cost = input_cost + output_cost

---

### 9. `services/openai_service.py`

**요구사항:**
- OpenAI Python SDK 사용
- 비동기 처리 (async/await)
- 에러 처리

**주요 함수:**
- `async chat_completion(model, messages, temperature, max_tokens)`
- 반환값: (response_text, prompt_tokens, completion_tokens)

**처리할 에러:**
- AuthenticationError: API 키 오류
- RateLimitError: Rate limit 초과
- APIError: 기타 API 오류

---

### 10. `services/anthropic_service.py`

**요구사항:**
- Anthropic Python SDK 사용
- OpenAI와 동일한 인터페이스

**주요 함수:**
- `async chat_completion(model, messages, temperature, max_tokens)`
- 반환값: (response_text, prompt_tokens, completion_tokens)

**특이사항:**
- Claude는 system 메시지를 별도 파라미터로 전달
- messages에서 role='system' 제거 필요

---

### 11. `services/gemini_service.py`

**요구사항:**
- google-generativeai SDK 사용
- OpenAI와 동일한 인터페이스

**주요 함수:**
- `async chat_completion(model, messages, temperature, max_tokens)`
- 반환값: (response_text, prompt_tokens, completion_tokens)

**특이사항:**
- Gemini는 메시지 포맷이 다름
- count_tokens() 메서드로 토큰 수 확인

---

### 12. `services/usage_tracker.py`

**요구사항:**
- DB에 사용량 저장
- 세션/일일/월별 집계 업데이트

**주요 함수:**
- `async track_usage(session_id, user_id, model_id, provider, prompt_tokens, completion_tokens, cost)`

**동작:**
1. session_usage 테이블에 INSERT
2. daily_usage 테이블 UPSERT (오늘 날짜로 집계)
   - total_tokens += ...
   - total_cost += ...
   - request_count += 1
3. monthly_usage 테이블 UPSERT (이번 달로 집계)

---

### 13. `utils/token_counter.py`

**요구사항:**
- tiktoken 사용 (OpenAI 토큰라이저)
- 실제 API 호출 전 토큰 수 예측용

**주요 함수:**
- `count_tokens(text, model="gpt-4")`: 텍스트의 토큰 수 계산

**참고:**
- Claude, Gemini는 정확하지 않을 수 있음 (근사값)

---

### 14. `routers/chat.py`

**엔드포인트:** `POST /api/chat/completions`

**요구사항:**
- ChatRequest 검증
- 모델별 프로바이더 자동 선택
- 해당 서비스 호출
- 사용량 추적
- 비용 계산
- 응답 반환

**처리 흐름:**
1. models_config.json에서 모델 정보 로드
2. provider 판별 (openai/anthropic/google)
3. 해당 서비스의 chat_completion() 호출
4. cost_calculator.calculate_cost() 호출
5. usage_tracker.track_usage() 호출
6. ChatResponse 반환

**에러 처리:**
- 지원하지 않는 모델 → 404
- API 호출 실패 → 500
- 잘못된 파라미터 → 400

---

### 15. `routers/usage.py`

**엔드포인트:**
- `GET /api/usage/session/{session_id}`: 세션 사용량
- `GET /api/usage/daily`: 오늘 사용량
- `GET /api/usage/daily/{date}`: 특정 날짜 (YYYY-MM-DD)
- `GET /api/usage/monthly`: 이번 달 사용량
- `GET /api/usage/monthly/{year_month}`: 특정 월 (YYYY-MM)

**요구사항:**
- DB 조회
- 모델별로 그룹화
- 응답 스키마 준수

**각 엔드포인트 동작:**
- `/session/{session_id}`: session_usage 테이블 조회
- `/daily`: daily_usage 테이블 조회 (date 없으면 오늘)
- `/monthly`: monthly_usage 테이블 조회 (year_month 없으면 이번 달)

---

### 16. `main.py`

**요구사항:**
- FastAPI 앱 생성
- CORS 설정
- 라우터 등록
- 시작 이벤트에서 DB 초기화

**주요 구성:**
- FastAPI 앱 인스턴스 (title, version, description 포함)
- CORS 미들웨어 (ALLOWED_ORIGINS 설정)
- 라우터 등록: chat.router (/api/chat), usage.router (/api/usage)
- @app.on_event("startup"): DB 초기화 (init_db() 호출)
- /health 엔드포인트: 헬스체크
- uvicorn.run(): 서버 실행

---

## 체크리스트

개발 완료 후 다음 항목을 확인하세요:

### 기본 동작
- [ ] `python main.py` 실행 시 서버 시작
- [ ] http://localhost:8000/docs 접속 가능
- [ ] http://localhost:8000/health 응답 확인

### API 테스트
- [ ] POST /api/chat/completions (OpenAI 모델)
- [ ] POST /api/chat/completions (Claude 모델)
- [ ] POST /api/chat/completions (Gemini 모델)
- [ ] GET /api/usage/session/{session_id}
- [ ] GET /api/usage/daily
- [ ] GET /api/usage/monthly

### 데이터베이스
- [ ] data/usage.db 파일 자동 생성
- [ ] session_usage 테이블 데이터 저장 확인
- [ ] daily_usage 집계 확인
- [ ] monthly_usage 집계 확인

### 비용 계산
- [ ] 각 모델별 비용 정확히 계산
- [ ] input_cost + output_cost = total_cost

### 에러 처리
- [ ] 잘못된 모델 ID → 에러 응답
- [ ] API 키 오류 → 에러 응답
- [ ] 필수 필드 누락 → 검증 에러

---

## 실행 가이드

### 1. 개발 환경 설정
- Python 가상환경 생성 및 활성화
- requirements.txt로 패키지 설치

### 2. .env 파일 생성
- 실제 API 키 입력 필요
- 외부 공개가 필요하면 `ENABLE_NGROK=true` 설정 (선택)
- ngrok 인증 토큰이 있다면 `NGROK_AUTHTOKEN=...` 로 추가 (선택)
- 특정 리전을 사용하려면 `NGROK_REGION=ap` 과 같이 지정 (선택)

### 3. 서버 실행
- `python main.py` 실행

### 4. API 테스트
- FastAPI 자동 문서: http://localhost:8000/docs
- 헬스체크: http://localhost:8000/health

### 5. ngrok으로 외부 접속
- `.env`에 `ENABLE_NGROK=true`를 설정하고 `python main.py` 실행
- 콘솔에 출력되는 ngrok URL을 프론트엔드에서 사용
- 수동으로 실행하려면 기존 방식대로 `ngrok http 8000`을 별도 터미널에서 실행해도 됨

---

## 중요 참고사항

1. **API 키 보안**: .env 파일은 절대 Git에 업로드하지 말 것
2. **비동기 처리**: 모든 DB 작업과 API 호출은 async/await 사용
3. **에러 처리**: 각 서비스에서 try-except로 에러 핸들링
4. **토큰 계산**: tiktoken은 OpenAI 기준이므로 Claude/Gemini는 근사값
5. **DB 집계**: UPSERT 로직으로 중복 방지 (daily/monthly)
6. **CORS**: 프론트엔드 URL을 ALLOWED_ORIGINS에 정확히 입력

---

## 개발 완료 기준

- 모든 파일 생성 완료
- 서버 정상 실행
- 3개 프로바이더 모두 작동
- 사용량 추적 및 조회 기능 정상 작동
- FastAPI 자동 문서 확인 가능
- 에러 처리 구현 완료