# Jarvis Voice Core v1 — Architecture and bounded rollout

Status: VOICE-01 foundation only. This document is a target contract, NOT a live speech cutover.

## Invariants

1. **Voice-first, not voice-blocking:** speech has its own bounded foreground output worker. Brain/Core/GoalState/worker progression never depends on a TTS completion. A muted or unavailable output device must not block canonical task acceptance.
2. **LLM-provider independence:** the speech system accepts text from any authorized source. Ollama is optional; no TTS/STT model is downloaded or selected by an LLM. Runtime voice extension requires a developer-reviewed adapter and tests.
3. **Multiple available voices, one active voice per user:** male/female/style choices are catalog entries with immutable `voice_id`, backend and exact asset mapping. Each speech request snapshots the selected `voice_id`. It must never silently choose another voice when rendering fails.
4. **No false identical-voice promise:** Edge Ahmet/Emel, Windows SAPI and Piper models are not the same voice. A local/online transition is allowed only when the EXACT same validated voice identity and timbre contract can be guaranteed; otherwise fail with a visible receipt. The current offline and online engines cannot meet this guarantee.
5. **Speech vs goal cancellation:** "sus" cancels only audio; cancelling a goal requires a separate Core-authorized goal transition. A speech interruption must not cancel research, file work, scheduler leases or GoalState.
6. **Privacy:** cloud synthesis is forbidden in privacy modes that do not authorize egress. Local synthesis assets must be installed explicitly by developers/users according to licensing; no autonomous discovery/downloads.
7. **Single output owner:** no mixing of per-domain speakers. Foreground speech gets priority over already-queued background notifications; an already-playing adapter must cooperate with the cancellation signal. No forced thread killing.

## Target flow

```
Authenticated source (text / speech / event / Core / WorkerResult)
  -> typed SpeechRequest (owner, request_id, voice_id, text, lane)
  -> VoiceCoordinator (nonblocking enqueue, bounded priority, generation fence)
  -> developer-installed VoiceCatalog -> one exact TTS adapter
  -> validated audio buffer -> Audio Player -> Windows output
  -> SpeechReceipt (played, cancelled, failed, rejected; reason_code)
```

The Coordinator does **not** choose an alternate TTS provider or a new voice, create a GoalState, or interpret user intents. The audio playback return receipt is not proof the human actually heard sound. Mute, default output selection, volume and physical devices require a real-machine probe.

## Existing implementation seams

- `modules/engine_loop.py` currently emits text and then calls `VoiceSession.speak` in its request-processing loop while holding `audio_lock`; an Edge/network wait can therefore occupy that loop. Move it into the dedicated speech lane **only after** cancellation, output identity and visible UI behavior are preserved.
- `modules/engine_voice.py` currently dispatches to `voice.speak` or Live, and `modules/engine_context.py:_voice_opts` reads the user's selected voice. Reuse the existing preference data and voice choices; do not add a second preference authority.
- `modules/voice.py` currently implements Edge TTS, pyttsx3 local mode, and Windows MCI playback. Media-only `modules/local_narration.py` supports Piper/SAPI WAV rendering. None of these is automatically a voice-identity-compatible fallback.
- Gemini Live `enabled()` currently returns False. Do not design Voice Core to depend on Live or Ollama.

## Stage gates

- **VOICE-01 (this PR):** pure `VoiceSpec`, `VoiceCatalog`, `SpeechRequest`, `SpeechReceipt`, `VoiceCoordinator` with unit tests. No production dispatch changes. The adapter callbacks are intentionally injected; the current `voice.speak` remains the production owner.
- **VOICE-02:** connect the actual `engine_loop`, `VoiceSession`, background `say` events and typed PC/phone boundaries to the coordinator behind a developer-controlled flag. Validate voice snapshot from the existing per-user pref, audio ownership, cancellation, UI status and no double-speech. The flag defaults off until acceptance passes.
- **VOICE-03:** integrate a specifically chosen, licensed Turkish offline TTS model via a stable adapter. Test CPU latency and RAM on the real PC. Different voice choices may be installed; only one is active at a time. There is no guaranteed offline equivalent for existing Edge voices.
- **VOICE-04:** typed synthesis/playback failure codes, output device and level diagnostics, cleanup and bounded timeouts. Do not confuse completed synthesis with audible playback.
- **VOICE-05:** exact-head Windows CI and same-SHA PC watcher, followed by **human-audible** tests for two voice identities, long responses, interruption, concurrent goal execution, provider down, privacy and Ollama absent.

## Accepted vs not yet proven

VOICE-01 tests use fake adapters without microphone, speaker, network or model. They establish contract behavior only. They do not prove real audio, local Turkish voice quality, foreground scheduling under CPU pressure, barge-in microphone performance or production binding.

## VOICE-03A: offline adapter foundation (separate PR, not a cutover)

`modules/voice_offline.py` provides an explicitly provisioned `PiperSynthesizer` and `WavePlayer`. A developer supplies `model_root`, installs the Piper executable and approved Turkish `.onnx` models, and registers exact `VoiceSpec(voice_id, label, 'piper', asset_id)` entries. No code path downloads/installs a model, uses a cloud provider, invokes Ollama, or selects a substitute identity. The adapter validates model-root confinement and regular non-symlink files; it generates an ephemeral PCM WAV, validates metadata/data and deletes intermediates. `WavePlayer` streams frames to the configured Windows output via `sounddevice.RawOutputStream`, cooperatively respecting an audio-only cancellation event.

The adapter is not wired into `engine_loop` or the installed user's profile yet. No Piper executable, voice pack or SAPI fallback is bundled. The real PC must establish installed model integrity/licence, Turkish quality, low latency under concurrent Core work, output device and Windows master/per-app volume, and reliable user interruption before enabling this route. The mock tests demonstrate only the isolated adapter contract.
