# PinVoice — Voice Intelligence Platform

PinVoice is a Russian-language, web-first voice analysis MVP. It creates an initial acoustic **Voice DNA** profile from an audio recording and prepares the architecture for consent-based voice synthesis.

## MVP status

- [x] Web audio upload with explicit consent
- [x] Audio validation, metadata and waveform preview
- [x] Acoustic feature extraction (duration, sample rate, RMS, pitch estimate, spectral centroid)
- [x] MongoDB metadata persistence (optional but recommended)
- [x] Delete recording/profile endpoint
- [ ] Russian speech transcription (optional Faster-Whisper engine; enable with `PINVOICE_ENABLE_WHISPER=true`)
- [ ] Phoneme-level forced alignment and context-aware Phoneme DNA
- [ ] Neural voice synthesis

**Important:** this first release does not clone or synthesize a voice. Acoustic measurements are not a trained voice model. Phoneme boundaries are not fabricated; they require a later alignment stage.

## Run locally

Python 3.11+ and FFmpeg/libsndfile are recommended.

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. API docs: http://localhost:8000/docs.

MongoDB is optional for local testing. Set `MONGODB_URI` and `MONGODB_DATABASE` to persist profile metadata.

## Render deployment

This repository includes `render.yaml` and a Dockerfile. Connect the GitHub repository to Render and create the Blueprint. Set `MONGODB_URI` to a MongoDB Atlas connection string in the Render dashboard. The blueprint mounts a persistent disk at `/var/data` for uploaded audio.

For transcription, set `PINVOICE_ENABLE_WHISPER=true`. The first transcription request downloads the configured model and may take time; use a Render instance with sufficient RAM and CPU. Set `WHISPER_MODEL=tiny` initially. Long-running jobs and production-scale inference should move to a dedicated background worker.

## Privacy and safety

Only upload your own voice or a voice for which you have explicit, documented permission. Voice recordings and voice profiles are sensitive personal data. Restrict dashboard/API access before public launch, use HTTPS, configure retention, and never expose uploaded files publicly. Delete a profile using `DELETE /api/voices/{voice_id}`.

## API

- `GET /api/health`
- `POST /api/voices` — multipart fields: `file`, `consent=true`, optional `display_name`
- `GET /api/voices`
- `GET /api/voices/{voice_id}`
- `DELETE /api/voices/{voice_id}`

The API currently accepts WAV, MP3, M4A, OGG, FLAC and WebM audio, subject to decoder availability.
