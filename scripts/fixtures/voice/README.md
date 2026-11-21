# Human audio smoke fixture

`bon.wav`: a human pronunciation of **bốn**, by speaker/recorder **Penn Zero MSSJ**,
recorded 2024-04-16 for Lingua Libre. License: **CC0 1.0**.

- Description and license: https://commons.wikimedia.org/wiki/File:LL-Q9199_(vie)-Penn_Zero_MSSJ-b%E1%BB%91n.wav
- Original: https://upload.wikimedia.org/wikipedia/commons/f/f0/LL-Q9199_%28vie%29-Penn_Zero_MSSJ-b%E1%BB%91n.wav
- SHA256: `5cbf7e3e08afb3d5016b502e37348e58df27e7d6497d08af1be06818d0208e0d`

The browser test resamples this recording with Web Audio and adds silence to flush
the real Vosk decoder. This is one recorded-word smoke test, not a chess-command
accuracy benchmark, multi-accent study, synthetic voice, or live microphone test.

`ep.wav`: **ép**, by the same speaker/recorder for Lingua Libre, **CC0 1.0**.

- Description and license: https://commons.wikimedia.org/wiki/File:LL-Q9199_(vie)-Penn_Zero_MSSJ-%C3%A9p.wav
- Original: https://upload.wikimedia.org/wikipedia/commons/8/8c/LL-Q9199_%28vie%29-Penn_Zero_MSSJ-%C3%A9p.wav
- SHA256: `c48a9fc4aed3edd6c6c23b8dc72fb07848b3049c2a2c1f3b94c1555272d1e1d2`

The baseline probe recognized `ép` at 16/48 kHz, establishing an acoustic spelling
for the F file; `f` is absent from the model vocabulary. The `bốn` fixture was
misrecognized and is deliberately retained as a known failing acoustic case.

## Full-command regression fixtures (2026-11-17 follow-up)

`hai.wav`, `ba.wav`, `ma.wav` are recordings by Penn Zero MSSJ. `bon2.wav`
is a second speaker's **bốn**, by Jessica Nguyen (Pamputt). All are CC0 1.0;
exact source pages, original URLs and SHA256 are in [word-sources.json](word-sources.json).
The source pages were checked for their CC0 declaration before copying the files.

`commands/*.wav` are **concatenated human word recordings**, produced by
`scripts/compose_voice_fixtures.py`. They are not recordings of natural connected
speech or synthesized voices. The script preserves 80ms either side of each word,
using 2% of the word's peak amplitude only to find the surrounding silence. It
adds 500ms leading / 2s trailing silence, without gain fitting or denoising.
The same composition rules apply to all cases, including the failing sample.

[commands.json](commands.json) lists the independently specified utterance and
expected UCI (or no move), component clips and output checksum. The positive cases
are `ép hai ép bốn` (two versions of bốn), `ép hai ép ba` and `mã ép ba`.
The negative case `ép ba ép hai` is illegal in the starting position.

The browser suite decodes the whole WAV through production Vosk using the current
position's production grammar, forwards its results through the real move parser,
and checks confirmation and the server move. Confirmation in the server check is
still supplied as a transcript. Each command is tested at 16/48kHz. A second pass
uses the previous word-list grammar on the same PCM to record the baseline.

This small, assembled corpus is a regression check, not a measure of general
command accuracy, dialect coverage or physical microphone performance. Known
recognition failures remain failing assertions in the browser suite.

## Expanded matrix corpus

[matrix-commands.json](matrix-commands.json) lists all 13 assembled WAVs (11
distinct texts). The original five WAVs and `commands.json` remain unchanged.
The additional files cover `mã ép bốn` (two versions of bốn), `mã ép hai`,
`ép bốn ép ba`, `ép bốn`, `ép ba`, the illegal starting-position command
`ép bốn ép hai`, and nonsense `ba bốn hai`. `uci` in this manifest describes
one reference position; the matrix specifies its own FEN and expectation for
each scenario in `scripts/voice-matrix-cases.mjs`. A short square name can have
multiple legal candidates and must require choice before confirmation.

`scripts/voice.ps1 matrix` runs 19 audio scenarios at 16/44.1/48kHz, each with
clean, gain 0.5, gain 1.8/clamped, interpolated speed 1.15x, and deterministic
nominal 20dB white-noise profiles. Noise is relative to the entire clip RMS,
including silence; interpolation changes pitch as well as speed. Raw PCM is
passed to production Vosk, bypassing MediaStream microphone processing.
Confirmations and candidate choices are supplied as transcripts. The matrix
captures moves at the application root boundary; the separate original browser
suite tests the server submission. Other controls and special moves are tested
with text, not acoustic recordings.

No new human source recordings were added in this extension (download attempts
returned HTTP 429/404). The same small corpus was used during tuning and final
validation; it is not held out. Real microphone, connected speech, new speakers
and naturally noisy-room accuracy remain unverified.
Generated run reports are kept locally in the ignored
`reports/voice-v1/` directory.
