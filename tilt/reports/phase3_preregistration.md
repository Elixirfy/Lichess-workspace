# Phase 3: đăng ký trước biến thể và quy tắc chọn

Viết xong trước khi chạy bất kỳ mô hình nào của Phase 3 trên validation. Sau khi chạy không đổi danh sách biến thể
hay quy tắc; nếu buộc phải đổi thì ghi ở mục "Thay đổi sau đăng ký" của `phase3_evaluation.md`.

> Nhãn là nhãn yếu từ 10 LF. Mô hình dự đoán nhãn yếu, không phát hiện tức giận. Không đổi LF hay công thức nhãn.

Các mục 1–5 do Fable 5.2 quyết định ngày 2026-11-14 và được chép nguyên văn. Người dùng duyệt Phase 3 cùng ngày. Mục
6 là ghi chú triển khai, viết trước khi chạy.

## 1. Quyết định về feature (từ Phase 2)

- Nhóm A (8 feature `*_delta_personal`, `*_z_personal`): LOẠI. Lý do: chỉ báo thiếu trùng chỉ báo thiếu của input
  LF (audit cơ học, fail closed); 3 feature z trùng tuyệt đối `deviation_*_rate_z` đã thử ở M2 Phase 1 và không
  nhận; còn lại trùng tỉ lệ thô của M3 (Spearman 0,90–0,95). Phần giá trị qua audit (|ρ| ≤ 0,46).
- `style_entropy`, `behavior_persistence`: LOẠI (fail closed, chỉ báo thiếu |ρ| 0,624 / 0,660 ở by_player).
- Nhóm B còn lại (`attack_trend_3w`, `risk_volatility_3w`, `behavior_change_point`): dùng, điền trung vị của
  train, KHÔNG `add_indicator` cho 3 cột này. Lý do: thiếu ⇔ ván dưới khoảng 9 nước ⇒ 100% TILT.
- Nhóm D (`attack_rate_p40`, `risk_rate_p40`, `defensive_rate_p40`, `style_switch_rate_p40`): dùng, không thiếu.
- 8 feature của M3 giữ tiền xử lý như Phase 1 (`SimpleImputer(median, add_indicator=True)`).

## 2. Biến thể

XGBoost, siêu tham số như Phase 1: 100 cây, `max_depth=3`, `learning_rate=0.06`, `subsample=0.85`,
`colsample_bytree=0.85`, `reg_lambda=3`, seed 42, `sample_weight='balanced'`. Không tune. Thứ tự cột: thứ tự của M3,
rồi feature mới theo đúng thứ tự liệt kê dưới đây.

M3 = `initial_seconds`, `increment_seconds`, `risk_rate`, `attack_rate`, `defensive_rate`, `style_switch_rate`,
`rematch_streak_before`, `baseline_risk_rate_games`.

| ID | Feature | Số cột | Vai trò |
|---|---|---|---|
| M3 | M3 (chạy lại) | 8 | mốc so sánh |
| P3-D | M3 + `attack_rate_p40`, `risk_rate_p40`, `defensive_rate_p40`, `style_switch_rate_p40` | 12 | thêm tiền tố |
| P3-R | M3, thay `risk_rate`, `attack_rate`, `defensive_rate`, `style_switch_rate` bằng 4 cột `*_p40` tương ứng | 8 | thay tiền tố |
| P3-B | M3 + `attack_trend_3w`, `risk_volatility_3w`, `behavior_change_point` | 11 | động lực trong ván |
| P3-DB | M3 + 4 cột D + 3 cột B | 15 | kết hợp |
| B-length | XGBoost chỉ trên `lf_input__plies` (chạy lại) | 1 | chẩn đoán, không triển khai |

Kiểm tra trước khi đọc kết quả khác: M3 chạy lại phải cho PR-AUC validation trong khoảng ±0,005 của 0,449 (A) và
0,370 (B). Nếu lệch thì dừng và báo, không so sánh tiếp.

## 3. Metric

Tính trên validation, cho split A (by_player) và B (by_time). Test niêm phong tới Phase 5.

- Chính: PR-AUC trên mọi dòng có nhãn.
- Phụ: PR-AUC trên dòng có nhãn của ván ≥ 40 nửa nước, kèm tỉ lệ lớp của nhóm.
- Khoảng tin cậy 95%: bootstrap theo cụm người chơi, 1.000 lần, seed 42. Chênh lệch giữa hai mô hình tính ghép
  cặp trên cùng mẫu bootstrap. Với chỉ số phụ: lấy mẫu người chơi trước, lọc ≥ 40 nửa nước sau; bỏ lần lặp không
  có dòng dương và ghi số lần bị bỏ.
- Ghi nhận, không dùng để chọn: ROC-AUC, Brier, ECE, nhóm ván thua / không thua, η² so với độ dài.

## 4. Quy tắc quyết định

Ký hiệu Δ = PR-AUC(biến thể) − PR-AUC(M3), ước lượng điểm trên validation; CI là khoảng ghép cặp 95%.

1. Nhận biến thể thêm feature (P3-D, P3-B, P3-DB) khi đủ cả ba:
   a. Δ chính ở A ≥ +0,05 và cận dưới CI ghép cặp ở A > 0;
   b. Δ chính ở B > 0;
   c. Δ phụ (≥ 40 nửa nước) > 0 ở cả A và B.
   Đạt a và b nhưng trượt c: ghi "tăng nhờ ván ngắn", KHÔNG nhận.
2. P3-R (thay): dùng P3-R làm mô hình chính thay M3 khi Δ chính > −0,05 ở cả A và B, và CI ghép cặp của Δ phụ
   không nằm hoàn toàn dưới 0 ở split nào. Nếu không, giữ M3 và báo P3-R như mốc "ít phụ thuộc độ dài". Ghi rõ:
   với ván dưới 40 nửa nước, p40 bằng tỉ lệ cả ván, nên P3-R không khử hết đường tắt độ dài.
3. Nếu nhiều biến thể ở mục 1 được nhận: chọn biến thể có PR-AUC chính ở A cao nhất; nếu một biến thể được nhận
   khác ít cột hơn và kém nó dưới 0,05 ở A thì chọn biến thể ít cột hơn.
4. Chỉ số phụ không tự nâng hạng: Δ phụ có CI > 0 ở cả hai split nhưng không đạt mục 1a thì ghi "tín hiệu ở ván
   ≥ 40 nửa nước, chưa đủ để nhận", không đổi mô hình chính.
5. Không biến thể nào được nhận: mô hình chính vẫn là M3 (hoặc P3-R theo mục 2). Đây là kết quả hợp lệ.
6. Mọi kết luận ghi kèm CI. CI ghép cặp chứa 0 thì ghi "không phân biệt được".
7. Không chọn ngưỡng, siêu tham số hay feature trên test. Không chọn mô hình cuối ở Phase 3; việc đó để Phase 5.

## 5. Không làm trong Phase 3

- Không đổi LF, công thức nhãn, split hay siêu tham số. Không ghi đè kết quả Phase 1.
- Không đưa nhóm A, `style_entropy`, `behavior_persistence` vào mô hình nào.
- Không thêm biến thể sau khi đã thấy kết quả validation.
- Huấn luyện chạy trên Colab.

## 6. Ghi chú triển khai (viết trước khi chạy, không đổi quy tắc)

- Code: `src/tilt/evaluation/phase3.py`. Hàm metric, chọn ngưỡng và bootstrap dùng lại từ `phase1.py`.
- Dữ liệu: các bảng aligned của Phase 1 (`~/tilt-phase1/aligned`), nối trái với 7 feature dùng được từ
  `~/tilt-phase2/behavior_features.parquet` theo (`player_id`, `game_id`). Kiểm tra split của Phase 1 chạy lại
  trên bảng đã nối. Mã băm manifest phải trùng mã băm của Phase 1.
- Tiền xử lý: một `SimpleImputer(median, add_indicator=True, keep_empty_features=True)` fit trên dòng train có nhãn,
  rồi `StandardScaler`, giống Phase 1. Ma trận đầu vào là giá trị các cột theo thứ tự ở mục 2, rồi tới chỉ báo thiếu.
  Chỉ báo thiếu của 3 cột nhóm B bị bỏ. Với riêng M3, cách này cho đúng ma trận của Phase 1. P3-R giữ vị trí cột:
  mỗi cột `*_p40` đứng đúng chỗ của tỉ lệ cả ván mà nó thay.
- Ngưỡng phân loại (chỉ để báo precision/recall) chọn như Phase 1 bằng `choose_threshold`, trên validation.
- Chỉ số phụ: lọc `lf_input__plies ≥ 40`. Một lần bootstrap bị bỏ khi nhóm ≥ 40 nửa nước của mẫu đó chỉ có một lớp.
- Thứ tự áp dụng quy tắc:
  - Nếu kiểm tra tái lập M3 trượt thì không áp dụng quy tắc nào.
  - Nếu có biến thể được nhận theo mục 1 thì mô hình chính là biến thể chọn theo mục 3.
  - Nếu không có thì mô hình chính là P3-R khi P3-R đạt mục 2, còn lại là M3.
  - Mục 3, khi có nhiều biến thể được nhận: chọn biến thể ít cột nhất trong các biến thể kém biến thể tốt nhất dưới
    0,05 ở A. Nếu số cột bằng nhau thì lấy PR-AUC ở A cao hơn.
- η² so với độ dài: η² của điểm validation của từng mô hình theo thập phân vị điểm, so với `lf_input__plies`.
- Môi trường: Colab, xgboost 2.1.4, scikit-learn 1.6.1 (giống Phase 1). 1.000 lần bootstrap.
