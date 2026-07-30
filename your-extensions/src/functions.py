# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Tool function definitions for Extended Agents.
"""
from chain_server.src.functions import parse_tool_call_fallback

check_inventory_stock_function = {
    "type": "function",
    "function": {
        "name": "check_inventory_stock",
        "description": "Checks the real-time stock levels of items in the cart or specified products across different locations.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_name": {
                    "type": "string",
                    "description": "The exact name of the item to check. If empty, checks all items in the cart."
                },
                "location": {
                    "type": "string",
                    "enum": ["all", "online_warehouse", "store_downtown", "store_suburbs"],
                    "description": "The location to check. Defaults to 'all'."
                }
            },
            "required": []
        }
    }
}

select_fulfillment_function = {
    "type": "function",
    "function": {
        "name": "select_fulfillment",
        "description": "Selects the fulfillment method for the order (ship to home, click and collect, or in-store reserve) and schedules slots if necessary.",
        "parameters": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["ship_to_home", "click_and_collect", "in_store_reserve"],
                    "description": "The selected fulfillment method."
                },
                "address": {
                    "type": "string",
                    "description": "Shipping address. Required ONLY for 'ship_to_home'."
                },
                "delivery_slot": {
                    "type": "string",
                    "description": "Preferred time slot or date. Optional."
                }
            },
            "required": ["method"]
        }
    }
}

process_checkout_payment_function = {
    "type": "function",
    "function": {
        "name": "process_checkout_payment",
        "description": "Processes payment for the current cart using card details, UPI, or gift cards.",
        "parameters": {
            "type": "object",
            "properties": {
                "payment_method": {
                    "type": "string",
                    "enum": ["card", "upi", "gift_card"],
                    "description": "The type of payment method."
                },
                "card_number_suffix": {
                    "type": ["string", "null"],
                    "description": "Last 4 digits of the card. Required if payment_method is 'card'."
                },
                "upi_id": {
                    "type": ["string", "null"],
                    "description": "The customer's UPI ID. Required if payment_method is 'upi'."
                },
                "gift_card_code": {
                    "type": ["string", "null"],
                    "description": "The gift card code. Required if payment_method is 'gift_card'."
                }
            },
            "required": ["payment_method"]
        }
    }
}

apply_loyalty_discount_function = {
    "type": "function",
    "function": {
        "name": "apply_loyalty_discount",
        "description": "Applies a coupon discount or redeems loyalty points for order discounts.",
        "parameters": {
            "type": "object",
            "properties": {
                "redeem_points": {
                    "type": "boolean",
                    "description": "Set to true to redeem current loyalty points for balance discount."
                },
                "coupon_code": {
                    "type": "string",
                    "description": "The coupon code to apply (e.g. WELCOME10, GOLD20)."
                }
            },
            "required": []
        }
    }
}

check_order_status_function = {
    "type": "function",
    "function": {
        "name": "check_order_status",
        "description": "Checks the status, tracking details, or pickup slot of a previously placed order using its reference ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_reference": {
                    "type": "string",
                    "description": "The order reference tracking ID or pickup confirmation code (e.g. REF_123456)."
                }
            },
            "required": ["order_reference"]
        }
    }
}

request_order_return_function = {
    "type": "function",
    "function": {
        "name": "request_order_return",
        "description": "Submits a return or exchange request for a specific item in a completed order.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_reference": {
                    "type": "string",
                    "description": "The order reference ID (e.g. REF_123456)."
                },
                "item_name": {
                    "type": "string",
                    "description": "The name of the item to return or exchange."
                },
                "reason": {
                    "type": "string",
                    "description": "The reason for return/exchange (e.g. size mismatch, damaged)."
                }
            },
            "required": ["order_reference", "item_name"]
        }
    }
}

cancel_order_function = {
    "type": "function",
    "function": {
        "name": "cancel_order",
        "description": "Cancels a previously placed order using its reference ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "order_reference": {
                    "type": "string",
                    "description": "The order reference ID (e.g. REF_123456)."
                }
            },
            "required": ["order_reference"]
        }
    }
}
