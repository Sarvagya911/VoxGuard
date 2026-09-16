# """
# VoxGuard — API Backend
# =========================
# Exposes the full VoxGuard pipeline (synthetic voice detection, speaker
# verification, context/intent analysis, risk fusion) as a REST API so any
# frontend (React, etc.) can call it directly.
#
# Run: uvicorn api.main:app --reload --port 8000
# Docs (auto-generated): http://localhost:8000/docs
# """
#
# import os
# import tempfile
# import json
# from datetime import datetime, timezone
#
# from fastapi import FastAPI, File, UploadFile, Form
# from fastapi.middleware.cors import CORSMiddleware
# from dotenv import load_dotenv
#
# load_dotenv()
#
# from backend.audio_layers.voxguard_layer1_synthetic_voice_detector import SyntheticVoiceDetector
# import backend.speaker_id.voxguard_layer2_speaker_verification as vg2
# from backend.context_nlp.voxguard_layer5_context_analyzer import analyze_context
# from backend.risk_engine.voxguard_risk_engine import compute_risk
#
# app = FastAPI(title="VoxGuard API", version="1.0")
#
# # Allow requests from any frontend origin during development.
# # Tighten this to your teammate's actual frontend URL before deploying.
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )
#
# print("[VoxGuard] Loading Synthetic Voice Detector (AASIST)...")
# detector = SyntheticVoiceDetector()
# print("[VoxGuard] Model loaded. API ready.")
#
#
# def _log(label: str, data: dict):
#     """Print a readable, timestamped block to the console for every request."""
#     timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
#     print(f"\n{'=' * 60}")
#     print(f"[{timestamp}] {label}")
#     print(json.dumps(data, indent=2, default=str))
#     print("=" * 60)
#
#
# @app.get("/health")
# def health():
#     return {"status": "ok", "service": "VoxGuard API"}
#
#
# @app.post("/enroll")
# async def enroll_speaker(name: str = Form(...), file: UploadFile = File(...)):
#     """Enroll a reference voice sample into the watchlist under `name`."""
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
#         tmp.write(await file.read())
#         tmp_path = tmp.name
#
#     vg2.enroll(name, tmp_path)
#     os.unlink(tmp_path)
#
#     result = {"status": "enrolled", "name": name}
#     _log(f"ENROLL — {name}", result)
#     return result
#
#
# @app.post("/analyze")
# async def analyze_call(file: UploadFile = File(...)):
#     """
#     Run the full VoxGuard pipeline on an uploaded audio file:
#     synthetic voice detection, watchlist matching, context/intent
#     analysis, and risk fusion. Returns the complete risk assessment.
#     """
#     with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
#         tmp.write(await file.read())
#         tmp_path = tmp.name
#
#     print(f"\n[VoxGuard] Analyzing '{file.filename}'...")
#
#     synth_result = detector.detect_full(tmp_path)
#     _log("Layer 1 — Synthetic Voice Detection", synth_result)
#
#     watch_result = vg2.check_watchlist(tmp_path)
#     _log("Layer 2 — Speaker Verification / Watchlist", watch_result)
#
#     context_result = analyze_context(tmp_path)
#     _log("Layer 5 — Context Analyzer", context_result)
#
#     final = compute_risk(synth_result, watch_result, context_result)
#     _log("RISK ENGINE — Final Assessment", final)
#
#     os.unlink(tmp_path)
#
#     # Combine everything into one response for the frontend
#     response = {
#         **final,
#         "transcript": context_result["transcript"],
#     }
#     return response
"""
VoxGuard — API Backend
=========================
Exposes the full VoxGuard pipeline (synthetic voice detection, speaker
verification, context/intent analysis, risk fusion) as a REST API so the
separate frontend/ (or any client) can call it directly.

Endpoints:
  - POST /enroll                  — enroll a reference voice into the watchlist
  - POST /analyze                 — analyze an uploaded or browser-recorded (mic) clip
  - POST /analyze-system-audio    — analyze a chunk of the system's current output
                                     audio (e.g. a Zoom/Meet/WhatsApp call playing
                                     on this device), captured via WASAPI loopback
  - GET  /call-status              — two-trigger call detection: is a monitored
                                     call app (or browser, for web-based calls like
                                     WhatsApp Web) both RUNNING and ACTIVELY
                                     producing sound right now?

Run (from inside backend/): python -m uvicorn api.main:app --reload --port 8001
Docs (auto-generated): http://localhost:8001/docs
"""

import os
import tempfile
import json
from datetime import datetime, timezone

import psutil
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()

from audio_layers.voxguard_layer1_synthetic_voice_detector import SyntheticVoiceDetector
from audio_layers.loopback_capture import (
    record_system_audio_chunk,
    save_chunk_to_wav,
    get_active_audio_sessions,
)
import speaker_id.voxguard_layer2_speaker_verification as vg2
from context_nlp.voxguard_layer5_context_analyzer import analyze_context
from risk_engine.voxguard_risk_engine import compute_risk

app = FastAPI(title="VoxGuard API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("[VoxGuard] Loading Synthetic Voice Detector (AASIST)...")
detector = SyntheticVoiceDetector()
print("[VoxGuard] Model loaded. API ready.")

# Desktop call apps + browsers (for web-based calls like WhatsApp Web,
# Google Meet, Discord in-browser, etc.). Note: browser detection can't
# distinguish a call tab from any other tab playing audio — Trigger 2
# (active audio session) still has to be true, but it can't tell WHICH
# tab is the source. This is a known limitation, not a bug.
CALL_APP_NAMES = [
    "zoom.exe", "whatsapp.exe", "teams.exe", "discord.exe",
    "chrome.exe", "msedge.exe", "firefox.exe",
]


def _log(label: str, data: dict):
    """Print a readable, timestamped block to the console for every request."""
    timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"\n{'=' * 60}")
    print(f"[{timestamp}] {label}")
    print(json.dumps(data, indent=2, default=str))
    print("=" * 60)


def _to_wav(raw_bytes: bytes, original_filename: str) -> str:
    """
    Converts any audio format the client sends (webm from the browser mic,
    mp3, plain wav, etc.) into a standard 16kHz mono WAV file that
    soundfile/librosa can read reliably downstream.
    """
    suffix = os.path.splitext(original_filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as raw_tmp:
        raw_tmp.write(raw_bytes)
        raw_path = raw_tmp.name

    wav_path = raw_path + "_converted.wav"
    audio = AudioSegment.from_file(raw_path)
    audio = audio.set_frame_rate(16000).set_channels(1)
    audio.export(wav_path, format="wav")

    os.unlink(raw_path)
    return wav_path


def _run_pipeline(wav_path: str, source_label: str) -> dict:
    """Shared pipeline runner used by /analyze and /analyze-system-audio."""
    synth_result = detector.detect_full(wav_path)
    _log(f"Layer 1 — Synthetic Voice Detection ({source_label})", synth_result)

    watch_result = vg2.check_watchlist(wav_path)
    _log(f"Layer 2 — Speaker Verification / Watchlist ({source_label})", watch_result)

    context_result = analyze_context(wav_path)
    _log(f"Layer 5 — Context Analyzer ({source_label})", context_result)

    final = compute_risk(synth_result, watch_result, context_result)
    _log(f"RISK ENGINE — Final Assessment ({source_label})", final)

    return {**final, "transcript": context_result["transcript"]}


@app.get("/health")
def health():
    return {"status": "ok", "service": "VoxGuard API"}


@app.get("/call-status")
def call_status():
    """
    Two-trigger call detection:
      Trigger 1 — is a monitored call app (or browser) process running?
      Trigger 2 — is that SAME app currently the source of an ACTIVE
                  audio session (i.e. genuinely making sound right now)?

    Both must be true, on the SAME app, for `likely_call_active`. Note:
    for browser-based calls (e.g. WhatsApp Web), this detects "the
    browser is actively playing audio" — it cannot distinguish a call
    tab from any other tab making sound (YouTube, music, etc.), since
    Windows doesn't expose per-tab audio sessions, only per-process.
    """
    running_apps = []
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info["name"].lower()
            if name in CALL_APP_NAMES:
                running_apps.append(name)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    active_audio_apps = get_active_audio_sessions()

    apps_with_active_audio = [app for app in running_apps if app in active_audio_apps]

    result = {
        "call_apps_running": running_apps,
        "apps_with_active_audio": active_audio_apps,
        "likely_call_active": len(apps_with_active_audio) > 0,
        "detected_call_app": apps_with_active_audio[0] if apps_with_active_audio else None,
    }
    return result


@app.post("/enroll")
async def enroll_speaker(name: str = Form(...), file: UploadFile = File(...)):
    """Enroll a reference voice sample into the watchlist under `name`."""
    raw_bytes = await file.read()
    wav_path = _to_wav(raw_bytes, file.filename)

    vg2.enroll(name, wav_path)
    os.unlink(wav_path)

    result = {"status": "enrolled", "name": name}
    _log(f"ENROLL — {name}", result)
    return result


@app.post("/analyze")
async def analyze_call(file: UploadFile = File(...)):
    """
    Run the full VoxGuard pipeline on an uploaded or browser-recorded
    (microphone) audio clip.
    """
    raw_bytes = await file.read()
    wav_path = _to_wav(raw_bytes, file.filename)

    print(f"\n[VoxGuard] Analyzing '{file.filename}' (mic/upload)...")
    result = _run_pipeline(wav_path, "mic/upload")

    os.unlink(wav_path)
    return result


@app.post("/analyze-system-audio")
async def analyze_system_audio():
    """
    Records a few seconds of the system's current output audio (e.g. an
    ongoing Zoom/Meet/WhatsApp call playing on this machine, captured via
    WASAPI loopback) and runs it through the full VoxGuard pipeline.
    """
    print("\n[VoxGuard] Recording system audio chunk (loopback)...")
    audio_array = record_system_audio_chunk(duration_sec=4.0)

    tmp_path = tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name
    save_chunk_to_wav(audio_array, tmp_path)

    result = _run_pipeline(tmp_path, "system audio")

    os.unlink(tmp_path)
    return result