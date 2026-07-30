# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
SQLAlchemy database access layer for SQLite (commerce.db).
Seeds the database dynamically from provided JSON files on initial boot.
"""
import os
import json
import logging
from typing import Optional
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "commerce.db")

DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class CustomerProfile(Base):
    __tablename__ = "customer_profiles"
    customer_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    loyalty_tier = Column(String, default="None")
    loyalty_points = Column(Integer, default=0)
    purchase_history = Column(Text, default="[]")  # JSON string of product names
    channel_preference = Column(String, default="web")

class InventoryItem(Base):
    __tablename__ = "inventory_items"
    sku = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)
    online_warehouse = Column(Integer, default=0)
    store_downtown = Column(Integer, default=0)
    store_suburbs = Column(Integer, default=0)

class PaymentStub(Base):
    __tablename__ = "payments_stub"
    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_method = Column(String, nullable=False)  # card, upi, gift_card
    card_number_suffix = Column(String, nullable=True)
    upi_id = Column(String, nullable=True)
    gift_card_code = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    holder_name = Column(String, nullable=True)
    status = Column(String, default="APPROVED")
    error_message = Column(String, nullable=True)

class CouponRule(Base):
    __tablename__ = "coupon_rules"
    code = Column(String, primary_key=True, index=True)
    discount_percentage = Column(Float, default=0.0)
    min_order_value = Column(Float, default=0.0)

# Create all tables
Base.metadata.create_all(bind=engine)

def seed_database():
    """Seed the database tables from JSON files if tables are empty."""
    db = SessionLocal()
    try:
        # 1. Seed Customer Profiles
        if db.query(CustomerProfile).count() == 0:
            cust_file = os.path.join(DATA_DIR, "customers.json")
            if os.path.exists(cust_file):
                logger.info(f"Seeding customer profiles from {cust_file}")
                with open(cust_file, "r") as f:
                    customers = json.load(f)
                for cust in customers:
                    profile = CustomerProfile(
                        customer_id=cust["customer_id"],
                        name=cust["name"],
                        email=cust["email"],
                        loyalty_tier=cust["loyalty_tier"],
                        loyalty_points=cust["loyalty_points"],
                        purchase_history=json.dumps(cust["purchase_history"]),
                        channel_preference=cust["channel_preference"]
                    )
                    db.add(profile)
                db.commit()

        # 2. Seed Inventory Items
        if db.query(InventoryItem).count() == 0:
            inv_file = os.path.join(DATA_DIR, "inventory.json")
            if os.path.exists(inv_file):
                logger.info(f"Seeding inventory items from {inv_file}")
                with open(inv_file, "r") as f:
                    inventory = json.load(f)
                for item in inventory:
                    inv_item = InventoryItem(
                        sku=item["sku"],
                        name=item["name"],
                        online_warehouse=item["online_warehouse"],
                        store_downtown=item["store_downtown"],
                        store_suburbs=item["store_suburbs"]
                    )
                    db.add(inv_item)
                db.commit()

        # 3. Seed Payment Stubs
        if db.query(PaymentStub).count() == 0:
            pay_file = os.path.join(DATA_DIR, "payments_stub.json")
            if os.path.exists(pay_file):
                logger.info(f"Seeding payment stubs from {pay_file}")
                with open(pay_file, "r") as f:
                    payments = json.load(f)
                for pay in payments:
                    stub = PaymentStub(
                        payment_method=pay["payment_method"],
                        card_number_suffix=pay.get("card_number_suffix"),
                        upi_id=pay.get("upi_id"),
                        gift_card_code=pay.get("gift_card_code"),
                        balance=pay.get("balance", 0.0),
                        holder_name=pay.get("holder_name"),
                        status=pay["status"],
                        error_message=pay.get("error_message")
                    )
                    db.add(stub)
                db.commit()

        # 4. Seed Coupons
        if db.query(CouponRule).count() == 0:
            rules_file = os.path.join(DATA_DIR, "loyalty_rules.json")
            if os.path.exists(rules_file):
                logger.info(f"Seeding coupon rules from {rules_file}")
                with open(rules_file, "r") as f:
                    rules = json.load(f)
                coupons = rules.get("coupons", [])
                for cp in coupons:
                    rule = CouponRule(
                        code=cp["code"],
                        discount_percentage=cp["discount_percentage"],
                        min_order_value=cp["min_order_value"]
                    )
                    db.add(rule)
                db.commit()

    except Exception as e:
        logger.error(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()

# Run the seeding operation
seed_database()

# Database helper functions
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def query_customer(customer_id: str) -> Optional[CustomerProfile]:
    db = SessionLocal()
    try:
        return db.query(CustomerProfile).filter(CustomerProfile.customer_id == customer_id).first()
    finally:
        db.close()

def query_inventory_by_name(name: str) -> Optional[InventoryItem]:
    db = SessionLocal()
    try:
        # String match normalized
        return db.query(InventoryItem).filter(InventoryItem.name == name).first()
    finally:
        db.close()

def update_inventory_stock(sku: str, location: str, amount: int) -> bool:
    db = SessionLocal()
    try:
        item = db.query(InventoryItem).filter(InventoryItem.sku == sku).first()
        if not item:
            return False
        
        if location == "online_warehouse":
            item.online_warehouse = max(0, item.online_warehouse + amount)
        elif location == "store_downtown":
            item.store_downtown = max(0, item.store_downtown + amount)
        elif location == "store_suburbs":
            item.store_suburbs = max(0, item.store_suburbs + amount)
        else:
            return False
        
        db.commit()
        return True
    except Exception as e:
        logger.error(f"DB Error updating inventory: {e}")
        db.rollback()
        return False
    finally:
        db.close()
