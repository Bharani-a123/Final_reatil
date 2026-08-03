#!/usr/bin/env bash

# Start Mock Catalog Retriever in background
python -m uvicorn your-extensions.src.mock_catalog:app --port 8010 --host 127.0.0.1 &

# Start Memory Retriever in background
python -m uvicorn memory_retriever.src.main:app --port 8011 --host 127.0.0.1 &

# Start main Chain Server bound to Render's exposed Port
python -m uvicorn your-extensions.src.main:app --port ${PORT:-8009} --host 0.0.0.0
