"""브라우저 채팅 화면: streamlit run src/app.py"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.chatbot import ask_turn, default_state, USE_LLM, MODEL, CARDS

st.set_page_config(page_title="내 카드 혜택 챗봇", page_icon="💳")
st.title("💳 내 카드 혜택 챗봇")

users = default_state()   # data/my_profile.json (없으면 전체 카드, 전월 실적 0원). 카드 선택은 웹 화면(server.py)에서
st.caption((f"LLM 모드 ({MODEL})" if USE_LLM else "키워드 모드") + " · 전월 실적: "
           + ", ".join(f"{CARDS[c]['card_name']} {u.prev_month:,}원" for c, u in users.items()))

if "messages" not in st.session_state:
    st.session_state.messages = []
    st.session_state.context = None

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if q := st.chat_input("예) 스벅에서 15000원 쓰면 뭐가 이득이야?"):
    st.session_state.messages.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        with st.spinner("계산 중..."):
            t = ask_turn(q, users, st.session_state.context)
            a, st.session_state.context, followed = t["answer"], t["context"], t["followup"]
        if followed:
            a = "_(이전 질문에 이어서)_\n" + a
        st.markdown(a.replace("\n", "  \n"))
    st.session_state.messages.append({"role": "assistant", "content": a.replace("\n", "  \n")})
