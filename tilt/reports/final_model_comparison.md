# Phase 5: so sánh và chọn mô hình cuối

Ngày 2026-11-15. Quy tắc nằm trong `phase5_preregistration.md` (sha256 `b90556c1…`), cố định và băm trước khi mở
test. Chạy trên Colab (xgboost 2.1.4, scikit-learn 1.6.1), 1.000 lần bootstrap theo cụm người chơi, seed 42. Lần 2
chạy trong một phiên Colab mới để kiểm tra tái lập.

> **The model predicts a behavioral proxy of tilt, not independently validated anger.**
>
> Mọi số dưới đây đo khả năng dự đoán nhãn yếu do 10 LF sinh ra, không đo cơn giận. Hiện có 0 nhãn người.

## 1. Kết luận

- **Mô hình cuối: P3-B** (M3 + `attack_trend_3w`, `risk_volatility_3w`, `behavior_change_point`). Theo quy tắc 1 của
  bản đăng ký, P3-B qua đủ 8 cổng và hơn M3 trên test ở cả hai split.
- PR-AUC test: 0,507 [0,407; 0,629] ở A (người chơi mới), 0,532 [0,378; 0,673] ở B (giai đoạn sau). Tỉ lệ nền là
  0,140 / 0,150.
- M3 cũng qua đủ 8 cổng, nhưng thấp hơn P3-B: +0,090 [0,060; 0,118] ở A và +0,056 [0,018; 0,097] ở B.
- E0 có PR-AUC test cao nhất (0,508 / 0,568) nhưng không được chọn. Phần hơn của E0 đến từ cột
  `phase_middlegame_fraction`, tức lối tắt độ dài ván (mục 5).
- Chỉ dùng độ dài ván (B-length, không triển khai được) vẫn hơn mọi mô hình: 0,672 / 0,658. Trên ván ≥ 40 nửa nước,
  P3-B chỉ đạt 0,153 / 0,140 so với tỉ lệ nền 0,083 / 0,091 (mục 7).
- Artifact nằm ở `~/tilt-phase5/run1/artifact/`. Ngày 2026-11-15, P3-B được triển khai thay mô hình cũ (mục 6).

## 2. Kiểm tra trước khi mở test

| Kiểm tra | A: by_player | B: by_time |
|---|---|---|
| sha256 bản đăng ký khớp | đạt | đạt |
| Manifest split trùng Phase 1 | đạt (`3243a255…`) | đạt (`034a3e09…`) |
| Tái lập validation P3-B (mục tiêu) | 0,528258 (0,528258) | 0,436663 (0,436663) |
| Tái lập validation M3 | 0,449016 (0,449016) | 0,370355 (0,370355) |
| Tái lập validation E0 | 0,537769 (0,537769) | 0,454314 (0,454314) |
| Validation bản nometa (ghi trước khi đọc test) | P3-B 0,540, M3 0,459 | P3-B 0,435, M3 0,363 |
| Lần bootstrap bị bỏ | 0 | 0 |

Cả ba mô hình tái lập đúng tới 6 chữ số, nên code chỉ đọc nhãn test sau bước này.

Dòng test có nhãn: A có 2.002 dòng, 36 người chơi, tỉ lệ TILT 0,140. B có 1.711 dòng, 139 người chơi, tỉ lệ 0,150.

## 3. Kết quả trên test

PR-AUC kèm CI 95% bootstrap theo người chơi; validation đặt cạnh để so. "≥ 40" là PR-AUC trên ván từ 40 nửa nước trở
lên (tỉ lệ nền 0,083 ở A, 0,091 ở B). "Tách ngắn" là max(AUC, 1 − AUC) của điểm khi phân biệt ván < 40 nửa nước.
Brier skill score (BSS) và ECE tính sau Platt (fit trên validation).

### A: by_player (người chơi mới)

| Mô hình | Validation | Test [CI 95%] | Lift | ROC | ≥ 40 [CI] | Tách ngắn | BSS | ECE |
|---|---|---|---|---|---|---|---|---|
| **P3-B** | 0,528 | **0,507** [0,407; 0,629] | 3,62 | 0,768 | 0,153 [0,109; 0,218] | 0,914 | 0,222 | 0,010 |
| M3 | 0,449 | 0,417 [0,310; 0,544] | 2,97 | 0,713 | 0,124 [0,088; 0,180] | 0,834 | 0,146 | 0,019 |
| P3-B-nometa | 0,540 | 0,493 [0,400; 0,607] | 3,52 | 0,765 | 0,149 | 0,907 | 0,209 | 0,012 |
| M3-nometa | 0,459 | 0,409 [0,315; 0,521] | 2,92 | 0,699 | 0,126 | 0,803 | 0,139 | 0,027 |
| E0 (tham chiếu) | 0,538 | 0,508 [0,412; 0,619] | 3,62 | 0,767 | 0,141 [0,107; 0,192] | 0,867 | 0,238 | 0,017 |
| M1 (chẩn đoán) | 0,449 | 0,417 [0,314; 0,543] | 2,97 | 0,714 | 0,124 | 0,834 | 0,147 | 0,018 |
| B-length | 0,656 | 0,672 [0,568; 0,768] | 4,79 | 0,854 | 0,180 [0,139; 0,235] | 1,000 | 0,442 | 0,014 |
| B-streak | 0,242 | 0,246 [0,203; 0,302] | 1,75 | 0,716 | 0,148 | 0,692 | 0,046 | 0,066 |
| B-result | 0,182 | 0,183 [0,143; 0,239] | 1,30 | 0,628 | 0,101 | 0,664 | 0,032 | 0,006 |
| B-meta | 0,137 | 0,168 [0,120; 0,259] | 1,20 | 0,577 | 0,083 | 0,667 | −1,127 | 0,370 |
| B-prior | 0,137 | 0,140 | 1,00 | 0,500 | 0,083 | 0,500 | −0,001 | 0,011 |

### B: by_time (giai đoạn thời gian sau)

| Mô hình | Validation | Test [CI 95%] | Lift | ROC | ≥ 40 [CI] | Tách ngắn | BSS | ECE |
|---|---|---|---|---|---|---|---|---|
| **P3-B** | 0,437 | **0,532** [0,378; 0,673] | 3,55 | 0,751 | 0,140 [0,104; 0,196] | 0,949 | 0,225 | 0,032 |
| M3 | 0,370 | 0,478 [0,311; 0,637] | 3,19 | 0,720 | 0,137 [0,099; 0,200] | 0,901 | 0,183 | 0,028 |
| P3-B-nometa | 0,435 | 0,529 [0,374; 0,675] | 3,54 | 0,747 | 0,134 | 0,954 | 0,223 | 0,030 |
| M3-nometa | 0,363 | 0,471 [0,303; 0,635] | 3,15 | 0,715 | 0,136 | 0,891 | 0,179 | 0,020 |
| E0 (tham chiếu) | 0,454 | 0,568 [0,412; 0,706] | 3,80 | 0,786 | 0,157 [0,118; 0,222] | 0,939 | 0,276 | 0,020 |
| M1 (chẩn đoán) | 0,366 | 0,475 [0,310; 0,636] | 3,18 | 0,717 | 0,138 | 0,886 | 0,179 | 0,032 |
| B-length | 0,608 | 0,658 [0,523; 0,771] | 4,40 | 0,826 | 0,180 [0,137; 0,244] | 1,000 | 0,416 | 0,014 |
| B-streak | 0,242 | 0,288 [0,204; 0,379] | 1,93 | 0,744 | 0,178 | 0,719 | 0,065 | 0,072 |
| B-result | 0,172 | 0,204 [0,147; 0,272] | 1,36 | 0,648 | 0,114 | 0,697 | 0,040 | 0,011 |
| B-meta | 0,147 | 0,162 [0,125; 0,209] | 1,08 | 0,534 | 0,095 | 0,547 | 0,000 | 0,013 |
| B-prior | 0,137 | 0,150 | 1,00 | 0,500 | 0,091 | 0,500 | 0,000 | 0,001 |

Số theo ngưỡng (ngưỡng chọn trên train + validation, áp lên test):

| | Ngưỡng | Precision | Recall | F1 | Tỉ lệ bị gắn cờ |
|---|---|---|---|---|---|
| P3-B, A | 0,273 | 0,515 | 0,427 | 0,467 | 0,116 |
| P3-B, B | 0,259 | 0,579 | 0,430 | 0,493 | 0,111 |
| M3, A | 0,227 | 0,393 | 0,381 | 0,387 | 0,136 |
| M3, B | 0,185 | 0,399 | 0,430 | 0,414 | 0,161 |

Số đầy đủ (gồm đường tin cậy, nhóm con, độ quan trọng) nằm trong `~/tilt-phase5/run1/results.json` và `metrics.csv`
(chỉ trong WSL).

### Chênh lệch ghép cặp trên test

| Δ PR-AUC | Toàn bộ A | Toàn bộ B | ≥ 40 A | ≥ 40 B |
|---|---|---|---|---|
| P3-B − M3 | +0,090 [0,060; 0,118] | +0,056 [0,018; 0,097] | +0,030 [0,011; 0,053] | +0,003 [−0,025; 0,026] |
| P3-B − B-result | +0,323 [0,251; 0,400] | +0,315 [0,215; 0,410] | +0,059 [0,020; 0,104] | +0,030 [−0,000; 0,069] |
| P3-B − B-streak | +0,259 [0,170; 0,350] | +0,232 [0,133; 0,320] | +0,009 [−0,040; 0,069] | −0,038 [−0,104; 0,022] |
| P3-B − B-length | −0,164 [−0,235; −0,105] | −0,129 [−0,181; −0,081] | −0,024 [−0,056; 0,014] | −0,041 [−0,082; −0,003] |
| P3-B − P3-B-nometa | +0,014 [0,000; 0,027] | +0,003 [−0,006; 0,012] | +0,005 | +0,007 |
| M3 − B-streak | +0,168 [0,077; 0,258] | +0,176 [0,065; 0,288] | −0,021 [−0,063; 0,027] | −0,041 [−0,107; 0,024] |
| E0 − M1 | +0,091 [0,052; 0,144] | +0,096 [0,060; 0,142] | +0,017 [−0,002; 0,032] | +0,021 [0,002; 0,037] |

## 4. Tám cổng

| # | Tiêu chí | P3-B | M3 |
|---|---|---|---|
| 1 | Không leakage đã biết: đúng danh sách feature, không feature cấm; ≥ 40: PR-AUC − nền có cận dưới CI > 0 ở A, > 0 ở B | đạt: CI thấp 0,034 (A), +0,049 (B) | đạt: 0,013, +0,046 |
| 2 | Hơn B-prior, B-result, B-streak, B-meta (A: cận dưới CI > 0; B: Δ > 0) | đạt: cận dưới nhỏ nhất 0,170 (so B-streak) | đạt: 0,077 |
| 3 | PR-AUC test A ≥ 0,337 | đạt: 0,507 | đạt: 0,417 |
| 4 | PR-AUC test B ≥ 0,278 và cổng 2 đạt ở B | đạt: 0,532 | đạt: 0,478 |
| 5 | nometa ≥ 0,75 × ứng viên ở A và B | đạt: 0,972 / 0,996 | đạt: 0,983 / 0,985 |
| 6 | BSS > 0 ở A và B; ECE ≤ 0,05 (A), ≤ 0,08 (B) | đạt: BSS 0,222 / 0,225, ECE 0,010 / 0,032 | đạt: 0,146 / 0,183, ECE 0,019 / 0,028 |
| 7 | Feature có trong registry; ≥ 2/3 top 3 validation A nằm trong top 5 test A | đạt: 3/3 (attack_rate, risk_volatility_3w, defensive_rate) | đạt: 3/3 |
| 8 | Hai lần chạy trùng nhau tới 1e-6 | đạt: chênh lệch lớn nhất 0,0; bundle trùng từng byte | đạt (cùng hai lần chạy) |

Quy tắc 1 của bản đăng ký: P3-B qua cả 8 cổng và Δ(P3-B − M3) trên test > 0 ở cả A (+0,090) và B (+0,056), nên P3-B
được chọn. Cổng 8 nêu ở mục 1.

## 5. E0 có PR-AUC test cao nhất

Ở cả hai split, E0 có PR-AUC test cao nhất trong các mô hình (không tính baseline): 0,508 so với 0,507 của P3-B ở A, và
0,568 so với 0,532 ở B. Theo bản đăng ký, E0 vẫn không được chọn. Nguyên nhân:

- E0 chỉ khác M1 ở cột `phase_middlegame_fraction`. Riêng cột này cho E0 − M1 = +0,091 [0,052; 0,144] ở A và +0,096
  [0,060; 0,142] ở B.
- Trên ván ≥ 40 nửa nước, phần tăng gần như biến mất: +0,017 [−0,002; 0,032] ở A và +0,021 [0,002; 0,037] ở B. Nghĩa
  là cột này chủ yếu giúp nhận ra ván ngắn, mà ván ngắn có nhãn thì 100% là TILT. Đây là lối tắt nhãn đã biết từ
  Phase 1, không phải tín hiệu hành vi.
- Trên ván ≥ 40 nửa nước, P3-B ngang E0: 0,153 so với 0,141 ở A, 0,140 so với 0,157 ở B.
- Test đã bị xem với pipeline cũ. Số Phase 0 của mô hình tương đương E0 là 0,509 ("đã xem trước"); lần chạy lại này
  ra 0,508.

## 6. Mô hình được chọn: P3-B

**Feature** (11 cột, theo thứ tự trong bundle):

| Feature | Nguồn | Ý nghĩa |
|---|---|---|
| `initial_seconds`, `increment_seconds` | metadata ván | thời gian cơ bản và cộng giờ |
| `risk_rate`, `attack_rate`, `defensive_rate`, `style_switch_rate` | nước đi trong ván | tỉ lệ nước mạo hiểm, tấn công, phòng thủ, đổi lối chơi |
| `rematch_streak_before` | phiên chơi | số ván liên tiếp ngay trước đó gặp cùng đối thủ |
| `baseline_risk_rate_games` | lịch sử | số ván trước đó có giá trị `risk_rate` (gần trùng `history_games`) |
| `attack_trend_3w` | động lực trong ván (Phase 2, nhóm B) | tỉ lệ tấn công ở 1/3 cuối trừ 1/3 đầu số nước của mình |
| `risk_volatility_3w` | nhóm B | độ lệch chuẩn của tỉ lệ mạo hiểm giữa ba phần ba ván |
| `behavior_change_point` | nhóm B | độ chênh tỉ lệ mạo hiểm trước/sau điểm chia tốt nhất (mỗi bên ≥ 5 nước) |

- Ba cột nhóm B điền trung vị, không có chỉ báo thiếu (thiếu khi dưới 9–10 nước của mình).
- Ở train của split A, 8 feature M3 không có giá trị thiếu, nên bundle không có cột chỉ báo thiếu nào: ma trận vào
  đúng 11 cột (`columns` của bundle).
- Các tỉ lệ lối chơi và ba cột nhóm B tính trên cả ván, nên điểm chỉ có sau khi ván kết thúc.

**Độ quan trọng hoán vị** (mức giảm PR-AUC, test A): `risk_volatility_3w` 0,102, `attack_rate` 0,089, `defensive_rate`
0,051, `risk_rate` 0,035, `behavior_change_point` 0,025. Bỏ hai cột metadata chỉ làm giảm 0,014 / 0,003.

**Artifact** (chỉ trong WSL, `~/tilt-phase5/run1/artifact/`):

- `by_player__P3-B.joblib`: imputer, cột giữ lại, scaler, XGBoost, Platt (fit trên validation), ngưỡng 0,273 (chọn
  theo F1 lớn nhất trên validation);
- `features.json` và `metadata.json` (seed, sha256 của bản đăng ký, manifest, code, bảng số, bundle, phiên bản thư
  viện).

Mô hình được fit trên train của split A. Đây đúng là mô hình đã chấm trên test, không refit.

**Chưa triển khai.** `processed/models/selection.json`, `score.py` và module Tilt trong lila giữ nguyên. Bundle mới không
có regressor. `score.py` hiện chưa tính 3 feature nhóm B, nên muốn chuyển mô hình đang chạy thì phải sửa thêm code. Việc
này để người dùng quyết định.

**Cập nhật ngày 2026-11-15: đã triển khai, theo quyết định của người dùng.** Đoạn trên là trạng thái lúc chọn mô hình.

- `processed/models/deployed.json` trỏ tới bản chép của bundle ở `processed/models/phase5/by_player__P3-B.joblib`, kèm sha256
  `cbd7a3f9…`. File này nằm trong `tilt/data` nên không có trong git.
- `service/deployment.py` từ chối nạp mô hình khi:
  - bundle khác hash;
  - danh sách feature không khớp;
  - có feature bị cấm, hoặc feature nằm trong input của LF.
- `selection.json` giữ nguyên. **Quay lại mô hình cũ:** xóa `deployed.json` rồi khởi động lại worker.
- `score.py` tính 3 feature nhóm B từ các nước của chính người chơi. Ở timeline, chúng chỉ được tính trên phần ván đã
  đi tới điểm đó.
- "Top factors" thay từng feature bằng trung vị train mà imputer dùng. Bundle mới không có regressor.
- Kiểm tra parity: 345/345 ván của test A chấm qua đường `score.py` cho đúng điểm đã hiệu chỉnh của Phase 5 (chênh lệch
  0,0).
- lila: `TiltUi.factorNames` có thêm tên tiếng Anh cho 3 feature nhóm B.

## 7. Hạn chế

- **Nhãn yếu.** Có 0 nhãn người. 100% nhãn TILT có thua ở ván này hoặc ván trước (Phase 4). Mô hình dự đoán proxy hành
  vi đó, không dự đoán cơn giận.
- **Lối tắt độ dài.** Ván < 40 nửa nước có nhãn thì 100% là TILT (126 dòng test ở A, 110 ở B). Chỉ dùng độ dài ván
  (B-length) vẫn hơn mọi mô hình: 0,672 / 0,658 so với 0,507 / 0,532 của P3-B. Điểm của P3-B tách ván ngắn với AUC
  0,914 / 0,949, cao hơn M3 (0,834 / 0,901). Phần lớn lợi thế của P3-B so với M3 vẫn đến từ ván ngắn: trên ván ≥ 40
  nửa nước, Δ chỉ là +0,030 ở A và +0,003 ở B (không phân biệt được với 0).
- **Trên ván ≥ 40 nửa nước mô hình yếu.** PR-AUC 0,153 / 0,140 so với tỉ lệ nền 0,083 / 0,091. Ở đó P3-B không hơn
  được baseline chuỗi thua B-streak: +0,009 [−0,040; 0,069] ở A, −0,038 [−0,104; 0,022] ở B. B-streak đọc kết quả các
  ván trước nên không triển khai được, nhưng điều này cho thấy tín hiệu hành vi trên ván dài vẫn nhỏ.
- **Ít người chơi.** Test A chỉ có 36 người chơi, nên CI rộng (P3-B: 0,407–0,629). CI của B rộng hơn nữa (0,378–0,673).
- **Ngưỡng các cổng 3–7 là quy ước** do Fable đặt trước, không suy ra từ dữ liệu. Cả P3-B và M3 đều qua với khoảng
  cách lớn, nên kết luận không phụ thuộc nhạy vào các ngưỡng này.
- **Test đã bị xem** với pipeline cũ ở Phase 0. M3, P3-B và B-length thì chấm test lần đầu.
- **Test B cao hơn validation B** ở mọi mô hình (ví dụ P3-B 0,532 so với 0,437, B-length 0,658 so với 0,608). Đây là
  khác biệt giữa các giai đoạn thời gian, đã thấy từ Phase 0, nằm trong CI.
- **Chỉ có blitz.** Không nói được gì về bullet, rapid hay classical.
- **Nhóm con theo rating** (chỉ mô tả): ở cả hai split, PR-AUC giảm khi rating tăng (A: 0,635 ở < 1200, 0,377 ở ≥ 2000),
  song song với tỉ lệ nền giảm (0,189 so với 0,110). Ở ván không thua, PR-AUC của P3-B chỉ 0,160 / 0,133 so với tỉ lệ
  nền 0,067 / 0,062.

## 8. Tái lập

Trong `~/lichess-workspace/tilt` (WSL). Dữ liệu vào: `~/tilt-phase1/aligned`, `~/tilt-phase1/out` (manifest và
`phase1_results.json`), `~/tilt-phase2/behavior_features.parquet`, `~/tilt-phase3/out/phase3_results.json`.

```
# 1 lần chạy (trên Colab, xem script p5_colab.sh; thư mục --out phải mới)
python -m tilt.evaluation.phase5 run --aligned ~/tilt-phase1/aligned \
  --behavior ~/tilt-phase2/behavior_features.parquet --phase1-out ~/tilt-phase1/out \
  --phase3-results ~/tilt-phase3/out/phase3_results.json \
  --prereg reports/phase5_preregistration.md --prereg-sha256 ~/tilt-phase5/prereg.sha256 \
  --registries reports --out <thư mục mới> --repetitions 1000 --threads <số lõi>
# cổng 8: so hai lần chạy
python -m tilt.evaluation.phase5 compare ~/tilt-phase5/run1 ~/tilt-phase5/run2
# unit test
TILT_SALT=<chuỗi bất kỳ ≥ 16 ký tự> .venv/bin/python -m pytest tests/unit/test_phase5.py
```

Băm:

| Mục | sha256 |
|---|---|
| `phase5_preregistration.md` | `b90556c1582f97204e4002700cdebe6de3c8ad18e715f3aea43346d222c650cd` |
| Manifest A / B | `3243a255…f9ec4b` / `034a3e09…e1b6` |
| `evaluation/phase5.py` | `7ed9ed67…` |
| `metrics.csv` (lần 1) | `84e4914e…` |
| Bundle (lần 1) | `cbd7a3f9…` |

Kết quả kiểm tra tái lập:
- Lần 2 chạy trong phiên Colab mới. `compare` cho chênh lệch lớn nhất 0,0 trên `results.json` và dự đoán test, không
  có khác biệt nào khác. `metrics.csv` và bundle của hai lần trùng sha256.
- Nạp lại bundle ở local (Python 3.12) cho đúng điểm thô và điểm đã hiệu chỉnh trên test A (chênh lệch 0,0).
- Colab dùng Python 3.13; xgboost 2.1.4 và scikit-learn 1.6.1 được khóa phiên bản.

Kết quả của hai lần chạy nằm ở `~/tilt-phase5/run1` và `run2`; quyết định cuối ở `run1/final_decision.json`.

## 9. Hậu nghiệm

Chưa có phân tích hậu nghiệm nào.
