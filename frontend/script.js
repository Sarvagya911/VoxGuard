const API_BASE = "http://localhost:8001";

// ---------------------------------------------------------------------
// Enroll
// ---------------------------------------------------------------------
document.getElementById("enrollBtn").addEventListener("click", async () => {
  const name = document.getElementById("enrollName").value.trim();
  const fileInput = document.getElementById("enrollFile");
  const statusEl = document.getElementById("enrollStatus");

  if (!name || !fileInput.files[0]) {
    statusEl.textContent = "Please provide a name and a .wav file.";
    statusEl.className = "status error";
    return;
  }

  const formData = new FormData();
  formData.append("name", name);
  formData.append("file", fileInput.files[0]);

  statusEl.textContent = "Enrolling...";
  statusEl.className = "status";

  try {
    const res = await fetch(`${API_BASE}/enroll`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();
    statusEl.textContent = `Enrolled '${data.name}' successfully.`;
    statusEl.className = "status success";
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}. Is the backend running on ${API_BASE}?`;
    statusEl.className = "status error";
  }
});

// ---------------------------------------------------------------------
// Analyze (file upload)
// ---------------------------------------------------------------------
document.getElementById("analyzeBtn").addEventListener("click", async () => {
  const fileInput = document.getElementById("analyzeFile");
  const statusEl = document.getElementById("analyzeStatus");
  const btn = document.getElementById("analyzeBtn");

  if (!fileInput.files[0]) {
    statusEl.textContent = "Please choose a .wav file first.";
    statusEl.className = "status error";
    return;
  }

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);

  statusEl.textContent = "Analyzing... (this can take a few seconds)";
  statusEl.className = "status";
  btn.disabled = true;

  try {
    const res = await fetch(`${API_BASE}/analyze`, { method: "POST", body: formData });
    if (!res.ok) throw new Error(`Server returned ${res.status}`);
    const data = await res.json();

    renderResult(data);
    statusEl.textContent = "";
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}. Is the backend running on ${API_BASE}?`;
    statusEl.className = "status error";
  } finally {
    btn.disabled = false;
  }
});

// ---------------------------------------------------------------------
// Live Microphone Monitoring
// ---------------------------------------------------------------------
const CHUNK_MS = 4000;

let liveStream = null;
let liveRunning = false;

const startLiveBtn = document.getElementById("startLiveBtn");
const stopLiveBtn = document.getElementById("stopLiveBtn");
const liveStatus = document.getElementById("liveStatus");

startLiveBtn.addEventListener("click", async () => {
  try {
    liveStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    liveStatus.textContent = "Microphone access denied or unavailable.";
    liveStatus.className = "status error";
    return;
  }

  liveRunning = true;
  startLiveBtn.disabled = true;
  stopLiveBtn.disabled = false;
  liveStatus.textContent = "Live monitoring started (microphone)...";
  liveStatus.className = "status";

  micRecordLoop();
});

stopLiveBtn.addEventListener("click", () => {
  liveRunning = false;
  if (liveStream) {
    liveStream.getTracks().forEach(track => track.stop());
  }
  startLiveBtn.disabled = false;
  stopLiveBtn.disabled = true;
  liveStatus.textContent = "Microphone monitoring stopped.";
});

async function micRecordLoop() {
  while (liveRunning) {
    const chunkBlob = await recordChunk(liveStream, CHUNK_MS);
    if (!liveRunning) break;

    liveStatus.textContent = "Analyzing chunk...";

    try {
      const formData = new FormData();
      formData.append("file", chunkBlob, "live_chunk.webm");

      const res = await fetch(`${API_BASE}/analyze`, { method: "POST", body: formData });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();

      renderResult(data);
      liveStatus.textContent = "Listening (microphone)...";
    } catch (err) {
      liveStatus.textContent = `Error analyzing chunk: ${err.message}`;
      liveStatus.className = "status error";
    }
  }
}

function recordChunk(stream, durationMs) {
  return new Promise((resolve) => {
    const recorder = new MediaRecorder(stream);
    const chunks = [];

    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = () => resolve(new Blob(chunks, { type: "audio/webm" }));

    recorder.start();
    setTimeout(() => recorder.stop(), durationMs);
  });
}

// ---------------------------------------------------------------------
// System Audio Loopback Monitoring
// ---------------------------------------------------------------------
let systemRunning = false;

const startSystemBtn = document.getElementById("startSystemBtn");
const stopSystemBtn = document.getElementById("stopSystemBtn");
const systemStatus = document.getElementById("systemStatus");

startSystemBtn.addEventListener("click", () => {
  if (systemRunning) return;
  systemRunning = true;
  startSystemBtn.disabled = true;
  stopSystemBtn.disabled = false;
  systemStatus.textContent = "Monitoring system audio (e.g. call/Meet audio playing on this device)...";
  systemStatus.className = "status";
  systemLoop();
});

stopSystemBtn.addEventListener("click", () => {
  systemRunning = false;
  startSystemBtn.disabled = false;
  stopSystemBtn.disabled = true;
  systemStatus.textContent = "System audio monitoring stopped.";
});

async function systemLoop() {
  while (systemRunning) {
    systemStatus.textContent = "Recording & analyzing system audio chunk...";
    try {
      const res = await fetch(`${API_BASE}/analyze-system-audio`, { method: "POST" });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);
      const data = await res.json();

      renderResult(data);
      systemStatus.textContent = "Listening to system audio...";
    } catch (err) {
      systemStatus.textContent = `Error: ${err.message}`;
      systemStatus.className = "status error";
      break;
    }
  }
}

// ---------------------------------------------------------------------
// Auto-detect an active call and auto-start system audio monitoring
// ---------------------------------------------------------------------
async function pollCallStatus() {
  setInterval(async () => {
    if (systemRunning) return;

    try {
      const res = await fetch(`${API_BASE}/call-status`);
      if (!res.ok) return;
      const status = await res.json();

      if (status.likely_call_active) {
        systemStatus.textContent = `Active call detected in ${status.detected_call_app} — auto-starting monitoring.`;
        startSystemBtn.click();
      }
    } catch (err) {
      // Silently ignore polling errors — background convenience only.
    }
  }, 5000);
}

pollCallStatus();

// ---------------------------------------------------------------------
// Risk Toast (floating popup for high-risk results)
// ---------------------------------------------------------------------
let toastTimeout = null;

function showRiskToast(riskScore, riskLevel) {
  const toast = document.getElementById("riskToast");
  const toastText = document.getElementById("riskToastText");

  if (riskScore < 75) return; // only pop up for genuinely high scores

  toastText.textContent = `${riskLevel} — Risk Score ${riskScore}/100`;
  toast.classList.remove("hidden");

  void toast.offsetWidth; // force reflow so the transition re-triggers
  toast.classList.add("show");

  if (toastTimeout) clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.classList.add("hidden"), 300);
  }, 5000);
}

// ---------------------------------------------------------------------
// Shared result rendering (used by mic, upload, and system-audio modes)
// ---------------------------------------------------------------------
function renderResult(data) {
  document.getElementById("resultCard").classList.remove("hidden");
  showRiskToast(data.risk_score, data.risk_level);

  document.getElementById("metricSynthetic").textContent =
    `${(data.synthetic_probability * 100).toFixed(1)}%`;
  document.getElementById("metricWatchlist").textContent =
    data.watchlist_match ? "Yes" : "No";
  document.getElementById("metricIntent").textContent = data.intent_category;
  document.getElementById("metricSpeaker").textContent = data.matched_name || "—";

  const riskDot = document.getElementById("riskDot");
  riskDot.className = "risk-dot";
  if (data.risk_level === "MEDIUM-RISK CALL") riskDot.classList.add("medium");
  if (data.risk_level === "HIGH-RISK CALL") riskDot.classList.add("high");

  document.getElementById("riskLevel").textContent = data.risk_level;
  document.getElementById("riskScore").textContent = `${data.risk_score}/100`;

  const reasonsList = document.getElementById("reasonsList");
  reasonsList.innerHTML = "";
  data.reasons.forEach(reason => {
    const li = document.createElement("li");
    li.textContent = reason;
    reasonsList.appendChild(li);
  });

  document.getElementById("actionText").textContent = data.recommended_action;
  document.getElementById("transcriptText").textContent = data.transcript;
}