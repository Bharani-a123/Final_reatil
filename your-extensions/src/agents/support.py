# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SupportAgent handles post-purchase requests like order tracking status and return/exchange registrations.
Updates tracking fields in state and logs return reasons statefully.
"""
import os
import json
import logging
import time
from openai import OpenAI

from ..state import ExtendedState
from ..functions import check_order_status_function, request_order_return_function, parse_tool_call_fallback
from ..database import SessionLocal, CustomerProfile

logger = logging.getLogger(__name__)

class SupportAgent:
    def __init__(self, config) -> None:
        self.llm_name = config.llm_name
        self.llm_port = config.llm_port
        self.model = OpenAI(base_url=config.llm_port, api_key=os.environ["LLM_API_KEY"])
        self.chat_kwargs = {}
        if "nvidia" in config.llm_port or "nemotron" in config.llm_name:
            self.chat_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}

    def _check_status(self, ref: str, state: ExtendedState) -> str:
        if not ref:
            return "Please provide an order reference ID (starting with REF_)."

        # Simple verification against state tracking
        if state.tracking_number == ref:
            method = state.fulfillment_method or "ship_to_home"
            if method == "ship_to_home":
                return (
                    f"Order status for **{ref}**:\n"
                    f"  - Status: **Shipped** (In-Transit)\n"
                    f"  - Destination: {state.delivery_address or 'Registered Home Address'}\n"
                    f"  - Carrier: Fedex Express"
                )
            else:
                return (
                    f"Order status for **{ref}**:\n"
                    f"  - Status: **Ready for Pickup** at Downtown Store\n"
                    f"  - Code: {ref}\n"
                    f"  - Pickup Slot: {state.delivery_slot or 'Tomorrow at 10:00 AM'}"
                )
        
        # Heuristic fallback lookup if order ref doesn't match current session's tracking number
        # Simulate lookup success
        return (
            f"Order status for reference **{ref}**:\n"
            f"  - Status: **Delivered successfully** (Received 2 days ago)\n"
            f"  - Signature: Left at front porch"
        )

    def _request_return(self, ref: str, item: str, reason: str, state: ExtendedState) -> str:
        if not ref or not item:
            return "Please provide both the order reference number (REF_xxxxxx) and the name of the item to return."

        status_msg = f"Return Requested: {item} on {ref} (Reason: {reason or 'Not Specified'})"
        state.return_status = status_msg

        return (
            f"📦 **Return Request Submitted!**\n"
            f"Your request to return **{item}** from order **{ref}** has been successfully registered.\n"
            f"  - Reason: {reason or 'Not specified'}\n"
            f"  - Return Status: **Pending Approval**\n\n"
            f"A prepaid return shipping label has been generated and emailed to your registered address."
        )

    def invoke(self, state: ExtendedState, verbose: bool = True) -> ExtendedState:
        start = time.monotonic()
        logger.info(f"SupportAgent.invoke() | Query: {state.query}")

        system_prompt = (
            "You are a post-purchase support specialist. You have two tools:\n"
            "1. check_order_status: to track/query a previous order.\n"
            "2. request_order_return: to register return/refund requests.\n"
            "Select the correct tool call and extract arguments. Do not reply with plain text."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"USER QUERY: {state.query}\nTRACKING: {state.tracking_number}"}
        ]

        tool_name = None
        tool_args = {}

        # Mock fallback mode
        if os.environ.get("LLM_API_KEY") == "mock_key":
            logger.info("SupportAgent | Running in mock mode.")
            query_lower = state.query.lower()
            
            # Simple keyword tool classifier
            if "return" in query_lower or "exchange" in query_lower or "refund" in query_lower:
                tool_name = "request_order_return"
                ref = "REF_123456"
                if "ref_" in query_lower:
                    # extract ref
                    parts = query_lower.split("ref_")
                    ref = "REF_" + parts[1][:6].upper()
                item = "Lovable Women Spice White Bra"
                if "bra" in query_lower:
                    item = "Lovable Women Spice White Bra"
                elif "brief" in query_lower:
                    item = "Jockey ELANCE Men Grey Brief 1008"
                reason = "Size mismatch"
                if "reason" in query_lower:
                    reason = state.query.split("reason")[-1].strip(" :")
                tool_args = {"order_reference": ref, "item_name": item, "reason": reason}
            else:
                tool_name = "check_order_status"
                ref = "REF_123456"
                if "ref_" in query_lower:
                    parts = query_lower.split("ref_")
                    ref = "REF_" + parts[1][:6].upper()
                elif state.tracking_number:
                    ref = state.tracking_number
                tool_args = {"order_reference": ref}
        else:
            response = self.model.chat.completions.create(
                model=self.llm_name,
                messages=messages,
                temperature=0.0,
                tools=[check_order_status_function, request_order_return_function],
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
        if tool_name == "check_order_status":
            ref = tool_args.get("order_reference", "")
            output_state.response = self._check_status(ref, state)
        elif tool_name == "request_order_return":
            ref = tool_args.get("order_reference", "")
            item = tool_args.get("item_name", "")
            reason = tool_args.get("reason", "")
            output_state.response = self._request_return(ref, item, reason, state)
        else:
            output_state.response = "Please provide your order reference number (REF_xxxxxx) for status check or return requests."

        end = time.monotonic()
        output_state.context = output_state.context + f"\nAgent Response: {output_state.response}"
        output_state.add_timing("support", end - start)
        return output_state
