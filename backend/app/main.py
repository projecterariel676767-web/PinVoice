from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from scipy.signal import find_peaks

try:
    from pymongo import MongoClient
except Exception:  # MongoDB is optional for local development
    MongoClient = None  # type: ignore

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("pinvoice")

BASE_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads")).resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "30")) * 1024 * 1024
ALLOWED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"}
ALLOWED_CONTENT_TYPES = {
    "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/mp4",
    "audio/x-m4a", "audio/ogg", "audio/flac", "audio/x-flac",
    "audio/webm", "application/octet-stream",
}

app = FastAPI(title="PinVoice API", version="0.1.0", description="Russian Voice Intelligence MVP")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

mongo_collection = None
if os.getenv("MONGODB_URI") and MongoClient:
    try:
        mongo_client = MongoClient(os.environ["MONGODB_URI"], serverSelectionTimeoutMS=5000)
        mongo_client.admin.command("ping")
        mongo_collection = mongo_client[os.getenv("MONGODB_DATABASE", "pinvoice")]["voices"]
        logger.info("MongoDB connected")
    except Exception:
        logger.exception("MongoDB unavailable; metadata will remain in process memory")

memory_profiles: dict[str, dict[str, Any]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_profile(profile: dict[str, Any]) -> None:
    memory_profiles[profile["id"]] = profile
    if mongo_collection is not None:
        mongo_collection.replace_one({"_id": profile["id"]}, {"_id": profile["id"], **profile}, upsert=True)


def get_profile(voice_id: str) -> dict[str, Any] | None:
    if mongo_collection is not None:
        doc = mongo_collection.find_one({"_id": voice_id})
        if doc:
            doc.pop("_id", None)
            return doc
    return memory_profiles.get(voice_id)


def list_profiles() -> list[dict[str, Any]]:
    if mongo_collection is not None:
        return [{k: v for k, v in item.items() if k != "_id"} for item in mongo_collection.find().sort("created_at", -1).limit(100)]
    return sorted(memory_profiles.values(), key=lambda item: item["created_at"], reverse=True)


def delete_profile(voice_id: str) -> bool:
    profile = get_profile(voice_id)
    if not profile:
        return False
    path = Path(profile["storage_path"])
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not remove audio file %s", path)
    memory_profiles.pop(voice_id, None)
    if mongo_collection is not None:
        mongo_collection.delete_one({"_id": voice_id})
    return True


def analyze_audio(path: Path) -> dict[str, Any]:
    # soundfile reads PCM WAV/FLAC directly. FFmpeg conversion is used for compressed formats.
    try:
        audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except Exception:
        import subprocess
        converted = path.with_suffix(".decoded.wav")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ac", "1", "-ar", "16000", str(converted)],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0 or not converted.exists():
            raise ValueError("Не удалось декодировать аудио. Попробуйте WAV, MP3 или FLAC.")
        audio, sample_rate = sf.read(str(converted), dtype="float32", always_2d=True)
        converted.unlink(missing_ok=True)

    if audio.size == 0:
        raise ValueError("Аудиозапись пуста.")
    mono = np.mean(audio, axis=1)
    duration = len(mono) / sample_rate
    if duration < 1.0:
        raise ValueError("Запись слишком короткая: нужно не менее 1 секунды.")
    if duration > 600:
        raise ValueError("Максимальная длительность записи — 10 минут.")

    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt(np.mean(np.square(mono))))
    clipping = float(np.mean(np.abs(mono) >= 0.999))
    # Estimate pitch with autocorrelation on voiced 40 ms frames.
    frame_len = max(512, int(sample_rate * 0.04))
    hop = max(256, int(sample_rate * 0.02))
    pitches: list[float] = []
    for start in range(0, max(0, len(mono) - frame_len), hop):
        frame = mono[start:start + frame_len]
        if np.sqrt(np.mean(frame * frame)) < 0.008:
            continue
        frame = frame - np.mean(frame)
        corr = np.correlate(frame, frame, mode="full")[len(frame) - 1:]
        min_lag = max(1, int(sample_rate / 400))
        max_lag = min(len(corr) - 1, int(sample_rate / 65))
        if max_lag <= min_lag:
            continue
        segment = corr[min_lag:max_lag]
        peaks, _ = find_peaks(segment)
        if len(peaks):
            lag = int(peaks[np.argmax(segment[peaks])]) + min_lag
            value = sample_rate / lag
            if 65 <= value <= 400:
                pitches.append(float(value))
    # Approximate spectral centroid from a bounded sample.
    sample = mono[:min(len(mono), sample_rate * 20)]
    spectrum = np.abs(np.fft.rfft(sample * np.hanning(len(sample))))
    freqs = np.fft.rfftfreq(len(sample), 1 / sample_rate)
    centroid = float(np.sum(freqs * spectrum) / (np.sum(spectrum) + 1e-9))
    waveform = mono[::max(1, len(mono) // 240)].tolist()[:240]

    return {
        "duration_seconds": round(duration, 2),
        "sample_rate_hz": int(sample_rate),
        "channels": int(audio.shape[1]),
        "peak_level": round(peak, 4),
        "rms_level": round(rms, 4),
        "clipping_percent": round(clipping * 100, 3),
        "estimated_pitch_hz": round(float(np.median(pitches)), 1) if pitches else None,
        "spectral_centroid_hz": round(centroid, 1),
        "waveform": [round(float(x), 3) for x in waveform],
        "quality_notes": (
            ["Возможна перегрузка микрофона: есть клиппинг."] if clipping > 0.01 else []
        ) + (["Низкий уровень сигнала; попробуйте говорить ближе к микрофону."] if rms < 0.012 else []),
    }


def transcribe_if_enabled(path: Path) -> dict[str, Any]:
    if os.getenv("PINVOICE_ENABLE_WHISPER", "false").lower() != "true":
        return {"status": "disabled", "text": None, "language": "ru"}
    try:
        from faster_whisper import WhisperModel
        model_name = os.getenv("WHISPER_MODEL", "tiny")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(path), language="ru", vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return {"status": "completed", "text": text, "language": info.language}
    except Exception as exc:
        logger.exception("Whisper transcription failed")
        return {"status": "error", "text": None, "language": "ru", "message": str(exc)[:240]}


@app.get("/api/health")
def health():
    return {"ok": True, "service": "pinvoice", "database": "connected" if mongo_collection is not None else "memory-only"}


@app.get("/api/voices")
def voices():
    return {"items": [{k: v for k, v in item.items() if k not in {"storage_path", "analysis"}} | {"analysis": {k: v for k, v in item.get("analysis", {}).items() if k != "waveform"}} for item in list_profiles()]}


@app.get("/api/voices/{voice_id}")
def voice_detail(voice_id: str):
    profile = get_profile(voice_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Voice profile not found")
    return {k: v for k, v in profile.items() if k != "storage_path"}


@app.post("/api/voices")
async def create_voice(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    consent: bool = Form(...),
    display_name: str = Form("Мой голос"),
):
    if not consent:
        raise HTTPException(status_code=400, detail="Необходимо подтвердить право на использование этой записи.")
    suffix = Path(file.filename or "recording.wav").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Поддерживаемые форматы: WAV, MP3, M4A, OGG, FLAC, WebM.")
    if file.content_type and file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Файл не распознан как аудиозапись.")
    voice_id = str(uuid.uuid4())
    destination = UPLOAD_DIR / f"{voice_id}{suffix}"
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"Максимальный размер файла — {MAX_UPLOAD_BYTES // (1024 * 1024)} МБ.")
                output.write(chunk)
        analysis = analyze_audio(destination)
        transcription = transcribe_if_enabled(destination)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except ValueError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        destination.unlink(missing_ok=True)
        logger.exception("Audio analysis failed")
        raise HTTPException(status_code=422, detail=f"Не удалось обработать аудио: {str(exc)[:200]}")

    profile = {
        "id": voice_id,
        "display_name": (display_name.strip() or "Мой голос")[:80],
        "language": "ru",
        "created_at": utc_now(),
        "status": "analyzed",
        "consent_confirmed": True,
        "file_name": Path(file.filename or "recording").name[:120],
        "file_size_bytes": size,
        "storage_path": str(destination),
        "analysis": analysis,
        "transcription": transcription,
        "phoneme_dna": {
            "status": "not_aligned",
            "description": "Акустический профиль создан. Для временных границ фонем и контекстных реализаций потребуется отдельный forced-alignment этап.",
            "phoneme_segments": [],
        },
    }
    persist_profile(profile)
    return {k: v for k, v in profile.items() if k != "storage_path"}


@app.delete("/api/voices/{voice_id}")
def remove_voice(voice_id: str):
    if not delete_profile(voice_id):
        raise HTTPException(status_code=404, detail="Voice profile not found")
    return {"ok": True, "deleted": voice_id}


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "src"), name="assets")
