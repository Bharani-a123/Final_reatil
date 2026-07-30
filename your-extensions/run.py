#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Orchestrates and runs the extended sales assistant services locally.
Starts the Mock Catalog Retriever on 8010 and the Extended Chain Server on 8009.
"""
import os
import sys
import time
import signal
import argparse
import subprocess
from pathlib import Path

# Path resolving
REPO_ROOT = Path(__file__).resolve().parent
PID_DIR = REPO_ROOT / ".run_pids"
LOG_DIR = REPO_ROOT / ".run_logs"

def ensure_dirs():
    PID_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    
    # Link ui/public/images -> selected_dataset/images
    ui_img_dir = REPO_ROOT.parent / "ui" / "public" / "images"
    selected_img_dir = REPO_ROOT.parent / "selected_dataset" / "images"
    
    # Always recreate link to ensure it points to selected_dataset/images
    if ui_img_dir.exists():
        try:
            if os.name == 'nt':
                subprocess.run(["cmd", "/c", f"rmdir \"{ui_img_dir}\""], capture_output=True)
            else:
                if os.path.islink(ui_img_dir):
                    os.unlink(ui_img_dir)
                else:
                    import shutil
                    shutil.rmtree(ui_img_dir)
        except Exception as e:
            pass

    if not ui_img_dir.exists() and selected_img_dir.exists():
        try:
            ui_img_dir.parent.mkdir(parents=True, exist_ok=True)
            if os.name == 'nt':
                subprocess.run(["cmd", "/c", f"mklink /j \"{ui_img_dir}\" \"{selected_img_dir}\""], capture_output=True)
            else:
                os.symlink(str(selected_img_dir), str(ui_img_dir))
            print("Successfully linked selected_dataset images to React UI public assets.")
        except Exception as e:
            print(f"Warning: Could not link selected_dataset images: {e}")

def get_status():
    ensure_dirs()
    status = {}
    for name, port in [("mock_catalog", 8010), ("memory_retriever", 8011), ("extended_chain", 8009)]:
        pid_file = PID_DIR / f"{name}.pid"
        alive = False
        pid = None
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                # Check if process is running
                if os.name == 'nt':
                    # Windows process check
                    proc_check = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
                    if str(pid) in proc_check.stdout:
                        alive = True
                else:
                    os.kill(pid, 0)
                    alive = True
            except (ValueError, OSError, subprocess.SubprocessError):
                pass
        
        status[name] = {"pid": pid, "alive": alive, "port": port}
    return status

def start_services(api_key: str = None):
    ensure_dirs()
    status = get_status()
    
    # Set default environment variables
    env = os.environ.copy()
    actual_key = api_key or env.get("LLM_API_KEY", "")
    is_groq = actual_key.startswith("gsk_")

    if api_key:
        env["LLM_API_KEY"] = api_key
        env["EMBED_API_KEY"] = "mock_key" if is_groq else api_key
    else:
        env.setdefault("LLM_API_KEY", "mock_key")
        env.setdefault("EMBED_API_KEY", "mock_key")
        
    if is_groq:
        env["CONFIG_OVERRIDE"] = "config-groq.yaml"
        print("Groq API key detected. Using Groq LLM config override (config-groq.yaml).")
    else:
        env["CONFIG_OVERRIDE"] = "config-build.yaml"
    env["SHARED_CONFIG_ROOT"] = str(REPO_ROOT.parent / "shared" / "configs")
    env["SHARED_ROOT"] = str(REPO_ROOT.parent / "shared")
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + str(REPO_ROOT.parent)
    env["PYTHONUNBUFFERED"] = "1"
    
    # Export Razorpay API credentials for secure online checkouts
    env["RAZORPAY_KEY_ID"] = "rzp_test_TInHtHhI5I48Mg"
    env["RAZORPAY_KEY_SECRET"] = "VSO3oG5CF11zNNWOtzW1DVPA"

    creationflags = 0
    if os.name == 'nt':
        creationflags = 0x00000200  # CREATE_NEW_PROCESS_GROUP

    # 1. Start Mock Catalog Retriever on 8010
    if not status["mock_catalog"]["alive"]:
        print("Starting Mock Catalog Retriever on port 8010...")
        log_file = LOG_DIR / "mock_catalog.log"
        f_log = open(log_file, "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "your-extensions.src.mock_catalog:app", "--port", "8010", "--host", "127.0.0.1"],
            env=env,
            stdout=f_log,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT.parent),
            creationflags=creationflags
        )
        (PID_DIR / "mock_catalog.pid").write_text(str(proc.pid))
        print(f"Mock Catalog Retriever started with PID {proc.pid}")
    else:
        print("Mock Catalog Retriever is already running.")


    # 2. Start Memory Retriever on port 8011
    if not status["memory_retriever"]["alive"]:
        print("Starting Memory Retriever on port 8011...")
        log_file = LOG_DIR / "memory_retriever.log"
        f_log = open(log_file, "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "memory_retriever.src.main:app", "--port", "8011", "--host", "127.0.0.1"],
            env=env,
            stdout=f_log,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT.parent),
            creationflags=creationflags
        )
        (PID_DIR / "memory_retriever.pid").write_text(str(proc.pid))
        print(f"Memory Retriever started with PID {proc.pid}")
    else:
        print("Memory Retriever is already running.")

    # 3. Start Extended Chain Server on 8009
    if not status["extended_chain"]["alive"]:
        print("Starting Extended Chain Server on port 8009...")
        log_file = LOG_DIR / "extended_chain.log"
        f_log = open(log_file, "ab")
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "your-extensions.src.main:app", "--port", "8009", "--host", "127.0.0.1"],
            env=env,
            stdout=f_log,
            stderr=subprocess.STDOUT,
            cwd=str(REPO_ROOT.parent),
            creationflags=creationflags
        )
        (PID_DIR / "extended_chain.pid").write_text(str(proc.pid))
        print(f"Extended Chain Server started with PID {proc.pid}")
    else:
        print("Extended Chain Server is already running.")

def stop_services():
    status = get_status()
    for name, info in status.items():
        if info["alive"]:
            print(f"Stopping {name} (PID {info['pid']})...")
            try:
                if os.name == 'nt':
                    subprocess.run(["taskkill", "/F", "/PID", str(info["pid"])], capture_output=True)
                else:
                    os.kill(info["pid"], signal.SIGTERM)
                print(f"Stopped {name}")
            except Exception as e:
                print(f"Failed to stop {name}: {e}")
            
            pid_file = PID_DIR / f"{name}.pid"
            if pid_file.exists():
                pid_file.unlink()
        else:
            print(f"{name} is not running.")

def print_status():
    status = get_status()
    print("\n--- Extended Services Status ---")
    for name, info in status.items():
        state = "ALIVE" if info["alive"] else "STOPPED"
        pid_str = f"PID={info['pid']}" if info["alive"] else ""
        print(f"  {name:15}: {state:8} {pid_str:10} (Port {info['port']})")
    print(f"Logs are stored in: {LOG_DIR}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extended Services Control Script")
    parser.add_argument("command", choices=["start", "stop", "status"], help="Command to run")
    parser.add_argument("--api-key", help="NVIDIA NGC or OpenAI API Key to export as LLM_API_KEY")
    args = parser.parse_args()

    if args.command == "start":
        start_services(args.api_key)
        time.sleep(2)
        print_status()
    elif args.command == "stop":
        stop_services()
    elif args.command == "status":
        print_status()
