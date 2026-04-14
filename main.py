from __future__ import annotations

import asyncio
from pathlib import Path

import dotenv
import streamlit as st
from agents import SQLiteSession
from openai import OpenAI, OpenAIError

dotenv.load_dotenv()

DB_PATH = Path(__file__).with_name("life_coach_memory.db")
SESSION_ID = "life-coach-chat"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_HISTORY_MESSAGES = 20
SYSTEM_PROMPT = """
You are a practical life coach assistant for a simple practice chat app.
Help the user think clearly, break problems into manageable steps, and stay supportive without sounding vague.
Reply in the user's language unless they ask otherwise.
Use the previous conversation as memory.
""".strip()


def run_async(coro):
    return asyncio.run(coro)


def get_chat_session() -> SQLiteSession:
    if "chat_session" not in st.session_state:
        st.session_state["chat_session"] = SQLiteSession(SESSION_ID, str(DB_PATH))
    return st.session_state["chat_session"]


def load_messages() -> list[dict[str, str]]:
    session = get_chat_session()
    items = run_async(session.get_items())
    messages: list[dict[str, str]] = []

    for item in items:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        messages.append({"role": role, "content": content})

    return messages


def save_message(role: str, content: str) -> None:
    session = get_chat_session()
    run_async(session.add_items([{"role": role, "content": content}]))


def clear_messages() -> None:
    session = get_chat_session()
    run_async(session.clear_session())


def build_input(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages[-MAX_HISTORY_MESSAGES:]
    ]


def generate_reply(messages: list[dict[str, str]], model: str) -> str:
    client = OpenAI()
    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=build_input(messages),
        temperature=0.8,
    )
    return (response.output_text or "").strip()


if "messages" not in st.session_state:
    st.session_state["messages"] = load_messages()

if "model" not in st.session_state:
    st.session_state["model"] = DEFAULT_MODEL


for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.write(message["content"])


user_message = st.chat_input("Write a message for your assistant")

if user_message:
    message = user_message.strip()

    if message:
        st.session_state["messages"].append({"role": "user", "content": message})
        save_message("user", message)

        with st.chat_message("human"):
            st.write(message)

        with st.chat_message("ai"):
            with st.spinner("생각 중..."):
                try:
                    reply = generate_reply(
                        st.session_state["messages"],
                        st.session_state["model"],
                    )
                except OpenAIError as error:
                    st.error(f"OpenAI API error: {error}")
                else:
                    assistant_reply = reply or "응답을 생성하지 못했습니다. 다시 시도해 주세요."
                    st.write(assistant_reply)
                    st.session_state["messages"].append(
                        {"role": "assistant", "content": assistant_reply}
                    )
                    save_message("assistant", assistant_reply)


with st.sidebar:
    reset = st.button("Reset memory")
    if reset:
        clear_messages()
        st.session_state["messages"] = []
        st.rerun()
    st.write(st.session_state["messages"])
