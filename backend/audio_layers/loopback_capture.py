"""
VoxGuard — System Audio Loopback Capture
===========================================
Captures whatever audio is currently playing through the system's default
output device (speakers/headphones) — e.g. a Zoom, Google Meet, or
WhatsApp Web call happening on this machine. This is different from
microphone capture: it hears BOTH sides of a VoIP call as played back
locally, not just what you say into the mic.

Also provides call-detection helpers:
  - which monitored call apps are currently running as processes
  - which apps currently have an ACTIVE audio session (i.e. are actually
    making sound right now, via Windows' per-app audio session API)

Notes:
  - The pycaw import inside get_active_audio_sessions() is intentionally
    deferred (imported inside the function, not at module load time).
    comtypes initializes Windows COM threading the moment it's imported,
    which conflicts with uvicorn's --reload subprocess bootstrap if
    imported at the top of the file. Delaying the import to first-call
    time avoids that crash with zero behavior change otherwise.
  - Session state is compared against the raw integer 1 (Active) rather
    than an AudioSessionState enum, since that enum's name/export varies
    across pycaw versions and isn't reliably importable. Per the Windows
    Audio Session API: 0 = Inactive, 1 = Active, 2 = Expired.

Install:
    pip install soundcard pycaw comtypes
"""

import soundcard as sc
import soundfile as sf
import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1


def record_system_audio_chunk(duration_sec: float = 4.0) -> np.ndarray:
    """
    Records `duration_sec` seconds of whatever is currently playing through
    the default speaker/output device, and returns it as a mono float32
    NumPy array at 16kHz — ready to feed directly into VoxGuard's layers.
    """
    default_speaker = sc.default_speaker()
    loopback_mic = sc.get_microphone(id=str(default_speaker.name), include_loopback=True)

    with loopback_mic.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS) as recorder:
        data = recorder.record(numframes=int(SAMPLE_RATE * duration_sec))

    if data.ndim > 1:
        data = data.mean(axis=1)

    return data.astype(np.float32)


def save_chunk_to_wav(audio_array: np.ndarray, path: str):
    sf.write(path, audio_array, SAMPLE_RATE)


def get_active_audio_sessions() -> list:
    """
    Returns the process names (lowercase) of apps that currently have an
    ACTIVE audio session on this machine — i.e. apps that are genuinely
    producing sound right now, not just open in the background.
    """
    from pycaw.pycaw import AudioUtilities  # deferred import — see module docstring

    ACTIVE_STATE = 1  # per Windows Audio Session API: 0=Inactive, 1=Active, 2=Expired

    active = []
    try:
        sessions = AudioUtilities.GetAllSessions()
        for session in sessions:
            if session.Process and session.State == ACTIVE_STATE:
                active.append(session.Process.name().lower())
    except Exception:
        # pycaw/session enumeration can occasionally throw on Windows —
        # fail safe by returning an empty list rather than crashing the
        # whole /call-status endpoint.
        pass
    return active