import sys
import os
import asyncio

# Set stdout encoding to UTF-8 to prevent charmap errors on Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Add paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("LLM_API_KEY", "mock_key")
os.environ.setdefault("EMBED_API_KEY", "mock_key")
os.environ.setdefault("CONFIG_OVERRIDE", "config-build.yaml")
os.environ.setdefault("SHARED_CONFIG_ROOT", "C:\\Final_retail\\shared\\configs")

from src.state import ExtendedState
from src.main import graph, config
from src.database import SessionLocal, CustomerProfile, CouponRule

async def test_loyalty_coupon():
    print("\n==============================================")
    print("  TEST 1: Apply Coupon Discount (WELCOME10)   ")
    print("==============================================")
    
    # Reset/seed memory retriever cart
    import requests
    try:
        requests.post("http://127.0.0.1:8011/user/123/cart/clear")
        requests.post("http://127.0.0.1:8011/user/123/cart/add", json={"item": "Lovable Women Spice White Bra", "amount": 2, "price": 25.0})
    except Exception as e:
        print("Warning: Could not seed cart:", e)

    from chain_server.src.agenttypes import Cart
    state = ExtendedState(
        user_id=123,
        customer_id="cust_001",
        cart=Cart(contents=[{"item": "Lovable Women Spice White Bra", "amount": 2, "price": 25.0}]),
        current_channel="web",
        query="apply coupon WELCOME10 to my cart",
        context=""
    )

    result = await graph.ainvoke(state)
    print(f"Routed: {result.get('next_agent')}")
    print(f"Savings: ${result.get('loyalty_savings'):.2f}")
    print(f"Cart contents: {result.get('cart').contents}")
    print(f"Response:\n{result.get('response')}")

async def test_loyalty_points():
    print("\n==============================================")
    print("  TEST 2: Redeem Loyalty Points                ")
    print("==============================================")
    
    # Check initial customer points in database
    db = SessionLocal()
    try:
        cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == "cust_001").first()
        print(f"Initial Points in DB for cust_001: {cust.loyalty_points}")
    finally:
        db.close()

    from chain_server.src.agenttypes import Cart
    state = ExtendedState(
        user_id=123,
        customer_id="cust_001",
        cart=Cart(contents=[{"item": "Lovable Women Spice White Bra", "amount": 2, "price": 25.0}]),
        current_channel="web",
        query="I want to redeem my points for discount",
        context=""
    )

    result = await graph.ainvoke(state)
    print(f"Routed: {result.get('next_agent')}")
    print(f"Savings: ${result.get('loyalty_savings'):.2f}")
    print(f"Remaining State Points: {result.get('loyalty_points')}")
    print(f"Cart contents: {result.get('cart').contents}")
    print(f"Response:\n{result.get('response')}")

    # Check updated points in database
    db = SessionLocal()
    try:
        cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == "cust_001").first()
        print(f"Final Points in DB for cust_001: {cust.loyalty_points}")
    finally:
        db.close()

async def test_post_purchase_support():
    print("\n==============================================")
    print("  TEST 3: Post-Purchase Support & Tracking   ")
    print("==============================================")

    # 1. Check order status
    state = ExtendedState(
        user_id=123,
        customer_id="cust_001",
        tracking_number="REF_987654",
        fulfillment_method="ship_to_home",
        delivery_address="742 Evergreen Terrace",
        query="where is my order REF_987654?",
        context=""
    )

    result = await graph.ainvoke(state)
    print(f"\n[Status Check] Routed: {result.get('next_agent')}")
    print(f"Response:\n{result.get('response')}")

    # 2. Request a return
    state = ExtendedState(**{**result, "query": "I want to return my Lovable Women Spice White Bra because of size mismatch"})
    result = await graph.ainvoke(state)
    print(f"\n[Return Request] Routed: {result.get('next_agent')}")
    print(f"Return status saved in state: {result.get('return_status')}")
    print(f"Response:\n{result.get('response')}")

async def main():
    config.memory_port = "http://127.0.0.1:8011"
    
    # Reset/seed customer points to 150 for predictable testing
    db = SessionLocal()
    try:
        cust = db.query(CustomerProfile).filter(CustomerProfile.customer_id == "cust_001").first()
        if cust:
            cust.loyalty_points = 150
            db.commit()
    finally:
        db.close()

    await test_loyalty_coupon()
    await test_loyalty_points()
    await test_post_purchase_support()

if __name__ == "__main__":
    asyncio.run(main())
