from __future__ import annotations

import asyncio
from pathlib import Path

import dotenv
import streamlit as st
from agents import (
    Agent,
    Runner,
    SQLiteSession,
    WebSearchTool,
)

dotenv.load_dotenv()

DB_PATH = Path(__file__).with_name("life_coach_memory.db")
SESSION_ID = "life-coach-chat"
DEFAULT_MODEL = "gpt-5-mini"
COACH_PERSONA = """
You are a warm, practical life coach.
Your job is to encourage the user, give specific and actionable advice, and help them build better habits step by step.
Your allowed topics are motivation, self-improvement, habit-building, productivity, mindset, focus, routines, goal setting, and personal growth.
If the user's request is clearly outside those topics, politely refuse to answer and briefly redirect them back to life-coaching topics you can help with.
For coaching requests, prefer using web search frequently so your advice is grounded, current, and evidence-backed.
For most non-trivial coaching questions, do a web search before answering.
Especially use web search for requests about techniques, best practices, research-backed advice, recent trends, or examples.
When you actually use web search, briefly mention it in your answer with a line formatted like: [웹 검색: "search query"].
Do not mention web search if you did not use it.
Reply in the user's language unless they ask otherwise.
Be concise, encouraging, and practical.
""".strip()


def run_async(coro):
    return asyncio.run(coro)


def get_chat_session() -> SQLiteSession:
    if "session" not in st.session_state:
        st.session_state["session"] = SQLiteSession(SESSION_ID, str(DB_PATH))
    return st.session_state["session"]


def format_tool_event(query: str) -> dict[str, str]:
    return {
        "role": "assistant",
        "kind": "tool",
        "tool": "web_search",
        "content": query,
    }


def session_items_to_messages(items: list[dict]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []

    for item in items:
        role = item.get("role")
        content = item.get("content")
        if role == "user" and isinstance(content, str):
            messages.append({"role": role, "kind": "message", "content": content})
            continue

        if item.get("type") == "web_search_call":
            action = item.get("action")
            if isinstance(action, dict):
                query = action.get("query")
                if isinstance(query, str) and query.strip():
                    messages.append(format_tool_event(query.strip()))
            continue

        if role == "assistant" and item.get("type") == "message":
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
    session = get_chat_session()
    items = run_async(session.get_items())
    return session_items_to_messages(items)


def load_latest_tool_events() -> list[dict[str, str]]:
    items = run_async(get_chat_session().get_items())
    current_turn_items: list[dict] = []
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


async def load_latest_tool_events_async() -> list[dict[str, str]]:
    items = await get_chat_session().get_items()
    current_turn_items: list[dict] = []
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


async def load_messages_async() -> list[dict[str, str]]:
    items = await get_chat_session().get_items()
    return session_items_to_messages(items)


def clear_messages() -> None:
    session = get_chat_session()
    run_async(session.clear_session())


def get_agent(model: str) -> Agent:
    return Agent(
        name="Life Coach",
        instructions=COACH_PERSONA,
        model=model,
        tools=[WebSearchTool()],
    )


if "messages" not in st.session_state:
    st.session_state["messages"] = load_messages()

if "model" not in st.session_state:
    st.session_state["model"] = DEFAULT_MODEL

if "pending_message" not in st.session_state:
    st.session_state["pending_message"] = None


for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        if message.get("kind") == "tool":
            st.write("🔧 **Life Coach** used tool: `web_search`")
            st.caption(f'query: "{message["content"]}"')
        else:
            st.write(message["content"])


user_message = st.chat_input("Write a message for your assistant")

async def run_agent(message: str) -> None:
    with st.chat_message("ai"):
        status_placeholder = st.empty()
        tool_placeholder = st.empty()
        query_placeholder = st.empty()
        text_placeholder = st.empty()
        response = ""
        used_web_search = False
        status_placeholder.write("생각 중...")

        try:
            stream = Runner.run_streamed(
                get_agent(st.session_state["model"]),
                message,
                session=get_chat_session(),
            )

            async for event in stream.stream_events():
                if event.type == "raw_response_event":
                    if event.data.type == "response.output_text.delta":
                        status_placeholder.empty()
                        response += event.data.delta
                        text_placeholder.write(response)
                    elif event.data.type == "response.web_search_call.searching":
                        used_web_search = True
                        tool_placeholder.write("🔧 **Life Coach** used tool: `web_search`")

            latest_tool_events = await load_latest_tool_events_async()
            if latest_tool_events:
                latest_query = latest_tool_events[-1]["content"]
                tool_placeholder.write("🔧 **Life Coach** used tool: `web_search`")
                query_placeholder.caption(f'query: "{latest_query}"')
            elif used_web_search:
                tool_placeholder.write("🔧 **Life Coach** used tool: `web_search`")

            assistant_reply = response.strip()
            if not assistant_reply:
                assistant_reply = "응답을 생성하지 못했습니다. 다시 시도해 주세요."
                text_placeholder.write(assistant_reply)

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

if user_message:
    message = user_message.strip()

    if message:
        st.session_state["messages"].append(
            {"role": "user", "kind": "message", "content": message}
        )
        st.session_state["pending_message"] = message
        st.rerun()


with st.sidebar:
    st.write(f"Current model: `{st.session_state['model']}`")
    reset = st.button("Reset memory")
    if reset:
        clear_messages()
        st.session_state["messages"] = []
        st.rerun()
    st.write(run_async(get_chat_session().get_items()))
