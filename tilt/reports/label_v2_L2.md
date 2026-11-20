# Weak-label v2 — L2: thiết kế postloss20 và fallback postloss40

**Verdict: cả hai thất bại ⇒ dừng hướng weak-label (`both failed => weak-label direction stops`).** Không chấp nhận postloss20 hoặc postloss40. postloss20 trượt G3/G4/G5 ở cả A và B. Fallback được kích hoạt bởi G4/G5; postloss40 trượt G3/G4/G5 ở cả hai và thêm G6 ở B. Không thay ngưỡng, thử thêm ứng viên hay chạy lại dữ liệu sau thất bại.

Mục tiêu được duyệt: suy giảm hành vi ngay sau một ván thua trong cùng phiên. Điều kiện thua trước thuộc **quần thể của cả hai lớp**, và được chấp nhận công khai. Không tuyên bố về tilt ngoài quần thể này.

The model predicts a behavioral proxy of tilt, not independently validated anger.

## Thiết kế đóng băng và phạm vi

- Tệp: `~/tilt-labels-v2/L2/design_v2_L2.json`; UTC đóng băng: `2026-11-14T21:14:07.089172+00:00`.
- SHA-256: `017a7f0afa204d171e4884fbd8fe7eabdf899e6f876a3bced37478c98f565c27`; tệp hash: `design_v2_L2.sha256`, có cùng timestamp UTC.
- Bắt đầu audit dữ liệu: `2026-11-14T21:18:06.991711+00:00`; kết thúc: `2026-11-14T21:18:13.583639+00:00`. Thiết kế và hash tồn tại trước mọi thống kê L2, kể cả kiểm tra tổng hợp trên fixture. CLI xác minh hash trước đọc dữ liệu, trước từng thiết kế/chính sách, từng biến thể sensitivity và trước ghi kết quả; sai hash thì từ chối.
- A = `by_player`, B = `by_time`. Chỉ đọc hai Parquet nguồn có sẵn dưới `~/tilt-phase1/aligned/`, bằng loader L1 `load_train` với predicate Parquet `split == train`; chiếu thêm riêng `split, player_id` với cùng predicate cho G6. Schema chỉ là metadata; không đọc/count/tóm tắt validation, test hoặc dữ liệu mới. Không xuất player_id hoặc bảng theo ván/người.
- Tái sử dụng `lf_input__*` đã đóng băng; không dựng lại phiên/lịch sử trên một bảng đã lọc. Loader L1 chiếu xác suất v1 nhưng L2 loại ngay cột đó; không tạo `weak_tilt_prob`, không fit Dawid–Skene, không gọi pipeline v1.

Một common gate cho mọi LF: `plies >= 20`, `move_count >= 10` là số nước thật của người chơi; `previous_result_score == 0`, `previous_same_session is true`, `0 <= (start_ms - previous_end_upper_ms)/1000 <= 120` giây. Thiếu/không hữu hạn bằng chứng cần thiết thì bỏ phiếu trắng; không thay move_count bằng plies/2. Thiếu plies không thể có nhãn. Bucket <20 nằm ngoài common gate.

| LF | Phiếu và điều kiện ngoài common gate |
| --- | --- |
| deteriorated | TILT nếu `deviation_mean_cpl_z >= 1.5` |
| fast_erratic | TILT nếu `z >= 1` và `0 <= mean_think <= 0.65 * baseline_mean_think_median`; baseline dương, hữu hạn |
| steady | NOT nếu `z < 1` và `0 <= adverse_events / move_count <= 0.25`; không có cận dưới cho z |

Có bất kỳ phiếu TILT ⇒ nhãn 1; chỉ steady ⇒ nhãn 0; không phiếu ⇒ không nhãn. `session_spiral` bị loại; không có LF khác. Không LF/common gate nào đọc kết quả hiện tại, status, final eval hoặc tương lai.

Fallback postloss40 giữ nguyên toàn bộ quy tắc, chỉ đổi sàn thành `plies >= 40`, `move_count >= 20`; bucket 40–59, 60–79, ≥80. Chỉ được tính nếu postloss20 trượt G2/G4/G5/G6 ở A hoặc B. Mọi G1–G7 phải đạt trên cả hai chính sách để được chấp nhận.

## G1: cấu trúc và provenance

Test dựng được TILT với z=2 và NOT với z=-100, adverse_events=0 ở mọi độ dài hợp lệ: kiểm tra từng số nguyên từ sàn tới 1.000 và ván dài 1.000.000 plies; lập luận cho mọi độ dài lớn hơn dựa trên việc LF không dùng plies ngoài common gate. Provenance dùng dictionary chặn đọc ngoài danh sách cho phép; test thêm thay đổi kết quả/status/final eval/tương lai mà phiếu không đổi. Không có gate độ dài riêng cho từng lớp.

| Phần | Trường hiện tại được đọc | Trường quá khứ được đọc |
| --- | --- | --- |
| Common gate | plies, move_count, start_ms | previous_result_score, previous_same_session, previous_end_upper_ms |
| deteriorated | deviation_mean_cpl_z | — |
| fast_erratic | deviation_mean_cpl_z, mean_think | baseline_mean_think_median |
| steady | deviation_mean_cpl_z, adverse_events | — |

## G6: quy trình đã khóa

Dùng `scikit-learn 1.6.1`, `GroupKFold(n_splits=5)` **không shuffle, không random_state**; seed 42 được ghi trong thiết kế nhưng không ảnh hưởng G6. Chỉ hàng TRAIN có nhãn; nhóm theo player_id băm và kiểm tra không giao người chơi giữa fold fit và holdout. Mỗi fold chỉ dùng plies của phần fit để tính `np.quantile` tại 0.1…0.9, khử trùng internal edges; gán bin bằng `np.digitize(plies, edges, right=False)`. Điểm là tỉ lệ TILT không smoothing trong bin của phần fit; bin rỗng dùng prevalence của phần fit. Gộp toàn bộ điểm OOF và tính `roc_auc_score` với TILT=1, **không lấy max hai chiều**. Ngưỡng ≤0,62. Edges/rates/counts theo fold được lưu dưới dạng aggregate trong results.json; không xuất điểm từng hàng. Thiếu player_id, ít hơn 5 người chơi hoặc fold fit chỉ có một lớp ⇒ G6 FAIL rồi dừng; trường hợp đó không xảy ra trong audit này. AUC không xác định hoặc bucket rỗng không thể qua cổng tương ứng.

## Kết quả postloss20

| Cổng | Ngưỡng cố định | A: by_player | B: by_time |
| --- | --- | --- | --- |
| G1 | Một common gate; cả hai lớp ở mọi độ dài hợp lệ; provenance hợp lệ | PASS — cấu trúc/provenance đạt | PASS — cấu trúc/provenance đạt |
| G2 | Mỗi bucket ≥30 TILT, ≥100 NOT; tổng ≥300 TILT, ≥1.200 có nhãn | PASS — 733 TILT; 2342 có nhãn; mọi bucket đủ | PASS — 752 TILT; 2343 có nhãn; mọi bucket đủ |
| G3 | Có nhãn / qua common gate ≥50% | **FAIL** — 2342/6081 = 38.51% | **FAIL** — 2343/6711 = 34.91% |
| G4 | max(AUC plies, 1−AUC) ≤0,60 | **FAIL** — 0.618038 | **FAIL** — 0.618046 |
| G5 | max−min tỉ lệ TILT giữa bucket ≤15 đpt | **FAIL** — 19.69 đpt | **FAIL** — 19.39 đpt |
| G6 | AUC OOF scorer decile theo người chơi ≤0,62 | PASS — 0.608932 | PASS — 0.602710 |
| G7 | Cả hai lớp 100% có thua trước cùng phiên; xung đột =0 | PASS — TILT 100.00%; NOT 100.00%; 0 xung đột | PASS — TILT 100.00%; NOT 100.00%; 0 xung đột |

| Chính sách | Toàn TRAIN | Qua common gate | Có nhãn | TILT | NOT | TILT / có nhãn | Phủ toàn TRAIN | AUC plies thô |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 22316 | 6081 | 2342 | 733 | 1609 | 31.30% | 10.49% | 0.381962 |
| B | 25403 | 6711 | 2343 | 752 | 1591 | 32.10% | 9.22% | 0.381954 |

| Chính sách | Bucket plies | Qua common gate | TILT | NOT | Có nhãn | Tỉ lệ TILT |
| --- | --- | --- | --- | --- | --- | --- |
| A | 20–39 | 962 | 186 | 290 | 476 | 39.08% |
| A | 40–59 | 1530 | 220 | 351 | 571 | 38.53% |
| A | 60–79 | 1464 | 169 | 311 | 480 | 35.21% |
| A | >=80 | 2125 | 158 | 657 | 815 | 19.39% |
| B | 20–39 | 1116 | 198 | 307 | 505 | 39.21% |
| B | 40–59 | 1773 | 239 | 357 | 596 | 40.10% |
| B | 60–79 | 1593 | 151 | 299 | 450 | 33.56% |
| B | >=80 | 2229 | 164 | 628 | 792 | 20.71% |

## Kết quả postloss40

| Cổng | Ngưỡng cố định | A: by_player | B: by_time |
| --- | --- | --- | --- |
| G1 | Một common gate; cả hai lớp ở mọi độ dài hợp lệ; provenance hợp lệ | PASS — cấu trúc/provenance đạt | PASS — cấu trúc/provenance đạt |
| G2 | Mỗi bucket ≥30 TILT, ≥100 NOT; tổng ≥300 TILT, ≥1.200 có nhãn | PASS — 547 TILT; 1866 có nhãn; mọi bucket đủ | PASS — 554 TILT; 1838 có nhãn; mọi bucket đủ |
| G3 | Có nhãn / qua common gate ≥50% | **FAIL** — 1866/5119 = 36.45% | **FAIL** — 1838/5595 = 32.85% |
| G4 | max(AUC plies, 1−AUC) ≤0,60 | **FAIL** — 0.632721 | **FAIL** — 0.640332 |
| G5 | max−min tỉ lệ TILT giữa bucket ≤15 đpt | **FAIL** — 19.14 đpt | **FAIL** — 19.39 đpt |
| G6 | AUC OOF scorer decile theo người chơi ≤0,62 | PASS — 0.604783 | **FAIL** — 0.625224 |
| G7 | Cả hai lớp 100% có thua trước cùng phiên; xung đột =0 | PASS — TILT 100.00%; NOT 100.00%; 0 xung đột | PASS — TILT 100.00%; NOT 100.00%; 0 xung đột |

| Chính sách | Toàn TRAIN | Qua common gate | Có nhãn | TILT | NOT | TILT / có nhãn | Phủ toàn TRAIN | AUC plies thô |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | 22316 | 5119 | 1866 | 547 | 1319 | 29.31% | 8.36% | 0.367279 |
| B | 25403 | 5595 | 1838 | 554 | 1284 | 30.14% | 7.24% | 0.359668 |

| Chính sách | Bucket plies | Qua common gate | TILT | NOT | Có nhãn | Tỉ lệ TILT |
| --- | --- | --- | --- | --- | --- | --- |
| A | 40–59 | 1530 | 220 | 351 | 571 | 38.53% |
| A | 60–79 | 1464 | 169 | 311 | 480 | 35.21% |
| A | >=80 | 2125 | 158 | 657 | 815 | 19.39% |
| B | 40–59 | 1773 | 239 | 357 | 596 | 40.10% |
| B | 60–79 | 1593 | 151 | 299 | 450 | 33.56% |
| B | >=80 | 2229 | 164 | 628 | 792 | 20.71% |

## Fallback và verdict

Fallback đã tính: **có**. Lý do được ghi tự động: `by_player:G4`, `by_player:G5`, `by_time:G4`, `by_time:G5`. G3 không phải trigger fallback; G4/G5 là trigger hợp lệ ở cả A và B. Sau fallback không có lần thử khác hoặc chỉnh ngưỡng.

Verdict máy đọc: `both failed => weak-label direction stops`. **Cả hai thất bại ⇒ dừng hướng weak-label.** Không dùng bất kỳ bảng report-only nào để thay đổi quyết định này.

## Bảng chỉ để báo cáo

Các bảng dưới đây không phải cổng. Tỉ lệ TILT có mẫu số là hàng có nhãn trong nhóm; phủ quần thể có mẫu số là hàng qua common gate trong nhóm. Dấu — là không xác định, không phải 0%. Kết quả ván hiện tại và rating chỉ được đọc sau bước bỏ phiếu để phân tầng báo cáo.

### Theo kết quả ván hiện tại

| Thiết kế | Chính sách | Nhóm | Qua common gate | Có nhãn | TILT | NOT | Tỉ lệ TILT | Phủ quần thể |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| postloss20 | A | thua | 2911 | 969 | 546 | 423 | 56.35% | 33.29% |
| postloss20 | A | hòa | 274 | 115 | 13 | 102 | 11.30% | 41.97% |
| postloss20 | A | thắng | 2863 | 1247 | 173 | 1074 | 13.87% | 43.56% |
| postloss20 | A | không rõ | 33 | 11 | 1 | 10 | 9.09% | 33.33% |
| postloss20 | B | thua | 3270 | 984 | 562 | 422 | 57.11% | 30.09% |
| postloss20 | B | hòa | 299 | 107 | 13 | 94 | 12.15% | 35.79% |
| postloss20 | B | thắng | 3099 | 1236 | 175 | 1061 | 14.16% | 39.88% |
| postloss20 | B | không rõ | 43 | 16 | 2 | 14 | 12.50% | 37.21% |
| postloss40 | A | thua | 2375 | 716 | 385 | 331 | 53.77% | 30.15% |
| postloss40 | A | hòa | 266 | 112 | 13 | 99 | 11.61% | 42.11% |
| postloss40 | A | thắng | 2445 | 1027 | 148 | 879 | 14.41% | 42.00% |
| postloss40 | A | không rõ | 33 | 11 | 1 | 10 | 9.09% | 33.33% |
| postloss40 | B | thua | 2647 | 715 | 394 | 321 | 55.10% | 27.01% |
| postloss40 | B | hòa | 287 | 104 | 13 | 91 | 12.50% | 36.24% |
| postloss40 | B | thắng | 2619 | 1003 | 145 | 858 | 14.46% | 38.30% |
| postloss40 | B | không rõ | 42 | 16 | 2 | 14 | 12.50% | 38.10% |

### Theo rating

| Thiết kế | Chính sách | Nhóm | Qua common gate | Có nhãn | TILT | NOT | Tỉ lệ TILT | Phủ quần thể |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| postloss20 | A | <1200 | 1484 | 419 | 193 | 226 | 46.06% | 28.23% |
| postloss20 | A | 1200–1599 | 1390 | 436 | 155 | 281 | 35.55% | 31.37% |
| postloss20 | A | 1600–1999 | 1197 | 467 | 141 | 326 | 30.19% | 39.01% |
| postloss20 | A | >=2000 | 2010 | 1020 | 244 | 776 | 23.92% | 50.75% |
| postloss20 | A | unknown | 0 | 0 | 0 | 0 | — | — |
| postloss20 | B | <1200 | 1999 | 487 | 216 | 271 | 44.35% | 24.36% |
| postloss20 | B | 1200–1599 | 1555 | 475 | 179 | 296 | 37.68% | 30.55% |
| postloss20 | B | 1600–1999 | 1042 | 376 | 121 | 255 | 32.18% | 36.08% |
| postloss20 | B | >=2000 | 2115 | 1005 | 236 | 769 | 23.48% | 47.52% |
| postloss20 | B | unknown | 0 | 0 | 0 | 0 | — | — |
| postloss40 | A | <1200 | 1067 | 263 | 118 | 145 | 44.87% | 24.65% |
| postloss40 | A | 1200–1599 | 1151 | 316 | 113 | 203 | 35.76% | 27.45% |
| postloss40 | A | 1600–1999 | 1053 | 378 | 111 | 267 | 29.37% | 35.90% |
| postloss40 | A | >=2000 | 1848 | 909 | 205 | 704 | 22.55% | 49.19% |
| postloss40 | A | unknown | 0 | 0 | 0 | 0 | — | — |
| postloss40 | B | <1200 | 1444 | 297 | 142 | 155 | 47.81% | 20.57% |
| postloss40 | B | 1200–1599 | 1305 | 348 | 127 | 221 | 36.49% | 26.67% |
| postloss40 | B | 1600–1999 | 905 | 300 | 90 | 210 | 30.00% | 33.15% |
| postloss40 | B | >=2000 | 1941 | 893 | 195 | 698 | 21.84% | 46.01% |
| postloss40 | B | unknown | 0 | 0 | 0 | 0 | — | — |

### So với v1 trên giao có nhãn

Dùng nhãn v1 đã lưu; không fit lại v1. Bốn ô là số hàng trong giao TRAIN có nhãn của cả hai phiên bản. “Mới” = v2 có nhãn, v1 không có; “mất” = v1 có nhãn, v2 không có. Khớp cao trên giao không xác nhận chất lượng nhãn, cũng không đánh giá các hàng được thêm/bỏ.

| Thiết kế | Chính sách | Giao | v1=0,v2=0 | v1=0,v2=1 | v1=1,v2=0 | v1=1,v2=1 | Khớp | Mới | Mất |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| postloss20 | A | 1145 | 433 | 17 | 18 | 677 | 96.94% | 1197 | 5283 |
| postloss20 | B | 1137 | 402 | 19 | 24 | 692 | 96.22% | 1206 | 6063 |
| postloss40 | A | 958 | 433 | 17 | 4 | 504 | 97.81% | 908 | 5470 |
| postloss40 | B | 933 | 402 | 19 | 6 | 506 | 97.32% | 905 | 6267 |

### Sensitivity postloss20 — one_at_a_time, đúng 10 biến thể

Mỗi biến thể chỉ đổi một ngưỡng, giữ mọi ngưỡng còn lại ở gốc: deteriorated_z 1,25/1,75; fast_z 0,75/1,25; steady_z 0,75/1,25; adverse_rate 0,20/0,30; prior_gap tối đa 60/180 giây. Miền xung đột ở fast_z=0,75 hoặc steady_z=1,25 được chấp nhận để báo cáo; phiếu TILT thắng. **Hai biến thể gap thay common gate, vì vậy thay cả quần thể.** Không chấm cổng, không fit G6 trên biến thể, không lựa chọn ngưỡng từ bảng này. postloss40 không có sensitivity grid.

| Chính sách | Ngưỡng đổi | Có nhãn | TILT | NOT | Tỉ lệ TILT | max AUC hai chiều | Khoảng tỉ lệ bucket | Xung đột |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A | deteriorated_z=1.25 | 2547 | 938 | 1609 | 36.83% | 0.605770 | 18.83 đpt | 0 |
| A | deteriorated_z=1.75 | 2204 | 595 | 1609 | 27.00% | 0.625617 | 19.28 đpt | 0 |
| A | fast_z=0.75 | 2359 | 754 | 1605 | 31.96% | 0.623865 | 21.35 đpt | 4 |
| A | fast_z=1.25 | 2325 | 716 | 1609 | 30.80% | 0.612860 | 18.92 đpt | 0 |
| A | steady_z=0.75 | 2294 | 733 | 1561 | 31.95% | 0.620126 | 20.40 đpt | 0 |
| A | steady_z=1.25 | 2379 | 733 | 1646 | 30.81% | 0.618430 | 19.69 đpt | 4 |
| A | adverse_rate=0.2 | 1343 | 733 | 610 | 54.58% | 0.519402 | 18.77 đpt | 0 |
| A | adverse_rate=0.3 | 3463 | 733 | 2730 | 21.17% | 0.645928 | 19.86 đpt | 0 |
| A | gap_seconds=60 | 2182 | 685 | 1497 | 31.39% | 0.611712 | 18.99 đpt | 0 |
| A | gap_seconds=180 | 2413 | 753 | 1660 | 31.21% | 0.616239 | 19.35 đpt | 0 |
| B | deteriorated_z=1.25 | 2563 | 972 | 1591 | 37.92% | 0.606541 | 20.00 đpt | 0 |
| B | deteriorated_z=1.75 | 2198 | 607 | 1591 | 27.62% | 0.620557 | 17.72 đpt | 0 |
| B | fast_z=0.75 | 2366 | 779 | 1587 | 32.92% | 0.622462 | 19.84 đpt | 4 |
| B | fast_z=1.25 | 2323 | 732 | 1591 | 31.51% | 0.614030 | 19.39 đpt | 0 |
| B | steady_z=0.75 | 2295 | 752 | 1543 | 32.77% | 0.618989 | 19.51 đpt | 0 |
| B | steady_z=1.25 | 2384 | 752 | 1632 | 31.54% | 0.617188 | 18.91 đpt | 4 |
| B | adverse_rate=0.2 | 1342 | 752 | 590 | 56.04% | 0.537215 | 20.03 đpt | 0 |
| B | adverse_rate=0.3 | 3590 | 752 | 2838 | 20.95% | 0.647340 | 19.33 đpt | 0 |
| B | gap_seconds=60 | 2194 | 703 | 1491 | 32.04% | 0.615044 | 19.06 đpt | 0 |
| B | gap_seconds=180 | 2413 | 771 | 1642 | 31.95% | 0.616826 | 18.64 đpt | 0 |

## Giới hạn

- G2 đạt không loại được shortcut độ dài: G4/G5 trượt trên cả hai chính sách, dù G6 đạt ở postloss20. Một scorer decile không bao quát mọi quan hệ phi tuyến hoặc đặc trưng tái dựng độ dài.
- G3 trượt: chỉ khoảng 35–39% quần thể postloss20 được gán nhãn, và phủ toàn TRAIN khoảng 9–10%. NOT nghĩa là đáp ứng quy tắc steady trong quần thể sau thua; hàng không nhãn không phải NOT. Tỉ lệ sự kiện đã chuẩn hóa theo số nước nhưng CPL/think và baseline cả ván vẫn có thể phụ thuộc độ dài, pha cờ và missingness.
- Đây là proxy dùng z/CPL, tốc độ và adverse_events, chưa có xác nhận cảm xúc độc lập; không đo precision/recall đối với giận dữ và không suy luận quan hệ nhân quả từ phân tầng kết quả/rating. The model predicts a behavioral proxy of tilt, not independently validated anger.
- A/B có thể trùng hàng TRAIN; không là hai mẫu xác nhận độc lập. Các ngưỡng cổng là tiêu chí quy ước đã duyệt, không là bằng chứng nhãn có giá trị tâm lý học. L2 không mở lại holdout; không khôi phục tính độc lập của test từng được xem ở các giai đoạn trước.
- Không chấp nhận thiết kế nào và không nối v2 vào pipeline/lila. Hướng weak-label dừng theo quy tắc đã khóa.

## Tệp, tái lập và kiểm tra

Mã mới `tilt/src/tilt/labels/postloss.py`, test `tilt/tests/unit/test_postloss.py` và báo cáo này. Trong `~/tilt-labels-v2/L2/`: `design_v2_L2.json`, `design_v2_L2.sha256`, `results.json`, `gates.csv`, `summary.csv`, `buckets.csv`, `current_result.csv`, `rating_band.csv`, `agreement_v1.csv`, `sensitivity.csv`; tất cả kết quả dữ liệu là aggregate. `results.json` ghi hash nguồn và phiên bản numpy/pandas/pyarrow/sklearn, quy trình loader, edges/rates/counts từng fold G6 và lý do fallback. `audit.log`, `audit_execution.json` ghi lệnh/thời gian/exit; `prepare_L2.py` chỉ tạo mới thiết kế, `write_report_L2.py` chỉ đọc aggregate, `run_full_tests.py` chạy suite. Không sửa artifact, báo cáo hoặc tệp L1 cũ.

Audit hoàn tất một lần, exit 0, 7.81 giây wall / 7.76 giây CPU, một thread BLAS/OMP; không có lệnh tính toán gần giới hạn 10 phút CPU. Không gọi mạng, thu dữ liệu, mở tilt/data hoặc salt/token. CLI từ chối ghi đè results.json; muốn tái lập phải dùng thư mục kết quả mới và giữ nguyên thiết kế/hash, không dùng tái lập để chọn tham số.

```bash
cd ~/lichess-workspace/tilt
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  PYTHONPATH="$PWD/src" .venv/bin/python -m tilt.labels.postloss \
  --aligned ~/tilt-phase1/aligned --out /tmp/postloss-L2-reproduction-new \
  --design ~/tilt-labels-v2/L2/design_v2_L2.json
```

**Toàn bộ suite: 277 passed**, exit 0, 54.68 giây wall; log `~/tilt-labels-v2/L2/full_test_suite.log`, tóm tắt máy đọc `test_verification.json`. Không skip test. 69 tệp cũ được đối chiếu SHA-256 trước/sau: 0 tệp đổi. Gồm 82 test postloss và 195 test đã có trước L2.

Tái sử dụng nguyên trạng runtime L1 `~/tilt-labels-v2/test_runtime/sitecustomize.py` để selector asyncio thức tối đa mỗi 20 ms trong sandbox chặn gửi self-pipe. Không sửa repo/venv để xử lý sandbox, không thay engine hay bỏ test. Các test mô hình hiện có chỉ dùng fixture tổng hợp; không huấn luyện/chấm mô hình dự đoán trên dữ liệu nguồn L2. Trong audit, scorer decile G6 là ngoại lệ duy nhất được fit.

```bash
cd ~/lichess-workspace/tilt
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime:$PWD/src \
  .venv/bin/python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=60
```

Nhánh giữ nguyên `private/ai-coach-tilt`; không commit, push hoặc đổi nhánh. Không sửa weak_labels.py, v1 pipeline, L1, báo cáo/artifact cũ hay nguồn dưới ~/tilt-phase*. Bản ghi hash bảo vệ nằm trong `protected_files_before.json` (không chứa dữ liệu ván/người).
