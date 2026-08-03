# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Mock Catalog Retriever service.
Replaces Milvus and the heavy catalog_retriever container with a lightweight,
in-memory keyword search over selected_dataset/products.csv.
"""
import os
import sys
import time
import logging
import csv
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CSV_PATH = os.path.join(PROJECT_ROOT, "selected_dataset", "products.csv")

app = FastAPI(title="Mock Catalog Retriever")

# Load products database
products_list = []
if os.path.exists(CSV_PATH):
    try:
        with open(CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                products_list.append(row)
        logger.info(f"Loaded {len(products_list)} products from {CSV_PATH}")
    except Exception as e:
        logger.error(f"Error loading CSV dataset: {e}")
else:
    logger.error(f"CSV dataset not found at {CSV_PATH}")

# Request schemas
class TextQueryRequest(BaseModel):
    text: List[str] = []
    categories: List[str] = []
    filters: Dict[str, Any] = Field(default_factory=dict)
    k: int = 4

class ImageQueryRequest(BaseModel):
    text: List[str] = []
    image_base64: str = ""
    categories: List[str] = []
    filters: Dict[str, Any] = Field(default_factory=dict)
    k: int = 4

def normalize_text(t: str) -> str:
    return t.strip().lower()

def perform_search(text_queries: List[str], req_categories: List[str], filters: Dict[str, Any], k: int) -> Dict[str, List[Any]]:
    """Helper method to filter and rank products from the CSV."""
    if not products_list:
        return {"texts": [], "ids": [], "similarities": [], "names": [], "images": []}

    # 1. Category Filtering
    req_cats_norm = {normalize_text(c) for c in req_categories if c}
    filtered_products = []
    for row in products_list:
        if req_cats_norm:
            cat = normalize_text(row.get("category") or "")
            subcat = normalize_text(row.get("subCategory") or "")
            mcat = normalize_text(row.get("masterCategory") or "")
            if not (cat in req_cats_norm or subcat in req_cats_norm or mcat in req_cats_norm):
                continue
        filtered_products.append(row)

    # 2. Price Filtering
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    
    price_filtered = []
    for row in filtered_products:
        try:
            price = float(row.get("price") or 0)
        except (ValueError, TypeError):
            price = 0.0
            
        if min_price is not None and price < float(min_price):
            continue
        if max_price is not None and price > float(max_price):
            continue
        price_filtered.append(row)

    if not price_filtered:
        return {"texts": [], "ids": [], "similarities": [], "names": [], "images": []}

    # 3. Text Query Matching and Ranking
    query_tokens = []
    for q in text_queries:
        if q:
            clean_q = "".join(char if char.isalnum() or char.isspace() else " " for char in q)
            query_tokens.extend(clean_q.lower().split())
            
    query_tokens = list(set(query_tokens)) # deduplicate
    
    generic_stop = {"show", "me", "find", "search", "anything", "everything", "under", "above", "in", "the", "a", "an", "do", "you", "have", "product", "item"}
    query_tokens = [tok for tok in query_tokens if tok not in generic_stop]

    results = []
    for row in price_filtered:
        name = str(row.get("name") or "")
        category = str(row.get("category") or "")
        color = str(row.get("color") or "")
        usage = str(row.get("usage") or "")
        gender = str(row.get("gender") or "")
        season = str(row.get("season") or "")
        year = str(row.get("year") or "")
        try:
            price = float(row.get("price") or 0.0)
        except (ValueError, TypeError):
            price = 0.0
        sku = str(row.get("source_id") or "")
        image_file = str(row.get("local_image_filename") or f"{sku}.jpg")

        description = f"A beautiful {color} {usage} {category} for {gender} (Season: {season}, Year: {year})"
        combined_fields = f"{name} {description} {category} {color}".lower()
        
        score = 0.0
        if query_tokens:
            matches = sum(1 for token in query_tokens if token in combined_fields)
            score = matches / len(query_tokens) if len(query_tokens) > 0 else 0.0
            
            for q in text_queries:
                q_clean = q.lower().strip()
                if q_clean in name.lower() or q_clean in category.lower():
                    score += 0.5
        else:
            score = 1.0

        subcategory = str(row.get("subCategory") or "")
        page_content = f"{name} | {description} | {category},{subcategory}\nPRICE: {price}"

        results.append({
            "text": page_content,
            "id": sku,
            "similarity": score,
            "name": name,
            "image": image_file
        })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    top_results = results[:k]

    return {
        "texts": [r["text"] for r in top_results],
        "ids": [r["id"] for r in top_results],
        "similarities": [float(r["similarity"]) for r in top_results],
        "names": [r["name"] for r in top_results],
        "images": [r["image"] for r in top_results]
    }

@app.post("/query/text")
async def query_text(req: TextQueryRequest):
    logger.info(f"Mock Catalog | query_text() | Received Text query: {req.text} | Categories: {req.categories} | Filters: {req.filters}")
    return perform_search(req.text, req.categories, req.filters, req.k)

@app.post("/query/image")
async def query_image(req: ImageQueryRequest):
    logger.info(f"Mock Catalog | query_image() | Received Image query text: {req.text} | Filters: {req.filters}")
    return perform_search(req.text, req.categories, req.filters, req.k)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "mode": "mock-local"
    }
