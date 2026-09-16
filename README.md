# 🛡️ VoxGuard

**Real-Time Voice Cloning & Impersonation Detection**
Smart India Hackathon 2026 — Problem Statement 26104

VoxGuard is a multi-layered voice security system that analyzes a call in
real time to answer three questions at once: *Is this voice AI-generated?
Does it match a known/enrolled speaker? Is the caller asking for something
they shouldn't be?* Each signal is combined into a single, explainable risk
score with a recommended action.

## Why this matters

AI voice cloning has turned identity into an attack surface. A short audio
sample is now enough to convincingly impersonate someone over a phone call
— enabling fraud, OTP theft, and social engineering that traditional
caller-ID and voice checks cannot catch. VoxGuard is built to close that
gap by never relying on a single signal.

## Architecture

| Layer | Question it answers | Model |
|---|---|---|
| Synthetic Voice Detector | Is the audio AI-generated? | AASIST (pretrained on ASVspoof 2019 LA), analyzed across sliding 4s windows (2s hop) for full-length audio |
| Speaker Verification / Watchlist | Does this voice match a known or flagged speaker? | ECAPA-TDNN (SpeechBrain, pretrained on VoxCeleb) |
| Context Analyzer | Is the caller requesting money, OTP, or making a threat? | Groq Whisper (`whisper-large-v3`) for transcription + Groq LLM (`openai/gpt-oss-120b`) for intent classification with confidence scoring |
| Risk Engine | How dangerous is the overall situation? | Custom fusion logic — strongest single signal sets the base risk, corroborating signals push it higher |

**Fusion logic:** rather than averaging signals (which mathematically caps
how high any single confident signal can push the score), the strongest
signal sets the base risk, and additional corroborating signals add on top
of it. A highly confident threat or fraud detection can trigger HIGH risk
on its own; multiple weaker signals together can also escalate.

## Project structure

VoxGuard/
├── backend/
│ ├── audio_layers/ # Layer 1: synthetic voice detection (AASIST) +
│ │ # system-audio loopback capture / call detection
│ ├── speaker_id/ # Layer 2: speaker verification & watchlist matching
│ ├── context_nlp/ # Layer 5: transcription + intent classification (Groq)
│ ├── risk_engine/ # Fusion logic — combines all signals into a risk score
│ ├── api/ # FastAPI backend — REST API for any frontend
│ ├── app.py # Streamlit dashboard (internal testing / fallback UI)
│ ├── data/ # Test audio samples
│ └── .env # GROQ_API_KEY (not committed)
├── frontend/
│ ├── index.html # Dashboard UI
│ ├── style.css
│ └── script.js # Talks to the backend API, handles mic capture,
│ # system-audio polling, and risk toast alerts
├── requirements.txt
├── API_CONTRACT.md # Full API spec for the frontend
└── README.md


## Running it

### 1. Backend (FastAPI)

```bash
cd backend
pip install -r ../requirements.txt
```

Create `backend/.env` with your Groq API key:

GROQ_API_KEY=your_key_here


Run:
```bash
python -m uvicorn api.main:app --reload --port 8001
```
API docs: `http://localhost:8001/docs`

### 2. Frontend

In a separate terminal:
```bash
cd frontend
python -m http.server 5500
```
Open `http://localhost:5500` in your browser. (Must be served over `http://`, not opened as a raw `file://` path — the browser blocks microphone access on `file://` origins.)

### 3. (Optional) Streamlit dashboard — internal testing / fallback

```bash
cd backend
python -m streamlit run app.py
```

## What you can do in the dashboard

1. **Enroll a known speaker** — upload a reference voice sample to add them to the watchlist
2. **Analyze an incoming call** — upload call audio and get a full risk breakdown: synthetic voice probability, watchlist match, intent classification with confidence, and a fused risk score with recommended action
3. **Live microphone monitoring** — captures short audio chunks from the browser mic and analyzes each one continuously
4. **System audio monitoring** — captures whatever is playing through the device's speakers (e.g. a Zoom/Meet/WhatsApp call happening on this machine) via WASAPI loopback, so it can hear both sides of a VoIP call, not just the mic
5. **Auto-detect active calls** — polls a two-trigger check (is a call app/browser running, AND is it actively producing sound) and automatically starts system-audio monitoring when a call is likely in progress
6. **High-risk alert** — a floating toast notification appears automatically whenever a result's risk score crosses 75/100

## Datasets & models used

- [ASVspoof 2019 LA](https://www.asvspoof.org/index2019.html) — synthetic/spoofed speech benchmark, used to validate the synthetic voice detector
- [In-the-Wild](https://huggingface.co/datasets/mueller91/In-The-Wild) — real-world deepfake audio, used for generalization testing
- [AASIST](https://github.com/clovaai/aasist) (Jung et al., 2022) — pretrained anti-spoofing checkpoint
- [SpeechBrain ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) — pretrained speaker embedding model
- [Groq API](https://console.groq.com) — `whisper-large-v3` for transcription, `openai/gpt-oss-120b` for intent classification

## Known limitations (honest, by design)

- The synthetic voice detector, like all anti-spoofing models, generalizes
  better to attack types present in its training data (ASVspoof) than to
  newer/unseen TTS systems — a known open problem in anti-spoofing
  research, not unique to this implementation.
- The watchlist in this demo uses synthetic/self-enrolled data, not a real
  law-enforcement or telecom database. In production this would integrate
  with an authorized watchlist API.
- The watchlist currently lives in memory only and resets when the backend
  restarts — persistence (e.g. a small database) is a natural next step.
- "Real-time" here means short-chunk (4s) analysis of browser-captured
  microphone or system-loopback audio, not live telephony call
  interception — extending to real cellular call audio would require
  telephony integration (e.g. Twilio, SIP trunking).
- Call-app auto-detection identifies desktop apps by process name and
  browsers by process name (for web-based calls like WhatsApp Web). It
  cannot distinguish a call tab from any other tab playing audio in the
  same browser, since Windows doesn't expose per-tab audio sessions.
- Risk fusion weights and thresholds are hand-tuned for this demo, not
  calibrated against a labeled dataset — production tuning would use
  validation data specific to the deployment context.

## Team

Built for SIH 2026 by [team name] — [team members].

## Tech stack

Python · PyTorch · SpeechBrain · Whisper (via Groq) · Groq LLM API ·
FastAPI · Streamlit · HTML/CSS/JavaScript (vanilla) · Librosa · Soundfile ·
Pydub/ffmpeg · Soundcard (WASAPI loopback) · Pycaw · Psutil