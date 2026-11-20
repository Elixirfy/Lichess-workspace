# Label v3 S1

Verdict: **FAIL**. Selected **v3** by the pre-registered failed-gate ordering. The selected variant fails one or more gates; S2 requires a user decision. This is a deterministic behavioural rule, not a measurement of emotion.

## Deviations

Stop 1 halted preflight before any label statistic because the original §1.1 stated 22,316 train rows for both splits. The accepted Erratum 1 corrects by_time to 25,403, retains by_player at 22,316, and clarifies the input conventions. This resumed run implements the erratum; no LF, threshold, combination, gate or train membership was changed.

- Old lock (`prereg.sha256.v0`, stop 1): `01b901a8499149a819225ab2b2b914013d402e595a9ad54b52021bd443b7ba9d`.
- Active lock (`prereg.sha256`, including Erratum 1): `ccf652ad6355b580f51f67a3667548828ba228da8f01b14b0ff504ffdc1a34f1`.
- Stop-1 record preserved at `~/tilt-labels-v3/S1/label_v3_S1-stop1.md`; the present report overwrites the prior repository stop report.

**Mandatory E1.5 rating check passed before aggregate/evidence construction.** Feature ratings exactly equal the cohort side’s normalized `white_rating` / `black_rating`. Consecutive rated games are ordered by start time; decisive train anchors with two known ratings enter the denominator. A zero change is a mismatch. The next rating may be an allowed non-train input. A second check restricts both endpoints to train; both checks pass the 95% requirement.

| Split | Matches / decisive train-anchor pairs | Sign agreement | Both-train matches / pairs | Both-train agreement |
|---|---:|---:|---:|---:|
| by_player | 20,565 / 20,760 | 99.0607% | 20,528 / 20,721 | 99.0686% |
| by_time | 23,356 / 23,719 | 98.4696% | 23,198 / 23,554 | 98.4886% |

**Execution exception:** the requested existing full test suite includes a real-Stockfish integration test and model-fitting tests. They executed on temporary synthetic test fixtures. This should have been checked against the no-Stockfish/no-model instruction before invoking the suite. The S1 pipeline itself starts no engine, fits no model, reanalyzes no cohort game and uses only the supplied cached features. No cohort model was trained. No further engine or fitting work was run.

No implementation bug was found after gate values were produced, so there are no superseded label/gate numbers. A synthetic quantile-boundary test was corrected before the cohort run to compare the exact interpolated float rather than a decimal spelling of it; no rule or tolerance changed.

## Gates and selection

Eight named gate rows are counted, including G3a and G3b separately. Every gate must pass on both splits. All percentages below use each split’s own train denominator; missing/undefined gate values fail closed. Gate comparisons use unrounded values.

| Gate (pass condition) | v3 by_player train | v3 by_time train | v3b by_player train | v3b by_time train |
|---|---:|---:|---:|---:|
| G1 length AUC ≤ 0.60 | 0.632509 FAIL | 0.639783 FAIL | 0.623131 FAIL | 0.623253 FAIL |
| G2 length gap ≤ 15 pp | 9.4713 pp PASS | 8.8523 pp PASS | 10.5118 pp PASS | 9.4261 pp PASS |
| G3a coverage ≥ 50% | 56.0181% PASS | 55.1470% PASS | 49.0410% FAIL | 47.0653% FAIL |
| G3b post-loss coverage ≥ 50% | 51.5822% PASS | 50.9717% PASS | 46.5035% FAIL | 44.5212% FAIL |
| G4 prevalence 10–35% | 7.6554% FAIL | 7.4952% FAIL | 9.2928% FAIL | 8.9829% FAIL |
| G5 won / TILT ≤ 10% | 5.0157% PASS | 4.5714% PASS | 5.1131% PASS | 4.3762% PASS |
| G6 max evidence dominance ≤ 70% | 77.4295% FAIL | 75.0476% FAIL | 78.9577% FAIL | 75.4190% FAIL |
| G7 rise ≥ 3 pp; adjacent drop ≤ 1 pp | 3.2808 pp PASS | 2.6750 pp FAIL | 4.1035 pp PASS | 3.3518 pp PASS |

| Variant | Failed gates on by_player | Failed gates on by_time |
|---|---|---|
| v3 | 3: G1, G4, G6 | 4: G1, G4, G6, G7 |
| v3b | 5: G1, G3a, G3b, G4, G6 | 5: G1, G3a, G3b, G4, G6 |

v3b ran only after v3 failed a gate. The selection key is failed-gate count on by_player, then by_time, then preference for v3. Known limitations are exactly the selected variant’s failed gates listed above; the report-only analyses do not change selection.

For selected v3, length remains predictive (G1 AUC 0.632509 / 0.639783), prevalence is below the 10% minimum (7.6554% / 7.4952%), and E1/E2 dominate more than 70% of TILT games. By-time evidence also falls short of the required three-point loss-run rise (2.6750 points); its adjacent-stratum comparisons pass. v3b improves neither the overall verdict nor the selection key and additionally misses both coverage requirements.

### G2 bucket audit

A bucket with fewer than 100 labelled rows is merged with its lower neighbour; the first bucket uses its upper neighbour. Merges repeat until no sparse bucket remains or only one remains. A single nonempty merged bucket has gap zero; no labelled bucket makes G2 undefined.

| Variant / split | Labelled bucket counts and TILT shares | Merges |
|---|---|---|
| v3 / by_player | short: n=2,037, T=14.0893%; 40–79: n=5,895, T=7.7863%; 80+: n=4,569, T=4.6181% | none |
| v3 / by_time | short: n=2,458, T=13.0594%; 40–79: n=6,702, T=7.8335%; 80+: n=4,849, T=4.2071% | none |
| v3b / by_player | short: n=1,817, T=16.5107%; 40–79: n=5,243, T=9.2314%; 80+: n=3,884, T=5.9990% | none |
| v3b / by_time | short: n=2,115, T=14.8463%; 40–79: n=5,819, T=9.3143%; 80+: n=4,022, T=5.4202% | none |

### G6 evidence dominance among TILT

| LF | v3 / by_player | v3 / by_time | v3b / by_player | v3b / by_time |
|---|---:|---:|---:|---:|
| E1 | 77.4295% | 73.8095% | 78.9577% | 75.4190% |
| E2 | 77.3250% | 75.0476% | 72.6647% | 70.4842% |
| E3 | 22.2571% | 23.7143% | 33.2350% | 34.7300% |
| E4 | 40.4389% | 42.2857% | 39.5280% | 41.1546% |
| E5 | 35.4232% | 36.3810% | 35.5949% | 37.0577% |
| E6 | 10.9718% | 12.0000% | 9.4395% | 10.0559% |
| E7 | 33.2288% | 34.4762% | 33.8250% | 35.0093% |

### G7 evidence monotonicity

Each cell is the share of eligible games with at least two evidence votes, followed by the eligible denominator. This gate tests evidence independently of label combination.

| Loss-run stratum | v3 / by_player | v3 / by_time | v3b / by_player | v3b / by_time |
|---|---:|---:|---:|---:|
| 0 | 28.1592% (n=13,722) | 28.7434% (n=15,614) | 33.8644% (n=12,615) | 34.3732% (n=13,976) |
| 1 | 28.5321% (n=4,721) | 29.2931% (n=5,206) | 33.7322% (n=4,346) | 34.7171% (n=4,649) |
| 2 | 31.9389% (n=1,769) | 31.8040% (n=1,918) | 38.7616% (n=1,615) | 38.4114% (n=1,687) |
| 3+ | 31.4400% (n=1,250) | 31.4184% (n=1,410) | 37.9679% (n=1,122) | 37.7250% (n=1,222) |

## Report-only statistics

These analyses do not select thresholds or variants and have no pass/fail condition.

| Variant / split | All train | TILT | NOT | ABSTAIN | Labelled | Result-score ROC AUC |
|---|---:|---:|---:|---:|---:|---:|
| v3 / by_player | 22,316 | 957 | 11,544 | 9,815 | 12,501 | 0.190518 |
| v3 / by_time | 25,403 | 1,050 | 12,959 | 11,394 | 14,009 | 0.191453 |
| v3b / by_player | 22,316 | 1,017 | 9,927 | 11,372 | 10,944 | 0.190764 |
| v3b / by_time | 25,403 | 1,074 | 10,882 | 13,447 | 11,956 | 0.191567 |

Result AUC is the signed ROC AUC of `result_score` for TILT versus NOT among labelled train rows (TILT is the positive class); unlike G1 it is not symmetrized.

### LF vote counts

Context counts are true / false. Evidence counts are fired / not_fired / missing. Counts include every train row, including ineligible and abstained rows.

| LF | v3 / by_player | v3 / by_time | v3b / by_player | v3b / by_time |
|---|---:|---:|---:|---:|
| C1 | 3,109 / 19,207 | 3,457 / 21,946 | 3,109 / 19,207 | 3,457 / 21,946 |
| C2 | 4,162 / 18,154 | 4,412 / 20,991 | 4,162 / 18,154 | 4,412 / 20,991 |
| C3 | 2,222 / 20,094 | 2,423 / 22,980 | 2,222 / 20,094 | 2,423 / 22,980 |
| C4 | 502 / 21,814 | 558 / 24,845 | 502 / 21,814 | 558 / 24,845 |
| C5 | 946 / 21,370 | 1,001 / 24,402 | 946 / 21,370 | 1,001 / 24,402 |
| E1 | 4,069 / 17,393 / 854 | 4,570 / 19,578 / 1,255 | 4,274 / 15,424 / 2,618 | 4,693 / 16,841 / 3,869 |
| E2 | 4,501 / 16,961 / 854 | 5,107 / 19,041 / 1,255 | 4,244 / 15,454 / 2,618 | 4,667 / 16,867 / 3,869 |
| E3 | 2,950 / 18,416 / 950 | 3,443 / 20,578 / 1,382 | 4,636 / 14,973 / 2,707 | 5,163 / 16,257 / 3,983 |
| E4 | 4,396 / 16,970 / 950 | 5,033 / 18,988 / 1,382 | 4,144 / 15,465 / 2,707 | 4,537 / 16,883 / 3,983 |
| E5 | 3,036 / 18,704 / 576 | 3,552 / 20,932 / 919 | 3,184 / 16,756 / 2,376 | 3,510 / 18,308 / 3,585 |
| E6 | 987 / 21,329 / 0 | 1,185 / 24,218 / 0 | 987 / 21,329 / 0 | 1,185 / 24,218 / 0 |
| E7 | 1,894 / 19,555 / 867 | 2,086 / 21,991 / 1,326 | 1,894 / 19,555 / 867 | 2,086 / 21,991 / 1,326 |

### Evidence-count distribution

| Value | v3 / by_player | v3 / by_time | v3b / by_player | v3b / by_time |
|---|---:|---:|---:|---:|
| 0 | 9,358 | 10,598 | 8,990 | 10,666 |
| 1 | 6,755 | 7,701 | 6,501 | 7,167 |
| 2 | 4,108 | 4,692 | 4,353 | 4,843 |
| 3 | 1,599 | 1,857 | 1,856 | 2,054 |
| 4 | 422 | 465 | 502 | 552 |
| 5 | 68 | 80 | 105 | 108 |
| 6 | 5 | 10 | 8 | 13 |
| 7 | 1 | 0 | 1 | 0 |

### Missing-evidence-count distribution

| Value | v3 / by_player | v3 / by_time | v3b / by_player | v3b / by_time |
|---|---:|---:|---:|---:|
| 0 | 20,778 | 23,159 | 19,550 | 21,387 |
| 1 | 588 | 862 | 59 | 33 |
| 2 | 91 | 120 | 89 | 113 |
| 3 | 5 | 7 | 0 | 1 |
| 4 | 259 | 306 | 240 | 281 |
| 5 | 340 | 522 | 1,572 | 2,299 |
| 6 | 255 | 427 | 806 | 1,289 |
| 7 | 0 | 0 | 0 | 0 |

### Context-level distribution

| Value | v3 / by_player | v3 / by_time | v3b / by_player | v3b / by_time |
|---|---:|---:|---:|---:|
| none | 8,914 | 10,829 | 8,914 | 10,829 |
| stale | 4,267 | 4,542 | 4,267 | 4,542 |
| weak | 6,381 | 7,053 | 6,381 | 7,053 |
| strong | 2,754 | 2,979 | 2,754 | 2,979 |

### Label by rating tercile and time control

Rating terciles use linear train-only rating quantiles, separately for each split. Boundaries belong to the lower tercile; ties stay together. Time control is initial seconds + increment seconds. Each row reports T / N / A, coverage (T+N)/all, and prevalence T/(T+N).

#### v3 / by_player

Rating boundaries: 1387.000000, 2025.000000.

| Group | TILT | NOT | ABSTAIN | Coverage | Prevalence |
|---|---:|---:|---:|---:|---:|
| rating high | 268 | 3,966 | 3,193 | 57.0082% | 6.3297% |
| rating low | 339 | 3,737 | 3,383 | 54.6454% | 8.3170% |
| rating middle | 350 | 3,841 | 3,239 | 56.4065% | 8.3512% |
| TC 120+2 | 0 | 0 | 4 | 0.0000% | undefined |
| TC 180+0 | 445 | 5,710 | 4,718 | 56.6081% | 7.2299% |
| TC 180+1 | 0 | 1 | 6 | 14.2857% | 0.0000% |
| TC 180+2 | 179 | 2,476 | 1,934 | 57.8557% | 6.7420% |
| TC 240+0 | 1 | 23 | 25 | 48.9796% | 4.1667% |
| TC 300+0 | 266 | 2,749 | 2,534 | 54.3341% | 8.8226% |
| TC 300+1 | 2 | 5 | 1 | 87.5000% | 28.5714% |
| TC 300+2 | 0 | 3 | 6 | 33.3333% | 0.0000% |
| TC 300+3 | 64 | 575 | 585 | 52.2059% | 10.0156% |
| TC 360+0 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 420+0 | 0 | 1 | 1 | 50.0000% | 0.0000% |
| TC 60+5 | 0 | 1 | 0 | 100.0000% | 0.0000% |

#### v3 / by_time

Rating boundaries: 1265.000000, 2002.000000.

| Group | TILT | NOT | ABSTAIN | Coverage | Prevalence |
|---|---:|---:|---:|---:|---:|
| rating high | 303 | 4,465 | 3,695 | 56.3394% | 6.3549% |
| rating low | 366 | 4,220 | 3,888 | 54.1185% | 7.9808% |
| rating middle | 381 | 4,274 | 3,811 | 54.9846% | 8.1847% |
| TC 0+5 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 0+8 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 120+2 | 0 | 0 | 4 | 0.0000% | undefined |
| TC 180+0 | 442 | 6,024 | 5,183 | 55.5069% | 6.8358% |
| TC 180+1 | 0 | 0 | 4 | 0.0000% | undefined |
| TC 180+2 | 172 | 2,261 | 1,805 | 57.4092% | 7.0695% |
| TC 240+0 | 1 | 23 | 25 | 48.9796% | 4.1667% |
| TC 300+0 | 325 | 3,421 | 3,202 | 53.9148% | 8.6759% |
| TC 300+1 | 2 | 5 | 1 | 87.5000% | 28.5714% |
| TC 300+2 | 0 | 4 | 6 | 40.0000% | 0.0000% |
| TC 300+3 | 108 | 1,216 | 1,158 | 53.3441% | 8.1571% |
| TC 300+4 | 0 | 3 | 2 | 60.0000% | 0.0000% |
| TC 360+0 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 420+0 | 0 | 1 | 1 | 50.0000% | 0.0000% |
| TC 60+5 | 0 | 1 | 0 | 100.0000% | 0.0000% |

#### v3b / by_player

Rating boundaries: 1387.000000, 2025.000000.

| Group | TILT | NOT | ABSTAIN | Coverage | Prevalence |
|---|---:|---:|---:|---:|---:|
| rating high | 289 | 3,419 | 3,719 | 49.9259% | 7.7940% |
| rating low | 369 | 3,170 | 3,920 | 47.4460% | 10.4267% |
| rating middle | 359 | 3,338 | 3,733 | 49.7577% | 9.7106% |
| TC 120+2 | 0 | 0 | 4 | 0.0000% | undefined |
| TC 180+0 | 466 | 4,947 | 5,460 | 49.7839% | 8.6089% |
| TC 180+1 | 0 | 1 | 6 | 14.2857% | 0.0000% |
| TC 180+2 | 201 | 2,118 | 2,270 | 50.5339% | 8.6675% |
| TC 240+0 | 2 | 21 | 26 | 46.9388% | 8.6957% |
| TC 300+0 | 275 | 2,335 | 2,939 | 47.0355% | 10.5364% |
| TC 300+1 | 0 | 3 | 5 | 37.5000% | 0.0000% |
| TC 300+2 | 0 | 3 | 6 | 33.3333% | 0.0000% |
| TC 300+3 | 73 | 497 | 654 | 46.5686% | 12.8070% |
| TC 360+0 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 420+0 | 0 | 1 | 1 | 50.0000% | 0.0000% |
| TC 60+5 | 0 | 1 | 0 | 100.0000% | 0.0000% |

#### v3b / by_time

Rating boundaries: 1265.000000, 2002.000000.

| Group | TILT | NOT | ABSTAIN | Coverage | Prevalence |
|---|---:|---:|---:|---:|---:|
| rating high | 316 | 3,746 | 4,401 | 47.9972% | 7.7794% |
| rating low | 366 | 3,546 | 4,562 | 46.1647% | 9.3558% |
| rating middle | 392 | 3,590 | 4,484 | 47.0352% | 9.8443% |
| TC 0+5 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 0+8 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 120+2 | 0 | 0 | 4 | 0.0000% | undefined |
| TC 180+0 | 445 | 5,036 | 6,168 | 47.0512% | 8.1190% |
| TC 180+1 | 0 | 0 | 4 | 0.0000% | undefined |
| TC 180+2 | 190 | 1,901 | 2,147 | 49.3393% | 9.0866% |
| TC 240+0 | 2 | 21 | 26 | 46.9388% | 8.6957% |
| TC 300+0 | 326 | 2,863 | 3,759 | 45.8981% | 10.2226% |
| TC 300+1 | 0 | 3 | 5 | 37.5000% | 0.0000% |
| TC 300+2 | 0 | 0 | 10 | 0.0000% | undefined |
| TC 300+3 | 111 | 1,053 | 1,318 | 46.8977% | 9.5361% |
| TC 300+4 | 0 | 3 | 2 | 60.0000% | 0.0000% |
| TC 360+0 | 0 | 0 | 1 | 0.0000% | undefined |
| TC 420+0 | 0 | 1 | 1 | 50.0000% | 0.0000% |
| TC 60+5 | 0 | 1 | 0 | 100.0000% | 0.0000% |

### Agreement with v1

Only `weak_by_player.parquet` rows filtered to `split == train` are read. Compare each current split’s labelled train rows with that source’s non-null labels. For by_time this is an intersection with v1 by_player train, not the full by_time train set. v1 validation/test/purged labels are never read.

| Variant / split | Joint labelled | Agreement | Cohen kappa | v3 NOT / v1 NOT | v3 NOT / v1 TILT | v3 TILT / v1 NOT | v3 TILT / v1 TILT |
|---|---:|---:|---:|---:|---:|---:|---:|
| v3 / by_player | 4,224 | 97.1117% | 0.839406 | 3,741 | 62 | 60 | 361 |
| v3 / by_time | 2,884 | 96.8447% | 0.815605 | 2,566 | 46 | 45 | 227 |
| v3b / by_player | 3,714 | 96.8767% | 0.836790 | 3,258 | 49 | 67 | 340 |
| v3b / by_time | 2,467 | 96.7167% | 0.811315 | 2,189 | 36 | 45 | 197 |

### ABSTAIN reasons

Eligibility reasons use the pre-registered order: short_game, no_eval, no_baseline. Eligible games failing the combination are `combination`. Reasons are mutually exclusive.

| Variant / split | Reason | Rows | Share of ABSTAIN | Share of all train |
|---|---|---:|---:|---:|
| v3 / by_player | combination | 8,961 | 91.2990% | 40.1550% |
| v3 / by_player | no_baseline | 575 | 5.8584% | 2.5766% |
| v3 / by_player | short_game | 279 | 2.8426% | 1.2502% |
| v3 / by_time | combination | 10,139 | 88.9854% | 39.9126% |
| v3 / by_time | no_baseline | 919 | 8.0656% | 3.6177% |
| v3 / by_time | short_game | 336 | 2.9489% | 1.3227% |
| v3b / by_player | combination | 8,754 | 76.9785% | 39.2275% |
| v3b / by_player | no_baseline | 2,339 | 20.5681% | 10.4813% |
| v3b / by_player | short_game | 279 | 2.4534% | 1.2502% |
| v3b / by_time | combination | 9,578 | 71.2278% | 37.7042% |
| v3b / by_time | no_baseline | 3,533 | 26.2735% | 13.9078% |
| v3b / by_time | short_game | 336 | 2.4987% | 1.3227% |

### Baseline kind by label

| Variant / split | Label | Bucketed | Pooled | None |
|---|---|---:|---:|---:|
| v3 / by_player | ABSTAIN | 7,380 (75.1910%) | 1,859 (18.9404%) | 576 (5.8686%) |
| v3 / by_player | NOT | 9,756 (84.5114%) | 1,788 (15.4886%) | 0 (0.0000%) |
| v3 / by_player | TILT | 705 (73.6677%) | 252 (26.3323%) | 0 (0.0000%) |
| v3 / by_time | ABSTAIN | 7,887 (69.2206%) | 2,588 (22.7137%) | 919 (8.0656%) |
| v3 / by_time | NOT | 10,481 (80.8782%) | 2,478 (19.1218%) | 0 (0.0000%) |
| v3 / by_time | TILT | 728 (69.3333%) | 322 (30.6667%) | 0 (0.0000%) |
| v3b / by_player | ABSTAIN | 7,994 (70.2955%) | 1,002 (8.8111%) | 2,376 (20.8934%) |
| v3b / by_player | NOT | 9,007 (90.7323%) | 920 (9.2677%) | 0 (0.0000%) |
| v3b / by_player | TILT | 840 (82.5959%) | 177 (17.4041%) | 0 (0.0000%) |
| v3b / by_time | ABSTAIN | 8,544 (63.5383%) | 1,318 (9.8014%) | 3,585 (26.6602%) |
| v3b / by_time | NOT | 9,688 (89.0278%) | 1,194 (10.9722%) | 0 (0.0000%) |
| v3b / by_time | TILT | 864 (80.4469%) | 210 (19.5531%) | 0 (0.0000%) |

## Verified conventions and mechanical choices

- Read the complete lock, including Erratum 1, and the stop-1 report before implementation. Verified the lock with `sha256sum` before starting. Mandatory preflight completed before the first real-data evidence vote or gate value.
- `features.move_features` stores `eval_after_cp` and `eval_after_mate` in mover POV. E6 changes both signs when that mover is the opponent, then uses `core.formulas.win_percent`, including mate values. Only the actual last game ply and its immediate predecessor are considered, in that order; an absent/null final value never searches further back. The last recorded own clock is the last non-null own-move clock.
- `timeout` is abandonment; `outoftime` is time forfeit, as confirmed by Erratum 1 and the existing evaluation documentation. A null time-control component makes E3 missing and disables the outoftime-clock condition; it does not disable timeout abandonment.
- Reused the robust/score_baseline formula with NumPy medians and MADs over small seven-column matrices. A synthetic test checks exact agreement with the existing helper. Floors are 5.0, .2, .002, .10, .05, .05, .02 in feature order. The existing risk/attack floors are .05; sacrifice has no existing floor.
- Existing session_id values are preserved. Session code uses true previous end_ms when present and previous start_ms as a membership proxy otherwise. C5 and E7 thresholds use only true-end gaps; q20 uses exact gaps only. No proxy gap enters a threshold. Baselines retain strict `end_upper_ms < current.start_ms` eligibility.
- Exact one-to-one metadata bridge: `(start_ms, color, rating, opponent_rating, result_score, end_upper_ms)`. Both sources have unique bridge keys; every one of 36,401 aligned cohort rows matches, and player-to-existing-player_id mapping is one-to-one for 196 players. The two aligned files match outside split membership. Their salted game IDs are reused in outputs. No new player or game pseudonym is generated, and no salt or token is read. All feature games of those players are covered by the bridge; no additional unmapped prior-game time controls are needed.
- Time controls come from the aligned game mapping for current and prior games. Raw status, plies, rated and side ratings come from the committed normalized shards selected by the same batch manifest as `tilt.data.storage.read`. A read-only SQLite connection avoids storage.read’s DDL/commit side effects. Input data is never rewritten or copied.
- Historical game ordering is start_ms then game_id for deterministic ties. Reference selection first searches all prior same-speed candidates for a matching length bucket, then caps the selected bucket or pooled window at 200. Every feature needs at least five non-null historical game values. v3b raises the pooled reference-set minimum to 20 games as specified; the unchanged per-feature five-value rule still applies inside that window. All quantiles use linear interpolation. Current per-move quantities obey their stated data minima before entering prior reference windows; flag rates use all own moves, with a null flag contributing no flagged move.
- E7’s explicit missing conditions (last collected game, lost game without true end_ms, fewer than ten prior exact gaps) take precedence over the not_fired condition for a next game outside the session. A non-lost game is always not_fired. q20 uses the last at most 200 prior exact non-first-session gaps, across speeds.
- Each split labels exactly its own train membership. Shared train targets are computed once per variant on their union, then each split is selected and scored separately; a row’s membership in a different split never changes its own split’s train set. All other rows are feature inputs only. Non-train evidence/label vectors and non-train label statistics are never constructed. The public labelling, gate and report-stat functions reject non-train target frames.
- Label codes are strings TILT / NOT / ABSTAIN; E states are fired / not_fired / missing. Ineligible rows remain in every coverage denominator. Missing evidence counts against NOT. ABSTAIN reason precedence and G2 merge mechanics are stated above. Undefined AUCs or empty gate strata fail closed.
- CLI is the standalone module entry point `.venv/bin/python -m tilt.labels.rules_v3`; no existing CLI file was changed. Design hash is SHA-256 of canonical sorted compact JSON for the one frozen Design dataclass (including both variants). Both variants therefore record the same design hash. Extra outside-repository `run_summary.json` preserves selection, full gate values, report-only statistics, ratings and runtime.

## Files, privacy and validation

Repository files created/overwritten:

- `tilt/src/tilt/labels/rules_v3.py` (new).
- `tilt/tests/unit/test_rules_v3.py` (new).
- `tilt/reports/label_v3_S1.md` (overwrites stop-1 report).

Artifacts in `~/tilt-labels-v3/S1/`:

- `labels_by_player_train.parquet`, `labels_by_time_train.parquet`, `gates.json`, `lf_stats.csv`, `design_hash.txt`.
- Corresponding `_v3b` files, because the fallback trigger was met.
- `run_summary.json` and `codex-last.md`.

Output tables use existing aligned game_id and player_id, with color for unique side keys. They contain no username, raw game ID, opponent, or raw session ID. No v1/v2 code/output or pre-registration was changed. Pre-existing workspace changes, including lila changes, were left untouched. No commit or push was performed.

The full label run took **233.51 seconds** for both variants, including preparation and output. Train target union: 32,061 distinct player-game sides. Runtime was below the 20-minute limit. The process reported peak resident memory of 1,857,564 KiB (about 1.77 GiB).

Post-run audits passed on all four label Parquets: exact train-key/player membership and row counts, unique side keys, absence of username/raw identifiers, all evidence-state/count identities, TILT/NOT eligibility and combination invariants, win restrictions, strict historical baseline end times, agreement of saved gate AUC/coverage with independent calculations, and LF CSV totals. Shared train targets have identical labels and evidence counts across the two split outputs. Both design-hash files match the recorded constants hash.

Tests:

- New unit module: `.venv/bin/python -m pytest -q tests/unit/test_rules_v3.py` — **74 passed**.
- Full suite from `tilt/`: `PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime .venv/bin/python -m pytest -q` — **356 passed, 0 failed, 0 skipped, 1 warning in 54.03 s**. The supplied outside-repository asyncio wake-up shim was used. The warning is the existing Starlette/AnyIO BlockingPortal deprecation. The existing engine/model tests described under Deviations ran on temporary fixtures.
- Coverage includes draw-skipping and session-boundary loss runs, C2’s absolute counts with short histories, LL/LLL/LWLL decay, exact C5 gaps, every context level, every evidence state, E6 mover/mate conversion, E7 collection/session edges, every truth-table cell, win restrictions and label invariants, strict prior-only/capped baselines, percentiles, train-only API guards, gate mechanics and selection order.

## Locked-document hash checks

Design constants SHA-256: `6393da7f066e1a8c3892fd894e381cb70ceb1f24d00366e97ef5ef40794fb0fb`.

Expected active pre-registration SHA-256:

`ccf652ad6355b580f51f67a3667548828ba228da8f01b14b0ff504ffdc1a34f1`

- Before starting, `sha256sum tilt/reports/label_v3_preregistration.md`: `ccf652ad6355b580f51f67a3667548828ba228da8f01b14b0ff504ffdc1a34f1` — MATCH.
- At the end, the same `sha256sum` check: `ccf652ad6355b580f51f67a3667548828ba228da8f01b14b0ff504ffdc1a34f1` — MATCH.
- The CLI also verified the active lock before loading inputs and verified the unchanged document after writing outputs.
