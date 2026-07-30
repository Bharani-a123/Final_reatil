# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
LoyaltyAgent handles coupon rules and points redemptions statefully against the SQLite database.
Adds discount line items to the cart and mutates state savings variables.
"""
import os
import json
import logging
import time
from openai import OpenAI

from ..state import ExtendedState
from ..functions import apply_loyalty_discount_function, parse_tool_call_fallback
from ..database import SessionLocal, CustomerProfile, CouponRule

logger = logging.getLogger(__name__)

class LoyaltyAgent:
    def __init__(self, config) -> None:
        self.config = config
        self.llm_name = config.llm_name
        self.llm_port = config.llm_port
        self.model = OpenAI(base_url=config.llm_port, api_key=os.environ["LLM_API_KEY"])
        self.chat_kwargs = {}
        if "nvidia" in config.llm_port or "nemotron" in config.llm_name:
            self.chat_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    def _apply_discount(self, redeem_points: bool, coupon_code: str, state: ExtendedState) -> str:
        db = SessionLocal()
        try:
            # 1. Fetch customer profile
            cust = None
            if state.customer_id:
                cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == state.customer_id).first()
            if not cust:
                # Default fallback lookup
                cust = db.query(CustomerProfile).first()

            if cust:
                state.customer_id = cust.customer_id
                state.loyalty_tier = cust.loyalty_tier
                state.loyalty_points = cust.loyalty_points

            # Compute current cart total
            cart_total = 0.0
            for entry in state.cart.contents:
                price = entry.get("price")
                amount = entry.get("amount", 1)
                # Ignore previous discount items when computing total
                if price is not None and entry.get("item") != "Loyalty Discount":
                    cart_total += float(price) * amount

            discount_applied = 0.0
            messages = []

            # 2. Handle Coupon Code
            if coupon_code:
                coupon = db.query(CouponRule).filter(CouponRule.code == coupon_code).first()
                if not coupon:
                    return f"The coupon code '{coupon_code}' is invalid or expired."
                
                # Validate requirements
                if cart_total < coupon.min_order_value:
                    return f"Coupon '{coupon_code}' requires a minimum order value of ${coupon.min_order_value:.2f} (current is ${cart_total:.2f})."
                
                # Calculate discount
                if coupon.discount_percentage:
                    discount_applied += cart_total * (coupon.discount_percentage / 100.0)

                state.applied_coupon = coupon_code
                messages.append(f"Applied coupon '{coupon_code}' successfully!")

            # 3. Handle Points Redemption (10 points = $1.00)
            if redeem_points and cust and cust.loyalty_points > 0:
                points_to_redeem = cust.loyalty_points
                points_value = points_to_redeem / 10.0 # e.g. 150 points = $15.00
                
                # Don't exceed cart total
                if points_value > (cart_total - discount_applied):
                    points_value = cart_total - discount_applied
                    points_to_redeem = int(points_value * 10)

                if points_to_redeem > 0:
                    discount_applied += points_value
                    # Deduct points in DB
                    cust.loyalty_points -= points_to_redeem
                    db.commit()
                    
                    state.loyalty_points = cust.loyalty_points
                    messages.append(f"Redeemed {points_to_redeem} loyalty points for a ${points_value:.2f} discount.")

            if discount_applied > 0.0:
                state.loyalty_savings = discount_applied
                
                # Check if a "Loyalty Discount" item is already in the cart and remove it
                state.cart.contents = [c for c in state.cart.contents if c.get("item") != "Loyalty Discount"]
                
                # Add negative line item representing savings
                state.cart.contents.append({
                    "item": "Loyalty Discount",
                    "amount": 1,
                    "price": -discount_applied
                })
                
                # Also request memory retriever to update cart in background
                try:
                    import requests
                    # Add discount item to memory retriever cart
                    requests.post(
                        f"{self.config.memory_port}/user/{state.user_id}/cart/add",
                        json={"item": "Loyalty Discount", "amount": 1, "price": -discount_applied}
                    )
                except Exception as e:
                    logger.error(f"Failed to post discount line to memory-retriever: {e}")

                final_total = cart_total - discount_applied
                messages.append(f"Your total savings are **${discount_applied:.2f}**. New cart total is **${final_total:.2f}**.")
                return "\n".join(messages)
            else:
                return "No discounts could be applied to your order."

        except Exception as e:
            logger.error(f"Loyalty discount exception: {e}")
            return "Loyalty service encountered an error processing your discount request."
        finally:
            db.close()

    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        start = time.monotonic()
        logger.info(f"LoyaltyAgent.invoke() | Query: {state.query}")

        # Sync profile info from DB if not already loaded
        db = SessionLocal()
        try:
            cust = None
            if state.customer_id:
                cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == state.customer_id).first()
            if not cust:
                cust = db.query(CustomerProfile).first()
            if cust:
                state.customer_id = cust.customer_id
                state.loyalty_tier = cust.loyalty_tier
                state.loyalty_points = cust.loyalty_points
        finally:
            db.close()

        system_prompt = (
            "You are a retail loyalty and coupon coordinator. Your ONLY job is to execute the apply_loyalty_discount "
            "tool call to apply savings. Do not return plain text.\n"
            "If the user wants to redeem their points or use rewards, set redeem_points to true.\n"
            "If the user mentions a coupon code (e.g. WELCOME10, GOLD20), extract it into coupon_code."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"USER QUERY: {state.query}\nTIER: {state.loyalty_tier}\nPOINTS: {state.loyalty_points}"}
        ]

        tool_name = None
        tool_args = {}

        # Mock fallback mode
        if os.environ.get("LLM_API_KEY") == "mock_key":
            logger.info("LoyaltyAgent | Running in mock mode.")
            tool_name = "apply_loyalty_discount"
            redeem = False
            code = ""
            query_lower = state.query.lower()
            if "point" in query_lower or "redeem" in query_lower or "reward" in query_lower:
                redeem = True
            
            # Extract coupon codes
            for c in ["WELCOME10", "GOLD20"]:
                if c.lower() in query_lower:
                    code = c
            tool_args = {"redeem_points": redeem, "coupon_code": code}
        else:
            response = self.model.chat.completions.create(
                model=self.llm_name,
                messages=messages,
                temperature=0.0,
                tools=[apply_loyalty_discount_function],
                tool_choice="auto",
                **self.chat_kwargs
            )
            message = response.choices[0].message
            if message.tool_calls:
                called_tool = message.tool_calls[0]
                tool_name = called_tool.function.name
                tool_args = json.loads(called_tool.function.arguments)
            else:
                tool_name, tool_args = parse_tool_call_fallback(message.content)

        output_state = state
        if tool_name == "apply_loyalty_discount":
            redeem_points = tool_args.get("redeem_points", False)
            coupon_code = tool_args.get("coupon_code", "")
            output_state.response = self._apply_discount(redeem_points, coupon_code, state)
        else:
            output_state.response = "I couldn't apply a loyalty discount. Please specify a coupon code or points redemption."

        end = time.monotonic()
        output_state.context = output_state.context + f"\nAgent Response: {output_state.response}"
        output_state.add_timing("loyalty", end - start)
        return output_state
