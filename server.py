"""
HYWorld Web Server - Flask + PocketBase
Minimal Tokyo-style UI
"""
import os
import json
import uuid
import base64
from datetime import datetime
from functools import wraps
from dotenv import load_dotenv

# Load .env
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

from flask import (
    Flask, request, redirect, url_for,
    render_template, send_from_directory,
    jsonify, session, flash
)
import requests

# ─── Config ──────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PROJECTS_DIR = os.path.join(BASE_DIR, "projects")  # local project storage
os.makedirs(PROJECTS_DIR, exist_ok=True)

# PocketBase
PB_URL      = os.environ.get("PB_URL", "http://localhost:8092")
PB_ADMIN    = os.environ.get("PB_ADMIN", "admin@hyworld.local")
PB_PASS     = os.environ.get("PB_PASS", "admin1234")
PB_ADMIN_TOKEN = os.environ.get("PB_ADMIN_TOKEN", "")  # pre-generated token from .env
COLLECTION  = "hyworld_data"

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "hyworld-dev-secret-2024")

# ─── PocketBase helpers ───────────────────────────────────
def pb_auth():
    """Get admin auth token for PocketBase."""
    # Use pre-generated token if available (from .env with PB_ADMIN_TOKEN)
    if PB_ADMIN_TOKEN:
        return PB_ADMIN_TOKEN
    r = requests.post(
        f"{PB_URL}/api/admins/auth-with-password",
        json={"identity": PB_ADMIN, "password": PB_PASS},
        timeout=10
    )
    if r.ok:
        return r.json().get("token", "")
    return None

def pb_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def pb_create_record(token, data, files=None):
    """Create a record in hyworld_data collection."""
    url = f"{PB_URL}/api/collections/{COLLECTION}/records"
    if files:
        # multipart upload
        form = {**data}
        files_arr = [(("files", (f, open(f, "rb"))) for f in files)]
        r = requests.post(url, data=form, files=files_arr, headers={"Authorization": f"Bearer {token}"}, timeout=60)
    else:
        r = requests.post(url, json=data, headers=pb_headers(token), timeout=10)
    return r.json() if r.ok else {"error": r.text}

def pb_update_record(token, record_id, data):
    url = f"{PB_URL}/api/collections/{COLLECTION}/records/{record_id}"
    r = requests.patch(url, json=data, headers=pb_headers(token), timeout=10)
    return r.json() if r.ok else {"error": r.text}

def pb_get_records(token, filter_="", per_page=200):
    url = f"{PB_URL}/api/collections/{COLLECTION}/records"
    params = {"perPage": per_page}
    if filter_:
        params["filter"] = filter_
    r = requests.get(url, params=params, headers=pb_headers(token), timeout=10)
    return r.json().get("items", []) if r.ok else []

def pb_get_record(token, record_id):
    url = f"{PB_URL}/api/collections/{COLLECTION}/records/{record_id}"
    r = requests.get(url, headers=pb_headers(token), timeout=10)
    return r.json() if r.ok else {}

def pb_delete_record(token, record_id):
    url = f"{PB_URL}/api/collections/{COLLECTION}/records/{record_id}"
    r = requests.delete(url, headers=pb_headers(token), timeout=10)
    return r.ok

def pb_download_file(token, record_id, filename, save_path):
    """Download file from PocketBase record to local path."""
    url = f"{PB_URL}/api/collections/{COLLECTION}/records/{record_id}/files/{filename}"
    r = requests.get(url, headers=pb_headers(token), timeout=60)
    if r.ok:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "wb") as f:
            f.write(r.content)
        return True
    return False

def user_auth(email, password):
    """Auth user via PocketBase users collection."""
    r = requests.post(
        f"{PB_URL}/api/collections/hyworld_user/auth-with-password",
        json={"identity": email, "password": password},
        timeout=10
    )
    if r.ok:
        data = r.json()
        return {
            "id": data.get("record", {}).get("id", ""),
            "email": data.get("record", {}).get("email", ""),
            "token": data.get("token", ""),
            "name": data.get("record", {}).get("name", email.split("@")[0]),
        }
    return None

def get_local_projects():
    """List projects from local projects directory."""
    projects = []
    if os.path.exists(PROJECTS_DIR):
        for pid in os.listdir(PROJECTS_DIR):
            proj_path = os.path.join(PROJECTS_DIR, pid)
            if os.path.isdir(proj_path):
                meta_path = os.path.join(proj_path, "meta.json")
                meta = {}
                if os.path.exists(meta_path):
                    with open(meta_path) as f:
                        meta = json.load(f)
                projects.append({
                    "id": pid,
                    "name": meta.get("name", pid),
                    "status": meta.get("status", "unknown"),
                    "created": meta.get("created", ""),
                    "image": meta.get("thumb", ""),
                    "input_count": meta.get("input_count", 0),
                })
    return sorted(projects, key=lambda x: x["created"], reverse=True)

# ─── Auth decorator ───────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# ─── Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        user = user_auth(email, password)
        if user:
            session["user"] = user
            session["token"] = user["token"]
            return redirect(url_for("dashboard"))
        error = "Invalid credentials"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    projects = get_local_projects()
    return render_template("dashboard.html", user=session["user"], projects=projects)

@app.route("/project/new", methods=["POST"])
@login_required
def project_new():
    name = request.form.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    
    pid = str(uuid.uuid4())[:8]
    proj_path = os.path.join(PROJECTS_DIR, pid)
    os.makedirs(os.path.join(proj_path, "input"), exist_ok=True)
    os.makedirs(os.path.join(proj_path, "output"), exist_ok=True)
    
    meta = {
        "id": pid,
        "name": name,
        "status": "pending",
        "created": datetime.now().isoformat(),
        "input_count": 0,
    }
    with open(os.path.join(proj_path, "meta.json"), "w") as f:
        json.dump(meta, f)
    
    # Create PocketBase record
    token = pb_auth()
    if token:
        record_data = {
            "id": pid,
            "json": json.dumps({"status": "pending", "name": name}),
        }
        pb_create_record(token, record_data)
    
    return jsonify({"id": pid, "name": name, "status": "pending"})

@app.route("/project/<pid>", methods=["GET"])
@login_required
def project_view(pid):
    proj_path = os.path.join(PROJECTS_DIR, pid)
    if not os.path.exists(proj_path):
        return "Project not found", 404
    
    meta_path = os.path.join(proj_path, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    
    # Get input images
    input_images = []
    inp_dir = os.path.join(proj_path, "input")
    if os.path.exists(inp_dir):
        for f in sorted(os.listdir(inp_dir))[:10]:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                input_images.append(f"/projects/{pid}/input/{f}")
    
    # Get output files
    output_files = []
    out_dir = os.path.join(proj_path, "output")
    if os.path.exists(out_dir):
        for f in sorted(os.listdir(out_dir)):
            output_files.append({"name": f, "url": f"/projects/{pid}/output/{f}"})
    
    return render_template("viewer.html", pid=pid, meta=meta,
                           input_images=input_images, output_files=output_files)

@app.route("/project/<pid>/upload", methods=["POST"])
@login_required
def project_upload(pid):
    proj_path = os.path.join(PROJECTS_DIR, pid)
    inp_dir = os.path.join(proj_path, "input")
    os.makedirs(inp_dir, exist_ok=True)
    
    uploaded = []
    files = request.files.getlist("images")
    for f in files:
        if f.filename:
            ext = os.path.splitext(f.filename)[1].lower()
            fname = f"{len(os.listdir(inp_dir))+1:04d}{ext}"
            f.save(os.path.join(inp_dir, fname))
            uploaded.append(fname)
    
    # Update meta
    meta_path = os.path.join(proj_path, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    meta["input_count"] = len(os.listdir(inp_dir))
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    
    return jsonify({"uploaded": len(uploaded), "files": uploaded})

@app.route("/project/<pid>/trigger", methods=["POST"])
@login_required
def project_trigger(pid):
    """Mark project as ready to process."""
    proj_path = os.path.join(PROJECTS_DIR, pid)
    meta_path = os.path.join(proj_path, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    meta["status"] = "processing"
    meta["triggered_at"] = datetime.now().isoformat()
    with open(meta_path, "w") as f:
        json.dump(meta, f)
    
    # Update PocketBase record
    token = pb_auth()
    if token:
        pb_update_record(token, pid, {"json": json.dumps({"status": "processing", "name": meta.get("name", pid)})})
    
    return jsonify({"status": "processing", "pid": pid})

@app.route("/project/<pid>/refresh", methods=["POST"])
@login_required
def project_refresh(pid):
    """Manually refresh project status (check output folder)."""
    proj_path = os.path.join(PROJECTS_DIR, pid)
    out_dir = os.path.join(proj_path, "output")
    meta_path = os.path.join(proj_path, "meta.json")
    meta = {}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta = json.load(f)
    
    # Check if output exists
    output_files = []
    if os.path.exists(out_dir):
        output_files = sorted(os.listdir(out_dir))
    
    if output_files and meta.get("status") == "processing":
        meta["status"] = "completed"
        with open(meta_path, "w") as f:
            json.dump(meta, f)
        
        token = pb_auth()
        if token:
            pb_update_record(token, pid, {"json": json.dumps({"status": "completed", "name": meta.get("name", pid)})})
    
    return jsonify({"status": meta.get("status", "unknown"), "output_count": len(output_files)})

@app.route("/projects/<pid>/input/<fname>")
@login_required
def project_input_file(pid, fname):
    return send_from_directory(os.path.join(PROJECTS_DIR, pid, "input"), fname)

@app.route("/projects/<pid>/output/<fname>")
@login_required
def project_output_file(pid, fname):
    return send_from_directory(os.path.join(PROJECTS_DIR, pid, "output"), fname)

@app.route("/api/projects")
@login_required
def api_projects():
    return jsonify(get_local_projects())

# ─── Start ───────────────────────────────────────────────
if __name__ == "__main__":
    print("Starting HYWorld Web Server...")
    print(f"Projects dir: {PROJECTS_DIR}")
    print(f"PocketBase:   {PB_URL}")
    print("Open http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)