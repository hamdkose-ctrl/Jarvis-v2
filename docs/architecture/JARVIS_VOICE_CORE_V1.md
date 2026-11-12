# Jarvis Voice Core v1 — Architecture and bounded rollout

Status: VOICE-V2 unified output cutover (see the VOICE-V2 section at the end). `modules/voice_runtime.py` is now the single always-active speech owner for every assistant utterance; the legacy `voice.py`/Live speech paths are retired. This is still **not** evidence of human-audible Windows output or measured latency/AEC — those remain manual PC acceptance.

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

- `modules/engine_loop.py` routes assistant text through `VoiceSession.speak`, which now enqueues to the single `VoiceLane`; it no longer holds an Edge/network wait in the request loop. The microphone transcription path gates on `voice_runtime.handoff_to_listen()` (cut → verify stopped → open mic), half-duplex, not AEC.
- `modules/engine_voice.py` dispatches only to `VoiceLane.say` (single owner). `modules/engine_context.py:_voice_opts`/`set_profile_rate` read/write the user's one selected voice and bounded rate. There is no second preference authority and no `voice.speak`/Live speech branch left.
- `modules/voice.py` now holds ONLY the living microphone/STT/privacy surface (`recognize`, `listen`, `VOICES`, guards) and `stop_speaking` as the single-owner router to `voice_runtime.interrupt_active`. Its former Edge TTS, pyttsx3 local mode, MCI playback, `_local_say/_play_mp3/_chunks/_seq/_stop_flag/TTS_*` machinery was retired in the VOICE-V2 cutover below. Media-only `modules/local_narration.py` (produces audio FILES, not assistant speaker speech) is unaffected.
- Gemini Live was retired on 11 November 2026 (SES VE İLETİŞİM §9): `modules/live.py` and the whole `live_*` stack, `voice_timing`, `speech_activity` and `audio_diagnostics` are deleted, and the consumerless `live_*` settings plus the `response_speed`/`idle_seconds` selfctl promises are gone. Voice Core never depended on Live or Ollama; it does not now. Evidence: `tests/test_live_retirement.py` (files absent, no production import, retired setting keys absent from production and UI, living authorities still owned). `modules/engine_live_brain._live_command` is deliberately NOT deleted here — BRAIN-MIG-079 marks it `KEEP_EXECUTION` and Brain PR #579 owns it; it is caller-zero in production and recorded as such.

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

## VOICE-02C — Bounded incremental long-answer speech and cancellation receipts (mock acceptance)

The existing single `VoiceCoordinator` is still the only local audio-output owner. A long `SpeechRequest` (at most 12,000 characters) is now split into ordered chunks, default at most 600 characters, preferring sentence/word boundaries and never changing or omitting input characters. Each chunk uses the **same immutable VoiceSpec** selected for that request, with `PiperSynthesizer` then `WavePlayer` called sequentially. One speech receipt is emitted only after the whole utterance ends, fails or is cancelled; `played` continues to mean *playback adapter returned*, **not** sound confirmed by a human. This avoids holding the Core/event loop for a whole long utterance and allows cancellation at chunk boundaries as well as within cooperative Piper/WAV adapters.

Speech-only `interrupt_speech()` and `close()` now immediately dequeue and acknowledge **waiting** utterances with `VOICE_INTERRUPTED`. The active utterance remains cooperatively cancellable. This prevents pending `VoiceLane` completion events from getting stuck forever after shutdown and stops queued text from being spoken after "sus". It does not cancel GoalState, WorkerResult or the user's background jobs.

`tests/test_voice_chunking.py` and the extra `VoiceLane` receipt regression in `tests/test_voice_runtime_bridge.py` cover Unicode/exact-text preservation, bounded chunks, sequential synthesis, foreground over background preemption, queue draining, close behavior, no text/voice switching and failure midway through output. Audio and listeners are **mocked**; this is not evidence of smooth live Turkish pronunciation, device latency, buffer crackle, AEC/full-duplex microphone listening, model licensing, speech speed/prosody or correct device selection. The new route stays operator-controlled/opt-in while physical acceptance (VOICE-02B) is outstanding.


## VOICE-02D — Per-user bounded Piper speech speed (software contract)

The local Voice Core uses the existing user profile `prefs.rate` (-40..+40). The single authoritative writer `modules.engine_context.set_profile_rate` is shared by spoken rate commands and the Web UI. The writer rejects invalid types, broken explicit configuration and unavailable selected voices. User identities, `prefs.voice`, catalog entries, ONNX file names, model rights and provider selection never change as a side effect of speech speed.

Every `SpeechRequest` snapshots the bounded rate. `VoiceCoordinator` attaches it to a **temporary frozen** `VoiceSpec.speaking_rate` using `dataclasses.replace`, leaving the registered catalog unchanged. `PiperSynthesizer` maps rate to the documented Piper `--length_scale` option using `round(2 ** (-rate / 60), 3)`: 0 is default 1.0, positive is faster, negative is slower. The new CLI flag is sent only for nonzero rate. No pitch, timbre, new voice ID or network fallback is selected. An explicit `slow=True` lesson-reading request snapshots at most -15 without altering the profile.

Web UI reports `rate_supported=true` **only** when a local `VoiceLane` is active. When disabled, it retains its existing legacy mode behavior. When configured but broken it reports unavailable. `tests/test_voice_speed.py`, `test_voice_offline.py` and `test_voice_runtime_bridge.py` use mocked synthesizers and output to check rate bounds, correct Piper command, exact model identity and profile ownership.

VOICE-02B manual listening CLI also accepts `--rate -20`, `--rate 0` or `--rate 20` with the **same** `--voice-id`, `--model`, `--model-root` and `--license-reviewed`; it reports `requested_rate` without asserting the sound has the requested duration/quality. This command must be run by a human on their Windows speakers for each explicitly approved model. Invalid rate or missing licence confirmation fails before audio. It does not change the persisted user preference.

**This is not yet human-audible rate/prosody acceptance.** Operator must test actual Piper CLI version, selected Turkish models at slow/normal/fast rates on Windows speakers, pronunciation and latency between long-speech chunks. Keep VOICE-02A opt-in, no unapproved model downloads or replacement of the active voice until manually accepted with the VOICE-02B procedure.

## VOICE-V2 — Unified always-active speech owner and legacy retirement

`modules/voice_runtime.py` is now the single, always-active speech-output owner for every assistant utterance. When `voice_core.json` is explicitly enabled and valid, the offline Piper catalog runs inside the coordinator; otherwise the living exact-Edge voice table (`voice.VOICES`) runs as an EXACT-voice adapter of the SAME `VoiceCoordinator` — not a separate legacy loop. An install without Piper therefore keeps speaking, and an invalid explicit config fails closed (no silent Edge/SAPI substitution). The per-user `prefs.voice`/`prefs.rate` remain the sole identity authority; each request snapshots `voice_id` and rate; rendering never switches to another voice.

Retired in this cutover (zero production callers verified):
- `modules/voice.py` `speak`, `_local_say`, `_play_mp3`, `_chunks`, `_clean`, `_seq`, `_stop_flag`, `_fallback`, `TTS_VOICE`, `TTS_RATE`, `PAUSE`, `last_speech_end` and the `asyncio/ctypes/os/queue/tempfile/threading/edge_tts/pyttsx3` imports. `voice.stop_speaking` is retained purely as the single-owner router to `voice_runtime.interrupt_active`.
- The independent Live/`voice.speak` speech branch inside `VoiceSession.speak`; the former `tests/test_voice_shutdown.py` that bound only to those deleted internals (its behaviors are covered by `test_voice_core`, `test_voice_output_contract` and `test_voice_edge`).

Preserved living capabilities that the retirement had to keep:
- **Echo guard:** `stt_guard.note_said(text)` is now registered at the real `playback_started` boundary in `VoiceLane._stage_event`, so only audio that actually reaches the speaker suppresses a matching user command; a privacy-, invalidation- or owner-rejected utterance never registers.
- **Bounded synthesis:** `EdgeSynthesizer` now runs the online stream under an `asyncio.wait_for` deadline (default 45s, parity with the retired legacy timeout and Piper's 40s); expiry is a typed `EdgeVoiceUnavailable` → coordinator `failed` receipt + written notice, so a hung service cannot stick the single worker or the mic handoff forever.

New production behavior added in VOICE-V2:
- **Audible owner boundary (§5):** `VoiceLane._privacy_gate`, checked at enqueue and before every playback chunk, now also rejects a request whose `owner` is not the active desktop profile (`VOICE_OWNER_SWITCHED`). Switching users mid-queue can no longer leak the previous user's still-queued audio into the new user's session; the drop is silent (no misleading written notice), and the new user's own result is unaffected. Regression: `test_speech_for_another_owner_never_reaches_the_player`, `test_user_switch_stops_queued_old_owner_audio_before_playback`.
- **Real playback/UI stages:** `speech/{accepted,synthesizing,audio_ready,playback_started}` and `state/speaking` are presented only from the player's own `on_start` boundary, never from enqueue or WAV readiness, are owner-gated, and a late/cancelled receipt cannot idle a newer utterance (idle is owned by the busy-guarded receipt). The user's window is never force-fronted.
- **Safe output→input handoff:** `voice_runtime.handoff_to_listen(timeout)` cuts speech, waits only on the local playback acknowledgement, and opens the mic only when output actually stopped; if it does not stop within the bound the caller keeps its one-shot-listen protection.
- **Backpressure/typed receipts:** bounded 8-pending queue yields `VOICE_QUEUE_FULL`, closed owner `VOICE_CLOSED`, invalid/privacy `VOICE_PRIVACY_LOCAL_ONLY`; every refusal is a typed receipt + already-acknowledged Event, never a silent drop, and a failed/absent playback never marks a completed task failed (written result preserved).

`SpeechRequest` schema `speech.request.v2` carries the caller-supplied result identity — `kind, turn_id, event_id, goal_id, artifact_id, approval_id, ttl_seconds` — which voice only presents and uses for explicit, identity-targeted `invalidate(*, owner, goal_id, turn_id, event_id, request_id)` (empty selector refused, so a state refresh can never blind-clear the queue). Foreground conversation preempts only the audio notification, never its GoalState.

**Brain/integration points NOT closed by this voice branch (recorded, not implemented here):**
1. No producer-facing Scheduler hook exists: `resource_leases.py` `_ALLOWED_KINDS` has no output-device/speech kind and no production `LeaseTable`/`Scheduler` consumes one. Voice exposes busy state through `active()/is_busy()/busy_event/handoff_to_listen`, consumed by the microphone handoff only. Serializing physical-output occupancy under the Scheduler requires a Brain-side resource kind + consult — no second lease table will be added from the voice side.
2. "sus" → response-*generation* cancellation is only half closed. Closed here (§6, mute scope narrowed on 12 November 2026): `engine_queue.submit` → `voice_runtime.interrupt_active()` mutes **only the turns whose audio this stop cut** — the utterance in the player, the utterances still waiting in the speech queue (returned by `VoiceLane.interrupt()` from `VoiceCoordinator.interrupt_speech()`), plus the turn that last actually reached this owner's speaker (`playback_started`) — through `requests_state.mute_speech(slug, turn_id)`. An answer for that turn which never reached the queue, including one the model finishes *after* the stop, is refused at `VoiceLane._privacy_gate` with `VOICE_SUSPENDED_TURN` and can never restart speech, while GoalState/worker and the written result survive. A request the voice owner was never given is deliberately *not* muted, so "sus" on one conversation cannot discard a different background job's later spoken result (regression: `tests/test_voice_runtime_bridge.py::test_sus_keeps_the_other_jobs_later_spoken_result_while_muting_its_own`, `test_sus_never_mutes_a_request_the_lane_was_never_given`). Still a Brain call: an in-flight model/provider request is not aborted by "sus"; only its speech presentation is. No general `requests_state.cancel(owner)` is issued from the voice path, and `dur/stop` task semantics are never silently downgraded to "sus".
3. Gemini Live engine + `live_mode/live_beep/live_headphones/live_silence_ms/live_idle_seconds` settings + the `voice_timing` bridge: **retired on 11 November 2026** by this voice branch (§9) after the living STT helpers (`DEFAULT_FIXES`/`parse_fixes`/`format_fixes`) were relocated to their own owner `modules/stt_fixes.py` (readers: `learning.py`, `web.py`). What remains outside this branch is behavioural, not file-level: `engine_live_brain._live_command` (Brain #579, `KEEP_EXECUTION`) and the `learning.pending_prompt`/`pending_ask_due`/`mark_pending_ask` ask-back reminder, whose only trigger was the live-session instruction that no longer exists — both are caller-zero and locked as such in `tests/test_live_retirement.py::CallerZeroResidueTests`, with the record kept in `docs/agents/ses-video.md` and the §9 hand-off file (`docs/BEKLEYEN_ISLER.md` is a historical redirect and opens no work).

**Verified here:** unified owner, exact-voice identity/rate snapshot, no auto voice switch, foreground/background priority, bounded queue + adapter error typed receipts, `Sus` does not cancel Core work, late TTS/receipt cannot restore old audio/idle new speech, single playback owner, real-playback echo guard, bounded Edge synthesis, audible owner-switch boundary, Ollama-independent. **Not measured (PC acceptance):** human-audible Windows output/two-identity quality, AEC/full-duplex, §12 p95/p99 latency budgets, 15-min load underrun, cold model start. **Pre-existing out-of-scope flakes (untouched):** `test_conversation_request_safety.test_live_deadline_blocks_side_effect` and `test_stt_guard.EngineClarifyTests.test_voice_and_typed_bare_close_are_clarified_without_handler_or_stop` leak a real model call in voice **input** routing. Both reproduced with the identical assertion on a clean detached worktree of the merge base `60f5564` (no changes from this branch), i.e. they are not caused by the voice output work; they are intermittent because the leaked model answer differs per run. Fixing the leak is Brain/quota work, not this branch, and the tests were not deleted or weakened.
