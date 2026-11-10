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


## VOICE-02A — Explicitly opt-in live bridge (production path, disabled by default)

`modules/voice_runtime.py` is the sole optional speech-output owner when explicitly enabled. The default without config remains the pre-existing Edge/SAPI route, because no licensed Turkish male/female models are bundled. A developer/operator must first supply Piper and approved models, inspect license and verify real Windows audio. No automatic model install or voice switching.

The operator creates `<DATA_DIR>/voice_core.json` with **exact** schema:

```json
{
  "schema": "voice_core.config.v1",
  "enabled": true,
  "voices": {
    "tr_erkek": {"label": "Kurulu erkek sesinin gerçek adı", "model": "approved-male.onnx"},
    "tr_kadin": {"label": "Kurulu kadın sesinin gerçek adı", "model": "approved-female.onnx"}
  }
}
```

These are **illustrative filenames, not supplied assets**. Put only approved, installed `.onnx` models (with required model-specific config/metadata) under `<DATA_DIR>/voice_models/`, with an installed `piper` executable on the PATH. Existing user's `prefs.voice` key is the only selection authority; default identity is `tr_erkek` if unset, never an arbitrary other voice. Only configured entries can be selected. Voice selection checks that the exact model and Piper executable exist; no silent alternative Edge/SAPI voice is used if unavailable. No user data or audio is sent to the network by this route. The profile's legacy speech rate preference is **not yet mapped to Piper prosody**; slow-reading parity is an open acceptance criterion.

Operational boundaries:
- `VoiceSession.speak` enqueues work to `VoiceCoordinator` and returns immediately, allowing the request/GoalState worker to continue. Foreground speech can preempt queued or currently producing background audio through the existing cooperative cancellation token.
- `voice.stop_speaking` also interrupts the single active local lane, covering web, PC guidance, emergency and keyboard stop callers. It does not cancel any Core job; explicit `dur`/`stop` task cancellation still follows the separate Core command.
- When speech is busy, the normal microphone transcription path is gated against Jarvis's own audio. A separate wakeword barge-in listener may interrupt output only when that wakeword stack is installed and ready. This is **not** a validated full-duplex AEC implementation.
- A broken explicit voice config fails closed rather than silently playing the legacy voice. Closing the engine clears the active speech owner.
- The callback means the sound buffer was submitted/returned by the output adapter, **not that a person actually heard the audio**. Long text chunking, speech rate/prosody, runtime device diagnostics and real PC audibility are additional acceptance gates.

VOICE-02A tests run with fake audio and no network/model/OS playback. Before enabling on a real PC: verify licence and actual male/female Turkish model files, microphone no-feedback behavior, explicit voice selection persistence, interruption and background GoalState progress, full Windows CI on exact PR head, same-SHA PC watcher, and human listening with correct output device/volume. Keep the new route opt-in until all checks pass. Do not delete the old voice path until production parity is proven.

## VOICE-02B — Real-device human-audible output acceptance (manual probe)

`modules/voice_acceptance.py` is an operator-invoked acceptance check, not an auto-configurer or runtime worker. It uses the existing Piper synthesis and WAV playback adapters but does not launch Jarvis, alter voice preferences, download models, or claim the selected voice is active in production.

First identify available Windows output-device indices locally (no model or licence flag required):

```powershell
python -m modules.voice_acceptance --list-output-devices
```

With Jarvis stopped, Piper installed, model rights and training-data rights individually reviewed, and an approved `.onnx` plus its `.onnx.json` already available, run on Windows:

```powershell
python -m modules.voice_acceptance --model-root "C:\path\to\voice_models" --model "approved-voice.onnx" --voice-id tr_kadin --license-reviewed
```

Optionally pass `--device-index N` for the chosen Windows output. These model filenames are illustrative, NOT bundled. Repeat for each separately approved male/female model. The probe validates the exact local model, Piper metadata and sample rate, produces a short original Turkish sample, streams PCM to the selected speaker, and asks the operator whether they really heard the voice.

The console JSON separates `synthesis`, `playback` and `human_heard`. Playback-returned does NOT imply audible. Only an explicit yes after listening sets `verdict=human_confirmed` and exit code zero. Bad model, no license acknowledgement, device failure, silence, EOF/headless test or no hearing confirmation cannot pass. It writes no voice preference and sends no audio to a provider.

**Still unproven:** Actual quality and identity of at least two approved Turkish voice models, output device/volume, microphone echo and barge-in, long-text timing, simultaneous background GoalState progress, privacy and Ollama-absent behavior. Fake-audio CI and unattended Windows PC watcher are not human listening evidence.
