# Branch documentation — 2026-11-18

## User scope

Provide a README for each branch for later report writing, including advantages
compared with Lichess features already available. Keep branch implementations,
historical results and claimed benefits distinct. A separate UI request removes
two live captions; that work is committed as 162bd1c and independently verified
under `reports/acceptance/compact-advantage/`.

- [x] Fetch remote refs and inspect all six branches: main, prediction, voice,
  commentary, commentary-v2 and webmcp. Use sparse isolated worktrees for the
  other branches; do not switch or reconfigure the user's running stack.
- [x] Create `docs/branch-report/README.md` on each branch and link from its root
  README. Include purpose, implemented behavior, architecture, comparison table,
  evidence, setup, limitations, future work and source links at exact revisions.
- [x] Distinguish existing upstream voice input/debug Vietnamese from the added
  parser/PhoWhisper/direct mode; distinguish analysis gauge/logistic evaluation
  from WDL/expected score. Record that sidebar reuse is possible, not implemented.
- [x] Record branch-specific caveats: main is not all feature branches merged;
  initial Piper differs from three-voice Nano; v2 retains optional Gemini TTS
  while main removes that provider; WebMCP returns JSON and reuses search/PGN.
  Do not call these features new LLM coaching or measured learning gains.
- [x] Keep existing operating guides. Document missing tracked launcher/LOCAL.md
  and the historical two coach test failures without declaring tests green.
- [x] Provide a six-branch index on main and voice. Check Markdown structure,
  UTF-8, whitespace, local links/source objects and documents-only changes.
  Validation is retained in `docs/branches/validation.json` on these two branches.
- [x] Commit/push only documentation changes to their respective branches and
  verify all remote heads; preserve code/model/patch/audio bytes on each branch.
  `git ls-remote --heads` confirmed all six README publication commits:
  main 0d2944e, prediction 78e300b, commentary 782dd5e, commentary-v2 82b47ae,
  webmcp 272a1a6, voice 0ff5b4d. The voice audit follow-up only records completion.
  Existing root sparse-checkout rules were retained; explicit `git add --sparse`
  staged the new docs without changing the running source checkout. Initial
  publication stopped on a new README EOF blank line and then a sparse-path
  staging guard; both were corrected before completing the remaining pushes.

No runtime/model tests are attributed to the README-only commits. Historical
measurements keep their original data/protocol limitations. Personal recordings
and private configuration are excluded.
