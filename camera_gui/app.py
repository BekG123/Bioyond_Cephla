"""Bioyond S4 operator console.

Live view of the three cell cameras (two Arducams + GigE eye-in-hand, using
the same capture modules as the bioyond-s4 MCP server), with box-annotate +
ask-Claude chat. Draw a box on any feed, type a question, and the annotated
frame (plus a native-resolution crop of the box) is sent to Claude with the
conversation history.

Run:  py camera_gui/app.py   ->  http://127.0.0.1:5001
The MCP server must not hold the cameras while this runs (one owner at a time).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import time

import cv2
import numpy as np
from flask import Flask, jsonify, request, Response

HERE = os.path.dirname(os.path.abspath(__file__))
MCP_DIR = os.path.join(os.path.dirname(HERE), "bioyond-s4-mcp")
sys.path.insert(0, MCP_DIR)

import vision  # noqa: E402  (Arducam capture, from the MCP server)
import hikcam  # noqa: E402  (GigE capture, from the MCP server)

import anthropic  # noqa: E402

CONFIG_PATH = os.path.join(HERE, "config.json")
MODEL = "claude-opus-4-8"
MAX_IMAGE_TURNS = 4          # older user turns get their images pruned
SEND_MAX_LONG_EDGE = 1560    # downscale full frames before sending to the API
REFRESH_SECONDS = 1.2

SYSTEM_PROMPT = """You are the vision assistant for a Bioyond LabGenius S4 \
robot cell (4-axis lab robot, E1 comb-plate gripper) at Cephla. The operator \
sends you live camera frames from the cell and asks questions about them.

Cameras:
- cam1: frontal view of the bench (balance with black 96-well plate on the \
left, robot column center, Squid microscope right).
- cam2: along-the-bench view from the left end, next to the fluidics station.
- gige: monochrome eye-in-hand camera mounted on the robot's Z-carriage, \
looking down at the deck (~13 px/mm at deck depth).

When the operator draws a box on a frame, you receive the full frame with the \
box drawn in red, plus a zoomed crop of the boxed region. Answer about what \
is inside the box unless asked otherwise. Be concrete and concise; give pixel \
positions when useful. If asked about robot actions, describe what you see \
and suggest steps, but note you cannot move the robot from this console."""


# ---------------------------------------------------------------- config

def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def get_api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY") or load_config().get("api_key", "")


# ---------------------------------------------------------------- cameras

class Feed:
    def __init__(self, name: str):
        self.name = name
        self.frame: np.ndarray | None = None   # BGR
        self.jpeg: bytes | None = None
        self.error: str = "starting..."
        self.ts: float = 0.0


class CameraHub:
    """Owns all three cameras; a background thread refreshes cached frames."""

    def __init__(self) -> None:
        self.feeds = {"cam1": Feed("cam1"), "cam2": Feed("cam2"),
                      "gige": Feed("gige")}
        self._arducams = {"cam1": vision.Camera(0), "cam2": vision.Camera(1)}
        self._gige = hikcam.HikCamera()
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _capture(self, name: str) -> np.ndarray:
        if name == "gige":
            f = self._gige.capture()
            if f.ndim == 2:
                f = cv2.cvtColor(f, cv2.COLOR_GRAY2BGR)
            return f
        return self._arducams[name].capture(discard=1)

    def _loop(self) -> None:
        while True:
            for name, feed in self.feeds.items():
                try:
                    frame = self._capture(name)
                    ok, buf = cv2.imencode(".jpg", frame,
                                           [cv2.IMWRITE_JPEG_QUALITY, 82])
                    if not ok:
                        raise RuntimeError("jpeg encode failed")
                    with self._lock:
                        feed.frame = frame
                        feed.jpeg = buf.tobytes()
                        feed.error = ""
                        feed.ts = time.time()
                except Exception as ex:
                    with self._lock:
                        feed.error = str(ex)[:200]
                    # drop broken handles so the next round reopens cleanly
                    try:
                        if name == "gige":
                            self._gige.release()
                        else:
                            self._arducams[name].release()
                    except Exception:
                        pass
                    time.sleep(1.0)
            time.sleep(REFRESH_SECONDS)

    def latest(self, name: str) -> tuple[bytes | None, str, float]:
        with self._lock:
            f = self.feeds[name]
            return f.jpeg, f.error, f.ts

    def latest_frame(self, name: str) -> np.ndarray | None:
        with self._lock:
            f = self.feeds[name].frame
            return None if f is None else f.copy()


# ---------------------------------------------------------------- chat

class Chat:
    def __init__(self) -> None:
        self.messages: list[dict] = []   # anthropic message dicts
        self.log: list[dict] = []        # display log for the UI
        self._image_turns = 0

    def _prune_old_images(self) -> None:
        """Keep images only in the most recent MAX_IMAGE_TURNS user turns."""
        turns_with_images = [
            m for m in self.messages
            if m["role"] == "user" and isinstance(m["content"], list)
            and any(b.get("type") == "image" for b in m["content"])
        ]
        for m in turns_with_images[:-MAX_IMAGE_TURNS]:
            m["content"] = [
                b if b.get("type") != "image"
                else {"type": "text", "text": "[image from an earlier turn, omitted]"}
                for b in m["content"]
            ]

    def ask(self, content_blocks: list[dict]) -> str:
        key = get_api_key()
        if not key:
            raise RuntimeError("NO_API_KEY")
        client = anthropic.Anthropic(api_key=key)
        self.messages.append({"role": "user", "content": content_blocks})
        self._prune_old_images()
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            messages=self.messages,
        )
        reply = "".join(b.text for b in response.content if b.type == "text")
        self.messages.append({"role": "assistant", "content": reply})
        return reply


# ---------------------------------------------------------------- image prep

def b64_jpeg(frame: np.ndarray, max_long_edge: int | None = None) -> str:
    if max_long_edge:
        h, w = frame.shape[:2]
        scale = max_long_edge / max(h, w)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return base64.standard_b64encode(buf.tobytes()).decode()


def image_block(b64: str) -> dict:
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": b64}}


def annotate(frame: np.ndarray, bbox: list[int] | None) -> np.ndarray:
    out = frame.copy()
    if bbox:
        x0, y0, x1, y1 = bbox
        cv2.rectangle(out, (x0, y0), (x1, y1), (0, 0, 255), 3)
    return out


# ---------------------------------------------------------------- app

app = Flask(__name__)
hub = CameraHub()
chat = Chat()


@app.get("/")
def index() -> Response:
    return Response(PAGE, mimetype="text/html")


@app.get("/frame/<cam>")
def frame(cam: str):
    if cam not in hub.feeds:
        return jsonify({"error": "unknown camera"}), 404
    jpeg, err, ts = hub.latest(cam)
    if jpeg is None:
        return jsonify({"error": err or "no frame yet"}), 503
    resp = Response(jpeg, mimetype="image/jpeg")
    resp.headers["X-Error"] = err
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/status")
def status():
    out = {}
    for name in hub.feeds:
        jpeg, err, ts = hub.latest(name)
        out[name] = {"ok": jpeg is not None and not err, "error": err,
                     "age_s": round(time.time() - ts, 1) if ts else None}
    out["has_key"] = bool(get_api_key())
    return jsonify(out)


@app.post("/setkey")
def setkey():
    key = (request.json or {}).get("key", "").strip()
    if not key:
        return jsonify({"error": "empty key"}), 400
    cfg = load_config()
    cfg["api_key"] = key
    save_config(cfg)
    return jsonify({"ok": True})


@app.post("/reset")
def reset():
    chat.messages.clear()
    chat.log.clear()
    return jsonify({"ok": True})


@app.post("/chat")
def do_chat():
    data = request.json or {}
    cam = data.get("cam")
    bbox = data.get("bbox")          # [x0, y0, x1, y1] in native pixels or None
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty message"}), 400

    blocks: list[dict] = []
    if cam in hub.feeds:
        frm = hub.latest_frame(cam)
        if frm is not None:
            annotated = annotate(frm, bbox)
            blocks.append({"type": "text",
                           "text": f"[live frame from camera '{cam}'"
                                   + (f", operator drew a red box at "
                                      f"{bbox} (x0,y0,x1,y1 full-frame px)"
                                      if bbox else "") + "]"})
            blocks.append(image_block(b64_jpeg(annotated, SEND_MAX_LONG_EDGE)))
            if bbox:
                x0, y0, x1, y1 = bbox
                pad = 40
                h, w = frm.shape[:2]
                cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
                cx1, cy1 = min(w, x1 + pad), min(h, y1 + pad)
                if cx1 - cx0 > 10 and cy1 - cy0 > 10:
                    crop = frm[cy0:cy1, cx0:cx1]
                    blocks.append({"type": "text",
                                   "text": "[native-resolution crop of the "
                                           "boxed region]"})
                    blocks.append(image_block(b64_jpeg(crop, 1200)))
    blocks.append({"type": "text", "text": text})

    try:
        reply = chat.ask(blocks)
    except RuntimeError as ex:
        if str(ex) == "NO_API_KEY":
            return jsonify({"error": "no_api_key"}), 401
        return jsonify({"error": str(ex)}), 500
    except anthropic.AuthenticationError:
        return jsonify({"error": "no_api_key"}), 401
    except anthropic.RateLimitError:
        return jsonify({"error": "rate limited — wait a moment and retry"}), 429
    except anthropic.APIStatusError as ex:
        return jsonify({"error": f"API error {ex.status_code}: {ex.message}"}), 502
    except anthropic.APIConnectionError:
        return jsonify({"error": "network error reaching the Claude API"}), 502

    return jsonify({"reply": reply})


# ---------------------------------------------------------------- page

PAGE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>S4 Camera Console</title>
<style>
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.45 system-ui, sans-serif; background:#14171c;
         color:#dde3ea; display:flex; height:100vh; }
  #cams { flex:1.4; display:flex; flex-direction:column; gap:8px; padding:8px;
          overflow-y:auto; }
  .cam { position:relative; border:2px solid #2a2f37; border-radius:8px;
         background:#000; cursor:crosshair; }
  .cam.selected { border-color:#4da3ff; }
  .cam img { width:100%; display:block; border-radius:6px; }
  .cam canvas { position:absolute; inset:0; width:100%; height:100%; }
  .cam .tag { position:absolute; top:6px; left:8px; background:#000a;
              padding:2px 8px; border-radius:4px; font-weight:600;
              pointer-events:none; }
  .cam .err { position:absolute; bottom:6px; left:8px; background:#a33a;
              padding:2px 8px; border-radius:4px; font-size:12px;
              pointer-events:none; display:none; }
  #side { flex:1; display:flex; flex-direction:column; border-left:1px solid
          #2a2f37; min-width:340px; max-width:520px; }
  #log { flex:1; overflow-y:auto; padding:12px; }
  .msg { margin-bottom:10px; white-space:pre-wrap; }
  .msg .who { font-weight:700; font-size:12px; opacity:.7; }
  .msg.user .who { color:#4da3ff; } .msg.claude .who { color:#7ee08a; }
  .msg.sys { color:#e2b34c; font-size:12px; }
  #inputrow { display:flex; gap:6px; padding:10px; border-top:1px solid #2a2f37; }
  #text { flex:1; background:#1d232b; color:#dde3ea; border:1px solid #2a2f37;
          border-radius:6px; padding:8px; resize:none; height:60px; }
  button { background:#2b6cb0; color:#fff; border:0; border-radius:6px;
           padding:8px 14px; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  button.ghost { background:#2a2f37; }
  #topbar { display:flex; gap:6px; align-items:center; padding:8px 10px;
            border-bottom:1px solid #2a2f37; font-size:13px; }
  #bboxinfo { color:#e2b34c; }
  #keybox { padding:10px; border-bottom:1px solid #2a2f37; display:none; }
  #keybox input { width:100%; padding:6px; background:#1d232b; color:#dde3ea;
                  border:1px solid #2a2f37; border-radius:6px; }
</style></head><body>
<div id="cams">
  <div class="cam" id="p-cam1"><span class="tag">cam1 — frontal</span>
    <img id="i-cam1"><canvas id="c-cam1"></canvas><span class="err" id="e-cam1"></span></div>
  <div class="cam" id="p-cam2"><span class="tag">cam2 — along bench</span>
    <img id="i-cam2"><canvas id="c-cam2"></canvas><span class="err" id="e-cam2"></span></div>
  <div class="cam" id="p-gige"><span class="tag">gige — eye-in-hand</span>
    <img id="i-gige"><canvas id="c-gige"></canvas><span class="err" id="e-gige"></span></div>
</div>
<div id="side">
  <div id="topbar">
    <span>Selected: <b id="selname">cam1</b></span>
    <span id="bboxinfo"></span>
    <span style="flex:1"></span>
    <button class="ghost" onclick="clearBox()">Clear box</button>
    <button class="ghost" onclick="resetChat()">Reset chat</button>
  </div>
  <div id="keybox">
    <div style="margin-bottom:6px">Enter your Anthropic API key (stored locally
    in camera_gui/config.json):</div>
    <input id="keyinput" type="password" placeholder="sk-ant-...">
    <button style="margin-top:6px" onclick="saveKey()">Save key</button>
  </div>
  <div id="log"></div>
  <div id="inputrow">
    <textarea id="text" placeholder="Draw a box on a feed (optional), then ask Claude..."></textarea>
    <button id="send" onclick="send()">Send</button>
  </div>
</div>
<script>
const cams = ["cam1","cam2","gige"];
let selected = "cam1", bbox = null, bboxCam = null, drag = null, busy = false;

function el(id){ return document.getElementById(id); }
function addMsg(who, text, cls){
  const d = document.createElement("div");
  d.className = "msg " + cls;
  d.innerHTML = '<div class="who">' + who + '</div>';
  d.appendChild(document.createTextNode(text));
  el("log").appendChild(d); el("log").scrollTop = 1e9;
}

async function refresh(cam){
  try{
    const r = await fetch("/frame/" + cam + "?t=" + Date.now());
    if(r.ok){
      const b = await r.blob();
      const img = el("i-" + cam);
      const url = URL.createObjectURL(b);
      img.onload = () => { URL.revokeObjectURL(url); syncCanvas(cam); };
      img.src = url;
      el("e-" + cam).style.display = "none";
    } else {
      const j = await r.json().catch(()=>({error:"offline"}));
      const e = el("e-" + cam); e.textContent = j.error; e.style.display = "block";
    }
  }catch(err){}
}
setInterval(()=>{ cams.forEach(refresh); }, 1500);
cams.forEach(refresh);

function syncCanvas(cam){
  const img = el("i-" + cam), cv = el("c-" + cam);
  cv.width = img.clientWidth; cv.height = img.clientHeight;
  drawBox(cam);
}
function drawBox(cam){
  const cv = el("c-" + cam), ctx = cv.getContext("2d");
  ctx.clearRect(0,0,cv.width,cv.height);
  if(bbox && bboxCam === cam){
    const img = el("i-" + cam);
    const sx = img.clientWidth / img.naturalWidth,
          sy = img.clientHeight / img.naturalHeight;
    ctx.strokeStyle = "#ff3b3b"; ctx.lineWidth = 2;
    ctx.strokeRect(bbox[0]*sx, bbox[1]*sy, (bbox[2]-bbox[0])*sx, (bbox[3]-bbox[1])*sy);
  }
}
function toNative(cam, ev){
  const img = el("i-" + cam), r = img.getBoundingClientRect();
  const x = (ev.clientX - r.left) * img.naturalWidth / r.width;
  const y = (ev.clientY - r.top) * img.naturalHeight / r.height;
  return [Math.round(x), Math.round(y)];
}
cams.forEach(cam => {
  const panel = el("p-" + cam), cv = el("c-" + cam);
  panel.addEventListener("mousedown", ev => {
    selected = cam; el("selname").textContent = cam;
    cams.forEach(c => el("p-"+c).classList.toggle("selected", c===cam));
    drag = toNative(cam, ev); bboxCam = cam;
  });
  panel.addEventListener("mousemove", ev => {
    if(!drag) return;
    const p = toNative(cam, ev);
    bbox = [Math.min(drag[0],p[0]), Math.min(drag[1],p[1]),
            Math.max(drag[0],p[0]), Math.max(drag[1],p[1])];
    drawBox(cam);
    el("bboxinfo").textContent = "box " + bbox.join(",");
  });
  window.addEventListener("mouseup", () => {
    if(drag && bbox && (bbox[2]-bbox[0] < 8 || bbox[3]-bbox[1] < 8)){
      bbox = null; el("bboxinfo").textContent = ""; drawBox(cam);
    }
    drag = null;
  });
});
el("p-cam1").classList.add("selected");

function clearBox(){
  bbox = null; el("bboxinfo").textContent = "";
  cams.forEach(drawBox);
}
async function resetChat(){
  await fetch("/reset", {method:"POST"});
  el("log").innerHTML = ""; addMsg("system", "conversation reset", "sys");
}
async function saveKey(){
  const k = el("keyinput").value.trim();
  if(!k) return;
  await fetch("/setkey", {method:"POST",
    headers:{"Content-Type":"application/json"},
    body: JSON.stringify({key:k})});
  el("keybox").style.display = "none";
  addMsg("system", "API key saved", "sys");
}
async function send(){
  if(busy) return;
  const text = el("text").value.trim();
  if(!text) return;
  busy = true; el("send").disabled = true;
  const tag = bbox ? (" [" + bboxCam + " + box]") : (" [" + selected + "]");
  addMsg("you" + tag, text, "user");
  el("text").value = "";
  try{
    const r = await fetch("/chat", {method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify({cam: bbox ? bboxCam : selected, bbox, text})});
    const j = await r.json();
    if(r.status === 401){ el("keybox").style.display = "block";
      addMsg("system", "API key needed — paste it above.", "sys"); }
    else if(j.error){ addMsg("system", "error: " + j.error, "sys"); }
    else { addMsg("claude", j.reply, "claude"); }
  }catch(err){ addMsg("system", "request failed: " + err, "sys"); }
  busy = false; el("send").disabled = false;
}
el("text").addEventListener("keydown", ev => {
  if(ev.key === "Enter" && !ev.shiftKey){ ev.preventDefault(); send(); }
});
</script></body></html>
"""


if __name__ == "__main__":
    print("S4 camera console -> http://127.0.0.1:5001")
    app.run(host="127.0.0.1", port=5001, threaded=True)
