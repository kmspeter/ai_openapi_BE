# AGENTS.md
### AI Backend Agent — Multi-Model Playground Gateway

---

## 1️⃣ 역할(Role)

- **에이전트 목적**  
  여러 AI 프로바이더(OpenAI / Anthropic Claude / Google Gemini)의 모델을 **하나의 API 게이트웨이**로 통합한다.  
  프론트엔드는 단일 `/api/chat/completions` 엔드포인트만 호출하며, 백엔드 에이전트가 내부적으로 모델별 라우팅, 토큰·비용 계산, 사용량 집계까지 처리한다.

- **핵심 기능**
  1. 모델 선택 자동화 (provider 구분)
  2. 토큰 사용량 추적 (세션·일·월 단위)
  3. 비용 계산 및 DB 기록
  4. 키 관리 및 보안 처리
  5. 표준화된 응답 반환

---

## 2️⃣ 환경(Environment)

| 항목 | 값 |
|------|----|
| OS | Windows 11 |
| 언어 | Python 3.13 |
| 실행 | FastAPI + uvicorn + ngrok |
| IDE | VS Code |
| DB | SQLite (aiosqlite + SQLAlchemy) |

---

## 3️⃣ 입력/출력 규약 (I/O Contract)

### ✅ 입력 (POST `/api/chat/completions`)

```json
{
  "model": "gpt-4-turbo-preview",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain quantum computing simply."}
  ],
  "temperature": 0.7,
  "max_tokens": 512,
  "stream": false,
  "session_id": "session-1234",
  "user_id": "user-001"
}
```

- **필수:** `model`, `messages`
- **옵션:** `temperature`, `max_tokens`, `stream`, `session_id`, `user_id`
- **유효성 규칙**
  - `model`은 `data/models_config.json`에 존재해야 함
  - `max_tokens`는 모델의 최대치 이하
  - `messages`는 최소 하나 이상의 `user` 메시지 포함

---

### ✅ 출력

```json
{
  "id": "chatcmpl-abc123",
  "model": "gpt-4-turbo-preview",
  "provider": "openai",
  "content": "Quantum computing uses qubits instead of bits...",
  "usage": {
    "prompt_tokens": 150,
    "completion_tokens": 220,
    "total_tokens": 370
  },
  "cost": {
    "input_cost": 0.0015,
    "output_cost": 0.0066,
    "total_cost": 0.0081,
    "currency": "USD"
  },
  "created_at": "2025-10-09T12:34:56Z"
}
```

- **응답 성공 시:** 200 OK  
- **에러 시:**
  | 코드 | 사유 |
  |------|------|
  | 400 | 잘못된 요청 파라미터 |
  | 401 | API 키 오류 |
  | 404 | 미지원 모델 |
  | 429 | Rate Limit 초과 |
  | 500 | 내부 API 실패 |

---

## 4️⃣ 의사결정 규칙 (Decision Logic)

1. **모델 판별**
   - `models_config.json`에서 `model_id`로 검색 → `provider` 결정
2. **서비스 선택**
   - `openai` → `openai_service.chat_completion`
   - `anthropic` → `anthropic_service.chat_completion`
   - `google` → `gemini_service.chat_completion`
3. **비용 계산**
   - `cost_calculator.calculate_cost(model_id, prompt_tokens, completion_tokens)`
4. **사용량 기록**
   - `usage_tracker.track_usage(session_id, user_id, model_id, provider, prompt_tokens, completion_tokens, total_cost)`
5. **응답 조립 및 반환**

---

## 5️⃣ 보안 및 정책 (Security Policy)

| 항목 | 정책 |
|------|------|
| **API 키 노출** | 절대 프론트엔드로 전달 금지 |
| **.env 관리** | Git에 포함 금지 (`.gitignore`) |
| **CORS 허용** | `ALLOWED_ORIGINS` 내 도메인만 |
| **로그 내용** | 요청 ID, 모델, 토큰 수만 기록 — Prompt 내용은 저장 금지 |
| **에러 메시지** | 내부 세부 정보 노출 금지, 표준화된 코드 반환 |
| **DB 접근** | 비동기 세션, 커넥션 풀링 최소화 |

---

## 6️⃣ 토큰 및 비용 계산 규약

**공식**
```python
input_cost = (prompt_tokens / 1000) * pricing["input"]
output_cost = (completion_tokens / 1000) * pricing["output"]
total_cost = input_cost + output_cost
```

- 기준: USD per 1K tokens
- 소수점 6자리 이하 반올림
- 비용 단위: `USD`

---

## 7️⃣ 데이터베이스 규약

| 테이블 | 역할 |
|---------|------|
| `session_usage` | 개별 요청 단위 기록 |
| `daily_usage` | 날짜별 집계 |
| `monthly_usage` | 월별 집계 |

**UPSERT 규칙**
- 동일한 `(date, user_id, model_id)` 조합 존재 시 `total_tokens`, `total_cost`, `request_count` 증가
- `session_usage`는 항상 신규 삽입

---

## 8️⃣ 에러 처리 매뉴얼

| 상황 | 감지 방법 | 대응 | 반환 코드 |
|------|------------|-------|------------|
| 모델 미지원 | 모델 ID 조회 실패 | 404 + "Unsupported model" | 404 |
| API 키 오류 | SDK 인증 실패 | "Invalid API key" | 401 |
| RateLimit | SDK RateLimitError | 백오프 후 실패시 429 | 429 |
| 파라미터 불일치 | Pydantic 검증 실패 | 필드명 포함 에러 | 400 |
| SDK 내부 오류 | APIError / HTTPError | "Provider API failure" | 500 |

---

## 9️⃣ 관찰 가능성 (Observability)

- **로그 수준:**  
  - `INFO`: 호출 결과, 사용량  
  - `DEBUG`: 개발 모드에서만 요청/응답 전문  
  - `ERROR`: 예외 스택  
- **헬스체크:** `GET /health` → DB 연결 + API 키 존재 확인  
- **지표 추천:** 요청 수, 평균 응답 시간, 성공률, 프로바이더별 토큰 합계

---

## 🔟 테스트 시나리오

| 테스트 | 입력 | 기대 결과 |
|---------|-------|------------|
| OpenAI 호출 | `gpt-4-turbo-preview` | 응답 + usage 기록 |
| Claude 호출 | `claude-3-sonnet-20240229` | system 분리 처리됨 |
| Gemini 호출 | `gemini-pro` | 메시지 변환 정상 |
| 미지원 모델 | `gpt-unknown` | 404 반환 |
| 키 오류 | .env 잘못된 키 | 401 반환 |
| 사용량 조회 | `/api/usage/session/{id}` | 누적 토큰 및 비용 확인 |

---

## 11️⃣ SLA 및 한계

- 평균 응답 시간: 5초 이하  
- 최대 입력 토큰: 모델 context의 85% 이하  
- 데이터베이스 용량 초과 시 자동 로테이션 예정  
- 스트리밍 응답은 MVP 이후 단계 지원 예정

---

## 12️⃣ 운영 지침 요약 (Agent Checklist)

- [ ] 서버 실행 시 `init_db()` 자동 호출  
- [ ] `.env` 키 모두 유효  
- [ ] `/api/chat/completions` 응답 정상  
- [ ] `usage.db` 자동 생성 및 갱신  
- [ ] `/api/usage/*` 조회 정상  
- [ ] 비용 계산 정확 (`input + output = total`)  
- [ ] CORS 오류 없음  
- [ ] API 키 외부 노출 없음  

---

## 13️⃣ 변경 관리 (Versioning)

| 항목 | 변경 시점 | 조치 |
|------|------------|------|
| 모델 가격 | 공급자 변경 시 | `models_config.json` 갱신 |
| DB 스키마 | 구조 수정 시 | 새 버전으로 마이그레이션 (`alembic` 고려) |
| 서비스 SDK 버전 | 주기적 점검 | `requirements.txt` 업데이트 |

---

## 14️⃣ 요약

이 에이전트는 **3개 AI 프로바이더를 단일 백엔드 인터페이스로 통합**하여  
토큰·비용 추적, 보안 관리, 통계 집계를 자동화한다.  
모든 의사결정은 `models_config.json`을 기준으로 수행되며,  
응답 구조와 에러 규약은 완전히 표준화되어 있다.  