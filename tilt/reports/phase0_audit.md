# Phase 0: Kiểm tra pipeline phát hiện tilt

Ngày 2026-11-14. Chỉ đọc code, không sửa pipeline, không huấn luyện lại.

Phạm vi kiểm tra:

- Code: `tilt/src/tilt/labels/weak_labels.py`, `features/model_features.py`, `features/features.py`,
  `core/train.py`, `data/dataset.py`, `evaluation/evaluate.py`.
- Dữ liệu: kết quả nhãn yếu phiên bản 2.6 (`WEAK_VERSION = 3`) trên Colab, gồm
  `out/weak_by_player.parquet`, `out/weak_by_time.parquet`, `models/manifest.json` và `out/weak_metrics.json`.

Tệp đi kèm:

- `feature_registry.csv`: 145 cột cấp ván.
- `leakage_analysis.md`: phân tích rò rỉ chi tiết.

Mọi con số dưới đây đo trên dữ liệu thật. Không có số nào là giả định.

> Nhãn ở đây là **nhãn yếu** do 10 labeling function (LF) sinh ra. Dự đoán của mô hình là dự đoán nhãn yếu đó,
> **không phải** phát hiện "tức giận/tilt" đã được kiểm chứng bằng nhãn người.

## 1. Tóm tắt

| Hạng mục | Kết quả |
|---|---|
| Quy mô dữ liệu | 36.401 dòng (người chơi × ván), 36.287 ván, 196 người chơi, **100% blitz** |
| Độ phủ nhãn | 10.476 dòng có nhãn (28,8%); tỉ lệ TILT 14,7% |
| Outcome gate (train) | **FAILED** ở cả hai cách chia. Tỉ lệ TILT ở ván không thua là 6,9% (by_player) và 6,4% (by_time), dưới ngưỡng 10% |
| Baseline 16 feature | `by_player__lf_ablated__xgboost`. Lần chạy lại (xgboost 2.1.4): test PR-AUC 0,509 [0,420; 0,613], ROC-AUC 0,767. Lần 1 (xgboost 3.4.1): 0,521 / 0,771 |
| Mô hình được chọn theo validation | Lần chạy lại chọn `by_player__full__xgboost` (18 feature = 16 + `history_games`, `baseline_speed_games`), test PR-AUC 0,509; `by_time__lf_ablated__random_forest`, test PR-AUC 0,548 |
| Baseline chẩn đoán (test) | class prior 0,140; losing_streak 0,246; result_only 0,183 |
| Tính toàn vẹn của split | Sạch: không trùng dòng, không lẫn người chơi hay ván giữa các tập, purge đúng (chi tiết ở mục 4) |
| Rủi ro lớn nhất | Feature quan trọng nhất `phase_middlegame_fraction` là proxy **phi tuyến** của độ dài ván, mà độ dài ván là input trực tiếp của LF. Audit Spearman không bắt được loại quan hệ này |
| Hạn chế lớn nhất | 13 feature lịch sử bị loại chỉ vì chỉ báo "thiếu lịch sử" trùng với chỉ báo thiếu của input LF (|rho| = 1,0). Bản thân giá trị của chúng có |rho| ≤ 0,56 |

Lần chạy lại trên Colab với xgboost 2.1.4 đã xong. Kết quả đã kiểm tra:

- Features giống hệt từng byte với bản cũ (md5 `moves.parquet` và `games.parquet` trùng).
- Nhãn yếu (`weak_tilt_prob`, `weak_tilt_label`, `split`) và cả hai audit giống hệt lần 1.
- Gate vẫn FAILED (0,0689 / 0,0639).
- PR-AUC trên test chênh không quá 0,012, nằm trong khoảng tin cậy.
- Permutation importance vẫn đứng đầu là `phase_middlegame_fraction` (0,231). Tiếp theo là `attack_rate` 0,074 và
  `defensive_rate` 0,061.

Như vậy lần chạy lại **không cải thiện gì**. Điều này đúng với dự đoán, vì outcome gate chỉ phụ thuộc vào nhãn.

## 2. Cách nhãn yếu được tạo (câu hỏi 1)

### 2.1 Mười LF

Mỗi LF bỏ phiếu TILT (1), NOT_TILT (0) hoặc bỏ qua (−1).

| LF | Phiếu | Điều kiện, tóm tắt từ `vote()` | Số phiếu |
|---|---|---|---:|
| `abandon` | TILT | thua, `status == 'timeout'`, thế cờ còn chơi được (không bị chiếu hết, `final_eval_cp > −150`, `last_adverse_distance ≤ 6`) | 101 |
| `early_resign` | TILT | thua bằng xin thua, `plies ≤ 60`, `final_eval_cp > −150`, `last_adverse_distance ≤ 6` | 274 |
| `carryover` | TILT | ván trước trong cùng phiên thua, nghỉ 0–60 s, `deviation_mean_cpl_z ≥ 1.5` | 1.132 |
| `session_spiral` | TILT | `prior_session_loss_run ≥ 3`, khoảng nghỉ co dần, z ≥ 1.5 | 38 |
| `fast_erratic_after_loss` | TILT | vừa thua, nghỉ ≤ 120 s, `mean_think ≤ 0.65 × baseline`, z ≥ 1 | 222 |
| `normal_accuracy` | NOT | ván "có trật tự" (≥ 40 nửa nước, kết thúc bình thường), accuracy ≥ baseline, \|z\| ≤ 1 | 8.007 |
| `rest_and_recover` | NOT | ván có trật tự, ván **sau** cách 300–1800 s và có \|next_z\| ≤ 1 | 1.239 |
| `calm_play` | NOT | ván có trật tự, accuracy bình thường, `adverse_events == 0` | **0** |
| `composed_loss` | NOT | xin thua, ≥ 80 nửa nước, thua rõ, nghỉ rồi chơi bình thường | 92 |
| `expected_loss` | NOT | ván có trật tự, thua, `rating_difference ≤ −200`, accuracy ≥ baseline − 5 | 387 |

### 2.2 Gộp phiếu

- Dùng Dawid–Skene đối xứng. Prior cố định 0,5, độ chính xác của mỗi LF có tiên nghiệm Beta(6,2) và bị chặn trong
  (0,5; 1). Mô hình chỉ fit trên dòng train.
- `weak_tilt_label = weak_tilt_prob ≥ 0.5`.
- Dòng không có phiếu nào thì không có nhãn.

### 2.3 Thực tế đo được (by_player, cả 36.401 dòng)

- 9.532 trong 10.476 dòng có nhãn (91%) chỉ có đúng **một** phiếu. Chỉ 27 dòng có phiếu mâu thuẫn.
- 99,74% nhãn trùng với quy tắc "có ít nhất một phiếu TILT". Như vậy label model gần như chỉ là phép OR của các LF
  TILT. Xác suất nhãn chỉ có 27 giá trị khác nhau.
- `calm_play` không bao giờ bỏ phiếu. Có 29.447 ván dài từ 40 nửa nước, nhưng không ván nào có `adverse_events == 0`
  (trung vị 11 sự kiện bất lợi mỗi ván).
- Nhãn NOT chủ yếu đến từ `normal_accuracy` (8.007/8.910). Nhãn TILT chủ yếu đến từ `carryover`.
- Theo trạng thái kết thúc, tỉ lệ TILT là:
  - `timeout`: 100% (120 dòng);
  - `resign`: 28,2%;
  - `mate`: 10,5%;
  - `outoftime`: 6,3%;
  - `draw`: 3,4%.
- Ở ván không thua, phiếu TILT chỉ có thể đến từ `carryover` (265), `fast_erratic_after_loss` (37) và
  `session_spiral` (9). Gate đòi tỉ lệ TILT ≥ 10% trong nhóm không thua mới đạt, mà với các LF hiện tại thì nhóm này
  không thể có đủ phiếu TILT. Muốn sửa thì phải đổi thiết kế LF. Việc đó nằm ngoài Phase 0 và cần người dùng duyệt.

## 3. Feature: số lượng, nguồn, lý do loại (câu hỏi 2, 4)

### 3.1 Input trực tiếp của LF (câu hỏi 2)

Lấy từ `LF.inputs` trong `weak_labels.py`. Đây là cột mà hàm `vote()` đọc.

| Nhóm | Cột |
|---|---|
| Kết cục ván | `status`, `result_score`, `plies` |
| Engine | `final_eval_cp`, `final_eval_mate`, `last_adverse_distance`, `adverse_event`, `adverse_events`, `eval_after_cp`, `eval_after_mate`, `ply` |
| Độ chính xác | `mean_accuracy`, `baseline_mean_accuracy_median`, `deviation_mean_cpl_z` |
| Thời gian nghĩ | `mean_think`, `baseline_mean_think_median` |
| Rating | `rating`, `opponent_rating`, `rating_difference` |
| Thời điểm, phiên | `start_ms`, `end_upper_ms`, `rest_gap_seconds`, `prior_session_loss_run`, `session_shrinking_gaps` |
| Ván trước (quá khứ) | `previous_result_score`, `previous_end_upper_ms`, `previous_same_session` |
| Ván sau (**tương lai**, chỉ dùng cho nhãn) | `next_start_ms`, `next_end_upper_ms`, `next_deviation_mean_cpl_z` |

Các giá trị tổng hợp mà audit dùng được lưu với tiền tố `lf_input__`. Có 44 cột như vậy, gồm thêm
`ply__min/max/mean`, `session_gap_0..2`, `move_count`, và `previous_`/`next_rest_gap_seconds`.

Đã kiểm tra: không có cột `next_*` nào nằm ngoài nhóm `lf_input__`, nên mô hình không đọc được thông tin tương lai.

### 3.2 Vì sao chỉ còn 16 feature (câu hỏi 4)

Các bước lọc, theo `model_features.feature_list`:

1. **Danh sách ứng viên:** 34 cột `RAW_FEATURES`, cộng mọi cột `baseline_*`, `deviation_*`, `historical_*`, cộng
   `behavioral_deviation_score_safe`.
2. **`forbidden()` loại theo token.** Bị loại:
   - mọi cột chứa `cpl`, `accuracy`, `error`, `blunder`, `adverse`, `eval`, `material`... (`QUALITY`);
   - mọi cột chứa `think`, `rating` hoặc `clock_fraction`;
   - `rest_gap`, `CURRENT_RELATIVES` (`losing_streak_before`, `recent_form`, ...), `sacrifice_rate`,
     `phase_speed_change`, `*_ms`.

   Còn lại **37 ứng viên**. Các nhóm baseline/deviation chỉ còn ba nhánh `risk_rate`, `attack_rate`,
   `style_switch_rate`. Sáu nhánh khác bị loại vì tên chứa token cấm: cpl, think, accuracy, error, blunder,
   post_event và rest_gap.
3. **Biến thể `lf_ablated` (strict)** bỏ thêm `history_games`, `baseline_speed_games` và
   `games_in_session_before`.
4. **Outcome audit:** max(AUC, 1−AUC) > 0,70 với kết cục thua hoặc hết giờ. Không loại cột nào; cao nhất là
   `phase_opening_fraction` với 0,68.
5. **LF-provenance audit:** |Spearman| ≥ 0,6 với bất kỳ đại lượng LF nào, xét ở 3 dạng: giá trị quan sát, giá trị
   đã điền trung vị, chỉ báo thiếu. Loại **19** cột:
   - 13 feature lịch sử, đều do chỉ báo thiếu trùng `baseline_mean_accuracy_median__missing` (|rho| = 1,0). Chỉ báo
     này giống hệt `deviation_mean_cpl_z__missing`: cả hai đều có nghĩa là "chưa đủ `min_prior_games = 5` ván trước";
   - `style_drift_in_session`: 1,0, chỉ báo thiếu trùng `session_gap_1__missing`;
   - `phase_opening_fraction`: 0,90 với `ply__mean`;
   - `clock_missing_fraction`: 0,89 với `mean_think__missing`;
   - `games_in_session_before`: 0,85;
   - `phase_endgame_fraction`: 0,85 với `ply__max`;
   - `rematch`: 0,80 với `opponent_rating__missing`.

Kết quả là **16 feature**:

- `initial_seconds`, `increment_seconds`;
- `speed_blitz`, `speed_bullet`, `speed_rapid`, `speed_classical`, `speed_correspondence`. Đây là đúng 5 cột one-hot
  sinh trong `prepare()`: `frame['speed_' + speed]` với speed thuộc `('blitz', 'bullet', 'rapid', 'classical', 'correspondence')`;
- `risk_rate`, `attack_rate`, `defensive_rate`, `style_switch_rate`;
- `phase_middlegame_fraction`, `rematch_streak_before`;
- `baseline_risk_rate_games`, `baseline_attack_rate_games`, `baseline_style_switch_rate_games`.

Số feature thật sự mang thông tin ít hơn 16:

- Bộ dữ liệu 100% blitz, nên **5 cột `speed_*` là hằng số**. Permutation importance của chúng đúng bằng 0.
- 3 cột `baseline_*_games` gần như trùng `history_games` (Spearman 0,998). Biến thể strict loại `history_games` vì
  "lịch sử", nhưng lại giữ ba bản gần như trùng này. Quy tắc strict đang không nhất quán.
- Permutation importance trên test:
  - `phase_middlegame_fraction` làm PR-AUC giảm 0,269;
  - `attack_rate` 0,064, `defensive_rate` 0,044, `risk_rate` 0,018;
  - mọi cột còn lại dưới 0,01.

Như vậy mô hình thực chất có khoảng 9 tín hiệu độc lập, và một tín hiệu chiếm phần lớn.

## 4. Kiểm tra toàn vẹn dữ liệu và split (câu hỏi 6)

Số liệu từ script chỉ đọc, chạy trên `weak_by_player` và `weak_by_time`.

| Kiểm tra | by_player | by_time |
|---|---|---|
| Dòng / ván / người chơi | 36.401 / 36.287 / 196 | giống bên trái |
| Trùng (player, game) hoặc (game, color) | 0 | 0 |
| Ván có cả hai màu trong dữ liệu | 114 | 114 |
| Chia split | train 22.316, val 6.697, test 6.923, purge 465 (ván chung hai người) | train 25.403, val 5.431, test 5.476, purge 91 (ván vắt qua mốc cắt) |
| Một ván nằm ở nhiều split | 0 | 0 |
| Một người chơi nằm ở nhiều split | 0 | 158 (đúng thiết kế chia theo thời gian) |
| `label_end_upper_ms` của train ≥ lúc bắt đầu val, hoặc của val ≥ lúc bắt đầu test | (không áp dụng) | 0 / 0 |
| `baseline_latest_end_ms ≥ start_ms` (lịch sử nhìn trước tương lai) | 0 trên 36.205 dòng | 0 |
| `end_upper_ms < start_ms` | 0 | 0 |
| `games_in_session_before` khác số ván trước đó trong cùng phiên | 0 | 0 |
| Cột `next_*` lọt ra ngoài nhóm `lf_input__` | không có | không có |
| Nhãn theo split (n, tỉ lệ TILT) | train 6.428 (15,1%), val 1.922 (13,7%), test 2.002 (14,0%) | train 7.200 (14,9%), val 1.549 (13,7%), test 1.711 (15,0%) |

Quy trình:

- Label model, outcome audit, LF audit và giá trị trung vị để điền dữ liệu thiếu đều chỉ tính trên train.
- Calibration (Platt) và ngưỡng F1 lấy trên validation. Mô hình được chọn theo PR-AUC trên validation.
- Test chỉ dùng để báo cáo, có bootstrap theo cụm người chơi.

Không thấy rò rỉ do cách chia split hay do dữ liệu hỏng. Có bốn điểm yếu, đều không phải rò rỉ split:

1. Test của by_player chỉ có 36 cụm người chơi, nên khoảng tin cậy PR-AUC rộng (0,43–0,62).
2. Ở by_time, PR-AUC trên test (0,55–0,57) cao hơn trên validation (0,46–0,48). Khác biệt nằm trong khoảng tin cậy,
   nhưng nên ghi lại.
3. 71% số dòng không có nhãn. Tập có nhãn nghiêng về ván dài có trật tự (nhãn NOT) và ván thua kết thúc đột ngột
   hoặc thua liên tiếp (nhãn TILT).
4. Quy tắc strict không nhất quán (mục 3.2).

## 5. Tương quan và rò rỉ (câu hỏi 3, 5)

Xem chi tiết ở `leakage_analysis.md`. Tóm tắt:

**Tương quan nhưng không phải rò rỉ (câu hỏi 3):**

- `attack_rate`, `defensive_rate`, `risk_rate`: AUC 0,60–0,67 với kết cục thua. Đây là hành vi trên bàn cờ (người
  đang thua thì phòng thủ nhiều hơn), không đọc từ đánh giá của engine.
- `initial_seconds`/`increment_seconds`: rho 0,53–0,54 với rating và think baseline. Đây là quan hệ dân số học:
  người rating cao chọn thể thức khác.
- `baseline_*_games`: rho 0,35 với `start_ms`, vì lịch sử tích lũy theo thời gian.

**Có thể khôi phục, nhưng phải thử bằng ablation ở Phase 1 (câu hỏi 5).** Có 15 cột được đánh dấu `review` trong
registry:

- 13 feature lịch sử:
  - `baseline_{risk,attack,style_switch}_rate_{median,mad}`;
  - `deviation_{risk,attack,style_switch}_rate_z`;
  - `historical_{risk,attack,style_switch}_rate_similar_fraction`;
  - `behavioral_deviation_score_safe`.
- `rematch` và `clock_missing_fraction`.

**Không nên khôi phục:**

- `phase_opening_fraction` và `phase_endgame_fraction`: tương quan 0,90 và 0,85 với độ dài ván.
- `games_in_session_before`: 0,76 với `session_gap_0` ngay cả khi chỉ xét giá trị.
- `style_drift_in_session`: chỉ báo thiếu của nó chính là "ván đầu phiên", tức input LF `previous_same_session`.
  1.220 dòng train có nhãn bị ảnh hưởng.
- Nhóm QUALITY/think/rating: input LF trực tiếp hoặc dùng chung đánh giá engine.

**Cần xem lại một feature đang được dùng:** `phase_middlegame_fraction` (mục 6).

## 6. Nên đổi gì trước (câu hỏi 7)

Đây là đề xuất cho Phase 1. **Chưa làm gì**, chờ phê duyệt. Không đổi công thức nhãn và không đổi baseline 16 feature.

1. **Định lượng rủi ro của `phase_middlegame_fraction` trước khi tin bất kỳ con số nào.**
   - Ba cột phase fraction cộng lại đúng bằng 1 (sai số 1e-16). Vì vậy middlegame = 1 − opening − endgame, mà hai cột
     kia đã bị audit loại.
   - Spearman của middlegame với độ dài ván xấp xỉ 0 (−0,05), nhưng quan hệ có hình chữ U. Ở nhóm decile thấp nhất
     (middlegame = 0), trung vị chỉ 21 nửa nước và 77% ván ≤ 60 nửa nước, đúng ngưỡng của `early_resign`.
     Correlation ratio η² = 0,17.
   - Đây là feature có permutation importance lớn nhất, 0,27.
   - Đề xuất: chạy ablation bỏ cột này, đánh giá trên validation. Đồng thời bổ sung vào audit một phép đo phi tuyến,
     ví dụ η² theo decile hoặc mutual information, chỉ để ghi nhận.
2. **Tách kênh "thiếu lịch sử" khỏi audit nguồn gốc nhãn.**
   - 13 feature lịch sử bị loại vì chỉ báo thiếu của chúng trùng chỉ báo thiếu của input LF. Cả hai đều chỉ là
     "chưa đủ 5 ván trước".
   - Chỉ 5 dòng train có nhãn rơi vào nhóm này, nên kênh này mang rất ít thông tin về nhãn.
   - Đề xuất: audit riêng giá trị quan sát/đã điền và chỉ báo thiếu. Với chỉ báo thiếu, đo theo nhãn trên dòng có nhãn.
     Sau đó chạy ablation thêm 13 feature, có và không có `add_indicator`.
3. **Dọn feature vô nghĩa** trong một biến thể chẩn đoán, không thay baseline: bỏ 5 cột `speed_*` hằng số và
   3 cột `*_games` trùng nhau.
4. **Ghi rõ giới hạn của gate.**
   - Tỉ lệ TILT ở ván không thua (6,4–6,9%) do thiết kế LF quyết định: ở nhóm này chỉ 3 LF có thể bỏ phiếu TILT, và
     `calm_play` chết hẳn.
   - Đổi feature hay mô hình đều không làm gate đạt. Muốn đạt thì phải đổi LF, và việc đó cần người dùng quyết định
     riêng.

Thứ tự đề xuất: 1, rồi 2, rồi 3. Mục 1 có thể làm giảm điểm hiện tại. Mục 2 là hướng có khả năng cải thiện điểm mà
không phạm quy tắc.

## 7. Cách tái lập

Các script chỉ đọc (lưu ngoài repo, trong scratchpad của phiên làm việc):

- `p0_integrity.py`: kiểm tra toàn vẹn dữ liệu và split.
- `p0_lfaudit.py`: chạy lại LF audit, tách theo từng dạng biểu diễn.
- `p0_labels.py`: thành phần nhãn.
- `p0_registry.py`: sinh `feature_registry.csv`.
- Lệnh kiểm tra phase fraction được ghi trong `leakage_analysis.md`.

Không ghi đè kết quả cũ. Bản sao lưu nằm ở `~/tilt-backup-20261114-1733` và `~/tilt-colab/results-xgb341`.
