# Phase 1: đăng ký trước biến thể và quy tắc chọn

Ngày 2026-11-14. Viết xong file này **trước khi** chạy bất kỳ mô hình nào trên validation. Kế hoạch Phase 1 là bản
Fable 5.2 sửa, đã được người dùng duyệt. Sau khi chạy, không đổi danh sách biến thể và không đổi quy tắc trong file
này. Nếu buộc phải đổi thì ghi lý do ở mục "Thay đổi sau đăng ký" của `phase1_evaluation.md`.

> Nhãn là **nhãn yếu** từ 10 LF. Mô hình dự đoán nhãn yếu, tức một proxy hành vi của tilt sau ván thua. Mô hình
> **không** phát hiện tức giận và chưa được kiểm chứng bằng nhãn người.

## 0. Bước 0: đo trên dòng train có nhãn (đã chạy, chỉ đọc)

Chỉ dùng dòng train. Không đọc nhãn validation/test.

| | by_player | by_time |
|---|---|---|
| Dòng train có nhãn, tỉ lệ TILT | 6.428, 15,1% | 7.200, 14,9% |
| `phase_middlegame_fraction = 0` | n = 193, **TILT 100%** | n = 240, **TILT 100%** |
| `phase_middlegame_fraction > 0` | n = 6.235, TILT 12,5% | n = 6.960, TILT 11,9% |
| Ván < 40 nửa nước | n = 411, **TILT 100%** | n = 477, **TILT 100%** |
| Ván ≥ 40 nửa nước | n = 6.017, TILT 9,3% | n = 6.723, TILT 8,8% |
| Ván ≤ 60 nửa nước | n = 1.816, TILT 37,2% | n = 2.195, TILT 35,6% |
| Trong nhóm middlegame = 0, tỉ lệ ván < 40 nửa nước | 100% | 99,6% |

Lý do: mọi LF bỏ phiếu NOT đều đòi "ván có trật tự", tức từ 40 nửa nước trở lên. Vì vậy ván ngắn có nhãn thì luôn là
TILT. Với nhãn hiện tại, độ dài ván là đường tắt (shortcut) dẫn thẳng tới nhãn.

**Quyết định từ bước 0, theo luật Fable:** tỉ lệ TILT ở nhóm middlegame = 0 là 100%, cao hơn ngưỡng khoảng 45%.
Vì vậy `phase_middlegame_fraction` bị **loại khỏi mô hình chính**. E0 vẫn được chạy, nhưng chỉ để đối chiếu với kết
quả cũ.

## 1. Cách chia (split)

Dùng đúng các split mà pipeline nhãn yếu đã sinh (`WEAK_VERSION = 3`). Không tạo split mới.

- **A, by_player:** chia theo người chơi theo tỉ lệ 60/20/20. Ván chung của hai người thuộc hai tập khác nhau bị purge.
  Script đánh giá kiểm tra lại: không người chơi và không ván nào nằm ở hai tập.
- **B, by_time:** chia theo thời gian, cắt ở mốc 70% và 85%. Script kiểm tra: không có `label_end_upper_ms` của train
  vượt qua lúc bắt đầu validation, và lịch sử không nhìn trước tương lai (`baseline_latest_end_ms < start_ms`).
- **C, split hiện có:** chính là A và B ở trên, vì kết quả cũ cũng dùng hai split này. Không có split thứ ba.

Mỗi split có manifest gồm `player_id`, `game_id` (đã HMAC), `split` và sha256. Manifest lưu ngoài repo, trong
`~/tilt-phase1/manifests/`.

## 2. Biến thể (đăng ký trước)

Mọi mô hình XGBoost giữ đúng siêu tham số hiện tại: 100 cây, `max_depth=3`, `learning_rate=0.06`,
`subsample=0.85`, `colsample_bytree=0.85`, `reg_lambda=3`, seed 42, `sample_weight='balanced'`. Không tune.

| ID | Mô hình | Feature | Vai trò |
|---|---|---|---|
| E0 | XGBoost | 16 feature cũ (`lf_ablated`), tiền xử lý như cũ | đối chiếu kết quả cũ |
| M1 | XGBoost | E0 bỏ `phase_middlegame_fraction` (15) | **mô hình chính** |
| M2 | XGBoost | M1 + 13 feature lịch sử, điền trung vị train, **không** `add_indicator` (28) | thử khôi phục lịch sử |
| M3 | XGBoost | M1 bỏ 5 cột `speed_*` hằng số và `baseline_attack_rate_games`, `baseline_style_switch_rate_games` (8) | dọn feature |
| L1 | Logistic Regression (C=1, `class_weight='balanced'`) | feature của M1, điền trung vị và chuẩn hóa | baseline tuyến tính |

13 feature lịch sử: `baseline_{risk,attack,style_switch}_rate_{median,mad}`, `deviation_{risk,attack,style_switch}_rate_z`,
`historical_{risk,attack,style_switch}_rate_similar_fraction` và `behavioral_deviation_score_safe`.

Baseline chẩn đoán. Chúng **không** được triển khai: một số đọc trực tiếp input của LF.

| ID | Cách tính |
|---|---|
| B-prior | tỉ lệ TILT của train (majority/class prior) |
| B-meta | Logistic Regression trên `initial_seconds`, `increment_seconds` (metadata) |
| B-length | XGBoost (cùng siêu tham số) chỉ trên `lf_input__plies` (độ dài ván, input LF) |
| B-streak | Logistic Regression trên `losing_streak_before` (như cũ) |
| B-result | 1 nếu thua, 0 nếu không (như cũ) |

## 3. Metric

Tính trên **validation**, cho từng split A và B:

- PR-AUC và ROC-AUC, với khoảng tin cậy 95% bằng bootstrap theo cụm người chơi (1.000 lần, seed 42).
- Brier score và calibration (10 bin theo phân vị, ECE). Tính trên xác suất thô của mô hình, chưa qua Platt.
- Ngưỡng chọn trên validation bằng F1 lớn nhất, như pipeline hiện tại. Tại ngưỡng đó báo macro-F1, balanced accuracy,
  precision, recall và confusion matrix. Các số này **lạc quan** vì ngưỡng chọn trên chính validation.
- Tỉ lệ lớp dương (prevalence).

Báo theo nhóm (chỉ để ghi nhận, không dùng để chọn):

- ván thua và ván không thua;
- ván ≥ 40 nửa nước. Đây là nhóm mà mô hình phải thật sự phân biệt; dưới 40 nửa nước thì nhãn luôn là TILT;
- dòng có từ 5 ván lịch sử trở lên (`history_games ≥ 5`), riêng cho so sánh M2 với M1.

Phép đo phi tuyến chỉ để ghi nhận, không dùng để loại feature: η² theo decile và mutual information giữa mỗi feature
của M1/M2 và `lf_input__plies`, tính trên train.

**Test bị niêm phong trong Phase 1.** Không tính metric nào trên test. Test chỉ được đánh giá một lần, ở Phase 5.

## 4. Quy tắc quyết định (đăng ký trước)

Metric chính: PR-AUC trên validation của split A (by_player). Split B phải không mâu thuẫn. Chênh lệch dưới 0,05 coi
là nhiễu.

1. **`phase_middlegame_fraction`:** đã loại theo bước 0. Ghi thêm, không đổi quyết định: nếu B-length có PR-AUC
   ≥ 0,30 thì đó là thêm một bằng chứng; nếu E0 − M1 < 0,03 thì cột này cũng không đóng góp gì.
2. **Feature lịch sử (M2):** nhận nếu PR-AUC của M2 − M1 ≥ 0,05 ở A **và** > 0 ở B. Nếu không, giữ M1.
3. **Dọn feature (M3):** nếu |M3 − M1| < 0,05 ở cả A và B thì dùng M3, vì ít feature hơn. Nếu không, giữ M1.
4. **L1:** chỉ để so sánh. Không chọn mô hình cuối ở Phase 1; việc đó để Phase 5.
5. Mọi kết luận "cải thiện" đều phải ghi kèm khoảng tin cậy. Nếu khoảng tin cậy chồng nhau nhiều thì ghi là "không
   phân biệt được".
6. Nếu PR-AUC của mô hình chính rơi xuống khoảng 0,28–0,35 thì đó là kết quả trung thực và được báo đúng như vậy.

## 5. Không làm trong Phase 1

- Không đổi công thức nhãn, không đổi LF và không sửa outcome gate. Gate vẫn FAILED, và báo cáo ghi rõ như vậy.
- Không đổi baseline 16 feature trong pipeline (`train.py` giữ nguyên). Code đánh giá mới nằm ở module riêng.
- Không xem test. Không tune siêu tham số.
- Không khôi phục `rematch` hay `clock_missing_fraction`.
- Huấn luyện chạy trên Colab, không chạy trên máy người dùng.
