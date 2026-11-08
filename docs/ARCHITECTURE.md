# PinVoice MVP architecture

## Flow

1. The browser asks the speaker to confirm ownership or explicit permission.
2. Audio is uploaded to FastAPI with a random UUID filename and size/type limits.
3. The backend decodes audio, validates duration and extracts measurable acoustic features.
4. Optional Faster-Whisper transcription runs in Russian when enabled.
5. Metadata and the initial Voice DNA summary are stored in MongoDB; audio is stored on the Render persistent disk.
6. The owner can list profiles and delete the profile plus its stored audio.

## Hybrid Voice DNA

The first version stores measurable features (pitch estimate, RMS, clipping, spectral centroid, sample rate and waveform preview). These are descriptive features, not a neural voice embedding.

The next phonetic stage should combine:
- Russian ASR transcript;
- forced alignment to obtain word/phoneme time spans;
- contextual phoneme realizations (neighboring phones, stress, position, speaking style);
- robust speaker embeddings and prosody statistics.

A phoneme is context-dependent. Do not treat one isolated recording per phoneme as a complete representation or synthesize speech by concatenating raw phoneme clips.

## Synthesis phase (not implemented)

A separately evaluated neural TTS model should consume text, phonetic/contextual conditioning and a consent-verified speaker representation. Model choice must be checked for Russian quality, commercial license, inference footprint and voice-cloning safeguards.

## Deployment boundaries

The web process currently performs analysis in the request lifecycle. This is suitable only for short MVP recordings and low concurrency. Move transcription, alignment and model inference into a background worker/queue before production. Keep MongoDB for metadata, and object storage or a persistent disk for audio assets.
