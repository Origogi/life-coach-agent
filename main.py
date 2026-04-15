from __future__ import annotations

import asyncio
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

import dotenv
import streamlit as st
from agents import Agent, FileSearchTool, Runner, SQLiteSession, WebSearchTool
from openai import OpenAI

dotenv.load_dotenv()

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "life_coach_memory.db"
SESSION_ID = "life-coach-chat"
DEFAULT_MODEL = "gpt-5-mini"
VECTOR_STORE_NAME = "life-coach-personal-records"
VECTOR_STORE_ID_ENV = "OPENAI_VECTOR_STORE_ID"
SUPPORTED_UPLOAD_TYPES = ["pdf", "txt"]
DOCUMENT_TYPES = {
    "Goal": "goal",
    "Journal": "journal",
    "Routine": "routine",
    "Other": "other",
}
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEFAULT_VECTOR_STORE_ID = os.getenv(VECTOR_STORE_ID_ENV)

COACH_PERSONA = """
You are a warm, practical life coach.
Your job is to encourage the user, give specific and actionable advice, and help them build better habits step by step.
Your allowed topics are motivation, self-improvement, habit-building, productivity, mindset, focus, routines, goal setting, and personal growth.
If the user's request is clearly outside those topics, politely refuse to answer and briefly redirect them back to life-coaching topics you can help with.
You may have access to the user's uploaded personal files such as goal documents, journals, routines, and progress notes.
When the user asks about their goals, habits, routines, diary entries, plans, or progress over time, search their uploaded files first.
If uploaded files contain dates or multiple records, compare them to identify progress, regressions, and consistency over time.
After checking the user's files, use web search when you need outside evidence, current information, or research-backed advice.
For most non-trivial coaching questions, use either file search, web search, or both before answering.
When you actually use file search, briefly mention it in your answer with a line formatted like: [개인 기록 검색]
When you actually use web search, briefly mention it in your answer with a line formatted like: [웹 검색: "search query"]
Do not mention a tool if you did not use it.
Reply in the user's language unless they ask otherwise.
Be concise, encouraging, and practical.
""".strip()


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def escape_markdown_text(text: str) -> str:
    return text.replace("$", "\\$")


def get_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    if "openai_client" not in st.session_state:
        st.session_state["openai_client"] = OpenAI(api_key=OPENAI_API_KEY)
    return st.session_state["openai_client"]


def get_saved_vector_store_id() -> str | None:
    if "vector_store_id" in st.session_state:
        return st.session_state["vector_store_id"]

    vector_store_id = DEFAULT_VECTOR_STORE_ID
    if vector_store_id:
        st.session_state["vector_store_id"] = vector_store_id
    return vector_store_id


def get_or_create_vector_store_id() -> str:
    vector_store_id = get_saved_vector_store_id()
    if vector_store_id:
        return vector_store_id

    vector_store = get_openai_client().vector_stores.create(name=VECTOR_STORE_NAME)
    st.session_state["vector_store_id"] = vector_store.id
    return vector_store.id


def get_uploaded_documents() -> list[dict[str, str]]:
    return st.session_state.setdefault("uploaded_documents", [])


def remember_uploaded_document(
    *,
    filename: str,
    openai_file_id: str,
    document_type: str,
    entry_date: str,
) -> None:
    get_uploaded_documents().insert(
        0,
        {
            "filename": filename,
            "file_id": openai_file_id,
            "document_type": document_type,
            "entry_date": entry_date,
        },
    )


def wait_until_vector_store_file_ready(
    *,
    client: OpenAI,
    vector_store_id: str,
    vector_store_file_id: str,
    timeout_seconds: int = 60,
    poll_interval_seconds: float = 1.0,
) -> None:
    started_at = time.monotonic()

    while True:
        vector_store_file = client.vector_stores.files.retrieve(
            vector_store_id=vector_store_id,
            file_id=vector_store_file_id,
        )
        status = getattr(vector_store_file, "status", "")
        if status == "completed":
            return
        if status == "failed":
            error = getattr(vector_store_file, "last_error", None)
            error_message = getattr(error, "message", "unknown error")
            raise RuntimeError(f"Vector store indexing failed: {error_message}")
        if time.monotonic() - started_at > timeout_seconds:
            raise RuntimeError(
                f"Vector store indexing timed out after {timeout_seconds} seconds."
            )
        time.sleep(poll_interval_seconds)


def build_upload_payload(uploaded_file: Any) -> tuple[Any, ...]:
    file_bytes = uploaded_file.getvalue()
    if uploaded_file.type:
        return (uploaded_file.name, file_bytes, uploaded_file.type)
    return (uploaded_file.name, file_bytes)


def upload_personal_file(
    uploaded_file: Any,
    *,
    document_type: str,
    entry_date: str,
) -> str:
    client = get_openai_client()
    vector_store_id = get_or_create_vector_store_id()
    uploaded = client.files.create(
        file=build_upload_payload(uploaded_file),
        purpose="user_data",
    )
    vector_store_file = client.vector_stores.files.create(
        vector_store_id=vector_store_id,
        file_id=uploaded.id,
        attributes={
            "document_type": document_type,
            "entry_date": entry_date,
            "source": "streamlit_chat_input",
        },
    )
    wait_until_vector_store_file_ready(
        client=client,
        vector_store_id=vector_store_id,
        vector_store_file_id=vector_store_file.id,
    )
    remember_uploaded_document(
        filename=uploaded_file.name,
        openai_file_id=uploaded.id,
        document_type=document_type,
        entry_date=entry_date,
    )
    return uploaded.id


def get_chat_session() -> SQLiteSession:
    if "session" not in st.session_state:
        st.session_state["session"] = SQLiteSession(SESSION_ID, str(DB_PATH))
    return st.session_state["session"]


def format_tool_event(tool: str, content: str) -> dict[str, str]:
    return {
        "role": "assistant",
        "kind": "tool",
        "tool": tool,
        "content": content,
    }


def session_items_to_messages(items: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for item in items:
        role = item.get("role")
        content = item.get("content")
        item_type = item.get("type")

        if role == "user" and isinstance(content, str):
            messages.append({"role": role, "kind": "message", "content": content})
            continue

        if item_type == "web_search_call":
            action = item.get("action")
            if isinstance(action, dict):
                query = action.get("query")
                if isinstance(query, str) and query.strip():
                    messages.append(format_tool_event("web_search", query.strip()))
            continue

        if item_type == "file_search_call":
            queries = item.get("queries")
            if isinstance(queries, list):
                normalized_queries = [
                    query.strip()
                    for query in queries
                    if isinstance(query, str) and query.strip()
                ]
                joined = " | ".join(normalized_queries) if normalized_queries else "uploaded files"
                messages.append(format_tool_event("file_search", joined))
            else:
                messages.append(format_tool_event("file_search", "uploaded files"))
            continue

        if role == "assistant" and item_type == "message":
            text_parts: list[str] = []
            if isinstance(content, list):
                for content_item in content:
                    if not isinstance(content_item, dict):
                        continue
                    if content_item.get("type") != "output_text":
                        continue
                    text = content_item.get("text")
                    if isinstance(text, str) and text.strip():
                        text_parts.append(text.strip())

            text = "\n".join(text_parts).strip()
            if text:
                messages.append({"role": role, "kind": "message", "content": text})

    return messages


def load_messages() -> list[dict[str, str]]:
    items = run_async(get_chat_session().get_items())
    return session_items_to_messages(items)


async def load_messages_async() -> list[dict[str, str]]:
    items = await get_chat_session().get_items()
    return session_items_to_messages(items)


async def load_latest_tool_events_async() -> list[dict[str, str]]:
    items = await get_chat_session().get_items()
    current_turn_items: list[dict[str, Any]] = []
    saw_non_user_item = False

    for item in reversed(items):
        if item.get("role") == "user":
            if saw_non_user_item:
                break
            continue

        current_turn_items.append(item)
        saw_non_user_item = True

    current_turn_messages = session_items_to_messages(list(reversed(current_turn_items)))
    return [message for message in current_turn_messages if message.get("kind") == "tool"]


def clear_messages() -> None:
    run_async(get_chat_session().clear_session())


def get_agent(model: str) -> Agent:
    tools: list[Any] = [WebSearchTool()]
    vector_store_id = get_saved_vector_store_id()
    if vector_store_id:
        tools.append(
            FileSearchTool(
                vector_store_ids=[vector_store_id],
                max_num_results=4,
            )
        )

    return Agent(
        name="Life Coach",
        instructions=COACH_PERSONA,
        model=model,
        tools=tools,
    )


def render_tool_message(message: dict[str, str]) -> None:
    tool = message.get("tool")
    if tool == "web_search":
        st.write("🔧 **Life Coach** used tool: `web_search`")
        if message.get("content"):
            st.caption(f'query: "{message["content"]}"')
        return

    if tool == "file_search":
        st.write("🗂️ **Life Coach** used tool: `file_search`")
        if message.get("content"):
            st.caption(f'query: "{message["content"]}"')
        return

    st.write(escape_markdown_text(message.get("content", "")))


if "messages" not in st.session_state:
    st.session_state["messages"] = load_messages()

if "model" not in st.session_state:
    st.session_state["model"] = DEFAULT_MODEL

if "pending_message" not in st.session_state:
    st.session_state["pending_message"] = None

if "upload_notice" not in st.session_state:
    st.session_state["upload_notice"] = None

if "uploaded_documents" not in st.session_state:
    st.session_state["uploaded_documents"] = []


st.title("Life Coach Agent")

if st.session_state["upload_notice"]:
    st.success(st.session_state["upload_notice"])
    st.session_state["upload_notice"] = None

if not OPENAI_API_KEY:
    st.warning("`OPENAI_API_KEY`가 설정되지 않았습니다. 파일 업로드와 채팅 응답은 동작하지 않습니다.")


for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        if message.get("kind") == "tool":
            render_tool_message(message)
        else:
            st.write(escape_markdown_text(message["content"]))


selected_document_type_label = "Goal"
selected_entry_date = date.today()

with st.sidebar:
    st.write(f"Current model: `{st.session_state['model']}`")
    vector_store_id = get_saved_vector_store_id()
    if vector_store_id:
        st.caption(f"Vector store: `{vector_store_id}`")
    else:
        st.caption("Vector store will be created automatically on the first file upload.")
        st.caption(f"Optional env: `{VECTOR_STORE_ID_ENV}`")

    selected_document_type_label = st.selectbox(
        "Next upload type",
        options=list(DOCUMENT_TYPES.keys()),
        index=0,
    )
    selected_entry_date = st.date_input(
        "Record date",
        value=date.today(),
    )

    reset = st.button("Reset memory")
    if reset:
        clear_messages()
        st.session_state["messages"] = []
        st.rerun()

    st.divider()
    st.write("Uploaded personal files")
    uploaded_documents = get_uploaded_documents()
    if uploaded_documents:
        for document in uploaded_documents[:10]:
            label = f"{document['filename']} · {document['document_type']}"
            if document["entry_date"]:
                label += f" · {document['entry_date']}"
            st.caption(label)
    else:
        st.caption("No files uploaded yet.")


async def run_agent(message: str) -> None:
    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        tool_placeholder = st.empty()
        text_placeholder = st.empty()
        response = ""
        used_web_search = False
        used_file_search = False
        status_placeholder.write("생각 중...")

        try:
            stream = Runner.run_streamed(
                get_agent(st.session_state["model"]),
                message,
                session=get_chat_session(),
            )

            async for event in stream.stream_events():
                if event.type != "raw_response_event":
                    continue

                event_type = event.data.type
                if event_type == "response.output_text.delta":
                    status_placeholder.empty()
                    response += event.data.delta
                    text_placeholder.write(escape_markdown_text(response))
                elif event_type in {
                    "response.file_search_call.in_progress",
                    "response.file_search_call.searching",
                }:
                    used_file_search = True
                    status_placeholder.write("개인 기록 검색 중...")
                elif event_type in {
                    "response.web_search_call.in_progress",
                    "response.web_search_call.searching",
                }:
                    used_web_search = True
                    status_placeholder.write("웹 검색 중...")

            latest_tool_events = await load_latest_tool_events_async()
            if latest_tool_events:
                with tool_placeholder.container():
                    for tool_event in latest_tool_events:
                        render_tool_message(tool_event)
            elif used_file_search:
                with tool_placeholder.container():
                    render_tool_message(
                        {
                            "role": "assistant",
                            "kind": "tool",
                            "tool": "file_search",
                            "content": "uploaded files",
                        }
                    )
            elif used_web_search:
                with tool_placeholder.container():
                    render_tool_message(
                        {
                            "role": "assistant",
                            "kind": "tool",
                            "tool": "web_search",
                            "content": "",
                        }
                    )

            assistant_reply = response.strip()
            if not assistant_reply:
                text_placeholder.write("응답을 생성하지 못했습니다. 다시 시도해 주세요.")

            status_placeholder.empty()
            st.session_state["messages"] = await load_messages_async()
        except Exception as error:
            status_placeholder.empty()
            st.error(f"Agent run error: {error}")


pending_message = st.session_state.get("pending_message")

if pending_message:
    asyncio.run(run_agent(pending_message))
    st.session_state["pending_message"] = None
    st.rerun()


prompt = st.chat_input(
    "Write a message for your assistant",
    accept_file=True,
    file_type=SUPPORTED_UPLOAD_TYPES,
)

if prompt:
    if isinstance(prompt, str):
        prompt_text = prompt.strip()
        prompt_files: list[Any] = []
    else:
        prompt_text = prompt.text.strip()
        prompt_files = list(prompt.files)

    uploaded_filenames: list[str] = []
    upload_failed = False
    selected_document_type = DOCUMENT_TYPES[selected_document_type_label]
    entry_date = selected_entry_date.isoformat()

    if prompt_files:
        with st.chat_message("assistant"):
            with st.status("⏳ 파일 업로드 중...", expanded=True) as status:
                try:
                    for index, uploaded_file in enumerate(prompt_files, start=1):
                        status.write(
                            f"{index}. `{uploaded_file.name}` 업로드 및 인덱싱 중..."
                        )
                        upload_personal_file(
                            uploaded_file,
                            document_type=selected_document_type,
                            entry_date=entry_date,
                        )
                        uploaded_filenames.append(uploaded_file.name)
                    status.update(label="✅ 파일 업로드 완료", state="complete")
                except Exception as error:
                    upload_failed = True
                    status.update(label="❌ 파일 업로드 실패", state="error")
                    st.error(f"File upload error: {error}")

    if uploaded_filenames:
        st.session_state["upload_notice"] = (
            f"{len(uploaded_filenames)}개 파일을 업로드했습니다: "
            + ", ".join(uploaded_filenames)
        )

    if prompt_text and not upload_failed:
        st.session_state["messages"].append(
            {"role": "user", "kind": "message", "content": prompt_text}
        )
        st.session_state["pending_message"] = prompt_text
        st.rerun()

    if uploaded_filenames:
        st.rerun()
