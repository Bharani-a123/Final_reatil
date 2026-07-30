import sys
import os
import asyncio

# Set stdout encoding to UTF-8 to prevent charmap errors on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Add paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set fallback env keys
os.environ.setdefault("LLM_API_KEY", "mock_key")
os.environ.setdefault("EMBED_API_KEY", "mock_key")
os.environ.setdefault("CONFIG_OVERRIDE", "config-build.yaml")
os.environ.setdefault("SHARED_CONFIG_ROOT", "C:\\Final_retail\\shared\\configs")

from src.state import ExtendedState
from src.main import graph, config
from src.database import SessionLocal, InventoryItem, CustomerProfile

# Export Razorpay Test Keys
os.environ["RAZORPAY_KEY_ID"] = "rzp_test_TInHtHhI5I48Mg"
os.environ["RAZORPAY_KEY_SECRET"] = "VSO3oG5CF11zNNWOtzW1DVPA"

def get_db_state():
    db = SessionLocal()
    try:
        item = db.query(InventoryItem).filter(InventoryItem.name == "Lovable Women Spice White Bra").first()
        cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == "cust_001").first()
        return {
            "inventory_online": item.online_warehouse if item else None,
            "customer_history": cust.purchase_history if cust else None,
        }
    finally:
        db.close()

async def main():
    config.memory_port = "http://127.0.0.1:8011"
    
    print("\n==============================================")
    print("  Razorpay-Only End-to-End Commerce Loop Test  ")
    print("==============================================")

    import requests
    try:
        requests.post("http://127.0.0.1:8011/user/123/cart/clear")
        requests.post("http://127.0.0.1:8011/user/123/cart/add", json={"item": "Lovable Women Spice White Bra", "amount": 2, "price": 25.0})
    except Exception as e:
        print("Warning: Could not seed cart:", e)

    print("Initial DB State:")
    print(get_db_state())

    from chain_server.src.agenttypes import Cart
    state = ExtendedState(
        user_id=123,
        customer_id="cust_001",
        cart=Cart(contents=[{"item": "Lovable Women Spice White Bra", "amount": 2, "price": 25.0}]),
        current_channel="web",
        query="Is Lovable Women Spice White Bra in stock?",
        context=""
    )

    # 1. Stock check
    result = await graph.ainvoke(state)
    print(f"\n[Stock Check] Routed: {result.get('next_agent')}")
    print(f"Response: {result.get('response')}")

    # 2. Fulfillment selection
    state = ExtendedState(**{**result, "query": "Deliver it to 742 Evergreen Terrace"})
    result = await graph.ainvoke(state)
    print(f"\n[Fulfillment] Routed: {result.get('next_agent')}")
    print(f"Response: {result.get('response')}")

    # 3. Pay (Triggers Razorpay Payment Link Generation)
    state = ExtendedState(**{**result, "query": "I want to pay now"})
    result = await graph.ainvoke(state)
    print(f"\n[Payment Link Generation] Routed: {result.get('next_agent')}")
    print(f"Razorpay Link ID: {result.get('razorpay_link_id')}")
    print(f"Razorpay Short URL: {result.get('razorpay_short_url')}")
    print(f"Payment Status: {result.get('payment_status')}")
    print(f"Response:\n{result.get('response')}")

    # 4. Verify status (polling pending)
    print("\n--- Verifying status before payment is captured ---")
    state = ExtendedState(**{**result, "query": "verify my payment status"})
    result = await graph.ainvoke(state)
    print(f"[Payment Status Poll] Payment Status: {result.get('payment_status')}")
    print(f"Response:\n{result.get('response')}")

    # 5. Simulate successful payment capture
    print("\n--- Simulating successful user payment capture ---")
    result["payment_status"] = "authorized"
    result["payment_method"] = "razorpay"

    # 6. Finalize Fulfillment (should succeed, decrement inventory, append customer history, and clear cart)
    state = ExtendedState(**{**result, "query": "Finalize my shipping selection to 742 Evergreen Terrace"})
    result = await graph.ainvoke(state)
    print(f"\n[Fulfillment Finalize] Routed: {result.get('next_agent')}")
    print(f"Final Cart: {result.get('cart').contents}")
    print(f"Tracking Code: {result.get('tracking_number')}")
    print(f"Response: {result.get('response')}")

    print("\nFinal DB State:")
    print(get_db_state())

if __name__ == "__main__":
    asyncio.run(main())
