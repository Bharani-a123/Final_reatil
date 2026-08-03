# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Main FastAPI server for the Omnichannel Conversational Sales Agent (Extensions).
Runs on port 8009, substituting the core chain-server process.
"""
import sys
import os

# Monkey patch OpenAI completions globally to remove chat_template_kwargs for non-NVIDIA providers
from openai.resources.chat.completions import Completions, AsyncCompletions

def patch_openai_completions():
    original_create = Completions.create
    original_async_create = AsyncCompletions.create

    def patched_create(self, *args, **kwargs):
        base_url = getattr(self._client, "base_url", "")
        if "nvidia" not in str(base_url) and "nemotron" not in str(kwargs.get("model", "")):
            if "extra_body" in kwargs:
                extra = kwargs["extra_body"]
                if isinstance(extra, dict) and "chat_template_kwargs" in extra:
                    del extra["chat_template_kwargs"]
                    if not extra:
                        del kwargs["extra_body"]
        return original_create(self, *args, **kwargs)

    async def patched_async_create(self, *args, **kwargs):
        base_url = getattr(self._client, "base_url", "")
        if "nvidia" not in str(base_url) and "nemotron" not in str(kwargs.get("model", "")):
            if "extra_body" in kwargs:
                extra = kwargs["extra_body"]
                if isinstance(extra, dict) and "chat_template_kwargs" in extra:
                    del extra["chat_template_kwargs"]
                    if not extra:
                        del kwargs["extra_body"]
        return await original_async_create(self, *args, **kwargs)

    Completions.create = patched_create
    AsyncCompletions.create = patched_async_create

patch_openai_completions()

# Set fallback environment variables to prevent KeyErrors from core dependencies
os.environ.setdefault("LLM_API_KEY", "mock_key")
os.environ.setdefault("EMBED_API_KEY", "mock_key")
os.environ.setdefault("CONFIG_OVERRIDE", "config-build.yaml")  # Force cloud configuration mapping

import time
import json
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

# Setup pathing to access core chain_server
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from chain_server.src.planner import PlannerAgent
from chain_server.src.retriever import RetrieverAgent
from chain_server.src.cart import CartAgent
from chain_server.src.chatter import ChatterAgent
from chain_server.src.summarizer import SummaryAgent
from chain_server.src.config import load_config
from chain_server.src.agenttypes import Cart

# Local imports
from .state import ExtendedState
from .graph import create_extended_graph

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Load product prices from CSV on startup
PRODUCT_PRICES = {}
try:
    import csv
    csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "selected_dataset", "products.csv")
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            PRODUCT_PRICES[row["name"].strip()] = float(row["price"] or 0)
    logger.info(f"Loaded {len(PRODUCT_PRICES)} product prices for UI display.")
except Exception as e:
    logger.error(f"Failed to load product prices on startup: {e}")

from .agents.inventory import InventoryAgent
from .agents.payment import PaymentAgent
from .agents.fulfillment import FulfillmentAgent
from .agents.loyalty import LoyaltyAgent
from .agents.support import SupportAgent

def save_session_state(state: ExtendedState):
    from .database import SessionLocal, SessionState
    db = SessionLocal()
    try:
        session = db.query(SessionState).filter(SessionState.user_id == state.user_id).first()
        if not session:
            session = SessionState(user_id=state.user_id)
            db.add(session)
        session.tracking_number = state.tracking_number
        session.razorpay_link_id = state.razorpay_link_id
        session.razorpay_short_url = state.razorpay_short_url
        session.fulfillment_method = state.fulfillment_method
        session.delivery_address = state.delivery_address
        session.delivery_slot = state.delivery_slot
        session.payment_status = state.payment_status
        session.order_status = state.order_status
        db.commit()
    except Exception as e:
        logger.error(f"Failed to save SessionState: {e}")
    finally:
        db.close()

class ExtendedPlannerAgent(PlannerAgent):
    def __init__(self, config):
        super().__init__(config)
        self.chat_kwargs = {}
        if "nvidia" in config.llm_port or "nemotron" in config.llm_name:
            self.chat_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        from .database import SessionLocal, SessionState
        db = SessionLocal()
        try:
            session = db.query(SessionState).filter(SessionState.user_id == state.user_id).first()
            if session:
                state.tracking_number = session.tracking_number
                state.razorpay_link_id = session.razorpay_link_id
                state.razorpay_short_url = session.razorpay_short_url
                state.fulfillment_method = session.fulfillment_method
                state.delivery_address = session.delivery_address
                state.delivery_slot = session.delivery_slot
                state.payment_status = session.payment_status
                state.order_status = session.order_status
            else:
                session = SessionState(user_id=state.user_id)
                db.add(session)
                db.commit()
        except Exception as e:
            logger.error(f"Failed to load SessionState: {e}")
        finally:
            db.close()
            
        return super().invoke(state, verbose=verbose)

    def _call_llm_for_routing(self, query: str, has_image: bool = False) -> str:
        q_lower = query.lower()

        # 1. Deterministic/Keyword-based Routing Rules (High accuracy overrides)
        if any(w in q_lower for w in ["track", "status", "return", "refund", "exchange", "ref_", "order", "cancel"]):
            return "support"
        if any(w in q_lower for w in ["coupon", "discount", "loyalty", "points", "redeem", "rewards"]):
            return "loyalty"
        if any(w in q_lower for w in ["stock", "inventory", "available", "store"]):
            return "inventory"
        if any(w in q_lower for w in ["pay", "card", "upi", "gift", "checkout", "paid", "verify", "confirm"]):
            return "payment"
        if any(w in q_lower for w in ["deliver", "ship", "address", "pickup", "collect", "reserve"]):
            return "fulfillment"
        if any(w in q_lower for w in ["cart", "add to", "remove", "delete", "checkout", "buy this", "buy the", "take out"]) or "total" in q_lower:
            return "cart"
            
        categories = ["sari", "saree", "shirt", "dress", "skirt", "bag", "sunglasses", "shoes", "earrings", "bracelet", "necklace"]
        search_keywords = ["show", "find", "search", "more", "recommend", "look for", "looking for", "browse", "get me", "any"]
        if any(cat in q_lower for cat in categories) and any(kw in q_lower for kw in search_keywords):
            return "retriever"
        if "more" in q_lower and any(cat in q_lower for cat in categories):
            return "retriever"

        if os.environ.get("LLM_API_KEY") == "mock_key":
            logger.info("PlannerAgent | Running in mock mode.")
            return "chatter"

        try:
            messages = self._create_routing_messages(query, has_image=has_image)
            response = self.model.chat.completions.create(
                model=self.llm_name,
                messages=messages,
                temperature=0.0,
                max_tokens=100,
                **self.chat_kwargs
            )
            response_content = response.choices[0].message.content.strip().lower()
            logger.debug(f"LLM routing response: {response_content}")
            return response_content
        except Exception as e:
            logger.error(f"Error calling LLM for routing: {e}")
            return "chatter"

class ExtendedRetrieverAgent(RetrieverAgent):
    def __init__(self, config):
        super().__init__(config)
        self.config = config

    async def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        q_lower = (state.query or "").strip().lower()
        if any(w in q_lower for w in ["more", "other", "additional", "another"]):
            self.k_value = 8
        else:
            self.k_value = self.config.top_k_retrieve
        state = await super().invoke(state, verbose=verbose)
        
        # Enrich retrieved catalog products with pricing metadata
        if state.retrieved:
            new_retrieved = {}
            for name, img in state.retrieved.items():
                price = PRODUCT_PRICES.get(name.strip(), 0.0)
                if isinstance(img, dict):
                    new_retrieved[name] = img
                else:
                    new_retrieved[name] = {"url": img, "price": price}
            state.retrieved = new_retrieved
            
        return state

def resolve_indices(query: str, state: ExtendedState, is_remove: bool = False) -> list[str]:
    import re
    words_to_num = {
        "first": 1, "1st": 1, "one": 1,
        "second": 2, "2nd": 2, "two": 2,
        "third": 3, "3rd": 3, "three": 3,
        "fourth": 4, "4th": 4, "four": 4,
        "fifth": 5, "5th": 5, "five": 5,
        "sixth": 6, "6th": 6, "six": 6,
        "seventh": 7, "7th": 7, "seven": 7,
        "eighth": 8, "8th": 8, "eight": 8,
        "ninth": 9, "9th": 9, "nine": 9,
        "tenth": 10, "10th": 10, "ten": 10,
    }
    
    query_clean = query.lower()
    parsed_nums = []
    
    for word, num in words_to_num.items():
        if re.search(r"\b" + re.escape(word) + r"\b", query_clean):
            parsed_nums.append(num)
            
    digit_matches = re.findall(r"\b\d+\b", query_clean)
    for dm in digit_matches:
        num = int(dm)
        if num <= 20 and num not in parsed_nums:
            parsed_nums.append(num)
            
    parsed_nums.sort()
    if not parsed_nums:
        return []
        
    resolved_names = []
    if is_remove:
        if state.cart and state.cart.contents:
            cart_items = [item.get("item") for item in state.cart.contents if item.get("item")]
            for num in parsed_nums:
                idx = num - 1
                if 0 <= idx < len(cart_items):
                    resolved_names.append(cart_items[idx])
    else:
        from chain_server.src.cart import CartAgent
        ctx = state.context or ""
        lines = ctx.split("\n")
        catalog_items = []
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            if " | " in line_str:
                parts = line_str.split(" | ")
                name = parts[0].strip()
                name = name.replace("**", "").replace("*", "")
                if name and len(name) > 2 and "price" not in name.lower() and "tip" not in name.lower():
                    if name not in catalog_items:
                        catalog_items.append(name)
                continue
            match = re.match(r"^(?:[-•*+]|\d+\.)\s*(?:\*\*)?(.*?)(?:\*\*)?(?:\s+(?:for|@|priced at)\s+|\s*\||\s*:\s+A beautiful|\s*$)", line_str)
            if match:
                name = match.group(1).strip()
                name = re.sub(r"[*:]+$", "", name).strip()
                if name and len(name) > 2 and "price" not in name.lower() and "tip" not in name.lower():
                    if name not in catalog_items:
                        catalog_items.append(name)
                        
        if not catalog_items:
            catalog_items = CartAgent._collect_known_products(state)
            
        logger.info(f"resolve_indices | parsed catalog items in order: {catalog_items}")
        for num in parsed_nums:
            idx = num - 1
            if 0 <= idx < len(catalog_items):
                resolved_names.append(catalog_items[idx])
                
    return resolved_names

def find_fuzzy_catalog_match(query: str, catalog_names: list, threshold: float = 0.5) -> Optional[str]:
    import re
    q_words = set(re.findall(r'\b\w+\b', query.lower()))
    if not q_words:
        return None
        
    best_match = None
    best_score = 0.0
    for name in catalog_names:
        n_words = set(re.findall(r'\b\w+\b', name.lower()))
        if not n_words:
            continue
        intersection = q_words & n_words
        score = len(intersection) / len(n_words)
        if score > best_score:
            best_score = score
            best_match = name
            
    if best_score >= threshold:
        return best_match
    return None

class ExtendedCartAgent(CartAgent):
    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        query = state.query or ""
        is_remove = "remove" in query.lower() or "delete" in query.lower() or "take out" in query.lower()
        resolved_names = resolve_indices(query, state, is_remove=is_remove)
        
        if not resolved_names:
            if is_remove:
                # Direct match cart items
                if state.cart and not state.cart.is_empty():
                    for item in state.cart.contents:
                        item_name = item.get("item", "")
                        if item_name.lower() in query.lower():
                            resolved_names = [item_name]
                            break
                    if not resolved_names:
                        # Fuzzy match cart items
                        cart_names = [item.get("item", "") for item in state.cart.contents if item.get("item")]
                        match = find_fuzzy_catalog_match(query, cart_names, threshold=0.5)
                        if match:
                            resolved_names = [match]
            else:
                # Direct match catalog items
                from chain_server.src.cart import CartAgent
                catalog_items = CartAgent._collect_known_products(state)
                for name in catalog_items:
                    if name.lower() in query.lower():
                        resolved_names = [name]
                        break
                if not resolved_names:
                    # Fuzzy match catalog items
                    match = find_fuzzy_catalog_match(query, catalog_items, threshold=0.5)
                    if match:
                        resolved_names = [match]

        if resolved_names:
            logger.info(f"ExtendedCartAgent | resolved index-based names: {resolved_names}")
            if len(resolved_names) > 1:
                tool_name = "bulk_remove_from_cart" if is_remove else "bulk_add_to_cart"
            else:
                tool_name = "remove_from_cart" if is_remove else "add_to_cart"
                
            output_state = state
            if tool_name == "add_to_cart":
                item_name = resolved_names[0]
                output_state.response = self._add_to_cart(state.user_id, item_name, 1)
                output_state.cart = self._get_cart(state.user_id)
            elif tool_name == "remove_from_cart":
                item_name = resolved_names[0]
                output_state.response = self._remove_from_cart(state.user_id, item_name, 1)
                output_state.cart = self._get_cart(state.user_id)
            elif tool_name == "bulk_add_to_cart":
                lines = []
                for name in resolved_names:
                    lines.append(self._add_to_cart(state.user_id, name, 1))
                output_state.response = "\n".join(lines)
                output_state.cart = self._get_cart(state.user_id)
            elif tool_name == "bulk_remove_from_cart":
                lines = []
                for name in resolved_names:
                    lines.append(self._remove_from_cart(state.user_id, name, 1))
                output_state.response = "\n".join(lines)
                output_state.cart = self._get_cart(state.user_id)
            
            output_state.next_agent = "cart"
            return output_state

        return super().invoke(state, verbose=verbose)

class ExtendedChatterAgent(ChatterAgent):
    def __init__(self, config):
        super().__init__(config)
        self.chat_kwargs = {}
        if "nvidia" in config.llm_port or "nemotron" in config.llm_name:
            self.chat_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    @staticmethod
    def _describe_preceding_agent(state: ExtendedState) -> str:
        agent = (state.next_agent or "").strip().lower()
        if agent in ("cart", "retriever", "inventory", "payment", "fulfillment", "loyalty", "support"):
            return agent
        return "none"

    async def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        query_text = state.query or "The user has submitted an image and is looking for items that appear similar."
        query_lower = query_text.lower()
        if any(w in query_lower for w in ["show my cart", "show cart", "view cart", "what's in my cart", "view my cart", "check my cart"]):
            import requests
            try:
                cart_resp = requests.get(f"{self.config.memory_port}/user/{state.user_id}/cart", timeout=3.0)
                if cart_resp.status_code == 200:
                    cart_data = cart_resp.json().get("cart", [])
                else:
                    cart_data = []
            except Exception as e:
                logger.error(f"Failed to fetch cart from memory retriever: {e}")
                cart_data = []
            state.cart = Cart(contents=cart_data)
            
            # Fetch cart images
            cart_retrieved = {}
            if state.cart and not state.cart.is_empty():
                import requests
                for item in state.cart.contents:
                    name = item.get("item")
                    if name:
                        try:
                            ret_response = requests.post(
                                f"{self.config.retriever_port}/query/text",
                                json={
                                    "text": [name],
                                    "categories": self.config.categories,
                                    "k": 1,
                                },
                                timeout=3.0
                            )
                            ret_response.raise_for_status()
                            res_json = ret_response.json()
                            images = res_json.get("images") or []
                            if images:
                                cart_retrieved[name] = {"url": images[0], "price": item.get("price", 0.0)}
                        except Exception as e:
                            logger.warning(f"Failed to lookup image for {name}: {e}")
            state.retrieved = cart_retrieved
            
            if not state.cart or state.cart.is_empty():
                state.response = "Your shopping cart is currently empty."
            else:
                lines = []
                total = 0.0
                for entry in state.cart.contents:
                    name = entry.get("item", "")
                    amount = int(entry.get("amount", 1))
                    price = entry.get("price")
                    if price is not None:
                        try:
                            price_val = float(price)
                            subtotal = price_val * amount
                            total += subtotal
                            lines.append(f"• {amount} x {name} @ ${price_val:.2f} (Subtotal: ${subtotal:.2f})")
                        except (TypeError, ValueError):
                            lines.append(f"• {amount} x {name}")
                    else:
                        lines.append(f"• {amount} x {name}")
                lines.append(f"\nTotal: ${total:.2f}")
                state.response = "Your current cart contains:\n" + "\n".join(lines)
            
            state.context = f"{state.context}\n{state.response}"
            save_session_state(state)
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
            writer(f"{json.dumps({'type' : 'images', 'payload' : state.retrieved, 'timestamp' : time.time()})}")
            writer(f"{json.dumps({'type' : 'content', 'payload' : state.response, 'timestamp' : time.time()})}")
            return state

        if os.environ.get("LLM_API_KEY") == "mock_key":
            logger.info("ChatterAgent | Running in mock mode.")
            state.response = state.response or "I am here to help you shop. What are you looking for?"
            state.context = state.context + f"\nChatter Response: {state.response}"
            save_session_state(state)
            return state

        # Explicit async invoke implementation
        query_text = state.query or "The user has submitted an image and is looking for items that appear similar."
        preceding_agent = self._describe_preceding_agent(state)
        agent_result = (state.response or "").strip() or "(none)"
        cart_block = self._format_cart(state)
        catalog_block = self._format_available_catalog(state)
        recent_context = (state.context or "").strip()
        if len(recent_context) > 1500:
            recent_context = "... " + recent_context[-1500:]
        recent_context = recent_context or "(none)"

        user_message = (
            f"USER QUERY: {query_text}\n\n"
            f"PRECEDING AGENT (ran this turn before you): {preceding_agent}\n"
            f"PRECEDING AGENT RESULT (verbatim, authoritative for this turn): {agent_result}\n\n"
            f"CURRENT CART (authoritative):\n{cart_block}\n\n"
            f"AVAILABLE CATALOG (fresh retrieval for this turn; the only NEW products you may introduce):\n"
            f"{catalog_block}\n\n"
            f"RECENT DISCUSSION (reference only; paraphrased past turns, NOT authoritative for cart state):\n"
            f"{recent_context}"
        )

        messages = [
            {"role": "system", "content": self.config.chatter_prompt},
            {"role": "user", "content": user_message},
        ]

        query_lower = query_text.lower()
        is_cart_query = preceding_agent == "cart" or any(w in query_lower for w in ["cart", "checkout", "pay", "buy", "remove", "add", "purchase", "shopping bag"])

        if is_cart_query:
            cart_retrieved = {}
            if state.cart and not state.cart.is_empty():
                import requests
                for item in state.cart.contents:
                    name = item.get("item")
                    if name:
                        try:
                            ret_response = requests.post(
                                f"{self.config.retriever_port}/query/text",
                                json={
                                    "text": [name],
                                    "categories": self.config.categories,
                                    "k": 1,
                                },
                                timeout=3.0
                            )
                            ret_response.raise_for_status()
                            res_json = ret_response.json()
                            images = res_json.get("images") or []
                            if images:
                                cart_retrieved[name] = {"url": images[0], "price": item.get("price", 0.0)}
                        except Exception as e:
                            logger.warning(f"Failed to lookup image for {name}: {e}")
            state.retrieved = cart_retrieved
        

        from langgraph.config import get_stream_writer
        import json
        import time

        writer = get_stream_writer()
        writer(f"{json.dumps({'type' : 'images', 'payload' : state.retrieved, 'timestamp' : time.time()})}")

        start = time.monotonic()
        full_response = ""
        ftr = False

        stream = await self.model.chat.completions.create(
            model=self.llm_name,
            messages=messages,
            stream=True,
            temperature=0.0,
            max_tokens=1024,
            **self.chat_kwargs
        )

        async for chunk in stream:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                state.response = full_response

                if not ftr:
                    ftr = True
                    state.timings["first_token"] = time.monotonic() - start

                writer(f"{json.dumps({'type' : 'content', 'payload' : content, 'timestamp' : time.time()})}")

        state.response = full_response
        state.context = f"{state.context}\n{full_response}"
        state.timings["chatter"] = time.monotonic() - start

        if preceding_agent in ("support", "payment") and state.tracking_number:
            from .database import SessionLocal, CustomerProfile
            db = SessionLocal()
            try:
                cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == state.customer_id).first()
                items = []
                if cust:
                    items = json.loads(cust.purchase_history or "[]")
                
                order_images = {}
                import requests
                for name in items:
                    if name:
                        try:
                            ret_response = requests.post(
                                f"{self.config.retriever_port}/query/text",
                                json={
                                    "text": [name],
                                    "categories": self.config.categories,
                                    "k": 1,
                                },
                                timeout=3.0
                            )
                            if ret_response.status_code == 200:
                                res_json = ret_response.json()
                                images = res_json.get("images") or []
                                if images:
                                    resolved_url = images[0]
                                    if resolved_url and not resolved_url.startswith('http') and not resolved_url.startsWith('data:') and not resolved_url.startsWith('/images/'):
                                        resolved_url = f"/images/{resolved_url}"
                                    order_images[name] = resolved_url
                        except Exception as e:
                            logger.warning(f"Failed to lookup order image for {name}: {e}")

                method = state.fulfillment_method or "ship_to_home"
                status = "Shipped (In-Transit)" if method == "ship_to_home" else "Ready for Pickup"
                carrier = "Fedex Express" if method == "ship_to_home" else "Downtown Store Pickup"
                address = state.delivery_address or "Registered Home Address"
                slot = state.delivery_slot or "Tomorrow morning"
                
                order_payload = {
                    "ref": state.tracking_number,
                    "status": status,
                    "carrier": carrier,
                    "method": method,
                    "address": address,
                    "slot": slot,
                    "items": [
                        {"productName": name, "productUrl": order_images.get(name, "/images/placeholder.jpg")}
                        for name in items
                    ]
                }
                writer(f"{json.dumps({'type' : 'order', 'payload' : order_payload, 'timestamp' : time.time()})}")
            except Exception as e:
                logger.error(f"Failed to emit order event: {e}")
            finally:
                db.close()

        save_session_state(state)
        return state

class ExtendedSummaryAgent(SummaryAgent):
    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        try:
            return super().invoke(state, verbose=verbose)
        except Exception as e:
            logger.warning(f"SummaryAgent | Gracefully caught offline memory retriever error: {e}")
            return state

# Load config
try:
    config = load_config()
    
    # 1. Update allowed categories to match the user's products.csv
    config.categories = [
        "bra", "briefs", "dresses", "innerwear vests", "jackets", "jeans", "kurtas", 
        "kurtis", "sarees", "shirts", "shorts", "socks", "sweaters", "sweatshirts", 
        "tops", "track pants", "trousers", "tshirts", "tunics"
    ]
    
    # Override memory and catalog retriever hosts to localhost for offline/local run
    config.memory_port = "http://127.0.0.1:8011"
    config.retriever_port = "http://127.0.0.1:8010"
    
    # 2. Add Phase 2 agent choices
    config.agent_choices = ["cart", "retriever", "chatter", "inventory", "payment", "fulfillment", "loyalty", "support"]
    
    # 3. Enhance routing prompt
    config.routing_prompt = config.routing_prompt + """
  INVENTORY OPERATIONS -> inventory:
  - Checking stock/availability at specific locations or warehouses: "is this in stock", "do you have it in downtown store", "check availability", "how many items are left at the suburbs store"
  
  FULFILLMENT OPERATIONS -> fulfillment:
  - Setting delivery or pick-up methods and details: "deliver it to my house", "shipping to 123 Main St", "reserve it in-store", "click and collect", "schedule pickup slot"
  
  PAYMENT OPERATIONS -> payment:
  - Authorizing transactions or paying for current orders: "pay for my order", "checkout with my card ending 4242", "use upi id barry@upi", "apply gift card code GIFT_100"
  
  LOYALTY OPERATIONS -> loyalty:
  - Applying coupons, checking loyalty points, or redeeming rewards: "apply coupon WELCOME10", "use my discount points", "do I have any rewards", "check my loyalty balance"
  
  POST-PURCHASE SUPPORT -> support:
  - Tracking orders, returns, exchanges, or order status checks: "where is my order REF_123456", "track my shipment", "return my item size mismatch", "request refund for order"
  
  Always route queries to inventory, fulfillment, payment, loyalty, or support if they match these operations.
"""

    # 4. Enhance chatter prompt grounding
    config.chatter_prompt = config.chatter_prompt.replace(
        "- PRECEDING AGENT = `cart`:",
        """- PRECEDING AGENT = `inventory`:
      Report the real-time stock levels or availability exactly as returned in PRECEDING AGENT RESULT.
  - PRECEDING AGENT = `payment`:
      Report the status of the payment transaction exactly as returned in PRECEDING AGENT RESULT.
  - PRECEDING AGENT = `fulfillment`:
      Report the fulfillment or order confirmation details exactly as returned in PRECEDING AGENT RESULT.
  - PRECEDING AGENT = `loyalty`:
      Report the coupon or points redemption status exactly as returned in PRECEDING AGENT RESULT.
  - PRECEDING AGENT = `support`:
      Report the order status details, returns status, or support logs exactly as returned in PRECEDING AGENT RESULT.
  - PRECEDING AGENT = `cart`:"""
    )
    
    # Initialize agents
    agents = {
        'planner_agent': ExtendedPlannerAgent(config=config),
        'retriever_agent': ExtendedRetrieverAgent(config=config),
        'cart_agent': ExtendedCartAgent(config=config),
        'chatter_agent': ExtendedChatterAgent(config=config),
        'summary_agent': ExtendedSummaryAgent(config=config),
        'inventory_agent': InventoryAgent(config=config),
        'payment_agent': PaymentAgent(config=config),
        'fulfillment_agent': FulfillmentAgent(config=config),
        'loyalty_agent': LoyaltyAgent(config=config),
        'support_agent': SupportAgent(config=config)
    }
    
    # Create the extended graph
    graph = create_extended_graph(
        **agents,
        config=config
    )
    logger.info("FastAPI Extensions server initializing graph successful.")
except Exception as e:
    logger.error(f"Failed to initialize extended application: {e}")
    raise

# Initialize FastAPI app
app = FastAPI(
    title="Shopping Assistant Extended API",
    description="Extended AI-powered shopping assistant supporting multi-agent omnichannel actions",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Extended Request / Response Pydantic schemas
class QueryRequest(BaseModel):
    user_id: int
    query: str
    image: str = ""
    context: Optional[str] = ""
    cart: Optional[Cart] = None
    retrieved: Optional[Dict[str, str]] = {}
    guardrails: Optional[bool] = True
    image_bool: bool = False
    
    # Extended attributes (Phase 0)
    current_channel: Optional[str] = "web"
    customer_id: Optional[str] = None

class QueryResponse(BaseModel):
    response: str
    images: Dict[str, str] = {}
    timings: Dict[str, float] = {}

def create_initial_extended_state(request: QueryRequest) -> ExtendedState:
    """Create initial ExtendedState from incoming query request."""
    return ExtendedState(
        user_id=request.user_id,
        query=request.query,
        image=request.image,
        context=request.context or "",
        cart=request.cart or Cart(),
        guardrails=request.guardrails,
        current_channel=request.current_channel or "web",
        customer_id=request.customer_id
    )

@app.post("/query/stream")
async def process_query_stream(request: QueryRequest):
    """
    Stream responses using the ExtendedState graph.
    """
    try:
        logger.info(
            f"extensions-server | /query/stream | Processing streaming query for user {request.user_id} "
            f"on channel {request.current_channel}: {request.query}"
        )
        
        # Handle image-only queries
        if request.image and not request.query:
            request.query = "The user has submitted an image, and is looking for items from the catalog that appear similar."
        
        # Initialize extended state
        state = create_initial_extended_state(request)
        
        async def send_updates():
            try:
                async for chunk in graph.astream(state, stream_mode="custom"):
                    yield f"data: {chunk}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error(f"Error in streaming updates: {e}")
                yield f"data: {json.dumps({'type': 'error', 'payload': str(e)})}\n\n"

        return StreamingResponse(send_updates(), media_type="text/event-stream")
        
    except Exception as e:
        logger.error(f"Error processing streaming query: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query/timing", response_model=QueryResponse)
async def process_query_timing(request: QueryRequest):
    """
    Process timing runs using the ExtendedState graph.
    """
    try:
        logger.info(f"extensions-server | /query/timing | Processing timing query for user {request.user_id}: {request.query}")
        
        state = create_initial_extended_state(request)
        
        start_time = time.monotonic()
        out_state_dict = await graph.ainvoke(state)
        end_time = time.monotonic()
        
        total_time = end_time - start_time
        
        # Extracted values from state dict output
        response = QueryResponse(
            response=out_state_dict.get("response", ""),
            images={},
            timings=out_state_dict.get("timings", {})
        )
        response.timings["total"] = total_time
        
        logger.info(f"extensions-server | /query | Successfully processed timing query in {total_time:.2f}s")
        return response

    except Exception as e:
        logger.error(f"Error processing timing query: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "2.0.0",
        "mode": "extended"
    }

@app.get("/")
async def root():
    """Root endpoint info."""
    return {
        "message": "Shopping Assistant Extended API (Omnichannel Sales Agent)",
        "version": "2.0.0",
        "endpoints": {
            "query": "/query",
            "stream": "/query/stream",
            "timing": "/query/timing",
            "health": "/health",
            "docs": "/docs"
        }
    }
