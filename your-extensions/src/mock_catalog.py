# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Mock Catalog Retriever service.
Replaces Milvus and the heavy catalog_retriever container with a lightweight,
in-memory Pandas keyword search over selected_dataset/products.csv.
"""
import os
import sys
import time
import logging
import pandas as pd
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
products_df = None
if os.path.exists(CSV_PATH):
    try:
        products_df = pd.read_csv(CSV_PATH)
        logger.info(f"Loaded {len(products_df)} products from {CSV_PATH}")
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
    if products_df is None:
        return {"texts": [], "ids": [], "similarities": [], "names": [], "images": []}

    df = products_df.copy()
    
    # 1. Category Filtering
    # Normalize categories in request
    req_cats_norm = {normalize_text(c) for c in req_categories if c}
    if req_cats_norm:
        # Check if category matches or subCategory matches
        def cat_matches(row):
            cat = normalize_text(str(row.get("category", "")))
            subcat = normalize_text(str(row.get("subCategory", "")))
            mcat = normalize_text(str(row.get("masterCategory", "")))
            return cat in req_cats_norm or subcat in req_cats_norm or mcat in req_cats_norm
        
        df = df[df.apply(cat_matches, axis=1)]

    # 2. Price Filtering
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    if min_price is not None:
        df = df[df["price"] >= float(min_price)]
    if max_price is not None:
        df = df[df["price"] <= float(max_price)]

    if df.empty:
        return {"texts": [], "ids": [], "similarities": [], "names": [], "images": []}

    # 3. Text Query Matching and Ranking
    query_tokens = []
    for q in text_queries:
        if q:
            # clean punctuation
            clean_q = "".join(char if char.isalnum() or char.isspace() else " " for char in q)
            query_tokens.extend(clean_q.lower().split())
            
    query_tokens = list(set(query_tokens)) # deduplicate
    
    # Exclude very generic tokens
    generic_stop = {"show", "me", "find", "search", "anything", "everything", "under", "above", "in", "the", "a", "an", "do", "you", "have", "product", "item"}
    query_tokens = [tok for tok in query_tokens if tok not in generic_stop]

    results = []
    for _, row in df.iterrows():
        name = str(row.get("name", ""))
        category = str(row.get("category", ""))
        color = str(row.get("color", ""))
        usage = str(row.get("usage", ""))
        gender = str(row.get("gender", ""))
        season = str(row.get("season", ""))
        year = str(row.get("year", ""))
        price = float(row.get("price", 0.0))
        sku = str(row.get("source_id", ""))
        image_file = str(row.get("local_image_filename", f"{sku}.jpg"))

        # Build dynamic description
        description = f"A beautiful {color} {usage} {category} for {gender} (Season: {season}, Year: {year})"
        
        # Combine text for matching
        combined_fields = f"{name} {description} {category} {color}".lower()
        
        # Scoring
        score = 0.0
        if query_tokens:
            matches = sum(1 for token in query_tokens if token in combined_fields)
            score = matches / len(query_tokens) if len(query_tokens) > 0 else 0.0
            
            # Exact name or category matching gets a boost
            for q in text_queries:
                q_clean = q.lower().strip()
                if q_clean in name.lower() or q_clean in category.lower():
                    score += 0.5
        else:
            # If no query tokens (e.g. image filter-only refinement), rank is default
            score = 1.0

        # Construct final page_content matching retriever.py:
        # final_texts = [res[0].page_content + f"\nPRICE: {res[0].metadata['price']}" for res in ranked_results]
        # where page_content = f"{name} | {description} | {category},{subcategory}"
        subcategory = str(row.get("subCategory", ""))
        page_content = f"{name} | {description} | {category},{subcategory}\nPRICE: {price}"

        results.append({
            "text": page_content,
            "id": sku,
            "similarity": score,
            "name": name,
            "image": image_file
        })

    # Sort results by similarity score descending
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
    # In lightweight mode, treat image query text as the retrieval key, similar to text-only
    return perform_search(req.text, req.categories, req.filters, req.k)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": "1.0.0",
        "mode": "mock-local"
    }
