# Retail Shopping Assistant: Architecture & Workflow Guide

This document outlines the system architecture, service maps, databases, and request workflows for the Retail Shopping Assistant application.

---

## 1. System Architecture Diagram

The application consists of a React UI frontend, an Nginx API gateway, three Python microservices (FastAPI), a Milvus vector database for visual discovery, SQLite relational databases, and a LangGraph-orchestrated LLM agent network.

```mermaid
graph TD
    %% Frontend / Routing
    UI[React TypeScript Web UI<br/>Port 3000] <-->|HTTP / SSE Streaming| Nginx[Nginx API Proxy<br/>Port 3000]
    Nginx <-->|Route /api/* -> Port 8009| CS[Chain Server<br/>Port 8009]

    %% Agent Core & Services
    subgraph Agent Orchestration & Core
        CS[Chain Server FastAPI]
        Graph[LangGraph Agent network]
        CS <--> Graph
    end

    %% External & Retrieval Services
    Graph <-->|REST API Port 8010| CR[Catalog Retriever FastAPI]
    Graph <-->|REST API Port 8011| MR[Memory Retriever FastAPI]
    Graph <-->|HTTPS| LLM[Groq / Llama API Gateway]
    Graph <-->|HTTPS| RZP[Razorpay API Gateway]

    %% Database Layer
    subgraph Storage Layer
        CR -->|Semantic Embedding Search| Milvus[(Milvus Vector DB)]
        CR -->|Local File Fallback| Shared[(shared/images/)]
        MR <-->|User Session Store| SQLiteMem[(SQLite: context.db)]
        Graph <-->|Stateful Inventory & Payments| SQLiteComm[(SQLite: commerce.db)]
    end

    %% Styles
    style UI fill:#b3e5fc,stroke:#01579b,stroke-width:2px
    style Nginx fill:#c8e6c9,stroke:#2e7d32,stroke-width:2px
    style CS fill:#ffe0b2,stroke:#e65100,stroke-width:2px
    style CR fill:#d1c4e9,stroke:#4527a0,stroke-width:2px
    style MR fill:#d1c4e9,stroke:#4527a0,stroke-width:2px
    style SQLiteMem fill:#f8bbd0,stroke:#c2185b,stroke-width:2px
    style SQLiteComm fill:#f8bbd0,stroke:#c2185b,stroke-width:2px
    style Milvus fill:#cfd8dc,stroke:#37474f,stroke-width:2px
```

---

## 2. Relational Database Schemas

### A. Memory Retriever Database (`context.db`)
Stores active session context, summarized chat history, and the stateful shopping cart session per user.

| Table Name | Primary Key | Columns | Purpose |
| :--- | :--- | :--- | :--- |
| `cart_items` | `id` (Auto-increment) | `user_id` (INT), `item` (VARCHAR), `amount` (INT), `price` (FLOAT) | Tracks items currently in the user's active shopping cart session. |
| `summaries` | `user_id` | `summary` (TEXT), `updated_at` (TIMESTAMP) | Holds summarized conversation context to feed the LLM memory. |

### B. Commerce Database (`commerce.db`)
Maintains catalog inventory levels, seeded customer profiles, payment stub records, and discount rules.

| Table Name | Primary Key | Columns | Purpose |
| :--- | :--- | :--- | :--- |
| `inventory_items` | `sku` | `name` (VARCHAR), `online_warehouse` (INT), `store_downtown` (INT), `store_suburbs` (INT) | Tracks physical stock levels across warehouses and storefronts. |
| `customer_profiles` | `customer_id` | `name`, `email`, `loyalty_tier`, `loyalty_points`, `purchase_history` (JSON string) | Contains user loyalty points and transaction history. |
| `coupon_rules` | `code` | `discount_percentage`, `min_order_value` | Defines active coupons (e.g. WELCOME10, GOLD20). |
| `payments_stub` | `id` | `payment_method`, `card_number_suffix`, `upi_id`, `gift_card_code`, `balance`, `status` | Contains mock balances for card/UPI/gift card stub test validation. |

---

## 3. End-to-End Request Workflow

The workflow diagram below details the path of a query from frontend submission to final streaming delivery.

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser
    participant React as React UI
    participant CS as Chain Server
    participant Planner as Planner Node
    participant DB as SQLite DB
    participant LLM as Llama LLM
    participant Chatter as Chatter Node

    User->>React: Submits query: "checkout my cart"
    React->>CS: POST /api/query/stream
    CS->>DB: Fetch active Cart & Profile
    CS->>Planner: Routes query to specific Agent Node
    Note over Planner: Matches "checkout" keyword<br/>Routes to [Payment Agent]
    
    activate CS
    Note over CS: Payment Agent processes total & discounts
    CS->>CS: Create Razorpay Payment Link (POST /v1/payment_links)
    CS-->>CS: Returns short checkout URL (https://rzp.io/rzp/...)
    deactivate CS

    CS->>Chatter: Generate response text
    Chatter->>LLM: Render prompt with PRECEDING AGENT RESULT
    LLM-->>Chatter: Response tokens
    Chatter->>React: Streams Server-Sent Events (SSE)
    React->>User: Renders green payment button
```

---

## 4. Post-Payment Automation Workflow

How the system handles stock decrementing and cart clearing after successful payment verification.

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser
    participant React as React UI
    participant CS as Chain Server (Payment Agent)
    participant DB as Commerce DB (Inventory)
    participant Mem as Memory Service (Cart)

    User->>React: Pays via Razorpay Test Link
    Note over User: Completes payment in test mode
    React->>React: Redirects back to http://localhost:3000
    Note over React: URL contains razorpay_payment_link_status=paid
    React->>CS: Auto-sends message: "verify my payment"
    
    CS->>CS: Query Razorpay Status (GET /v1/payment_links/:id)
    Note over CS: Razorpay returns status: "paid"
    
    CS->>DB: Deduct purchased items from Inventory (online_warehouse)
    CS->>CS: Generate shipping tracking ID (REF_XXXXXX)
    CS->>Mem: Clear User Cart (POST /user/:id/cart/clear)
    CS->>React: SSE stream: "Payment Verified! Tracking Ref: REF_XXXXXX"
    React->>User: Displays confirmation and clears active sidebar cart
```
