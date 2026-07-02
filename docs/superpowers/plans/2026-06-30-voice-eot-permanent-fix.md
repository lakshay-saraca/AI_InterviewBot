# Voice EOT — Permanent Fix for "Bot Interrupts the Candidate"

Date: 2026-06-30. Supersedes the deferral in `VOICE_FIXES_PLAN.md` ("Item 3: EOT
semantic turn-taking"). Decisions: **two-phase**; Phase-2 engine = **LiveKit
turn-detector (ONNX), backend, replacing the debounce ladder** (GRILL_NOTES_2.md Q4/Q6
default).

Test baseline: run targeted (`tests/test_turn_taking.py`, `tests/test_voice_turn_processor.py`)
— the full suite hangs post-run on orphaned aiosqlite threads (known-red baseline).

---

## Root cause (verified)

The bot talks over the candidate because **end-of-turn (EOT) is decided by three
independent fixed timers, none of which knows whether the candidate's *thought* is
finished.** Any one firing during a natural mid-sentence pause makes the bot speak:

1. **Client VAD `speech_end`** — `vad.worker.ts` declares the turn over after 1500 ms
   of sub-threshold audio (`SILENCE_FRAMES_THRESHOLD = 75`). The server then flushes to
   the LLM after only a 0.35 s grace (`SPEECH_END_FINAL_GRACE_SECS`). A 1.5 s thinking
   pause = interruption.
2. **Server debounce** — `voice_ws.py` flushes 2.0 s after a Deepgram final
   (`DEBOUNCE_SECS`), with thin lexical heuristics (`_looks_complete`/`_looks_incomplete`)
   that miss most mid-thought pauses (they only extend on a trailing conjunction).
3. **Deepgram endpointing** — `endpointing=700` / `utterance_end_ms=2000` emit
   `speech_final` after ~700 ms of silence, feeding #2.

Two compounding defects turn a brief overlap into a sustained one:

- **No barge-in on `speech_start`.** When the bot wrongly starts and the candidate
  resumes, `voice_ws.py` `speech_start` cancelled the debounce/silence-monitor but never
  called `handle_barge_in()`; TTS kept playing until the next full Deepgram final flushed
  through `process_voice_turn` (seconds later).
- **Silero VAD silently in energy-fallback.** `onnxruntime-web` is a declared dep, but
  there is no `silero_vad.onnx` and no `/onnx/` wasm dir in `frontend/public`, so
  `loadOnnxModel()` throws → `useEnergyFallback = true`. Raw RMS is far worse at telling a
  pause from a turn-end, and the failure is swallowed silently (a "fail loud" violation).

---

## Phase 1 — Deterministic hardening (no new infra)

### 1.1 Barge-in the instant the candidate resumes — **IMPLEMENTED (pending test)**
`backend/src/routes/voice_ws.py`, `speech_start` branch: after `cancel_silence_monitor()`,
`if turn_state.bot_speaking: await turn_state.handle_barge_in()`. `handle_barge_in`
self-guards on `bot_speaking` (no-op on a normal turn start) and resets `bot_speaking`,
so the later `process_voice_turn` barge-in becomes a no-op — no double count.
- Risk to validate: echo-triggered false barge-in. Mitigated by `echoCancellation: true`
  + a real Silero VAD (1.2). Confirm the bot's own TTS doesn't self-cancel.
- Note: `barge_in_ack` (voice_ws.py:480) is handled but never sent by the client — dead
  path; leave for cleanup, not load-bearing.

### 1.2 Robust turn-taking net (reframed) — **IMPLEMENTED (server tested; frontend needs live validation)**

**Finding that reframed this:** the Silero VAD has *never* run. The worker does
`import(/* webpackIgnore */ 'onnxruntime-web')` — a bare specifier a browser module
worker can't resolve at runtime — so it always falls into energy (RMS) fallback. The
reported bug (candidate speaks ~12 s, bot says "Are you still there?") is the energy VAD
missing `speech_start`: the server never gets the cancel signal AND the client never
forwards the candidate's audio (forwarding was gated on the `speaking` state). So the fix
must not depend on VAD quality.

- **Fix A (server, `voice_ws.py`) — DONE + unit-tested.** New `_note_candidate_activity()`
  called from `on_transcript` on every Deepgram transcript (interim or final) cancels the
  silence monitor. Deepgram hearing words is hard proof the candidate is talking, so the
  ladder stops regardless of what the client VAD reported. Test:
  `test_transcript_activity_cancels_silence_monitor` (24 passed).
- **Fix B (frontend, `vad.worker.ts` + `voice-capture.ts`) — DONE, needs live validation.**
  "Listen mode": while the candidate's turn is open (server `turn`/`barge_in` events) the
  worker forwards *every* audio frame and the client forwards it to the server — making
  Deepgram the source of truth. The VAD path still covers barge-in during bot speech
  (listen mode off). Cannot be verified here (`frontend/node_modules` empty, no browser/mic).
- **Genuine dead-air still works:** if the candidate is truly silent, no transcript arrives,
  so the silence ladder still nudges/advances as designed.

### 1.2b Silero loader — **IMPLEMENTED (verified: model interface, type-check, build; browser runtime pending)**

Root issue confirmed: the worker imported the bare specifier `'onnxruntime-web'`, which a
browser worker cannot resolve at runtime → always energy fallback.

- **Model interface validated (Python ORT):** Silero **v4** ONNX takes `input/sr/h/c` →
  `output/hn/cn`, exactly the worker's wiring, and accepts the worker's 320-sample frames.
  v5 has a different interface and must NOT be used. The setup script pins v4.
- `vad.worker.ts`: import `/onnx/ort.wasm.bundle.min.mjs` (real same-origin URL, variable
  specifier + `webpackIgnore` so webpack never bundles the package), `wasmPaths='/onnx/'`,
  `numThreads=1` (no SharedArrayBuffer → no COOP/COEP), cache the module (no per-frame
  re-import), and **fail loud** on load error (`postMessage({event:'vad_fallback'})` +
  `console.error`). `voice-capture.ts` logs the fallback warning.
- **Assets:** `frontend/public/onnx/` (ort bundle mjs + `ort-wasm-simd-threaded.{mjs,wasm}`)
  and `frontend/public/models/silero_vad.onnx` (v4). Regenerated by
  `frontend/scripts/setup-vad-assets.mjs` (`npm run setup:vad`, also `postinstall`).
  Gitignored (large binaries; reproduced by the script).
- **Verified here:** `npm run type-check` clean; `npm run build` ✓ compiled (the worker no
  longer crashes the build). **Not verifiable here:** actual browser ORT/wasm load + Silero
  inference quality — needs a browser + mic. If it ever fails to load, the loud
  `vad_fallback` warning fires and the energy path still works.

### 1.2c Deepgram-driven barge-in — **IMPLEMENTED + tested (2026-07-01)**

**The defect prior Phase 1 work missed.** Barge-in fired through exactly ONE fast
path: the browser VAD's `speech_start` (`voice_ws.py` speech_start handler). But the
browser VAD is least reliable precisely while the bot speaks: `echoCancellation: true`
suppresses the candidate's voice during double-talk, so the VAD's probability often
never crosses threshold and no `speech_start` is emitted → the bot talks over the
candidate until the slow debounce → `process_voice_turn` barge-in (seconds later, or
never if the bot's utterance finished first). Every earlier fix tuned the unreliable
VAD path; the reliable signal — a Deepgram transcript, which arrives because candidate
audio is forwarded even during bot speech — was wired only to `cancel_silence_monitor`
(`_note_candidate_activity`), never to stop TTS.

- **Fix (server, `voice_ws.py`) — DONE + unit-tested.** New `_maybe_barge_in_on_transcript()`
  is awaited from `on_transcript` on every Deepgram transcript (interim or final): if
  `turn_state.bot_speaking`, call `handle_barge_in()` now. Runs on interims so the bot
  stops within a few hundred ms of the candidate resuming. Guarded by `_is_echo_of_flushed()`
  against a late trailing final of the just-flushed answer (tracked via `last_flushed_text`),
  so the bot never cuts its own reply on a stale tail. Echo of the bot's own TTS is
  mitigated by `echoCancellation: true` (same accepted mitigation as the speech_start path).
  Tests: `test_transcript_during_bot_speech_triggers_barge_in`,
  `test_trailing_tail_transcript_does_not_barge_in` (26 passed total).
- Still needs live (browser + mic + keys) validation, but unlike the VAD path this does
  not depend on VAD quality at all.

### 1.3 Make EOT pause-tolerant (interim, until Phase 2 supersedes) — **IMPLEMENTED + tested (2026-07-01)**
- `vad.worker.ts`: `SILENCE_FRAMES_THRESHOLD` 75 → **110** (2.2 s). DONE.
- `voice_ws.py`: `speech_end` no longer short-circuits the adaptive debounce. DONE.
  `flush_accumulated_now(force=False)` now **defers** to a pending Deepgram-final-driven
  debounce (the debounce owns EOT timing) and only flushes immediately for the
  interim-only safety net (no final → no debounce). `end_session` calls
  `flush_accumulated_now(force=True)` to cancel the debounce and flush the last answer
  before finalization. Decision isolated in pure `_speech_end_should_flush(debounce_pending,
  force)`. `DEBOUNCE_SECS` 2.0 → **2.5**.
  Tests: `TestSpeechEndDeferral` (defers to pending debounce / flushes interim-only /
  force-flushes on session end) + `test_standard_debounce_tolerates_thinking_pause`
  (41 passed total across turn-taking + voice_turn_processor).
- Constants are interim; empirically tuned in 2.4 (needs live mic validation); Phase 2
  replaces the ladder with semantic EOT.

**Phase 1 tests (Rule 7):** barge-in fires on `speech_start` only when `bot_speaking`;
VAD-fallback emits the loud signal; a simulated 1.8 s mid-utterance pause does not flush;
a real end-of-answer still flushes within the window.

---

## Phase 2 — Semantic EOT (LiveKit turn-detector, ONNX, backend)

Placement = backend, on Deepgram finals, replacing the debounce ladder.

### 2.1 Vendor model + deps
`backend/requirements.txt` += `onnxruntime`, `numpy`, `tokenizers` (or `transformers`).
Vendor the `livekit/turn-detector` ONNX artifact into `backend/models/` (or a one-shot
download step). Input = chat-formatted conversation tail; output = P(end-of-turn).

### 2.2 EOT service
New `backend/src/services/audio/eot_detector.py`: load the ONNX session once (global
singleton, like `_redis_client`), `predict_end_of_turn(text) -> float`, run via
`asyncio.to_thread` so it never blocks the event loop. Fail loud if the artifact is missing.

### 2.3 Wire into the turn loop
`voice_ws.py`: on each Deepgram final, compute P(end) on the accumulated text:
- `P >= threshold` → flush (candidate done).
- `P < threshold` → hold and keep listening (semantic replacement for the lexical heuristics).
- Hard upper-bound silence timeout (~6–8 s) so we never hang.
- Keep the `_looks_wait_request` fast-path untouched.

### 2.4 Validation spike (the reason it was deferred — do not skip)
Run representative transcripts / scripted pause patterns; measure false-interrupt rate vs
end-of-turn latency; tune threshold + timeout. **Tests:** low P for trailing-conjunction
text, high P for complete answers; flush only on threshold crossing; hard-timeout still
flushes; wait-request bypass intact.

---

## Sequencing & guardrails
- Phase 1 ships independently (immediate relief). Phase 2's model replaces the ladder;
  Phase 1's barge-in fix + loaded VAD stay.
- Run tests targeted (full suite hangs on orphaned aiosqlite threads).
- Out of scope / untouched: text mode, scoring, JD planning, the `tts_turn_complete`
  handshake (already correct).

## External artifacts needed (the original deferral blocker)
- `silero_vad.onnx` (Phase 1.2) — public artifact, dropped into `frontend/public/models/`.
- `livekit/turn-detector` ONNX (Phase 2.1) — vendored into `backend/models/` or fetched
  via a download step.
- Runtime API keys to test voice end-to-end: `DEEPGRAM_API_KEY`, `ELEVENLABS_API_KEY`,
  `ANTHROPIC_API_KEY` (in `backend/.env`). Not needed for unit tests of the turn logic.
