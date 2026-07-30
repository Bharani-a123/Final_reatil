import sys
import os

# Add paths
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set fallback env keys
os.environ.setdefault("LLM_API_KEY", "mock_key")
os.environ.setdefault("EMBED_API_KEY", "mock_key")
os.environ.setdefault("CONFIG_OVERRIDE", "config-build.yaml")
os.environ.setdefault("SHARED_CONFIG_ROOT", "C:\\Final_retail\\shared\\configs")

from src.state import ExtendedState
from src.main import agents

planner = agents["planner_agent"]
print(f"Planner Agent Choices: {planner.agent_choices}")
print("--- Test Routing Queries ---")

test_cases = [
    "do you have any lovables spice bra in stock in downtown store?",
    "i want home delivery to 123 Main Street",
    "please charge my card ending in 4242",
    "apply coupon WELCOME10 to my order",
    "can I redeem my points for a discount?",
    "where is my order REF_999999?",
    "I want to return my item size mismatch"
]

for idx, q in enumerate(test_cases, 1):
    state = ExtendedState(
        user_id=1,
        query=q,
        context="",
        current_channel="web"
    )
    # Invoke planner
    result_state = planner.invoke(state)
    print(f"Query {idx}: '{q}' -> Routed to: {result_state.next_agent}")
