# Đề xuất weak-label v2 — L1: kiểm kê và thiết kế, chưa chọn nhãn triển khai

Ngày 2026-11-15. Nhãn là **proxy hành vi**, chưa có kiểm chứng độc lập bằng nhãn người. Theo bối cảnh hiện có,
số nhãn người là 0; L1 không mở cơ sở dữ liệu nhãn người để đếm lại.

## Phạm vi và phương pháp

Đã đọc `phase0_audit.md`, `leakage_analysis.md`, `phase4_label_validation.md`,
`final_model_comparison.md`, `phase1_preregistration.md`, `evaluation/phase1.py`, `phase4.py` và mã LF v1.
Các báo cáo cũ cung cấp bối cảnh, không được dùng làm số liệu đánh giá ứng viên. **Toàn bộ số mới trong báo cáo
này chỉ tính trên TRAIN**, kể cả v1, độ phủ, EM và kiểm tra độ ổn định. Không huấn luyện/chấm mô hình dự đoán.

Nguồn chỉ đọc: `~/tilt-phase1/aligned/aligned_by_player.parquet` và `aligned_by_time.parquet`.
Loader đọc schema (metadata), chiếu riêng `split`, `weak_tilt_label`, `weak_tilt_prob`, `lf_input__*`,
và áp bộ lọc Parquet `split == train` ngay khi quét; mọi hàm thống kê từ chối frame lẫn tập khác.
Không đọc bảng feature/label validation hoặc test vào frame phân tích; không tổng hợp, đếm hay xuất dữ liệu của
hai tập đó. Không cần mở `tilt/data`, không chép dữ liệu, không dùng salt/token hay mạng.

A = by_player (22.316 hàng TRAIN), B = by_time (25.403 hàng TRAIN), giữ nguyên manifest và purge của Phase 1.
Hai chính sách có hàng TRAIN trùng nhau; không coi A/B là hai mẫu độc lập. Chỉ dùng ngữ cảnh `lf_input__*` đã
được đóng băng, không dựng lại lịch sử từ một tập đã lọc và không thu hồi hàng từng bị purge. Các LF dùng tương
lai ở v1/floor40 giữ nguyên horizon/purge hiện có; symmetric20/speed_quality20 chỉ dùng hiện tại và quá khứ.

Ngưỡng ba ứng viên được ghi trong `~/tilt-labels-v2/design_before_results.json` **trước lần tính thống kê đầu**,
không thay theo kết quả. Không thử thêm ứng viên hoặc tune ngưỡng. 20 nửa nước + 10 nước của mình là mức mẫu tối
thiểu đề xuất, chưa phải ước lượng độ tin cậy. Không thực hiện so khớp lịch sử theo độ dài vì bản tổng hợp hiện
có chưa chứa baseline cá nhân theo ply; muốn làm cần một giai đoạn thiết kế khác.

Quy ước: phủ = số có ít nhất một phiếu / toàn TRAIN; tỉ lệ TILT = TILT / số có nhãn.
Firing rate trong nhóm có nhãn = số phiếu LF / số hàng được bất kỳ LF nào phủ (không phải precision).
Chồng lấp = hàng có >=2 LF; xung đột = hàng có cả phiếu 0 và 1. AUC thô dùng **plies tăng dần** làm điểm,
chỉ trên hàng có nhãn và biết plies; báo thêm max(AUC, 1−AUC) để tránh hiểu AUC thấp là ít liên hệ độ dài.
Đây là thống kê xếp hạng một biến, không phải kết quả B-length hoặc kiểm tra mọi quan hệ phi tuyến.
“Tỉ trọng theo kết quả” có mẫu số là **mọi TILT**, khác với “tỉ lệ TILT trong nhóm kết quả có nhãn”.
Dấu — = không có mẫu số, không phải 0%. Số đếm chính xác, phần trăm/AUC làm tròn khi hiển thị.

## Kiểm kê v1: điều kiện chính xác

Mỗi LF trả 1=TILT, 0=NOT TILT, −1=bỏ qua. Các biến dùng trong so sánh phải biết, trừ `final_eval_mate` ở điều
kiện viable phải **thiếu**. Không suy diễn thiếu z/accuracy thành bình thường.

- `z = deviation_mean_cpl_z`; `normal = mean_accuracy >= baseline_mean_accuracy_median`.
- `clearly_lost = final_eval_cp <= −500 HOẶC final_eval_mate < 0` (chỉ nhánh có dữ liệu mới đúng).
- `orderly = plies >= 40 VÀ [status ∈ {mate, stalemate, draw, outoftime} HOẶC
  (status == resign VÀ clearly_lost)]`.
- `viable = final_eval_cp > −150 VÀ final_eval_mate thiếu VÀ last_adverse_distance <= 6`.
  `last_adverse_distance` là số nửa nước từ sự kiện bất lợi cuối đến cuối ván, không phải tổng độ dài ván.
- `after_loss = previous_result_score == 0 VÀ previous_same_session đúng`;
  `prior_gap = (start_ms − previous_end_upper_ms)/1000`.
- `rested_normal = 300 <= (next_start_ms − end_upper_ms)/1000 <= 1800 VÀ |next_z| <= 1`.
- `session_shrinking_gaps` đúng khi đủ ba gap biết, không âm và giảm nghiêm ngặt (hai gap trước và gap hiện tại);
  `prior_session_loss_run` chỉ đếm các ván hoàn tất trước start trong cùng phiên, dừng ở ván không thua/thiếu kết quả.

| LF | Phiếu | Điều kiện VÀ đầy đủ | Yêu cầu độ dài | Phụ thuộc kết quả |
|---|---:|---|---|---|
| abandon | 1 | result=0; status=timeout; viable | Không ngưỡng tổng plies; adverse distance <=6 | Thua hiện tại |
| early_resign | 1 | result=0; status=resign; plies<=60; viable | <=60; không sàn | Thua hiện tại |
| carryover | 1 | after_loss; 0<=prior_gap<=60; z>=1,5 | Không ngưỡng plies | Thua ván trước cùng phiên |
| session_spiral | 1 | prior_session_loss_run>=3; session_shrinking_gaps đúng; z>=1,5 | Không ngưỡng plies/gap tuyệt đối bổ sung | Chuỗi thua trước; không đọc result hiện tại trong vote |
| normal_accuracy | 0 | orderly; normal; abs(z)<=1 | >=40 qua orderly | Không chặn theo result; status/eval quyết định orderly |
| rest_and_recover | 0 | orderly; rested_normal | >=40 qua orderly | Không chặn theo result; có tương lai |
| calm_play | 0 | orderly; normal; adverse_events==0 | >=40 qua orderly | Không chặn theo result; **không đòi z** |
| composed_loss | 0 | result=0; status=resign; plies>=80; clearly_lost; rested_normal | >=80 | Thua hiện tại; có tương lai |
| expected_loss | 0 | orderly; result=0; rating_difference<=−200; mean_accuracy>=baseline_mean_accuracy_median−5; abs(z)<=1 | >=40 qua orderly | Thua hiện tại và chênh Elo |
| fast_erratic_after_loss | 1 | after_loss; 0<=prior_gap<=120; baseline_mean_think_median>0; mean_think<=0,65×baseline; z>=1 | Không ngưỡng plies | Thua ván trước cùng phiên |

Mã nguồn `vote()` nguyên văn và khai báo input hiện tại/quá khứ/tương lai của từng LF được lưu trong
`train_audit/provenance.json`; khai báo provenance gồm cả nguồn dựng ngữ cảnh, không phải mọi cột đều được đọc
trực tiếp trong `vote()`. `lf_strata.csv` có min/max plies quan sát và phiếu theo từng nhóm độ dài.

| LF v1 | Phiếu A / B | Phủ TRAIN A / B | Firing rate trong có nhãn A / B | Chồng lấp A / B | Xung đột A / B |
|---|---:|---:|---:|---:|---:|
| abandon | 66 / 82 | 0.30% / 0.32% | 1.03% / 1.14% | 2 / 3 | 0 / 0 |
| early_resign | 155 / 208 | 0.69% / 0.82% | 2.41% / 2.89% | 6 / 4 | 0 / 0 |
| carryover | 730 / 752 | 3.27% / 2.96% | 11.36% / 10.44% | 129 / 129 | 13 / 15 |
| session_spiral | 24 / 27 | 0.11% / 0.11% | 0.37% / 0.38% | 24 / 26 | 1 / 1 |
| normal_accuracy | 4893 / 5506 | 21.93% / 21.67% | 76.12% / 76.47% | 392 / 461 | 0 / 0 |
| rest_and_recover | 735 / 807 | 3.29% / 3.18% | 11.43% / 11.21% | 314 / 354 | 14 / 16 |
| calm_play | 0 / 0 | 0.00% / 0.00% | 0.00% / 0.00% | 0 / 0 | 0 / 0 |
| composed_loss | 48 / 63 | 0.22% / 0.25% | 0.75% / 0.88% | 48 / 63 | 0 / 1 |
| expected_loss | 242 / 300 | 1.08% / 1.18% | 3.76% / 4.17% | 151 / 181 | 0 / 0 |
| fast_erratic_after_loss | 139 / 139 | 0.62% / 0.55% | 2.16% / 1.93% | 99 / 94 | 0 / 0 |

| Chỉ số TRAIN | A: by_player | B: by_time |
|---|---:|---:|
| v1: có nhãn; phủ | 6428; 28.80% | 7200; 28.34% |
| v1: TILT; tỉ lệ trong có nhãn | 973; 15.14% | 1069; 14.85% |
| v1: nhiều LF; xung đột | 561; 14 | 631; 16 |
| v1: AUC plies thô; hai chiều | 0.1705; 0.8295 | 0.1644; 0.8356 |
| v1: nhãn <40; tỉ lệ TILT | 411; 100% | 477; 100% |
| v1: TILT có thua hiện tại/trước | 973/973; 100% | 1069/1069; 100% |

Tái tạo v1 từ LF inputs khớp 100% nhãn đã lưu trên TRAIN ở cả A/B; sai lệch xác suất lớn nhất chỉ
4,44×10⁻¹⁶. Vì thế các thay đổi bên dưới không xuất phát từ lệch hàng hay lệch input. `calm_play` có 0 phiếu ở
cả hai chính sách; trong TRAIN >=40 cũng có 0 hàng `adverse_events==0`. Số sự kiện tuyệt đối tăng theo số cơ hội
đi nước, nên yêu cầu bằng 0 là một ràng buộc không phù hợp với dữ liệu này. Causal/emotion validity chưa được đo.
`lf_pairs.csv` lưu đầy đủ 45 cặp v1 mỗi chính sách và mọi cặp ứng viên (cả cặp 0); tổng xung đột từng LF không
được cộng thành số hàng xung đột vì một hàng có thể đóng góp nhiều LF.

## Gộp phiếu và giả định

Giữ Dawid–Skene đối xứng của v1: prior cố định 0,5; Beta(6,2) dạng pseudocount; accuracy khởi tạo 0,75,
chặn [0,500001; 0,999999]; bỏ phiếu trắng khỏi log evidence; EM tối đa 150 vòng, dừng khi max thay đổi accuracy
<10⁻⁷. Nhãn cứng = xác suất >=0,5; không phiếu thì không nhãn. Bảng chính dùng ngân sách 150 giống v1.
Chỉ **label model** được fit trên TRAIN, không có classifier/regressor nào được fit hay chấm trên dữ liệu thật.

v1 A hội tụ ở vòng 147; v1 B chưa ở 150 (Δ=1,35×10⁻⁶). Kiểm tra phụ tăng ngân sách lên 1.000 trên cùng TRAIN:
v1 B hội tụ ở 199; floor40 A/B ở 244/152; **không nhãn cứng nào đổi**, sai lệch xác suất tối đa của floor40 A
là 0,000172. Đây là kiểm tra ổn định của EM, không đổi ngưỡng LF hay âm thầm thay số liệu chính.
Accuracy EM không có chuẩn người để kiểm chứng. Các LF sau thua dùng chung z và ngữ cảnh, vi phạm độc lập có
điều kiện; thêm phiếu tương quan có thể chỉ tăng độ tự tin, không tăng bằng chứng.

## Ứng viên 1 — floor40

Giữ nguyên cả 10 LF v1, thêm điều kiện chung `plies >=40` cho **mọi** LF; thiếu plies bỏ qua.
Ván <40 luôn không có nhãn. Ở mỗi độ dài hợp lệ vẫn có đường tới cả hai lớp (carryover và normal_accuracy),
nhưng giữ nguyên cap <=60 của early_resign và floor >=80 của composed_loss.

Ưu điểm: thay đổi nhỏ, loại bỏ cơ chế “ngắn có nhãn thì chỉ TILT”. Đổi lại mất toàn bộ 411/477 nhãn TILT ngắn,
giữ LF chết, giữ phụ thuộc thua và các chặn status/độ dài còn lại. Không phải giải pháp đầy đủ cho shortcut;
nhãn trong giao khớp v1 hoàn toàn nhưng quần thể có nhãn đã thay đổi.

| Chỉ số TRAIN | A: by_player | B: by_time |
|---|---:|---:|
| Có nhãn / tổng TRAIN (phủ) | 6017 / 22316 (26.96%) | 6723 / 25403 (26.47%) |
| TILT / NOT TILT; tỉ lệ TILT trong có nhãn | 562 / 5455; 9.34% | 592 / 6131; 8.81% |
| <20 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 0 / 0; —; 0.00% | 0 / 0; —; 0.00% |
| 20–39 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 0 / 0; —; 0.00% | 0 / 0; —; 0.00% |
| 40–59 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 254 / 1075; 19.11%; 24.84% | 292 / 1343; 17.86%; 25.78% |
| 60–79 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 159 / 1352; 10.52%; 29.16% | 147 / 1548; 8.67%; 29.48% |
| >=80 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 149 / 3028; 4.69%; 41.03% | 153 / 3240; 4.51%; 40.65% |
| ROC-AUC thô của plies; max(AUC, 1−AUC) | 0.2953; 0.7047 | 0.2969; 0.7031 |
| TILT có thua hiện tại hoặc trước / tất cả TILT | 562 / 562; 100.00% | 592 / 592; 100.00% |
| TILT theo kết quả thua: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 414 / 562; 73.67%; 12.21% | 447 / 592; 75.51%; 11.61% |
| TILT theo kết quả hòa: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 12 / 562; 2.14%; 2.41% | 12 / 592; 2.03%; 2.32% |
| TILT theo kết quả thắng: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 135 / 562; 24.02%; 6.57% | 131 / 592; 22.13%; 5.79% |
| TILT theo kết quả không rõ: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 1 / 562; 0.18%; 1.37% | 2 / 592; 0.34%; 2.17% |
| Dòng nhiều LF / xung đột (tỉ lệ xung đột trong có nhãn) | 466 / 14 (0.23%) | 538 / 16 (0.24%) |
| LF abandon: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 16; 0.07%; 1 / 0 | 22; 0.09%; 1 / 0 |
| LF early_resign: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 47; 0.21%; 4 / 0 | 67; 0.26%; 2 / 0 |
| LF carryover: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 507; 2.27%; 36 / 13 | 508; 2.00%; 38 / 15 |
| LF session_spiral: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 12; 0.05%; 12 / 1 | 13; 0.05%; 13 / 1 |
| LF normal_accuracy: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 4893; 21.93%; 392 / 0 | 5506; 21.67%; 461 / 0 |
| LF rest_and_recover: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 735; 3.29%; 314 / 14 | 807; 3.18%; 354 / 16 |
| LF calm_play: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 0; 0.00%; 0 / 0 | 0; 0.00%; 0 / 0 |
| LF composed_loss: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 48; 0.22%; 48 / 0 | 63; 0.25%; 63 / 1 |
| LF expected_loss: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 242; 1.08%; 151 / 0 | 300; 1.18%; 181 / 0 |
| LF fast_erratic_after_loss: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 20; 0.09%; 11 / 0 | 22; 0.09%; 10 / 0 |
| DS ngân sách 150: hội tụ; vòng; max Δ accuracy cuối | chưa; 150; 7.18e-06 | chưa; 150; 1.15e-07 |
| DS ngân sách 1.000: hội tụ ở vòng; nhãn cứng đổi so với 150 | 244; 0 | 152; 0 |
| Khớp v1 trên giao có nhãn; số dòng trong giao | 100.00%; 6017 | 100.00%; 6723 |
| Có nhãn mới / mất nhãn so với v1 | 0 / 411 | 0 / 477 |

## Ứng viên 2 — symmetric20

Mọi LF đòi `plies >=20` **và** `move_count >=10` (số nước của chính người chơi, không mặc định plies/2
trong dữ liệu thật). Giữ carryover, session_spiral, fast_erratic_after_loss; thêm kiểm tra think không âm/hữu hạn
cho LF tốc độ. Bỏ abandon, early_resign, normal_accuracy, rest_and_recover, composed_loss, expected_loss và
thay calm_play bằng một LF NOT duy nhất: `abs(z)<=1` và `0<=adverse_events/move_count<=0,25`.
Ngưỡng 0,25 nghĩa là tối đa một sự kiện bất lợi trên bốn nước của mình, là **giả định thiết kế**, chưa được
kiểm chứng bởi người. Thiếu z/count/events thì LF NOT bỏ qua; không điền thiếu thành 0.

NOT không đòi status, thắng/thua, baseline accuracy, nghỉ sau ván hay tương lai. Cả hai lớp đạt được ở ván 20–39
và ván dài; <20 bỏ qua. Quy tắc calm_rate dùng tần suất thay số đếm bằng 0, và có phiếu thực ở cả A/B.
Tỉ lệ sự kiện đã chuẩn hóa theo số nước nhưng z vẫn so với baseline cả ván cá nhân, chưa so khớp theo độ dài.

Ưu điểm: hai phía dùng chung sàn và có cả hai lớp trong mọi nhóm độ dài được phủ; ít liên hệ plies hơn hai ứng
viên còn lại theo thống kê xếp hạng một chiều. Đổi lại vẫn định nghĩa proxy **sau thua** (100% TILT có thua),
bỏ bằng chứng kết thúc đột ngột và giảm độ phủ. Không gọi đây là nhãn cho mọi kiểu tilt. Xung đột quan sát là 0,
nhưng không bị cấm tuyệt đối: z=1 có thể làm fast_erratic và calm_rate cùng bỏ phiếu trái chiều.

| Chỉ số TRAIN | A: by_player | B: by_time |
|---|---:|---:|
| Có nhãn / tổng TRAIN (phủ) | 4950 / 22316 (22.18%) | 5057 / 25403 (19.91%) |
| TILT / NOT TILT; tỉ lệ TILT trong có nhãn | 690 / 4260; 13.94% | 708 / 4349; 14.00% |
| <20 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 0 / 0; —; 0.00% | 0 / 0; —; 0.00% |
| 20–39 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 172 / 629; 21.47%; 25.92% | 186 / 703; 20.92%; 23.48% |
| 40–59 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 207 / 880; 19.04%; 20.32% | 223 / 922; 19.48%; 18.05% |
| 60–79 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 158 / 889; 15.09%; 20.21% | 141 / 892; 13.65%; 17.97% |
| >=80 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 153 / 1862; 7.59%; 26.02% | 158 / 1832; 7.94%; 23.84% |
| ROC-AUC thô của plies; max(AUC, 1−AUC) | 0.3537; 0.6463 | 0.3562; 0.6438 |
| TILT có thua hiện tại hoặc trước / tất cả TILT | 690 / 690; 100.00% | 708 / 708; 100.00% |
| TILT theo kết quả thua: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 515 / 690; 74.64%; 27.28% | 530 / 708; 74.86%; 27.81% |
| TILT theo kết quả hòa: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 13 / 690; 1.88%; 4.68% | 13 / 708; 1.84%; 4.78% |
| TILT theo kết quả thắng: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 161 / 690; 23.33%; 5.84% | 163 / 708; 23.02%; 5.75% |
| TILT theo kết quả không rõ: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 1 / 690; 0.14%; 3.57% | 2 / 708; 0.28%; 4.76% |
| Dòng nhiều LF / xung đột (tỉ lệ xung đột trong có nhãn) | 60 / 0 (0.00%) | 56 / 0 (0.00%) |
| LF carryover: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 655; 2.94%; 60 / 0 | 668; 2.63%; 56 / 0 |
| LF session_spiral: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 20; 0.09%; 19 / 0 | 21; 0.08%; 19 / 0 |
| LF fast_erratic_after_loss: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 78; 0.35%; 44 / 0 | 77; 0.30%; 39 / 0 |
| LF calm_rate: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 4260; 19.09%; 0 / 0 | 4349; 17.12%; 0 / 0 |
| DS ngân sách 150: hội tụ; vòng; max Δ accuracy cuối | có; 122; 9.5e-08 | có; 132; 9.8e-08 |
| DS ngân sách 1.000: hội tụ ở vòng; nhãn cứng đổi so với 150 | 122; 0 | 132; 0 |
| Khớp v1 trên giao có nhãn; số dòng trong giao | 97.18%; 2338 | 96.82%; 2390 |
| Có nhãn mới / mất nhãn so với v1 | 2612 / 4090 | 2667 / 4810 |

## Ứng viên 3 — speed_quality20

Dùng cùng sàn >=20 nửa nước, >=10 nước của mình và cùng LF NOT calm_rate như ứng viên 2. Chỉ một LF TILT:
`z>=1,5` **và** `0<=mean_think<=0,65×baseline_mean_think_median`, baseline dương/hữu hạn. Không đọc kết quả
hiện tại/trước, phiên, status hay tương lai. Bỏ toàn bộ LF v1 khác. Có thể cho TILT sau thắng, kể cả không biết
kết quả, nếu hai điều kiện hành vi đúng.

Ưu điểm: mất ràng buộc thua trong công thức; quan sát có 6/107 TILT ở A và 13/114 ở B không thua hiện tại/trước
(không có hàng thiếu kết quả trong nhóm TILT không thua này). Đổi lại rất ít dương và liên hệ độ dài **mạnh hơn
v1 theo AUC một chiều**. Ở 60–79 nửa nước, A quan sát 0 TILT, B chỉ 1; >=80 chỉ 7 ở mỗi chính sách. Đây là thiếu
hỗ trợ thực nghiệm, khác với việc lớp TILT bị cấm trong công thức: unit test dựng được cả hai lớp ở mọi độ dài
hợp lệ. Không diễn giải “không có length gate riêng cho lớp” thành “không còn shortcut”.

Hai LF dùng hai miền z rời nhau nên không có overlap/conflict theo cấu tạo. EM dừng ngay ở vòng 1, accuracy đều
0,75: mỗi hàng chỉ có một phiếu và prior/pseudocount tự giữ trạng thái khởi tạo. Đây **không phải** bằng chứng DS
đã học được chất lượng LF. Label model ở đây thực chất chỉ diễn đạt lại quy tắc, xác suất có nhãn là 0,25/0,75.

| Chỉ số TRAIN | A: by_player | B: by_time |
|---|---:|---:|
| Có nhãn / tổng TRAIN (phủ) | 4367 / 22316 (19.57%) | 4463 / 25403 (17.57%) |
| TILT / NOT TILT; tỉ lệ TILT trong có nhãn | 107 / 4260; 2.45% | 114 / 4349; 2.55% |
| <20 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 0 / 0; —; 0.00% | 0 / 0; —; 0.00% |
| 20–39 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 81 / 629; 11.41%; 22.98% | 84 / 703; 10.67%; 20.79% |
| 40–59 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 19 / 880; 2.11%; 16.80% | 22 / 922; 2.33%; 14.88% |
| 60–79 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 0 / 889; 0.00%; 17.16% | 1 / 892; 0.11%; 15.53% |
| >=80 nửa nước: TILT / NOT; tỉ lệ TILT; phủ trong nhóm | 7 / 1862; 0.37%; 24.14% | 7 / 1832; 0.38%; 22.03% |
| ROC-AUC thô của plies; max(AUC, 1−AUC) | 0.1414; 0.8586 | 0.1467; 0.8533 |
| TILT có thua hiện tại hoặc trước / tất cả TILT | 101 / 107; 94.39% | 101 / 114; 88.60% |
| TILT theo kết quả thua: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 89 / 107; 83.18%; 6.09% | 89 / 114; 78.07%; 6.08% |
| TILT theo kết quả hòa: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 2 / 107; 1.87%; 0.75% | 0 / 114; 0.00%; 0.00% |
| TILT theo kết quả thắng: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 16 / 107; 14.95%; 0.61% | 25 / 114; 21.93%; 0.93% |
| TILT theo kết quả không rõ: số / mọi TILT; tỉ trọng; tỉ lệ TILT trong nhóm có nhãn | 0 / 107; 0.00%; 0.00% | 0 / 114; 0.00%; 0.00% |
| Dòng nhiều LF / xung đột (tỉ lệ xung đột trong có nhãn) | 0 / 0 (0.00%) | 0 / 0 (0.00%) |
| LF fast_deterioration: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 107; 0.48%; 0 / 0 | 114; 0.45%; 0 / 0 |
| LF calm_rate: phiếu; phủ TRAIN; dòng chồng lấp / xung đột | 4260; 19.09%; 0 / 0 | 4349; 17.12%; 0 / 0 |
| DS ngân sách 150: hội tụ; vòng; max Δ accuracy cuối | có; 1; 0 | có; 1; 0 |
| DS ngân sách 1.000: hội tụ ở vòng; nhãn cứng đổi so với 150 | 1; 0 | 1; 0 |
| Khớp v1 trên giao có nhãn; số dòng trong giao | 96.87%; 1695 | 96.41%; 1726 |
| Có nhãn mới / mất nhãn so với v1 | 2672 / 4733 | 2737 / 5474 |


## Circularity và giới hạn của kết luận

Không ứng viên nào đọc risk/attack/defensive/style_switch, metadata thời gian cờ, rematch hay ba feature động lực
của P3-B. Do đó không định nghĩa nhãn trực tiếp bằng feature của mô hình đang được đề xuất ở Phase 5. Tuy nhiên:

- z/CPL và adverse_events cùng nguồn engine/chất lượng; calm_rate trực tiếp thêm **move_count** vào provenance.
  Các đặc trưng QUALITY, tốc độ nghĩ, đánh giá engine, kết quả, lịch sử thắng/thua và biến dẫn xuất vẫn phải
  bị chặn; không được đưa z hoặc adverse rate vào mô hình rồi coi điểm cao là xác nhận nhãn.
- Sàn mẫu là một cơ chế chọn hàng. Tỉ lệ theo nước có phương sai lớn hơn ở ván ngắn; tốc độ và CPL cả ván cũng
  thay đổi theo pha/độ dài. Chuẩn hóa số đếm không tự sửa baseline không so khớp độ dài.
- Feature phase fractions và các feature động lực cả ván có thể khôi phục độ dài gián tiếp. Cần cập nhật registry
  cho mọi input mới, audit cả quan hệ phi tuyến và missingness trên TRAIN trong giai đoạn sau. Không kết luận
  “an toàn circularity” chỉ vì tương quan tuyến tính thấp hoặc AUC plies gần 0,5.
- Phủ 17,6–27,0% tùy ứng viên/chính sách nghĩa là đa số hàng vẫn không được phán định. Khớp v1 cao chỉ đo tính
  liên tục trên **giao** có nhãn, không chứng minh đúng hơn và không áp dụng cho các hàng mới được phủ.
- Chưa có nhãn người; không thể báo precision/recall của trạng thái hành vi thực hoặc coi NOT là chắc chắn ổn
  định. Không ép cân bằng theo bucket, không đảo nhãn ngẫu nhiên hay lấy số liệu test để “sửa” prevalence.

## Quyết định cần đưa ra

1. **Chọn ứng viên nào, hoặc không chọn.** Khuyến nghị của L1: **chưa chấp nhận ứng viên nào để thay pipeline**;
   lấy symmetric20 làm phương án nghiên cứu tiếp nếu đích được chốt là proxy suy giảm hành vi *sau thua*.
   Nó giảm vấn đề phân cực độ dài nhưng AUC hai chiều vẫn khoảng 0,646/0,644 và phụ thuộc thua còn nguyên.
   Nếu đích bắt buộc độc lập thua, symmetric20 không đáp ứng; speed_quality20 hiện quá ít dương và còn lệch
   độ dài mạnh, không nên chọn chỉ vì công thức không đọc kết quả. floor40 chỉ nên là phương án đối chứng bảo thủ.
2. **Xử lý test đã xem ở Phase 5 dưới v1.** Đổi nhãn không làm test cũ trở lại nguyên trạng niêm phong. Khuyến nghị
   giữ nguyên test cũ và gắn vai trò đối chiếu/thăm dò; đăng ký trước một holdout mới trước khi thu thêm dữ liệu
   (người chơi mới cho mục tiêu A và/hoặc giai đoạn thời gian mới cho B), đóng băng ứng viên/feature/ngưỡng trước
   khi mở. Không chuyển test cũ vào train hoặc tái chia ngẫu nhiên rồi gọi đó là test độc lập. Nếu chưa có holdout
   mới, chỉ được gọi đánh giá tương lai trên test cũ là kết quả thăm dò, không là xác nhận độc lập. L1 chưa đọc,
   tái gắn nhãn hay tính thống kê feature/label của validation/test.
3. **Tiêu chí chấp nhận nhãn v2.** Cần duyệt và đăng ký trước L2. Đề xuất sau audit (chưa phải cổng đã thông qua):
   sàn mẫu chung; có đường tới hai lớp ở mọi độ dài hợp lệ hoặc cả hai bỏ qua; từng bucket được phủ có >=30
   TILT và >=100 NOT trên TRAIN; tổng phủ >=15% ở cả A/B; max(AUC plies,1−AUC)<=0,60 trên hàng có nhãn và
   chênh tỉ lệ TILT cao nhất–thấp nhất giữa các bucket được phủ <=15 điểm phần trăm. Đây là ngưỡng quy ước cần
   quyết định, không bằng chứng khoa học, và không tune LF để vừa qua cổng trên cùng TRAIN. AUC một biến chưa
   đủ: cần kiểm tra shortcut phi tuyến trong một protocol đã khóa. DS phải hội tụ ở ngân sách đã khóa, có kiểm tra
   độ ổn định nhãn; không gọi EM accuracy là chất lượng thực. Chốt rõ có chấp nhận 100% TILT liên quan thua hay
   không. Muốn chấp nhận như nhãn hành vi đã được kiểm chứng còn cần bộ nhãn người độc lập, làm mù với mô hình,
   phủ cả ván ngắn/dài, thua/thắng/hòa và hàng LF bỏ qua; khóa protocol/cỡ mẫu/tiêu chí trước khi thu. Hiện chưa
   ứng viên nào đủ bằng chứng để được chấp nhận theo toàn bộ đề xuất này.
4. **Có/chạy lại Phase 1–5 thế nào.** Chỉ chạy sau khi chốt ý nghĩa nhãn, ứng viên, cổng và chính sách test. Tạo
   preregistration v2 riêng; giữ bản v1 và artifact cũ nguyên vẹn. Fit label model riêng trên TRAIN từng split,
   đóng băng tham số rồi áp cho tập sau; giữ purge/horizon đủ cho LF tương lai nếu chọn floor40. Nếu làm holdout
   mới, phải đăng ký split và dựng lịch sử chỉ từ quá khứ. Cập nhật registry/provenance và chạy lại audit Phase 0/1,
   chuẩn bị feature Phase 2 (chỉ tái sử dụng nếu xác minh công thức/horizon/hash không đổi), rồi chạy lại toàn bộ
   bước chọn feature, mô hình, calibration và ngưỡng Phase 1/3/5 theo nhãn v2. Chạy lại kiểm định nhãn Phase 4;
   không dùng lại Platt/ngưỡng/F1/gate v1 vì prevalence và quần thể có nhãn thay đổi. Báo B-length/B-result/B-streak,
   theo bucket, theo kết quả, coverage và bootstrap theo cụm người chơi; so v1/v2 trên giao hàng kèm số hàng
   được thêm/bỏ. Các phép huấn luyện này **chưa được thực hiện trong L1** và chỉ có ý nghĩa sau khi protocol mới
   được duyệt. Chỉ mở holdout mới đúng một lần sau đóng băng; nhãn người đánh giá độc lập theo protocol riêng.

## Artifact và tái lập

Ba tệp mới trong repo (không nối vào pipeline v1):

- `src/tilt/labels/weak_labels_v2.py`: vote của ba ứng viên, loader TRAIN-only, diagnostics EM và CLI xuất bảng.
- `tests/unit/test_weak_labels_v2.py`: kiểm tra sàn chung, khả năng đạt hai lớp, missingness, rate thay count,
  ranh giới tốc độ/gap, provenance không đọc kết quả của speed_quality20, parity EM với v1, từ chối mixed split,
  lọc/projection từ Parquet và mẫu số thống kê.
- `reports/label_v2_proposal.md`: báo cáo này.

Trong `~/tilt-labels-v2/`: thiết kế trước kết quả, `audit_supplement.py`, `write_proposal.py` và `train_audit/`:
`audit_results.json` (toàn bộ số, xác suất/nhãn chỉ được tổng hợp), `summary.csv`, `lf_inventory.csv`,
`lf_pairs.csv`, `ply_buckets.csv`, `result_breakdown.csv`, `lf_strata.csv`, `supplement.json`, `provenance.json`.
Không xuất bảng theo ván/người. `provenance.json` ghi hash mã/thiết kế và phiên bản thư viện; kết quả chính có
hash của **riêng bảng TRAIN đã chiếu**, không hash bảng validation/test. Chạy lại vào thư mục mới để giữ artifact.

```bash
cd ~/lichess-workspace/tilt
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -m tilt.labels.weak_labels_v2 \
  --aligned ~/tilt-phase1/aligned --out ~/tilt-labels-v2/reproduction-new
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python ~/tilt-labels-v2/audit_supplement.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python ~/tilt-labels-v2/write_proposal.py
```

Supplement cố ý ghi vào `train_audit/`; main CLI từ chối ghi đè `audit_results.json`. Thiết kế chỉ có ba ứng viên;
v1 là mốc, chạy thêm vòng EM không tạo ứng viên thứ tư. Mỗi lệnh audit hoàn tất trong vài giây, giới hạn một
thread BLAS/OMP; không có lệnh tính toán dữ liệu thật gần ngưỡng 10 phút CPU.

## Kiểm tra

**195 passed, 1 warning trong 50.20 giây**; không bỏ qua test nào.
Gồm 50 test mới và 145 test hiện có. Warning là deprecation của
Starlette/AnyIO, không phải lỗi. Hash của 65 tệp nguồn/test/báo cáo/docs cũ trước và
sau suite giống nhau; nhánh vẫn là `private/ai-coach-tilt`. Không commit, push hoặc đổi nhánh.

Lệnh mặc định đã được thử nhưng treo ở integration Stockfish; lần chẩn đoán tiếp theo cho thấy TestClient cũng
treo. Thử nghiệm socketpair cục bộ trả `PermissionError: EPERM` khi gửi byte đánh thức asyncio. Đây là lỗi môi
trường chạy, tái hiện được ngoài code v2. Log và stack trace giữ trong `full_test_suite.log`,
`full_test_suite_retry.log`, `tests_without_engine.log`. Không coi những lần bị ngắt đó là pass.

Để hoàn tất **toàn bộ suite, kể cả Stockfish thật và TestClient**, tạo duy nhất bộ tương thích
`~/tilt-labels-v2/test_runtime/sitecustomize.py`: selector của asyncio thức tối đa mỗi 20 ms để chạy callback
đã xếp hàng, thay vì phụ thuộc vào tín hiệu self-pipe bị sandbox chặn. Không sửa tệp repo/venv cũ, không bỏ qua
test, không thay engine, không mock assertion. Smoke test Stockfish + TestClient hoàn tất trong 0,35 giây;
suite đầy đủ ở trên dùng runtime này. Không khẳng định suite mặc định đã chạy thành công trong sandbox.

```bash
cd ~/lichess-workspace/tilt
PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  PYTHONPATH=/home/trantrien/tilt-labels-v2/test_runtime:/home/trantrien/lichess-workspace/tilt/src \
  .venv/bin/python -m pytest -q -p no:cacheprovider -o faulthandler_timeout=60
```

Log hoàn tất: `~/tilt-labels-v2/full_test_suite_polling.log`; tóm tắt máy đọc:
`~/tilt-labels-v2/test_verification.json`. `existing_files_before_tests.json` lưu dấu kiểm nguyên vẹn tệp cũ.
Các test hiện có dùng fixture tổng hợp và có fit mô hình trên fixture; đó là kiểm tra bắt buộc, không là
huấn luyện/đánh giá mô hình trên dữ liệu TRAIN thật. Các lệnh audit nhãn không dùng runtime tương thích này.
