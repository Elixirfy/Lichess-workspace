# Shared probability ownership and voice-only branch — 2026-11-18

The user assigns live/review advantage to the group, on main. Vietnamese speech
input remains an independent feature branch. Keep the old published combined
branch as an archive before replacing its ref with a clean main-based branch.

- [x] Read current remote refs and preserve main's commentary updates. A new
  feature/coach branch is unrelated; do not merge it as part of this task.
- [x] Transfer only probability/advantage, analysis setup and common AI stack
  support. Keep ASR service/model/recorder code out of main. Apply the probability
  delta to vendored lila as well as the reproducible patch; three-way merge
  preserves main's commentary changes.
- [x] Verify shared source, unchanged commentary/model artifacts, focused/full
  frontend/build and configuration. Report existing unrelated failures honestly.
- [ ] Build a new voice-only commit on the resulting main tree. Preserve the
  deployed voice patch and all previously published voice source/recordings
  provenance, without adding private local recordings.
- [ ] Verify main..voice file ownership and matching shared implementation.
- [ ] Push archived old HEAD, then main normally, then voice with an exact
  force-with-lease against e4d8477. Verify all remote refs and update the local
  workspace without discarding edits or ignored runtime data.

Old combined HEAD: e4d8477548c6550ed3174ae8a79fa077fcca30c0.
Main base: 0d2944ea4f62caf4222dde21b2f04a3ddee0a04b.

Fresh main evidence: `reports/acceptance/shared-probability/validation.json`.
Probability tests 38/38; full frontend 300/305. The five failures are unchanged
commentary tests expecting six/Piper voices after main switched to three Nano
voices. Production build, type-aware lint (16 files), stylelint, LF-source format
(19 files), Compose config and pinned browser NNUE install passed. Preserved 27
commentary files and the exact human-model/WDL-patch checksums. No fresh Scala,
browser gameplay or ASR benchmark is claimed for this Git ownership change.

The publication/voice steps above are the follow-up to this shared commit; final
voice-specific evidence belongs in `reports/voice-v1/branch-separation/` on the
voice branch. Archive ref was pushed and verified at the old combined SHA before
any rewrite. Keep unrelated remote feature branches unchanged.
