# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
ExtendedState definition for the Omnichannel Conversational Sales Agent.
Inherits from the core State model and adds context fields.
"""
from chain_server.src.agenttypes import State as CoreState, Cart as CoreCart
from pydantic import Field
from typing import Optional, Dict, Any, List

class ExtendedState(CoreState):
    # Channel & Session Management
    current_channel: str = Field(default="web", description="The current active channel (e.g. web, mobile, whatsapp, kiosk)")
    customer_id: Optional[str] = Field(default=None, description="The customer identifier matching user profile database records")
    retrieved: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Dictionary of retrieved product information and pricing")
    
    # Loyalty & Offers Status
    loyalty_tier: str = Field(default="None", description="Loyalty tier of the customer (None, Bronze, Silver, Gold, Platinum)")
    loyalty_points: int = Field(default=0, description="Loyalty points balance")
    applied_coupon: Optional[str] = Field(default=None, description="Applied coupon code")
    loyalty_savings: float = Field(default=0.0, description="Savings in dollars from discounts or loyalty points")
    
    # Fulfillment State
    fulfillment_method: Optional[str] = Field(default=None, description="Fulfillment choice (ship_to_home, click_and_collect, in_store_reserve)")
    delivery_address: Optional[str] = Field(default=None, description="Shipping address for ship_to_home")
    delivery_slot: Optional[str] = Field(default=None, description="Time slot or reservation details")
    
    # Payment State
    payment_method: Optional[str] = Field(default=None, description="Active payment method (card, upi, gift_card, pos)")
    payment_status: str = Field(default="unpaid", description="Status of payment transaction (unpaid, processing, authorized, declined)")
    payment_attempts: int = Field(default=0, description="Count of payment transaction attempts")
    
    # Support & Tracking
    tracking_number: Optional[str] = Field(default=None, description="Tracking identifier for shipped orders")
    return_status: Optional[str] = Field(default=None, description="Current tracking of returns or exchanges")
    
    # Razorpay Integration Fields
    razorpay_link_id: Optional[str] = Field(default=None, description="The Razorpay Payment Link ID")
    razorpay_short_url: Optional[str] = Field(default=None, description="The Razorpay short URL for payment link")
    order_status: Optional[str] = Field(default=None, description="Status of the placed order (e.g. placed, cancelled)")
