# Life Coach Agent

간단한 라이프 코치형 AI agent 실습용 Streamlit 앱입니다.

OpenAI Agents SDK 기반으로 대화 메모리를 유지하고, 필요할 때 웹 검색을 사용해 더 근거 있는 코칭 답변을 제공합니다.

![Life Coach Agent UI](docs/images/실행화면.png)

## 주요 기능

- 채팅 폼으로 대화하기
- `gpt-5-mini` 기반 라이프 코치 페르소나
- OpenAI Agents SDK의 `SQLiteSession`으로 세션 메모리 유지
- `WebSearchTool`을 활용한 코칭 관련 웹 검색
- 웹 검색 사용 시 채팅 화면에 tool 사용 표시
- Streamlit 기반 단일 페이지 UI

## 프로젝트 구조

```text
.
├── docs/images/실행화면.png
├── main.py
├── pyproject.toml
└── uv.lock
```

## 실행

```bash
uv sync
cp .env.example .env
uv run streamlit run main.py
```

## 환경 변수

`.env` 파일에 아래 값을 넣으면 됩니다.

```bash
OPENAI_API_KEY=your-api-key-here
```

## 메모리

대화 메모리는 로컬 파일 `life_coach_memory.db`에 저장됩니다.

## 참고

- 주제가 라이프 코칭 범위를 벗어나면 답변을 거절하도록 페르소나를 제한했습니다.
- 코칭 관련 질문은 웹 검색을 적극적으로 사용하도록 설정했습니다.
