# spotdl_gui.py – multi‑link with settings (rev‑4)
"""
Bulk‑paste GUI for **spotDL** with live status **and** a quick‑access settings
menu for audio quality.

Changes
-------
* New **Quality** dropdown (Best, 320 kbps, 256 kbps, 128 kbps) sitting right
  next to **Download All**.  Selection is remembered during the session.
* Server `/download` endpoint now receives a `quality` field and appends an
  appropriate `--bitrate` argument to the spotDL command.
* Default behaviour is *Best* (spotDL’s auto mode – highest available).
"""

from __future__ import annotations

import subprocess
import threading
import pathlib
from typing import Dict

from flask import Flask, request, jsonify, render_template_string
import webview

# ------------------------------------------------------------------
DOWNLOAD_DIR = pathlib.Path.home() / "Downloads" / "spotdl"
PORT = 5001

# -------------------------- spotDL import -------------------------
try:
    from spotdl.utils.spotify import SpotifyClient  # type: ignore
    from spotdl.types.song import Song  # type: ignore
except ImportError as e:
    raise SystemExit("spotdl>=4 must be installed: pip install spotdl") from e

_sp_ready = False

def _ensure_sp_client():
    global _sp_ready
    if not _sp_ready:
        SpotifyClient.init(
            client_id="f8a606e5583643beaa27ce62c48e3fc1",
            client_secret="f6f4c8f73f0649939286cf417c811607",
            user_auth=False,
        )
        _sp_ready = True

# --------------------------- Flask -------------------------------
app = Flask(__name__)

STATUS: Dict[str, str] = {}  # link -> idle|downloading|done|error

_HTML = r"""<!doctype html><html lang='en'><head><meta charset='utf-8'/><title>spotDL Bulk</title><style>:root{font-family:Arial,Helvetica,sans-serif;--green:#1db954;--gray:#eee}body{margin:0;height:100vh;display:flex;flex-direction:column;background:#fafafa}header{background:#fff;padding:1rem 1.5rem;display:flex;align-items:center;gap:1rem;box-shadow:0 2px 6px rgba(0,0,0,.05)}header h1{font-size:1.15rem;margin:0;flex:1}button{padding:.6rem 1rem;border:none;border-radius:8px;color:#fff;background:var(--green);cursor:pointer;font-size:.9rem}button[disabled]{opacity:.5;cursor:default}select{padding:.45rem .6rem;border-radius:6px;border:1px solid #bbb;font-size:.9rem}#zone{flex:1;overflow:auto;padding:1rem}table{width:100%;border-collapse:collapse}th,td{padding:.45rem .6rem;text-align:left}tr:nth-child(odd){background:#fff}tr:nth-child(even){background:#f3f7f3}img{width:48px;height:48px;border-radius:4px;object-fit:cover}.actions button{border:none;border-radius:6px;font-size:.8rem;padding:.35rem .7rem;margin-right:.4rem;cursor:pointer}.xbtn{background:#e65555;color:#fff}.dlbtn{background:var(--green);color:#fff}.placeholder{border:2px dashed #bbb;border-radius:12px;padding:3rem;text-align:center;color:#666;max-width:460px;margin:4rem auto}progress{width:100%;height:6px;appearance:none}progress::-webkit-progress-bar{background:var(--gray)}progress::-webkit-progress-value{background:var(--green)}</style></head><body><header><h1>spotDL Bulk Downloader</h1><select id='qualitySel'><option value='best'>Best</option><option value='320k'>320 kbps</option><option value='256k'>256 kbps</option><option value='128k'>128 kbps</option></select><button id='allBtn' onclick='dlAll()' disabled>Download All</button></header><div id='zone'><div id='ph' class='placeholder'>Paste Spotify / YouTube links (⌘V / Ctrl+V)<br>Separate with space, comma, or newline.</div><table id='tbl' style='display:none'><thead><tr><th></th><th>Title</th><th>Artist</th><th>Album</th><th>Status</th><th class='actions'>Actions</th></tr></thead><tbody></tbody></table></div><script>const tblBody=document.querySelector('#tbl tbody');const ph=document.getElementById('ph');const allBtn=document.getElementById('allBtn');const qualitySel=document.getElementById('qualitySel');let rows={};document.addEventListener('paste',e=>{const txt=(e.clipboardData||window.clipboardData).getData('text');const links=txt.split(/[\s,]+/).filter(t=>t.startsWith('http'));if(!links.length)return;e.preventDefault();links.forEach(addRow);});function addRow(link){if(rows[link])return;const r=document.createElement('tr');r.innerHTML=`<td><img/></td><td>-</td><td>-</td><td>-</td><td class='status'>idle</td><td class='actions'><button class='dlbtn' onclick="dlOne('${link}')">Download</button><button class='xbtn' onclick="rmRow('${link}')">✕</button></td>`;tblBody.appendChild(r);rows[link]=r;ph.style.display='none';document.getElementById('tbl').style.display='table';allBtn.disabled=false;fetch('/meta',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({link})}).then(r=>r.json()).then(m=>{if(!rows[link])return;r.children[0].firstChild.src=m.cover||'';r.children[1].textContent=m.title||'(unknown)';r.children[2].textContent=m.artist||'';r.children[3].textContent=m.album||'';}).catch(()=>{});}function rmRow(l){if(!rows[l])return;tblBody.removeChild(rows[l]);delete rows[l];if(!Object.keys(rows).length){ph.style.display='block';document.getElementById('tbl').style.display='none';allBtn.disabled=true;}}function dlOne(link){if(!rows[link])return;rows[link].querySelector('.dlbtn').disabled=true;rows[link].querySelector('.status').innerHTML='<progress></progress>';fetch('/download',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({link,quality:qualitySel.value})});}function dlAll(){Object.keys(rows).forEach(dlOne);allBtn.textContent='Downloading…';allBtn.disabled=true;}setInterval(()=>{const qs=Object.keys(rows);if(!qs.length)return;fetch('/status?links='+encodeURIComponent(qs.join(','))).then(r=>r.json()).then(st=>{qs.forEach(l=>{const s=st[l];if(!s||!rows[l])return;if(s==='done'){rows[l].querySelector('.status').textContent='✓';}else if(s==='error'){rows[l].querySelector('.status').textContent='error';rows[l].querySelector('.dlbtn').disabled=false;} });if(Object.values(st).every(v=>v==='done'||v==='error')){allBtn.textContent='Download All';allBtn.disabled=false;}});},2000);</script></body></html>"""

@app.route("/")
def idx():
    return render_template_string(_HTML)

# ---------------------- Metadata ----------------------------------

def _meta(link: str):
    _ensure_sp_client()
    try:
        song: Song = Song.from_url(link)  # type: ignore[arg-type]
        artists = [getattr(a, "name", a) for a in song.artists]
        return {
            "title": song.name,
            "artist": ", ".join(artists),
            "album": song.album_name or "",
            "cover": song.cover_url or "",
        }
    except Exception as e:
        print("meta error", e)
        return {}

@app.post("/meta")
def meta_ep():
    link = request.get_json(force=True).get("link", "")
    return jsonify(_meta(link))

# ---------------------- Download & status -------------------------

def _run(link: str, quality: str):
    STATUS[link] = "downloading"
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cmd = ["spotdl", "download", link, "--output", f"{DOWNLOAD_DIR}/{{artists}} - {{title}}.{{output-ext}}"]
    if quality and quality != "best":
        cmd += ["--bitrate", quality]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        STATUS[link] = "done" if proc.returncode == 0 else "error"
        if proc.returncode != 0:
            print(proc.stderr)
    except Exception as e:
        STATUS[link] = "error"
        print("download error", e)

@app.post("/download")
def dl_ep():
    data = request.get_json(force=True)
    link = data.get("link", "")
    quality = data.get("quality", "best")
    if not link:
        return ("", 400)
    if STATUS.get(link) in {"downloading", "done"}:
        return ("", 204)
    STATUS[link] = "queued"
    threading.Thread(target=_run, args=(link, quality), daemon=True).start()
    return ("", 204)

@app.get("/status")
def status_ep():
    links = request.args.get("links", "").split(",")
    return jsonify({l: STATUS.get(l, "idle") for l in links})

# ---------------------- Bootstrap ---------------------------------

def _serve():
    app.run(port=PORT, threaded=True)

if __name__ == "__main__":
    threading.Thread(target=_serve, daemon=True).start()
    webview.create_window("spotDL Bulk Downloader", f"http://127.0.0.1:{PORT}", width=920, height=660, resizable=True)
    webview.start()
