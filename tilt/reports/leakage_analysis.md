# Phân tích rò rỉ nhãn (Phase 0)

Ngày 2026-11-14. Chỉ đọc. Dữ liệu là nhãn yếu phiên bản 2.6, chia by_player, chỉ tính trên dòng train (22.316 dòng,
trong đó 6.428 dòng có nhãn), trừ khi ghi khác.

Tương quan với nhãn hoặc với input LF **không** tự động là bằng chứng rò rỉ. Tài liệu này phân loại theo cơ chế:

- **direct:** feature là input LF, hoặc tính từ cùng dữ liệu nguồn.
- **structural:** feature là hàm số, kể cả phi tuyến, của một input LF.
- **coverage:** chỉ báo thiếu dữ liệu của feature quyết định LF nào được bỏ phiếu.
- **benign:** quan hệ có nghĩa về mặt hành vi hoặc dân số học.

## 1. Rò rỉ trực tiếp: đã bị chặn

`forbidden()` chặn những cột sau, và `assert_no_lf_inputs()` kiểm tra lại lúc train:

- mọi input LF (`ALL_LF_COLUMNS`);
- mọi cột chứa token QUALITY: cpl, accuracy, wc_loss, error, mistake, blunder, adverse, eval, advantage, recovery,
  unsound, realized_sacrifice, post_event, material, best_second, differs_from_best;
- mọi cột chứa `think`, `rating` hoặc `clock_fraction`;
- `rest_gap*`, `immediate_after_loss`, `CURRENT_RELATIVES`, `sacrifice_rate`, `phase_speed_change`, `*_ms`,
  `deviation_feature_count`, `behavioral_deviation_score`.

Đã kiểm tra trên dữ liệu:

- Không có cột `next_*` (thông tin ván sau) nào nằm ngoài nhóm `lf_input__`.
- `baseline_latest_end_ms < start_ms` đúng trên toàn bộ 36.205 dòng có lịch sử, nên baseline không nhìn thấy ván hiện
  tại hay ván tương lai.
- Có 145 cột cấp ván, trong đó 93 cột có rủi ro `high` (xem `feature_registry.csv`). 92 cột đã bị loại. Cột còn lại
  là `phase_middlegame_fraction` (mục 3).

## 2. Kết quả chạy lại LF audit, tách theo dạng biểu diễn

Audit gốc lấy |Spearman| lớn nhất trên mọi cặp (dạng biểu diễn × đại lượng LF). Bảng dưới tách ra ba trường hợp:

- `observed/imputed`: chỉ xét giá trị của feature.
- `missing vs all`: chỉ báo thiếu của feature so với mọi đại lượng LF, kể cả chỉ báo thiếu của chúng (đúng cách audit
  gốc làm).
- `missing vs values`: chỉ báo thiếu của feature so với giá trị của đại lượng LF.

| Feature | observed/imputed max \|rho\| | missing vs all | missing vs values | Dòng train có nhãn bị thiếu | Kết luận |
|---|---:|---:|---:|---:|---|
| `baseline_attack_rate_median` | 0,20 (opponent_rating) | 1,00 (`deviation_mean_cpl_z__missing`) | 0,11 | 5 | coverage, review |
| `baseline_attack_rate_mad` | 0,55 (rating) | 1,00 | 0,11 | 5 | coverage, review |
| `baseline_risk_rate_median` | 0,30 | 1,00 | 0,11 | 5 | coverage, review |
| `baseline_risk_rate_mad` | 0,46 (rating) | 1,00 | 0,11 | 5 | coverage, review |
| `baseline_style_switch_rate_median` | 0,19 | 1,00 | 0,11 | 5 | coverage, review |
| `baseline_style_switch_rate_mad` | 0,48 (rating) | 1,00 | 0,11 | 5 | coverage, review |
| `deviation_attack_rate_z` | 0,45 (eval_after_mate__max) | 1,00 | 0,11 | 5 | coverage, review |
| `deviation_risk_rate_z` | 0,14 | 1,00 | 0,11 | 5 | coverage, review |
| `deviation_style_switch_rate_z` | 0,15 | 1,00 | 0,11 | 5 | coverage, review |
| `historical_attack_rate_similar_fraction` | 0,15 | 1,00 | 0,11 | 5 | coverage, review |
| `historical_risk_rate_similar_fraction` | 0,26 (plies) | 1,00 | 0,11 | 5 | coverage, review |
| `historical_style_switch_rate_similar_fraction` | 0,21 (plies) | 1,00 | 0,11 | 5 | coverage, review |
| `behavioral_deviation_score_safe` | 0,23 (plies) | 1,00 | 0,11 | 5 | coverage, review |
| `rematch` | 0,34 (session_gap_2) | 0,80 (`rating_difference__missing`) | 0,04 | 8 | coverage, review |
| `clock_missing_fraction` | 0,40 (`mean_think__missing`) / 0,03 (giá trị) | 0,89 (`mean_think__missing`) | 0,47 | 2 | coverage, review |
| `style_drift_in_session` | 0,12 | 1,00 (`session_gap_1__missing`) | **1,00 (`previous_same_session`)** | 1.220 | structural, giữ loại |
| `games_in_session_before` | **0,76 (`session_gap_0`)** | không có | không có | 0 | structural, giữ loại |
| `phase_opening_fraction` | **0,90 (`ply__mean`)** | không có | không có | 0 | structural, giữ loại |
| `phase_endgame_fraction` | **0,85 (`ply__max`)** | không có | không có | 0 | structural, giữ loại |

### Diễn giải kênh "thiếu lịch sử"

- Có 980 dòng (2,7%) có ít hơn 5 ván lịch sử hợp lệ. Ở những dòng này mọi feature `baseline_*`, `deviation_*` và
  `historical_*` đều bị thiếu cùng lúc. Đó là lý do |rho| = 1,0 giữa hai chỉ báo thiếu.
- Kênh này có ảnh hưởng thật tới độ phủ nhãn:
  - ở 980 dòng đó chỉ có 1,5% có nhãn (15 dòng), so với 29,5% ở phần còn lại;
  - không có `deviation_mean_cpl_z` thì 7 trên 10 LF không thể bỏ phiếu;
  - trong 15 dòng có nhãn đó, tỉ lệ TILT là 67% vì chỉ còn `abandon` và `early_resign` có thể bỏ phiếu.
- Việc loại các feature này là có chủ ý. `docs/research/MODEL_STATUS.md` ghi lý do: "Their missing indicators reveal
  availability of personal quality baselines read by LFs".
- Vì vậy chỉ báo thiếu đúng là một kênh coverage. Nhưng trong train chỉ có 5 dòng có nhãn mà feature bị thiếu, nên
  lượng thông tin về nhãn đi qua kênh này rất nhỏ.
- Giá trị của các feature lịch sử thì không vượt ngưỡng 0,6.
- Để khôi phục an toàn (Phase 1): bỏ `add_indicator` cho nhóm này, hoặc đo chỉ báo thiếu theo nhãn trên dòng có nhãn.
  Sau đó chạy ablation, so sánh trên validation.

## 3. Rò rỉ cấu trúc chưa bị chặn: `phase_middlegame_fraction`

Đây là feature quan trọng nhất của mô hình đang chọn: permutation importance làm PR-AUC giảm 0,269, gấp hơn 4 lần
feature thứ hai.

Đo trên `features/moves.parquet` (72.575 cặp người chơi–ván):

| Kiểm tra | Kết quả |
|---|---|
| opening + middlegame + endgame = 1 | 100% số ván, sai số tối đa 1,4e-16 |
| Spearman (opening, độ dài ván) | −0,90, bị audit loại |
| Spearman (endgame, độ dài ván) | +0,85, bị audit loại |
| Spearman (middlegame, độ dài ván) | **−0,05**, lọt qua audit |
| η² của độ dài ván theo decile middlegame | **0,17** |

Độ dài ván theo decile của `phase_middlegame_fraction`:

| Decile | middlegame (trung vị) | Nửa nước (trung vị) | Tỉ lệ ≤ 60 nửa nước | Tỉ lệ ≥ 80 nửa nước |
|---:|---:|---:|---:|---:|
| 0 | 0,000 | 21 | **0,77** | 0,21 |
| 1 | 0,167 | 97 | 0,24 | 0,65 |
| 2 | 0,235 | 89 | 0,24 | 0,60 |
| 3 | 0,294 | 76 | 0,34 | 0,47 |
| 4 | 0,353 | 70 | 0,40 | 0,39 |
| 5 | 0,407 | 62 | 0,48 | 0,31 |
| 6 | 0,464 | 60 | 0,51 | 0,23 |
| 7 | 0,524 | 56 | 0,60 | 0,15 |
| 8 | 0,593 | 57 | 0,57 | 0,12 |
| 9 | 0,684 | 63 | 0,44 | 0,14 |

Diễn giải:

- Quan hệ có hình chữ U. Ván kết thúc trong khai cuộc thì middlegame = 0 và ván rất ngắn. Ván dài thì endgame lớn nên
  middlegame nhỏ.
- `plies` là input trực tiếp của nhiều LF:
  - `early_resign` đòi ≤ 60;
  - "orderly" (điều kiện của 4 LF NOT) đòi ≥ 40;
  - `composed_loss` đòi ≥ 80.
- Mô hình cây học được quan hệ phi tuyến này, còn Spearman thì không bắt được.

Kết luận: đây là **rủi ro structural cao** (proxy phi tuyến của input LF). Nó chưa phải bằng chứng rò rỉ, vì độ dài
ván cũng có thể liên quan thật tới tilt. Cần ablation ở Phase 1 để định lượng: đo PR-AUC trên validation khi bỏ cột
này, so với losing_streak baseline (0,242 trên validation).

Ghi chú tái lập:

- Nguồn là `features/moves.parquet`. Bản ngày 9/11 trùng md5 với bản Colab ngày 14/11, nên kết quả áp dụng được cho
  lần chạy mới.
- Phép tính phase fraction giống hệt `model_features.enrich`: `pd.crosstab([player, game_id], phase, normalize='index')`.
- Permutation importance ở lần chạy lại: 0,231.

## 4. Tương quan lành tính: không coi là rò rỉ

| Feature | Quan hệ mạnh nhất | Vì sao không phải rò rỉ |
|---|---|---|
| `attack_rate` | AUC 0,669 với thua; rho 0,46 với `eval_after_mate__max` | Tỉ lệ nước tấn công tính từ luật cờ (ăn quân, chiếu, áp sát vua), không đọc đánh giá của engine. Người đang thắng thì tấn công nhiều hơn |
| `defensive_rate` | AUC 0,60; rho 0,46 với `eval_after_mate__min` | Tỉ lệ nước đi khi đang bị chiếu. Hành vi trên bàn cờ |
| `risk_rate`, `style_switch_rate` | rho 0,18 với `adverse_event__mean` | Yếu |
| `initial_seconds`, `increment_seconds` | rho 0,53 với rating; 0,54 với `baseline_mean_think_median` | Thể thức được chọn trước ván. Quan hệ dân số học |
| `baseline_*_games`, `history_games` | rho 0,35 với `start_ms` | Lịch sử tích lũy theo thời gian |
| `rematch_streak_before` | rho 0,34 với `session_gap_2` | Phiên dài thì có nhiều ván tái đấu |

Lưu ý: `attack_rate` và `defensive_rate` là trung bình trên cả ván, nên chỉ biết được khi ván kết thúc. Điều này
không sai với thiết kế hiện tại vì mô hình chấm điểm sau ván. Nếu sau này cần cảnh báo giữa ván thì phải xét lại.

## 5. Rò rỉ theo split và thời gian

Không phát hiện (xem bảng ở mục 4 của `phase0_audit.md`):

- by_player: không có người chơi hay ván nào xuất hiện ở hai split. Đã purge 465 dòng của ván chung hai người.
- by_time:
  - các split nối nhau theo thời gian;
  - `label_end_upper_ms` của train không vượt qua lúc bắt đầu validation, của validation không vượt qua lúc bắt đầu
    test;
  - đã purge 91 dòng vắt qua mốc cắt.

  Điều này quan trọng vì `rest_and_recover` và `composed_loss` đọc ván sau.
- Label model, các audit và giá trị trung vị dùng để điền chỉ fit trên train. Ngưỡng, calibration và việc chọn mô hình
  dùng validation. Test chỉ để báo cáo.

## 6. Kết luận

| Mức | Hạng mục |
|---|---|
| Đã chặn | Input LF trực tiếp, nhóm QUALITY/think/rating, cột tương lai |
| Rủi ro cao, đang được dùng | `phase_middlegame_fraction` (proxy phi tuyến của `plies`) |
| Bị loại quá tay, cân nhắc khôi phục ở Phase 1 | 13 feature lịch sử, `rematch`, `clock_missing_fraction` (kênh coverage; giá trị đều dưới ngưỡng) |
| Giữ loại | `phase_opening_fraction`, `phase_endgame_fraction`, `games_in_session_before`, `style_drift_in_session` |
| Không rò rỉ, nhưng vô dụng | 5 cột `speed_*` (dữ liệu 100% blitz); 3 cột `baseline_*_games` trùng `history_games` (rho 0,998) |
