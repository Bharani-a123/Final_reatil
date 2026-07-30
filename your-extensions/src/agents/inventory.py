# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
InventoryAgent checks product availability across different stores/warehouses.
Queries the SQLite commerce.db database statefully.
"""
import os
import json
import logging
import time
from openai import OpenAI
from typing import Dict, Any, List

from ..state import ExtendedState
from ..functions import check_inventory_stock_function, parse_tool_call_fallback
from ..database import query_inventory_by_name, SessionLocal, InventoryItem

logger = logging.getLogger(__name__)

class InventoryAgent:
    def __init__(self, config) -> None:
        self.llm_name = config.llm_name
        self.llm_port = config.llm_port
        self.model = OpenAI(base_url=config.llm_port, api_key=os.environ["LLM_API_KEY"])
        self.chat_kwargs = {}
        if "nvidia" in config.llm_port or "nemotron" in config.llm_name:
            self.chat_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    def _check_stock(self, item_name: str, location: str, state: ExtendedState) -> str:
        db = SessionLocal()
        try:
            items_to_check = []
            
            # If item_name is provided, check that specific item
            if item_name:
                # Query catalog name match
                inv_item = query_inventory_by_name(item_name)
                if inv_item:
                    items_to_check.append(inv_item)
                else:
                    # Try to search using SQLAlchemy filter
                    inv_item = db.query(InventoryItem).filter(InventoryItem.name.like(f"%{item_name}%")).first()
                    if inv_item:
                        items_to_check.append(inv_item)
                    else:
                        return f"I could not locate any product named '{item_name}' in our inventory catalog."
            else:
                # Check all items currently in cart
                if not state.cart or not state.cart.contents:
                    return "Your shopping cart is empty, so there are no items to check stock for."
                for entry in state.cart.contents:
                    item_in_cart = entry.get("item", "")
                    inv_item = query_inventory_by_name(item_in_cart)
                    if inv_item:
                        items_to_check.append(inv_item)
                    else:
                        # Fallback search
                        inv_item = db.query(InventoryItem).filter(InventoryItem.name.like(f"%{item_in_cart}%")).first()
                        if inv_item:
                            items_to_check.append(inv_item)

            if not items_to_check:
                return "No items could be resolved to inventory products."

            lines = []
            for item in items_to_check:
                lines.append(f"Stock status for **{item.name}**:")
                if location in ("all", "online_warehouse"):
                    lines.append(f"  - Online Warehouse: {item.online_warehouse} units")
                if location in ("all", "store_downtown"):
                    lines.append(f"  - Downtown Store: {item.store_downtown} units")
                if location in ("all", "store_suburbs"):
                    lines.append(f"  - Suburbs Store: {item.store_suburbs} units")
            
            return "\n".join(lines)
        finally:
            db.close()

    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        start = time.monotonic()
        logger.info(f"InventoryAgent.invoke() | Query: {state.query}")
        
        system_prompt = (
            "You are a retail inventory agent. Your ONLY job is to execute the check_inventory_stock "
            "tool call to check product stock across stores/locations. Do not return plain text.\n"
            "If the user does not specify a product, leave item_name blank to check all items in their cart.\n"
            "If the user asks about availability/stock at a specific store (e.g. downtown), set location accordingly."
        )

        # Local mock mode fallback
        if os.environ.get("LLM_API_KEY") == "mock_key":
            logger.info("InventoryAgent | Running in mock mode.")
            tool_name = "check_inventory_stock"
            item_name = ""
            # Simple keyword matching for products
            for name in [
                "Lovable Women Spice White Bra", "Avirate Black Bra", "Enamor Navy Blue Smooth Bra",
                "Jockey ELANCE Men Grey Melange Brief 1008", "Biara Skin Coloured Everyday Support Bra MW 1002"
            ]:
                words = name.lower().split()
                # If product name or two keywords match
                if name.lower() in state.query.lower() or sum(1 for w in words[:3] if w in state.query.lower()) >= 2:
                    item_name = name
                    break
            
            location = "all"
            if "downtown" in state.query.lower():
                location = "store_downtown"
            elif "suburb" in state.query.lower():
                location = "store_suburbs"
            elif "online" in state.query.lower() or "warehouse" in state.query.lower():
                location = "online_warehouse"
            
            tool_args = {"item_name": item_name, "location": location}
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"USER QUERY: {state.query}\nCURRENT CART: {[c.get('item') for c in state.cart.contents]}"}
            ]

            response = self.model.chat.completions.create(
                model=self.llm_name,
                messages=messages,
                temperature=0.0,
                tools=[check_inventory_stock_function],
                tool_choice="auto",
                **self.chat_kwargs
            )

            message = response.choices[0].message
            tool_name = None
            tool_args = {}

            if message.tool_calls:
                called_tool = message.tool_calls[0]
                tool_name = called_tool.function.name
                tool_args = json.loads(called_tool.function.arguments)
            else:
                tool_name, tool_args = parse_tool_call_fallback(message.content)

        output_state = state
        if tool_name == "check_inventory_stock":
            item_name = tool_args.get("item_name", "")
            location = tool_args.get("location", "all")
            output_state.response = self._check_stock(item_name, location, state)
        else:
            output_state.response = "I encountered an issue determining which product or store stock level you want to check."

        end = time.monotonic()
        output_state.context = output_state.context + f"\nAgent Response: {output_state.response}"
        output_state.add_timing("inventory", end - start)
        return output_state
