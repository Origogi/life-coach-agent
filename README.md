# Life Coach Agent

간단한 AI agent 실습용 스트림릿 앱입니다.

현재 범위는 작게 잡았습니다.

- 채팅 폼으로 대화하기
- OpenAI SDK로 응답 생성하기
- OpenAI Agents SDK의 `SQLiteSession`으로 대화 메모리 유지하기
- 툴 호출과 서브 에이전트는 제외하기

## 실행

```bash
uv sync
uv run streamlit run main.py
```

## 환경 변수

`.env` 파일에 아래 값을 넣으면 됩니다.

```bash
OPENAI_API_KEY=your-api-key-here
```

## 메모리

대화 메모리는 로컬 파일 `life_coach_memory.db`에 저장됩니다.

