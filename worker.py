"""
HYWorld ML Worker - Polls PocketBase for pending projects and processes them.
Run manually: python worker.py
Or via: D:\GitHub\HYWorldWeb\worker.bat
"""
import os
import sys
import json
import time
import glob
import shutil
import requests
from datetime import datetime

# ─── Config ──────────────────────────────────────────────
HYWORLD_DIR = r"D:\GitHub\HY-World-2.0"
PROJECTS_DIR = r"D:\GitHub\HYWorldWeb\projects"
PB_URL = os.environ.get("PB_URL", "http://localhost:8092")
PB_ADMIN = os.environ.get("PB_ADMIN", "admin@hyworld.local")
PB_PASS = os.environ.get("PB_PASS", "admin1234")
COLLECTION = "hyworld_data"
POLL_INTERVAL = 30  # seconds

# Add HY-World to path
sys.path.insert(0, HYWORLD_DIR)
os.environ["PYTHONPATH"] = HYWORLD_DIR

# ─── PocketBase helpers ──────────────────────────────────
def pb_auth():
    r = requests.post(
        f"{PB_URL}/api/admins/auth-with-password",
        json={"identity": PB_ADMIN, "password": PB_PASS},
        timeout=10
    )
    return r.json().get("token", "") if r.ok else None

def pb_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def pb_update_record(token, record_id, data):
    url = f"{PB_URL}/api/collections/{COLLECTION}/records/{record_id}"
    r = requests.patch(url, json=data, headers=pb_headers(token), timeout=10)
    return r.ok

def pb_get_records(token, filter_="", per_page=200):
    url = f"{PB_URL}/api/collections/{COLLECTION}/records"
    params = {"perPage": per_page}
    if filter_:
        params["filter"] = filter_
    r = requests.get(url, params=params, headers=pb_headers(token), timeout=10)
    return r.json().get("items", []) if r.ok else []

def pb_delete_file(token, record_id, filename):
    url = f"{PB_URL}/api/collections/{COLLECTION}/records/{record_id}/files/{filename}"
    r = requests.delete(url, headers=pb_headers(token), timeout=10)
    return r.ok

def pb_upload_file(token, record_id, filepath, field_name="files"):
    """Upload a file to an existing PocketBase record."""
    url = f"{PB_URL}/api/collections/{COLLECTION}/records/{record_id}/files"
    with open(filepath, "rb") as f:
        files = {field_name: (os.path.basename(filepath), f)}
        data = {"files": (os.path.basename(filepath),)}
        r = requests.patch(url, data=data, files=files, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    return r.ok

# ─── ML Processing ───────────────────────────────────────
def process_project(project_id, project_path):
    """Run WorldMirror 2.0 on a project."""
    print(f"\n{'='*50}")
    print(f"Processing project: {project_id}")
    print(f"Project path: {project_path}")
    
    input_dir = os.path.join(project_path, "input")
    output_dir = os.path.join(project_path, "output")
    
    # Get input images
    images = sorted(glob.glob(os.path.join(input_dir, "*.[jp][pn][g]")))  # jpg, jpeg, png
    if not images:
        print(f"ERROR: No images found in {input_dir}")
        return False
    
    print(f"Found {len(images)} input images")
    
    # Check ML environment
    try:
        import torch
        print(f"PyTorch: {torch.__version__} | CUDA: {torch.cuda.is_available()}")
        from hyworld2.worldrecon.pipeline import WorldMirrorPipeline
        print("WorldMirrorPipeline: OK")
    except Exception as e:
        print(f"ERROR importing ML modules: {e}")
        return False
    
    # Run reconstruction
    try:
        print(f"Initializing WorldMirrorPipeline...")
        pipeline = WorldMirrorPipeline.from_pretrained(
            "tencent/HY-World-2.0",
            device="cuda" if torch.cuda.is_available() else "cpu",
            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        )
        
        # Run on first image for testing (expand to full folder later)
        # For now: process first image as demo
        print(f"Running reconstruction on {images[0]}...")
        
        result = pipeline.reconstruct(
            image=images[0],
            output_dir=output_dir,
            progress=True,
        )
        
        print(f"Reconstruction complete!")
        print(f"Result keys: {list(result.keys())}")
        
        # List output files
        output_files = glob.glob(os.path.join(output_dir, "*"))
        for f in output_files:
            size = os.path.getsize(f) / 1e6
            print(f"  Output: {os.path.basename(f)} ({size:.1f} MB)")
        
        return True
        
    except Exception as e:
        print(f"ERROR during processing: {e}")
        import traceback
        traceback.print_exc()
        return False

# ─── Worker Loop ─────────────────────────────────────────
def run_worker():
    """Main polling loop."""
    print("=" * 50)
    print("HYWorld ML Worker")
    print(f"Polling interval: {POLL_INTERVAL}s")
    print(f"Projects dir: {PROJECTS_DIR}")
    print(f"PocketBase: {PB_URL}")
    print("=" * 50)
    
    while True:
        try:
            token = pb_auth()
            if not token:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Auth failed, retrying in {POLL_INTERVAL}s...")
                time.sleep(POLL_INTERVAL)
                continue
            
            # Find pending/processing projects from local dir
            pending = []
            if os.path.exists(PROJECTS_DIR):
                for pid in os.listdir(PROJECTS_DIR):
                    proj_path = os.path.join(PROJECTS_DIR, pid)
                    meta_path = os.path.join(proj_path, "meta.json")
                    if os.path.exists(meta_path):
                        with open(meta_path) as f:
                            meta = json.load(f)
                        if meta.get("status") == "processing":
                            pending.append((pid, proj_path))
            
            if pending:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Found {len(pending)} project(s) to process")
            else:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] No pending projects, sleeping...")
            
            for pid, proj_path in pending:
                success = process_project(pid, proj_path)
                
                # Update status
                meta_path = os.path.join(proj_path, "meta.json")
                with open(meta_path) as f:
                    meta = json.load(f)
                
                meta["status"] = "completed" if success else "failed"
                meta["finished_at"] = datetime.now().isoformat()
                with open(meta_path, "w") as f:
                    json.dump(meta, f)
                
                # Update PocketBase
                pb_update_record(token, pid, {
                    "json": json.dumps({
                        "status": meta["status"],
                        "name": meta.get("name", pid),
                        "finished_at": meta["finished_at"],
                    })
                })
                
                if success:
                    print(f"✓ Project {pid} completed!")
                else:
                    print(f"✗ Project {pid} failed!")
        
        except Exception as e:
            print(f"Worker error: {e}")
            import traceback
            traceback.print_exc()
        
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    print("Starting ML Worker...")
    run_worker()