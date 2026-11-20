# Phase 1: khung đánh giá và kết quả trên validation

Ngày 2026-11-14. Kế hoạch là bản Fable 5.2 sửa, đã được người dùng duyệt. Biến thể và quy tắc được ghi trong
`phase1_preregistration.md` **trước khi** chạy. Mọi số dưới đây đo trên validation. **Test vẫn niêm phong**: không
tính metric nào trên test.

> Nhãn là **nhãn yếu** do 10 LF sinh ra. Mô hình dự đoán nhãn yếu, tức một proxy hành vi của tilt sau ván thua. Mô
> hình **không** phát hiện tức giận và chưa được kiểm chứng bằng nhãn người. Outcome gate vẫn **FAILED**: Phase 1
> không đổi nhãn và không đổi LF.

## 1. Tóm tắt

| Câu hỏi | Kết quả |
|---|---|
| `phase_middlegame_fraction` | **Loại.** Ở train, ván có middlegame = 0 có tỉ lệ TILT 100%. Bỏ cột này làm PR-AUC giảm 0,088–0,089, nhưng phần điểm đó đến từ độ dài ván |
| 13 feature lịch sử (M2) | **Không nhận.** So với M1: +0,008 ở A và −0,012 ở B. Không đạt ngưỡng +0,05 |
| Dọn feature (M3) | **Nhận.** \|M3 − M1\| ≤ 0,004 ở cả hai split, nên dùng 8 feature thay vì 15 |
| Mô hình chính sau Phase 1 | **M3**. PR-AUC validation A 0,449 [0,343; 0,538], B 0,370 [0,299; 0,445] |
| Phát hiện quan trọng nhất | **Chỉ dùng độ dài ván (B-length) đã đạt PR-AUC 0,656 / 0,608, cao hơn mọi mô hình, kể cả E0.** Với LF hiện tại, nhãn yếu chủ yếu mã hóa "ván ngắn" |
| Toàn vẹn split | Sạch, như Phase 0. Kiểm tra lại trong code đánh giá; script dừng ngay nếu có vi phạm |

Fable từng dự báo điểm có thể rơi xuống 0,28–0,35. Thực tế mô hình chính đạt 0,449 (A) và 0,370 (B), giảm
0,088–0,089 so với E0. Đây là điểm trung thực sau khi bỏ đường tắt qua độ dài ván, không phải lỗi.

## 2. Cách chia và kiểm tra toàn vẹn

| | A: by_player | B: by_time |
|---|---|---|
| Train / validation / test (dòng) | 22.316 / 6.697 / 6.923, purge 465 | 25.403 / 5.431 / 5.476, purge 91 |
| Người chơi train / val / test | 122 / 38 / 36 | 189 / 146 / 145 |
| Dòng validation có nhãn (TILT) | 1.922 (263; 13,7%) | 1.549 (212; 13,7%) |
| Ván nằm ở nhiều split | 0 | 0 |
| Người chơi ở nhiều split | 0 | 158 (đúng thiết kế chia theo thời gian) |
| Nhãn train/val vượt qua mốc của tập sau | (không áp dụng) | 0 / 0 |
| Lịch sử cá nhân nhìn trước tương lai | 0 | 0 |
| sha256 manifest | `3243a255…f9ec4b` | `034a3e09…e1b6` |

Split C ("split hiện có") chính là A và B, vì kết quả cũ cũng dùng hai split này.

Manifest (`player_id`, `game_id` đã HMAC, `split`) lưu ngoài repo, ở `~/tilt-phase1/out/manifests/`.

**Tái lập E0.** E0 dùng đúng 16 feature cũ. PR-AUC validation 0,538 / 0,454, so với lần chạy cũ 0,5375 / 0,451. Từng
dự đoán lệch tối đa 0,08 / 0,13. Lý do là pipeline cũ sắp feature theo bảng chữ cái, còn `colsample_bytree=0.85` chọn
cột theo thứ tự. Như vậy mô hình được tái lập ở mức metric. Riêng thứ tự cột đã gây chênh khoảng 0,003 PR-AUC; đây
là một thước đo nhiễu.

## 3. So sánh trên validation

PR-AUC và ROC-AUC kèm khoảng tin cậy 95% bootstrap theo người chơi (1.000 lần). Brier và ECE tính trên xác suất thô,
chưa qua Platt.

### A: by_player (38 người chơi, 1.922 dòng có nhãn)

| ID | Mô tả | PR-AUC [95%] | ROC-AUC [95%] | Brier | ECE |
|---|---|---|---|---:|---:|
| E0 | 16 feature cũ | 0,538 [0,433; 0,620] | 0,770 [0,724; 0,811] | 0,178 | 0,281 |
| M1 | E0 bỏ middlegame | 0,449 [0,343; 0,538] | 0,727 [0,674; 0,772] | 0,193 | 0,296 |
| M2 | M1 + 13 lịch sử | 0,456 [0,347; 0,551] | 0,732 [0,678; 0,774] | 0,185 | 0,287 |
| **M3** | M1 bỏ 7 cột hằng số/trùng | **0,449 [0,343; 0,538]** | 0,729 [0,679; 0,773] | 0,192 | 0,297 |
| L1 | Logistic trên feature M1 | 0,314 [0,237; 0,389] | 0,664 [0,621; 0,705] | 0,227 | 0,327 |
| B-prior | tỉ lệ lớp | 0,137 | 0,500 | 0,118 | 0,015 |
| B-meta | `initial_seconds`, `increment_seconds` | 0,137 [0,107; 0,177] | 0,495 | 0,260 | 0,372 |
| **B-length** | chỉ độ dài ván (input LF) | **0,656 [0,564; 0,723]** | **0,826** | 0,149 | 0,256 |
| B-streak | `losing_streak_before` | 0,242 | 0,722 | 0,221 | 0,326 |
| B-result | thua = 1 | 0,182 | 0,637 | 0,506 | 0,460 |

### B: by_time (146 người chơi, 1.549 dòng có nhãn)

| ID | PR-AUC [95%] | ROC-AUC [95%] | Brier | ECE |
|---|---|---|---:|---:|
| E0 | 0,454 [0,390; 0,520] | 0,748 [0,710; 0,785] | 0,163 | 0,244 |
| M1 | 0,366 [0,293; 0,441] | 0,692 [0,646; 0,735] | 0,178 | 0,258 |
| M2 | 0,355 [0,284; 0,427] | 0,680 [0,637; 0,719] | 0,177 | 0,253 |
| **M3** | **0,370 [0,299; 0,445]** | 0,692 [0,648; 0,735] | 0,177 | 0,260 |
| L1 | 0,290 [0,230; 0,351] | 0,641 [0,592; 0,686] | 0,202 | 0,285 |
| B-prior | 0,137 | 0,500 | 0,118 | 0,012 |
| B-meta | 0,147 | 0,523 | 0,241 | 0,349 |
| **B-length** | **0,608 [0,539; 0,671]** | **0,816** | 0,131 | 0,211 |
| B-streak | 0,242 | 0,738 | 0,216 | 0,321 |
| B-result | 0,172 | 0,611 | 0,491 | 0,422 |

### Chênh lệch có ghép cặp (cùng mẫu bootstrap)

| | A: trung bình [95%] | B: trung bình [95%] |
|---|---|---|
| M2 − M1 | +0,007 [−0,010; +0,022] | −0,013 [−0,028; +0,003] |
| M3 − M1 | −0,000 [−0,008; +0,008] | +0,004 [−0,002; +0,011] |
| E0 − M1 | +0,088 [+0,047; +0,127] | +0,087 [+0,055; +0,120] |
| L1 − M1 | −0,133 [−0,172; −0,089] | −0,077 [−0,124; −0,033] |

### Metric theo ngưỡng (lạc quan, vì ngưỡng chọn trên chính validation)

| | Ngưỡng | Precision | Recall | Macro-F1 | Balanced acc. | TN / FP / FN / TP |
|---|---:|---:|---:|---:|---:|---|
| M3, A | 0,618 | 0,425 | 0,422 | 0,666 | 0,666 | 1.509 / 150 / 152 / 111 |
| M3, B | 0,536 | 0,356 | 0,425 | 0,639 | 0,651 | 1.174 / 163 / 122 / 90 |
| E0, A | 0,649 | 0,593 | 0,399 | 0,705 | 0,678 | 1.587 / 72 / 158 / 105 |
| B-length, A | 0,997 | 1,000 | 0,456 | 0,793 | 0,728 | 1.659 / 0 / 143 / 120 |

Số đầy đủ cho mọi mô hình nằm ở `phase1_metrics.csv`.

## 4. Áp quy tắc đã đăng ký

1. **Middlegame: loại** (quyết định từ bước 0, xem `phase1_preregistration.md`). Hai điều kiện ghi thêm cũng xác nhận
   quyết định này:
   - B-length có PR-AUC 0,656 / 0,608, cao hơn ngưỡng 0,30.
   - E0 − M1 = 0,088 / 0,087, tức cột này có đóng góp. Nhưng đóng góp đó đến từ độ dài ván: chỉ riêng độ dài đã vượt
     E0.
2. **Lịch sử: không nhận.** Quy tắc đòi M2 − M1 ≥ 0,05 ở A và > 0 ở B. Thực tế là +0,008 và −0,012. Nhóm
   `history_ge_5` không giúp phân biệt: nó gồm 1.916/1.922 dòng ở A và toàn bộ dòng ở B, vì gần như mọi dòng có nhãn
   đều đã có đủ 5 ván lịch sử.
3. **Dọn feature: dùng M3.** \|M3 − M1\| ≤ 0,004 ở cả hai split, dưới 0,05. M3 còn 8 feature: `initial_seconds`,
   `increment_seconds`, `risk_rate`, `attack_rate`, `defensive_rate`, `style_switch_rate`, `rematch_streak_before`,
   `baseline_risk_rate_games`.
4. **L1** kém M1 rõ rệt (khoảng tin cậy không chứa 0). Chỉ dùng để so sánh; mô hình cuối do Phase 5 chọn.

Không có thay đổi nào sau đăng ký. Cả danh sách biến thể, siêu tham số và quy tắc đều giữ nguyên.

## 5. Theo nhóm (chỉ ghi nhận)

PR-AUC (ROC-AUC), validation. Tỉ lệ TILT của nhóm nằm ở cột "Tỉ lệ".

| Nhóm | Split | n (TILT) | Tỉ lệ | M3 | E0 | B-length |
|---|---|---|---:|---|---|---|
| Ván thua | A | 1.147 (219) | 0,191 | 0,546 (0,742) | 0,635 (0,787) | 0,751 (0,856) |
| Ván không thua | A | 751 (44) | 0,059 | 0,078 (0,595) | 0,124 (0,635) | 0,196 (0,656) |
| Ván ≥ 40 nửa nước | A | 1.802 (143) | 0,079 | 0,137 (0,634) | 0,154 (0,667) | 0,150 (0,681) |
| Ván thua | B | 866 (159) | 0,184 | 0,481 (0,723) | 0,559 (0,765) | 0,715 (0,850) |
| Ván không thua | B | 669 (53) | 0,079 | 0,107 (0,552) | 0,159 (0,659) | 0,278 (0,698) |
| Ván ≥ 40 nửa nước | B | 1.474 (137) | 0,093 | 0,149 (0,602) | 0,166 (0,691) | 0,216 (0,715) |

Đọc bảng:

- Ở ván không thua, M3 gần như không hơn tỉ lệ lớp: 0,078 so với 0,059 ở A, 0,107 so với 0,079 ở B.
- Ở ván ≥ 40 nửa nước, nơi nhãn không còn bị độ dài quyết định trọn, M3 chỉ đạt 0,137–0,149 so với tỉ lệ lớp
  0,079–0,093. ROC-AUC khoảng 0,60–0,63. Phần lớn điểm của mô hình đến từ nhóm ván ngắn.
- Ngay trong nhóm ≥ 40 nửa nước, độ dài ván vẫn dự đoán được nhãn (0,150 / 0,216), tức độ dài vẫn là tín hiệu mạnh.

## 6. Calibration

Xác suất thô bị đẩy cao, vì mô hình huấn luyện với `sample_weight='balanced'`; ECE khoảng 0,26–0,30. Ví dụ M3 ở A:
bin thấp nhất có điểm trung bình 0,23 nhưng tỉ lệ TILT thật là 0,05; bin cao nhất có điểm 0,79 và tỉ lệ thật 0,49.

Pipeline cũ đã có bước Platt trên validation. Bước đó giữ được thứ hạng nhưng chưa được đánh giá độc lập. Phase 5
cần đánh giá calibration trên test.

## 7. Phép đo phi tuyến (chỉ ghi nhận)

η² theo decile của feature so với độ dài ván, tính trên train.

| Feature | η² A | η² B |
|---|---:|---:|
| `phase_middlegame_fraction` (đã loại) | 0,151 | 0,170 |
| `defensive_rate` (trong M3) | 0,156 | 0,158 |
| `attack_rate` (trong M3) | 0,107 | 0,094 |
| `risk_rate` (trong M3) | 0,089 | 0,095 |
| `style_switch_rate` (trong M3) | 0,082 | 0,090 |

`defensive_rate` gắn với độ dài ván mạnh ngang `phase_middlegame_fraction`. Các tỉ lệ còn lại của M3 cũng có η² khoảng
0,08–0,11. Một phần điểm của M3 vì vậy có thể vẫn đến từ độ dài ván, đi đường gián tiếp. Theo đăng ký, phép đo này
chưa được dùng để loại feature. Nếu muốn dùng thì cần duyệt ngưỡng trước.

## 8. Kết luận và đề xuất cho Phase 2

1. **Vấn đề nằm ở nhãn, chưa phải ở feature.**
   - Mọi LF bỏ phiếu NOT đều đòi ván từ 40 nửa nước trở lên. Vì vậy ván ngắn có nhãn thì 100% là TILT.
   - Chỉ dùng độ dài ván đã thắng mọi mô hình.
   - Thêm feature hành vi ở Phase 2 khó cải thiện điểm số trên nhãn này, và điểm cao hơn cũng chưa chắc phản ánh tilt.
2. **Đề xuất cho Phase 2** (cần bạn duyệt):
   - Dùng **PR-AUC trên nhóm ván ≥ 40 nửa nước** làm metric chính thứ hai, đăng ký trước. Đây là nơi feature hành
     vi phải chứng minh giá trị, không bị độ dài ván che lấp.
   - Feature mới (độ lệch cá nhân, động học theo thời gian) phải được báo η² với độ dài ván.
   - Không đổi LF trong dự án này. Theo Fable, LF phiên bản 2 là dự án riêng, cần split test mới và khoảng 100–200 ván
     có nhãn người.
3. Test vẫn niêm phong. Chỉ đánh giá một lần, ở Phase 5.

## 9. File và cách chạy lại

Đã thêm (chưa commit):

- `src/tilt/evaluation/phase1.py`: module đánh giá. Không sửa `train.py` hay pipeline cũ.
- `tests/unit/test_phase1.py`: 6 test, đều qua. Các test kiểm tra:
  - biến thể khớp bản đăng ký;
  - người chơi nằm ở hai split thì bị từ chối;
  - lịch sử nhìn trước tương lai thì bị từ chối;
  - đảo nhãn test không làm đổi kết quả nào (test không bị đọc);
  - chạy lại cho kết quả giống hệt;
  - quy tắc quyết định chạy cơ học.
- `reports/phase1_preregistration.md`, `reports/phase1_evaluation.md`, `reports/phase1_metrics.csv`.

Ngoài repo, trong WSL (không copy sang Windows):

- `~/tilt-phase1/aligned/`: bảng đã ghép nhãn.
- `~/tilt-phase1/out/`: `phase1_results.json`, manifest, dự đoán validation.
- `~/tilt-phase1/step0.json`.

Chạy lại. Huấn luyện chạy trên Colab với xgboost 2.1.4 và scikit-learn 1.6.1, mất khoảng 87 giây:

```bash
# 1. Dựng bảng đã ghép nhãn (cần TILT_SALT, chỉ đọc dữ liệu)
python p1_step0.py
# 2. Đánh giá
PYTHONPATH=tilt/src python -m tilt.evaluation.phase1 --aligned ~/tilt-phase1/aligned \
  --out ~/tilt-phase1/out --previous ~/tilt-phase1/previous --repetitions 1000
# Test
TILT_SALT=<bất kỳ chuỗi ≥ 16 ký tự> python -m pytest tests/unit/test_phase1.py
```
