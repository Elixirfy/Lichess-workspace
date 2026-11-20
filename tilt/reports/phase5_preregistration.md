# Phase 5 — Đăng ký trước việc chọn mô hình cuối

Trạng thái: cố định TRƯỚC khi mở tập test. Ngày cố định: 2026-11-15, trước lần chạy đầu tiên có đọc test. sha256 của
file này ghi vào `~/tilt-phase5/prereg.sha256` trước lần chạy đó; code Phase 5 từ chối chạy nếu sha256 không khớp.

Mục 0–8 là quyết định của Fable 5.2 (theo cách làm người dùng đã giao), chép nguyên văn. Mục 9 là ghi chú cài đặt,
viết trước khi mở test.

Câu bắt buộc: "The model predicts a behavioral proxy of tilt, not independently validated anger."
Mọi số trong Phase 5 là khả năng dự đoán nhãn yếu (weak label), không phải phát hiện cơn giận.

## 0. Tình trạng tập test

- M1, M3, P3-B, các bản ablation và B-length chưa từng được chấm trên test.
- Test KHÔNG còn nguyên vẹn với pipeline cũ: Phase 0 đã chạy lại pipeline cũ và in số test
  (by_player xgboost lf_ablated ≈ E0: PR-AUC 0,509 [0,420; 0,613], ROC 0,767; by_time random_forest lf_ablated
  0,548; baseline: prior 0,140, losing_streak 0,246, result_only 0,183).
- Từ Phase 0 tới nay không quyết định nào dùng các số đó.
- Vì vậy số test của E0 và của B-prior/B-streak/B-result là "đã xem trước", được ghi rõ như vậy trong báo cáo.

## 1. Ứng viên

| Mã | Vai trò | Feature |
|---|---|---|
| P3-B | Ứng viên chính (cố định từ Phase 3) | M3 + attack_trend_3w, risk_volatility_3w, behavior_change_point (điền trung vị, không chỉ báo thiếu) |
| M3 | Ứng viên dự phòng | initial_seconds, increment_seconds, risk_rate, attack_rate, defensive_rate, style_switch_rate, rematch_streak_before, baseline_risk_rate_games |
| E0 | Tham chiếu, không được chọn | 16 feature cũ |
| M1 | Chẩn đoán (E0 − phase_middlegame_fraction) | 15 feature |
| P3-B-nometa, M3-nometa | Chẩn đoán phụ thuộc metadata | bỏ initial_seconds, increment_seconds |
| B-length, B-result, B-streak, B-prior, B-meta | Baseline chẩn đoán | như Phase 1 |

- Chỉ P3-B và M3 có thể được chấp nhận. Test không dùng để chọn giữa các ứng viên ngoài quy tắc ở mục 5.
- E0 không được chọn vì: (a) lối tắt nhãn đã biết (ván có nhãn với middlegame = 0 là 100% TILT); (b) test đã bị xem
  ở Phase 0.
- B-length, B-streak, B-result đọc đầu vào của LF hoặc kết quả ván, nên không triển khai được.
- Không chấm M2, L1.

## 2. Dữ liệu và fit

- Split, manifest (sha256 cố định ở Phase 1), LF, công thức nhãn yếu, 16 feature gốc: không đổi. Kiểm tra sha256
  manifest trước khi chạy; lệch thì dừng.
- Hai split: A = by_player (test 6.923 dòng, 36 người chơi, 2.002 dòng có nhãn, TILT 14,0%); B = by_time (test
  5.476 dòng, 1.711 có nhãn, TILT 15,0%).
- Fit: chỉ trên dòng TRAIN có nhãn, đúng cấu hình Phase 3 (XGBoost 100 cây, sâu 3, trọng số mẫu cân bằng, điền
  trung vị, chỉ báo thiếu trừ cột nhóm B, StandardScaler, cùng seed). Không refit trên train+validation.
- Hiệu chỉnh: Platt fit trên điểm thô của dòng VALIDATION có nhãn, cho từng mô hình và từng split.
- Ngưỡng: `choose_threshold` trên train+validation như Phase 1/3. Không dùng test.
- Hai bản nometa: fit cùng cách, chỉ bỏ 2 cột.
- Cổng trước khi mở test: code Phase 5 phải tái lập PR-AUC validation của Phase 3, sai lệch ≤ 0,001:
  P3-B 0,528 / 0,437; M3 0,449 / 0,370; E0 0,538 / 0,454. Không tái lập được thì dừng, không đọc test.
- Số validation của hai bản nometa được tính và ghi lại trước khi đọc test.

## 3. Quy trình test

1. Băm file này; kiểm tra manifest; chạy cổng tái lập validation.
2. Một lần chạy duy nhất chấm mọi mô hình ở mục 1 trên dòng test có nhãn của A và B, ghi vào
   `~/tilt-phase5/` (thư mục mới; không ghi đè kết quả Phase 0–4).
3. Chạy lại đúng lệnh đó lần thứ hai trong môi trường mới, chỉ để kiểm tra tái lập (tiêu chí 8). Không có lần
   chạy nào khác với seed hay cấu hình khác.
4. Áp quy tắc mục 5 một cách cơ học, viết `reports/final_model_comparison.md`.

Bootstrap: 1000 lần theo cụm người chơi, phân vị 95%, cùng seed Phase 3. Các hiệu Δ tính ghép cặp trên cùng mẫu
bootstrap.

## 4. Chỉ số

Chính: PR-AUC trên dòng test có nhãn, kèm CI (A và B).

Phụ, báo cáo cho mọi mô hình ở mục 1:
- lift = PR-AUC / tỉ lệ nền; ROC-AUC;
- PR-AUC trên ván ≥ 40 ply và tỉ lệ nền của nhóm đó;
- AUC tách ván < 40 ply với ván ≥ 40 ply của điểm số;
- sau Platt: Brier, Brier skill score so với dự đoán hằng bằng tỉ lệ nền train+validation, ECE (cùng hàm ECE đã
  dùng ở Phase 1/3), đường tin cậy;
- tại ngưỡng: precision, recall, F1, tỉ lệ bị gắn cờ;
- Δ ghép cặp kèm CI: ứng viên − từng baseline (B-prior, B-result, B-streak, B-meta, B-length); P3-B − M3;
  E0 − M1; ứng viên − bản nometa; mỗi Δ tính cả trên toàn bộ lẫn trên ván ≥ 40 ply;
- nhóm con (chỉ mô tả, không làm cổng): ván thua / không thua, ≥ 40 ply / < 40 ply, dải rating nếu bảng feature
  có cột rating (không có thì ghi "không có");
- độ quan trọng hoán vị (mức giảm PR-AUC, 20 lần lặp, seed cố định) trên validation và trên test, cùng gain của
  XGBoost.

## 5. Quy tắc chọn theo 8 tiêu chí

Áp cho P3-B trước. Một cổng trượt là trượt.

| # | Tiêu chí của plan | Kiểm tra cụ thể |
|---|---|---|
| 1 | Không có leakage đã biết | (a) Danh sách feature đúng như mục 1; không có số ply, kết quả ván, đầu vào LF, phase_middlegame_fraction, nhóm A, nhóm D. (b) Trên ván ≥ 40 ply: Δ(PR-AUC − tỉ lệ nền) có cận dưới CI > 0 ở A và Δ > 0 ở B. |
| 2 | Hơn baseline | So với từng baseline B-prior, B-result, B-streak, B-meta: ở A cận dưới CI của Δ PR-AUC > 0; ở B Δ > 0. Không yêu cầu hơn B-length. |
| 3 | Tổng quát hóa sang người chơi mới | PR-AUC test A ≥ 0,337 (= 0,75 × PR-AUC validation A của M3; sàn chung cho cả hai ứng viên). |
| 4 | Ổn định theo thời gian | PR-AUC test B ≥ 0,278 (= 0,75 × PR-AUC validation B của M3), và cổng 2 đạt ở B. |
| 5 | Không phụ thuộc quá mức metadata | PR-AUC test của bản nometa ≥ 0,75 × PR-AUC test của ứng viên, ở cả A và B. |
| 6 | Hiệu chỉnh chấp nhận được | Sau Platt: Brier skill score > 0 ở cả A và B; ECE ≤ 0,05 ở A và ≤ 0,08 ở B. |
| 7 | Giải thích được | (a) Mọi feature có định nghĩa trong feature registry. (b) Trong 3 feature quan trọng nhất theo hoán vị trên validation A, ít nhất 2 nằm trong top 5 trên test A. |
| 8 | Tái lập được | Hai lần chạy cho các chỉ số trùng nhau tới 1e-6; ghi sha256 của manifest, code, bảng chỉ số, artifact. |

Quy tắc quyết định:
1. P3-B qua đủ 8 cổng và Δ(P3-B − M3) PR-AUC test > 0 ở cả A và B → chọn P3-B.
2. Ngược lại xét M3 với đúng 8 cổng đó (cổng 5 dùng M3-nometa). M3 qua đủ → chọn M3.
3. Cả hai trượt → kết luận "không mô hình mới nào đạt tiêu chí". Giữ nguyên mô hình đang triển khai (pipeline cũ,
   tương đương E0), không coi đó là mô hình đạt tiêu chí, và nêu rõ cổng nào trượt.
4. Nếu E0 có PR-AUC test cao nhất: báo cáo đúng như vậy và giải thích bằng E0 − M1 cùng so sánh trên ván ≥ 40 ply.
   Việc này không làm E0 đủ điều kiện được chọn.
5. Ứng viên thua B-length không phải là trượt; ghi vào phần hạn chế.

## 6. Artifact

- Là đúng mô hình được chọn của split A (fit trên train, Platt trên validation, ngưỡng từ train+validation):
  mô hình đã được chấm trên test, không refit.
- Lưu ở thư mục mới `~/tilt-phase5/artifact/` (chỉ trong WSL): bundle `.joblib` (model, preprocessor, features,
  calibration, threshold), `features.json`, `metadata.json` (split, seed, sha256 manifest, sha256 code, sha256
  bundle, phiên bản thư viện).
- Không sửa `processed/models/selection.json`, không ghi đè bundle cũ, không đổi `score.py` hay module Tilt trong
  lila. Việc chuyển triển khai do người dùng quyết định sau. Bundle mới không có regressor, chưa kiểm tra tương
  thích với `score.py`.
- Không mô hình nào đạt thì không tạo artifact.

## 7. Nội dung báo cáo (`reports/final_model_comparison.md`)

- Bảng đủ mọi mô hình ở mục 1, cả A và B, validation cạnh test, mọi chỉ số ở mục 4; không bỏ dòng nào.
- Bảng 8 cổng: giá trị, ngưỡng, đạt/trượt, cho P3-B và M3.
- Kết luận theo quy tắc mục 5. Số test Phase 0 của E0 đặt cạnh số chạy lại, đánh dấu "đã xem trước".
- Danh sách feature, hướng dẫn tái lập (lệnh, seed, băm), và các hạn chế:
  - nhãn yếu, 0 nhãn người; 100% nhãn TILT có ván thua hiện tại hoặc ngay trước;
  - lối tắt độ dài (ván < 40 ply có nhãn là 100% TILT), B-length hơn mọi mô hình;
  - test chỉ có 36 người chơi nên CI rộng;
  - ngưỡng các cổng 3–7 là quy ước đặt trước, không suy ra từ dữ liệu;
  - test đã bị xem với pipeline cũ.
- Phân tích hậu nghiệm (nếu có) nằm ở mục riêng, tiêu đề "Hậu nghiệm".

## 8. Điều bị cấm sau khi mở test

- Đổi feature, siêu tham số, seed, cách điền thiếu, cách hiệu chỉnh, ngưỡng, số bin, chỉ số chính, hay ngưỡng các
  cổng.
- Fit hoặc hiệu chỉnh bất cứ thứ gì trên test; chọn ngưỡng trên test.
- Chạy lại với seed hoặc cấu hình khác để lấy số đẹp hơn; bỏ người chơi hoặc ván khỏi test.
- Thêm ứng viên mới; cho E0 hoặc baseline thành mô hình được chọn.
- Ghi đè kết quả Phase 0–4; đổi LF, công thức nhãn, split.
- Báo giả định như kết quả; gọi dự đoán nhãn yếu là phát hiện cơn giận hay tilt đã kiểm chứng.

Được phép, phải ghi nhãn "hậu nghiệm" và không đổi kết luận: phân tích lỗi, phân bố điểm theo số ply hoặc theo
người chơi, đường tin cậy chi tiết, bảng nhóm con bổ sung.

Lỗi cài đặt (không phải lựa chọn mô hình) phát hiện sau khi mở test: được sửa, nhưng phải mô tả lỗi, báo cả số cũ
lẫn số mới, và ghi "test mở lần 2".

## 9. Ghi chú cài đặt (viết trước khi mở test)

Code: `src/tilt/evaluation/phase5.py`. Các điểm mục 0–8 chưa nói rõ được cài như sau.

- **Cách fit.** P3-B, M3 và hai bản nometa dùng đúng ma trận của `phase3.design`. E0, M1 và B-length dùng
  `phase1.design` như Phase 1 (E0/M1 có chỉ báo thiếu, B-length không có). B-meta, B-streak, B-prior, B-result dùng
  `phase1.fit_predict`.
- **Cổng tái lập.** So với giá trị đầy đủ lưu trong `phase3_results.json` (P3-B, M3) và `phase1_results.json` (E0),
  không so với số đã làm tròn.
- **Thứ tự trong một lần chạy.** Fit mọi mô hình, chạy cổng tái lập, tính và ghi `validation.json` (gồm hai bản
  nometa) xuống đĩa. Chỉ sau đó code mới lấy chỉ số dòng test có nhãn. Cổng trượt thì dừng trước bước này.
- **Hiệu chỉnh và ngưỡng.** Platt dùng `train.calibrate` trên điểm thô của validation. Ngưỡng dùng `choose_threshold`
  trên điểm đã hiệu chỉnh của train và validation. Platt đồng biến, nên PR-AUC và ROC-AUC tính trên điểm thô cũng
  bằng trên điểm đã hiệu chỉnh.
- **F1** là F1 của lớp TILT. Tỉ lệ bị gắn cờ là tỉ lệ dòng test có nhãn có điểm đã hiệu chỉnh ≥ ngưỡng.
- **Brier skill score** = 1 − Brier(mô hình) / Brier(hằng bằng tỉ lệ TILT của train + validation có nhãn).
- **ECE** dùng `phase1.calibration_bins` (10 bin theo phân vị điểm).
- **Tách ván ngắn**: max(AUC, 1 − AUC) của điểm số khi phân biệt ván < 40 ply với ván ≥ 40 ply, như Phase 3.
- **Bootstrap.** Rút người chơi có hoàn lại, `default_rng(42)`, 1000 lần. Mẫu lại một lớp thì bỏ và đếm.
  - Cổng 1b: trong mỗi mẫu lại, lấy PR-AUC trên ván ≥ 40 ply trừ tỉ lệ TILT của ván ≥ 40 ply trong chính mẫu đó.
  - Ở B, "Δ > 0" là ước lượng điểm trên toàn bộ test B.
  - B-prior là điểm hằng, nên PR-AUC của nó bằng tỉ lệ nền.
- **Độ quan trọng hoán vị.**
  - Mỗi feature gốc (trước khi điền thiếu) được hoán vị giữa các dòng có nhãn của tập đánh giá, 20 lần,
    `default_rng(42)`. Độ quan trọng là mức giảm PR-AUC trung bình.
  - Cổng 7b so 3 feature đứng đầu trên validation A với 5 feature đứng đầu trên test A.
  - Gain của XGBoost được gộp về feature gốc (cột chỉ báo thiếu cộng vào feature của nó).
- **Cổng 7a.** Mỗi feature phải có dòng trong `reports/feature_registry.csv` hoặc `reports/phase2_feature_registry.csv`.
- **Cổng 1a.** Danh sách feature phải đúng bằng mục 1. Không feature nào là `lf_input__*`, `result_score`,
  `phase_middlegame_fraction`, cột `*_p40` hay cột nhóm A (`behavior.DEVIATIONS`), và không feature nào bị
  `model_features.forbidden` chặn.
- **Cổng 8 và quyết định.** Lần chạy 1 ghi quyết định với cổng 8 = "chờ". Lần chạy 2 dùng phiên Colab mới, cùng lệnh.
  Lệnh `compare` so mọi số trong hai file kết quả (sai lệch tuyệt đối ≤ 1e-6) và so dự đoán test của artifact, rồi
  mới chốt cổng 8 và quyết định cuối.
- **Nhóm con theo rating** dùng cột `rating` với các dải của Phase 4: < 1200, 1200–1599, 1600–1999, ≥ 2000.
