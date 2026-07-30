# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
PaymentAgent processes customer transactions statefully using the payments_stub database table.
Handles success cases, insufficient funds declines, and gift card balance deductions.
"""
import os
import json
import logging
import time
from openai import OpenAI

from ..state import ExtendedState
from ..functions import process_checkout_payment_function, parse_tool_call_fallback
from ..database import SessionLocal, PaymentStub, CustomerProfile, InventoryItem, update_inventory_stock

logger = logging.getLogger(__name__)

class PaymentAgent:
    def __init__(self, config) -> None:
        self.config = config
        self.memory_port = config.memory_port
        self.llm_name = config.llm_name
        self.llm_port = config.llm_port
        self.model = OpenAI(base_url=config.llm_port, api_key=os.environ["LLM_API_KEY"])
        self.chat_kwargs = {}
        if "nvidia" in config.llm_port or "nemotron" in config.llm_name:
            self.chat_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    def _process_payment(self, args: dict, state: ExtendedState) -> str:
        import requests
        rzp_key = os.environ.get("RAZORPAY_KEY_ID")
        rzp_secret = os.environ.get("RAZORPAY_KEY_SECRET")

        # Calculate total cart cost
        cart_total = 0.0
        for entry in state.cart.contents:
            price = entry.get("price")
            amount = entry.get("amount", 1)
            if price is not None:
                try:
                    cart_total += float(price) * amount
                except (TypeError, ValueError):
                    pass
        cart_total = max(cart_total, 0.0)

        # 1. Razorpay Integration path
        if rzp_key and rzp_secret and rzp_key != "mock_key":
            amount_in_inr = cart_total * 85.0 # Mock exchange rate
            amount_in_paise = min(max(int(amount_in_inr * 100), 100), 10000000) # Minimum ₹1.00, maximum ₹1,00,000 to prevent Razorpay limits

            # If we don't have a payment link yet, create one
            if not state.razorpay_link_id:
                try:
                    payload = {
                        "amount": amount_in_paise,
                        "currency": "INR",
                        "accept_partial": False,
                        "description": f"Payment for shopping cart checkout of total {cart_total:.2f} USD",
                        "customer": {
                            "name": "Sarah Connor",
                            "email": "sarah.connor@example.com",
                            "contact": "+919876543210"
                        },
                        "notify": {"sms": False, "email": False},
                        "callback_url": "http://localhost:3000",
                        "callback_method": "get"
                    }
                    response = requests.post(
                        "https://api.razorpay.com/v1/payment_links",
                        json=payload,
                        auth=(rzp_key, rzp_secret),
                        timeout=10
                    )
                    if response.status_code in (200, 201):
                        data = response.json()
                        state.razorpay_link_id = data.get("id")
                        state.razorpay_short_url = data.get("short_url")
                        state.payment_status = "processing"
                        return (
                            f"I've generated a secure Razorpay Payment Link for your order total of "
                            f"**₹{amount_in_inr:.2f}** (approximately ${cart_total:.2f} USD).\n\n"
                            f"Please complete the payment here: **[Pay with Razorpay]({state.razorpay_short_url})**\n\n"
                            f"Once you've made the payment, just say **'I have paid'** or **'verify my payment'** "
                            f"and I will confirm the transaction status!"
                        )
                    else:
                        logger.error(f"Razorpay Error response: {response.text}")
                        return "Failed to create a payment link with Razorpay. Please try again."
                except Exception as e:
                    logger.error(f"Failed to communicate with Razorpay: {e}")
                    return "I encountered a network issue reaching the Razorpay payment gateway. Please retry."
            else:
                # We have a payment link, verify its status and check for failed attempts
                try:
                    # Check payment attempts
                    attempts_resp = requests.get(
                        f"https://api.razorpay.com/v1/payments?payment_link_id={state.razorpay_link_id}",
                        auth=(rzp_key, rzp_secret),
                        timeout=10
                    )
                    error_msg = None
                    if attempts_resp.status_code == 200:
                        attempts_data = attempts_resp.json()
                        items = attempts_data.get("items") or []
                        if items:
                            items.sort(key=lambda x: x.get("created_at", 0), reverse=True)
                            latest = items[0]
                            if latest.get("status") == "failed":
                                error_msg = latest.get("error_description") or "Payment attempt failed."

                    response = requests.get(
                        f"https://api.razorpay.com/v1/payment_links/{state.razorpay_link_id}",
                        auth=(rzp_key, rzp_secret),
                        timeout=10
                    )
                    if response.status_code == 200:
                        data = response.json()
                        status = data.get("status")
                        if status == "paid":
                            state.payment_status = "authorized"
                            state.payment_method = "razorpay"
                            
                            # 1. Decrement stock for purchased items
                            db = SessionLocal()
                            try:
                                for entry in state.cart.contents:
                                    item_name = entry.get("item", "")
                                    amount = entry.get("amount", 1)
                                    location = "online_warehouse"
                                    if state.fulfillment_method in ("click_and_collect", "in_store_reserve"):
                                        location = "store_downtown"
                                    
                                    inv_item = db.query(InventoryItem).filter(InventoryItem.name == item_name).first()
                                    if inv_item:
                                        update_inventory_stock(inv_item.sku, location, -amount)
                                    else:
                                        inv_item = db.query(InventoryItem).filter(InventoryItem.name.like(f"%{item_name}%")).first()
                                        if inv_item:
                                            update_inventory_stock(inv_item.sku, location, -amount)
                            except Exception as ex:
                                logger.error(f"Failed to decrement stock in payment verification: {ex}")
                            finally:
                                db.close()

                            # 2. Proceed with fulfillment flow
                            import random
                            ref_number = f"REF_{random.randint(100000, 999999)}"
                            state.fulfillment_status = "fulfilled" if state.fulfillment_method == "ship_to_home" else "ready_for_pickup"
                            state.fulfillment_ref = ref_number
                            
                            fulfillment_desc = ""
                            if state.fulfillment_method == "ship_to_home":
                                fulfillment_desc = f"Your order will be shipped to **{state.delivery_address}** (Tracking Ref: **{ref_number}**)."
                            elif state.fulfillment_method == "click_and_collect":
                                fulfillment_desc = f"Your order is ready for pickup at our Downtown Store (Slot: **{state.delivery_slot or 'tomorrow morning'}**, Ref: **{ref_number}**)."
                            else:
                                fulfillment_desc = f"Your reservation is confirmed for try-on at our Downtown Store (Slot: **{state.delivery_slot or 'today afternoon'}**, Ref: **{ref_number}**)."

                            # 3. Clear session.cart
                            try:
                                clear_resp = requests.post(f"{self.memory_port}/user/{state.user_id}/cart/clear", timeout=3.0)
                                if clear_resp.status_code == 200:
                                    state.cart.contents = []
                                else:
                                    # Fallback
                                    requests.post(f"http://127.0.0.1:8011/user/{state.user_id}/cart/clear", timeout=3.0)
                                    state.cart.contents = []
                            except Exception as ex:
                                logger.error(f"Failed to clear cart: {ex}")
                            
                            return (
                                f"🎉 **Payment Verified!** Razorpay confirmed that your payment of "
                                f"**₹{amount_in_inr:.2f}** has been successfully captured.\n\n"
                                f"**Order Confirmation & Fulfillment Status**:\n"
                                f"- {fulfillment_desc}\n\n"
                                f"Thank you for shopping with us! Your cart has been cleared."
                            )
                        elif error_msg:
                            state.payment_status = "failed"
                            return (
                                f"❌ **Payment Failed!** Razorpay declined the transaction: **{error_msg}**.\n\n"
                                f"Please try paying again using a different test card/UPI instrument: "
                                f"**[Pay with Razorpay]({state.razorpay_short_url})**"
                            )
                        else:
                            return (
                                f"Your payment is still pending. Please complete the transaction using the link: "
                                f"**[Pay with Razorpay]({state.razorpay_short_url})**.\n\n"
                                f"Once paid, let me know so I can check again!"
                            )
                    else:
                        logger.error(f"Razorpay Status Check Error: {response.text}")
                        return "Could not verify your payment status with Razorpay at this moment. Please retry."
                except Exception as e:
                    logger.error(f"Razorpay Verification exception: {e}")
                    return "Error contacting Razorpay to verify payment. Please retry."

        # 2. Enforce secure Razorpay only: raise configuration error if missing
        else:
            state.payment_status = "declined"
            state.payment_attempts += 1
            return "Secure payment gateway is currently unconfigured. Please check payment credentials."

    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        start = time.monotonic()
        logger.info(f"PaymentAgent.invoke() | Query: {state.query}")

        system_prompt = (
            "You are a retail payment manager. Your ONLY job is to execute the process_checkout_payment "
            "tool call to authorize transactions. Do not return plain text.\n"
            "If the user provides a card number, extract the last 4 digits for card_number_suffix.\n"
            "If they provide a UPI ID (e.g. name@upi), extract it for upi_id.\n"
            "If they provide a gift card code, extract it for gift_card_code."
        )

        # Local mock mode fallback
        if os.environ.get("LLM_API_KEY") == "mock_key":
            logger.info("PaymentAgent | Running in mock mode.")
            tool_name = "process_checkout_payment"
            method = "card"
            card_suffix = "4242"
            upi_id = "sarah@upi"
            gift_code = "GIFT_100"
            
            query_lower = state.query.lower()
            if "upi" in query_lower:
                method = "upi"
                if "tony" in query_lower:
                    upi_id = "tony@upi"
            elif "gift" in query_lower:
                method = "gift_card"
                if "expired" in query_lower:
                    gift_code = "GIFT_EXPIRED"
            else:
                method = "card"
                if "9999" in query_lower:
                    card_suffix = "9999"
                    
            tool_args = {
                "payment_method": method,
                "card_number_suffix": card_suffix,
                "upi_id": upi_id,
                "gift_card_code": gift_code
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
                tools=[process_checkout_payment_function],
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
        query_lower = (state.query or "").lower()
        if tool_name == "process_checkout_payment" or any(w in query_lower for w in ["checkout", "pay", "verify", "paid"]):
            output_state.response = self._process_payment(tool_args, state)
        else:
            output_state.response = "I couldn't process that payment. Please specify the payment method (UPI, Card, or Gift Card)."

        end = time.monotonic()
        output_state.context = output_state.context + f"\nAgent Response: {output_state.response}"
        output_state.add_timing("payment", end - start)
        return output_state
