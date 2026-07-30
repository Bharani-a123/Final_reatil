# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Interactive CLI Chat Client to test the Omnichannel Conversational Sales Agent.
Runs the compiled LangGraph statefully in a terminal loop.
"""
import os
import sys
import asyncio
import logging
from colorama import init, Fore, Style

# Set stdout encoding to UTF-8
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Disable verbose framework loggers to keep output clean
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.state import ExtendedState
from src.main import graph, config
from src.database import SessionLocal, CustomerProfile
from chain_server.src.agenttypes import Cart

init(autoreset=True)

# ANSI terminal colors
C_HEADER = Fore.CYAN + Style.BRIGHT
C_PLANNER = Fore.YELLOW + Style.BRIGHT
C_AGENT = Fore.MAGENTA + Style.BRIGHT
C_CHATTER = Fore.GREEN + Style.BRIGHT
C_USER = Fore.WHITE + Style.BRIGHT
C_SYSTEM = Fore.BLUE + Style.BRIGHT
C_ALERT = Fore.RED + Style.BRIGHT

async def chat_loop():
    print(C_HEADER + "\n=======================================================")
    print(C_HEADER + "      OMNICHANNEL CONVERSATIONAL SALES ASSISTANT       ")
    print(C_HEADER + "=======================================================")
    
    # 1. Check API Key
    key = os.environ.get("LLM_API_KEY", "")
    if not key or key == "mock_key":
        print(C_ALERT + "WARNING: Running in offline MOCK mode (LLM_API_KEY is not set or is 'mock_key').")
        print(C_ALERT + "To use live Groq models, set environment variable LLM_API_KEY to your Groq API key.")
    elif key.startswith("gsk_"):
        print(C_SYSTEM + f"Connected: Groq API Endpoint (Model: {config.llm_name})")
    else:
        print(C_SYSTEM + f"Connected: OpenAI/NVIDIA API Endpoint (Model: {config.llm_name})")

    # 2. Get customer profile
    db = SessionLocal()
    try:
        cust = db.query(CustomerProfile).first()
        customer_id = cust.customer_id if cust else "cust_001"
        customer_name = cust.name if cust else "Sarah Connor"
        customer_points = cust.loyalty_points if cust else 150
        customer_tier = cust.loyalty_tier if cust else "Gold"
    finally:
        db.close()

    print(C_SYSTEM + f"Customer Profile Loaded: {customer_name} ({customer_tier} Tier, {customer_points} Points)")
    print(C_SYSTEM + "Start chatting below. Type 'exit' to quit.\n")

    # Initialize State
    state = ExtendedState(
        user_id=123,
        customer_id=customer_id,
        loyalty_tier=customer_tier,
        loyalty_points=customer_points,
        cart=Cart(contents=[]),
        current_channel="web",
        query="",
        context=""
    )

    while True:
        try:
            user_input = input(C_USER + "You > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit"):
                print(C_SYSTEM + "Goodbye!")
                break

            # Update query in state
            state.query = user_input

            # Run step
            print(C_SYSTEM + "... Processing request ...")
            state = await graph.ainvoke(state)

            # Print routing decision
            next_agent = state.next_agent or "chatter"
            print(C_PLANNER + f"\n[Planner] Selected Agent: {next_agent.upper()}")

            # Print specialist response if it ran
            if next_agent != "chatter" and state.response:
                print(C_AGENT + f"[Agent Result]:\n{state.response}")

            # Print final chatter response
            print(C_CHATTER + f"\nAssistant > {state.response}")
            
            # Print cart summary if not empty
            if state.cart and state.cart.contents:
                total = sum(float(c.get("price", 0.0)) * c.get("amount", 1) for c in state.cart.contents)
                items_desc = ", ".join(f"{c.get('amount')}x {c.get('item')}" for c in state.cart.contents)
                print(C_SYSTEM + f"🛒 [Current Cart]: {items_desc} (Total: ${total:.2f})")
            print()

        except KeyboardInterrupt:
            print(C_SYSTEM + "\nGoodbye!")
            break
        except Exception as e:
            print(C_ALERT + f"\n[Error] System encountered an issue: {e}")
            print()

if __name__ == "__main__":
    # Ensure memory retriever is config port
    config.memory_port = "http://127.0.0.1:8011"
    asyncio.run(chat_loop())
