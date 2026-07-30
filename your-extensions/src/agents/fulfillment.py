# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
FulfillmentAgent handles shipping (ship_to_home) or collection (click_and_collect / in_store_reserve) selections.
If payment is authorized, it statefully decrements inventory stock and generates tracking/reservation codes.
"""
import os
import json
import logging
import time
import random
from openai import OpenAI

from ..state import ExtendedState
from ..functions import select_fulfillment_function, parse_tool_call_fallback
from ..database import SessionLocal, InventoryItem, CustomerProfile, update_inventory_stock

logger = logging.getLogger(__name__)

class FulfillmentAgent:
    def __init__(self, config) -> None:
        self.llm_name = config.llm_name
        self.llm_port = config.llm_port
        self.memory_port = config.memory_port
        self.model = OpenAI(base_url=config.llm_port, api_key=os.environ["LLM_API_KEY"])
        self.chat_kwargs = {}
        if "nvidia" in config.llm_port or "nemotron" in config.llm_name:
            self.chat_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    def _complete_fulfillment(self, args: dict, state: ExtendedState) -> str:
        db = SessionLocal()
        try:
            method = args.get("method")
            address = args.get("address")
            slot = args.get("delivery_slot")

            if method == "ship_to_home" and not address:
                return "To ship the order to your home, please provide a valid shipping address."

            # Cache choices in state
            state.fulfillment_method = method
            state.delivery_address = address
            state.delivery_slot = slot

            # Calculate total cost
            cart_total = 0.0
            for entry in state.cart.contents:
                price = entry.get("price")
                amount = entry.get("amount", 1)
                if price is not None:
                    cart_total += float(price) * amount

            # If payment is not yet authorized, state is updated, ask for payment
            if state.payment_status != "authorized":
                fulfillment_desc = ""
                if method == "ship_to_home":
                    fulfillment_desc = f"shipping to **{address}**"
                elif method == "click_and_collect":
                    fulfillment_desc = f"click & collect at Downtown Store (slot: {slot or 'tomorrow morning'})"
                else:
                    fulfillment_desc = f"in-store try-on reservation (slot: {slot or 'today afternoon'})"

                return (
                    f"I've set your fulfillment preference to **{method.replace('_', ' ').title()}** ({fulfillment_desc}). "
                    f"Your order total is **${cart_total:.2f}**. Please provide your payment details (e.g. UPI or Card) to complete the checkout."
                )

            # If payment IS authorized, finalize the order and deduct stock statefully!
            # Deduct stock based on method
            location = "online_warehouse" # Default for ship_to_home
            if method in ("click_and_collect", "in_store_reserve"):
                location = "store_downtown" # Default store location for pickup in mock flow

            deduction_success = True
            lines = []
            for entry in state.cart.contents:
                item_name = entry.get("item", "")
                amount = entry.get("amount", 1)
                
                # Retrieve item to deduct
                inv_item = db.query(InventoryItem).filter(InventoryItem.name == item_name).first()
                if inv_item:
                    # Update stock counts in DB
                    success = update_inventory_stock(inv_item.sku, location, -amount)
                    if not success:
                        deduction_success = False
                else:
                    # Try fallback search
                    inv_item = db.query(InventoryItem).filter(InventoryItem.name.like(f"%{item_name}%")).first()
                    if inv_item:
                        success = update_inventory_stock(inv_item.sku, location, -amount)
                        if not success:
                            deduction_success = False

            if not deduction_success:
                logger.warning("FulfillmentAgent | stock deduction encountered issues.")

            # Generate tracking or reservation number
            ref_number = f"REF_{random.randint(100000, 999999)}"
            state.tracking_number = ref_number

            # Save purchase history in customer profile in DB
            if state.customer_id:
                cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == state.customer_id).first()
                if cust:
                    history = json.loads(cust.purchase_history or "[]")
                    for entry in state.cart.contents:
                        history.append(entry.get("item"))
                    cust.purchase_history = json.dumps(history)
                    db.commit()

            # Clear the cart state
            cart_items_desc = ", ".join([f"{c.get('amount')}x **{c.get('item')}**" for c in state.cart.contents])
            
            # Request memory retriever to clear cart
            try:
                import requests
                requests.post(f"{self.memory_port}/user/{state.user_id}/cart/clear")
            except Exception as e:
                logger.error(f"Failed to clear cart in memory: {e}")

            # Empty local state cart
            state.cart.contents = []

            # Confirmation message
            if method == "ship_to_home":
                return (
                    f"🎉 **Order Confirmed!**\n"
                    f"Thank you for shopping with us! We have processed your payment of **${cart_total:.2f}**.\n"
                    f"Your items ({cart_items_desc}) are being prepared for shipping to **{address}**.\n"
                    f"Your tracking number is **{ref_number}**."
                )
            else:
                collect_type = "collection" if method == "click_and_collect" else "try-on"
                return (
                    f"🎉 **Reservation Confirmed!**\n"
                    f"Your items ({cart_items_desc}) have been reserved for {collect_type} at our **Downtown Store**.\n"
                    f"Time slot: **{slot or 'Tomorrow at 10:00 AM'}**.\n"
                    f"Your pickup confirmation code is **{ref_number}**. See you soon!"
                )

        except Exception as e:
            logger.error(f"Fulfillment finalization error: {e}")
            return "Fulfillment service encountered an error finalizing your order. Please retry."
        finally:
            db.close()

    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        start = time.monotonic()
        logger.info(f"FulfillmentAgent.invoke() | Query: {state.query}")

        system_prompt = (
            "You are a retail fulfillment assistant. Your ONLY job is to execute the select_fulfillment "
            "tool call to choose delivery or in-store reservation slots. Do not return plain text.\n"
            "If the user wants delivery/shipping, set method to 'ship_to_home' and extract their address.\n"
            "If they want click-and-collect or to pick up/reserve, set method to 'click_and_collect' or 'in_store_reserve'.\n"
            "Extract any slot or timing request for delivery_slot."
        )

        # Local mock mode fallback
        if os.environ.get("LLM_API_KEY") == "mock_key":
            logger.info("FulfillmentAgent | Running in mock mode.")
            tool_name = "select_fulfillment"
            method = "ship_to_home"
            address = ""
            slot = ""
            
            query_lower = state.query.lower()
            if "collect" in query_lower or "pickup" in query_lower:
                method = "click_and_collect"
            elif "reserve" in query_lower or "try-on" in query_lower:
                method = "in_store_reserve"
            else:
                method = "ship_to_home"
                # Simple address extractor
                if " to " in query_lower:
                    address = state.query.split(" to ")[-1].strip()
                elif " at " in query_lower:
                    address = state.query.split(" at ")[-1].strip()
                else:
                    address = "123 Main Street, Bangalore"
            
            if "tomorrow" in query_lower:
                slot = "Tomorrow"
            elif "evening" in query_lower:
                slot = "Evening slot"
                
            tool_args = {
                "method": method,
                "address": address,
                "delivery_slot": slot
            }
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"USER QUERY: {state.query}"}
            ]

            response = self.model.chat.completions.create(
                model=self.llm_name,
                messages=messages,
                temperature=0.0,
                tools=[select_fulfillment_function],
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
        if tool_name == "select_fulfillment":
            output_state.response = self._complete_fulfillment(tool_args, state)
        else:
            output_state.response = "Please specify whether you would like home delivery or to reserve your items in-store."

        end = time.monotonic()
        output_state.context = output_state.context + f"\nAgent Response: {output_state.response}"
        output_state.add_timing("fulfillment", end - start)
        return output_state
