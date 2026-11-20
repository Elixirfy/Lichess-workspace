# Phase 2: feature hành vi

Ngày 2026-11-14. Phase 2 chỉ định nghĩa, tính và kiểm tra feature. Chưa huấn luyện hay ablation: việc đó thuộc
Phase 3. Không đổi LF hay công thức nhãn yếu. Mọi số liệu audit dưới đây chỉ lấy từ dòng **train**. Ở validation chỉ
đo tỉ lệ thiếu, không đọc nhãn. Tập test vẫn niêm phong.

Kết quả là dự đoán nhãn yếu, không phải phát hiện cảm xúc tức giận.

## Tóm tắt

- Có 17 feature mới, chia 3 nhóm. Tất cả chỉ đọc 4 cờ hình học của nước đi (attack, risk, defensive, style_switch) và
  số ply. Không feature nào đọc engine, đồng hồ, rating, kết quả ván hay input của LF.
- Không có dữ liệu tương lai: 0/72.575 ván có ván lịch sử kết thúc sau khi ván hiện tại bắt đầu.
- `*_z_personal` của risk/attack/style_switch khớp tuyệt đối với `deviation_*_rate_z` có sẵn: sai khác 0,0 trên
  36.493 dòng. Cách tính baseline vì vậy đúng như pipeline cũ.
- Audit cơ học hiện có cho qua 7 feature và loại 10. Cả 10 feature bị loại đều do **chỉ báo thiếu**. Phần giá trị
  của chúng có |ρ| với mọi đại lượng LF ≤ 0,47, và AUC so với kết quả ván ≤ 0,67 (ngưỡng 0,70).
- Đường tắt độ dài lại xuất hiện, lần này qua giá trị thiếu: dòng train có nhãn mà feature động trong ván bị thiếu thì
  **100% là TILT**, vì thiếu nghĩa là ván dưới khoảng 9 nước của mình.
- 4 tỉ lệ tiền tố 40 ply (nhóm D) sạch nhất: không thiếu giá trị, η² so với độ dài 0,03–0,07, và chỉ 0,003–0,016 trên
  ván ≥ 40 ply.
- Feature lệch cá nhân (nhóm A) gần như trùng tỉ lệ thô đã có trong M3: Spearman 0,90–0,95.

## Code và test

- `src/tilt/features/behavior.py`: `game_dynamics` (nhóm B, D), `personal_deviations` (nhóm A), `build`.
- `tests/unit/test_behavior.py`: 8 test, gồm:
  - cold start (dưới 5 ván trước thì NaN, không lấy baseline của cả nhóm);
  - MAD = 0 thì dùng sàn 0,05;
  - ván chồng thời gian không được tính là lịch sử;
  - lịch sử tách theo tốc độ và giới hạn 200 ván;
  - ván ngắn thì NaN;
  - một chuỗi đã biết đáp án;
  - entropy bằng 0;
  - tên feature qua được `forbidden(strict=True)` và không thuộc input LF.
- Toàn bộ `tests/unit`: 33/33 qua.
- Dữ liệu tính ra chỉ nằm trong WSL, ở `~/tilt-phase2/`: `behavior_features.parquet` (id đã HMAC), `audit.csv`,
  `representations.json`, `dynamics_missing.json`, `report.json`. Script tính và audit nằm ngoài repo (scratchpad
  phiên làm việc). Chưa đưa vào repo vì Phase 3 sẽ có module đánh giá riêng.

## Định nghĩa

Thời điểm dự đoán là lúc ván kết thúc, nên mọi nước của ván hiện tại đều dùng được. Mỗi feature tính cho một người
chơi trong một ván, chỉ từ nước của chính người đó. Chi tiết từng feature nằm trong `phase2_feature_registry.csv`.

**Nhóm A, lệch so với chính mình** (8 feature): `{attack,risk,defensive,style_switch}_{delta,z}_personal`.

- `delta` = tỉ lệ của ván này trừ median của tối đa 200 ván trước. Các ván trước phải cùng tốc độ và có
  `end_upper_ms < start_ms`.
- `z` = `delta / max(1,4826·MAD, 0,05)`.
- Dưới 5 ván trước thì NaN. Các quy ước này giống `features.py`.
- `defensive` là feature mới hẳn, vì pipeline cũ không có baseline cho nó.

**Nhóm B, động lực trong ván** (5 feature):

| Feature | Định nghĩa | Thiếu khi |
|---|---|---|
| `attack_trend_3w` | tỉ lệ tấn công ở 1/3 cuối trừ 1/3 đầu của các nước mình đi | dưới 9 nước |
| `risk_volatility_3w` | độ lệch chuẩn của tỉ lệ risk qua 3 phần ba | dưới 9 nước |
| `style_entropy` | entropy Shannon chuẩn hóa của hỗn hợp tấn công > risk > phòng thủ > yên lặng | dưới 6 nước |
| `behavior_change_point` | \|trung bình sau − trung bình trước\| của cờ risk tại điểm cắt đơn có sai số bình phương nhỏ nhất, mỗi bên ≥ 5 nước | dưới 10 nước |
| `behavior_persistence` | tự tương quan trễ 1 của cờ attack | dưới 6 nước, hoặc cờ không đổi |

**Nhóm D, tiền tố cố định độ dài** (4 feature, thêm vào vì kết quả Phase 1):
`{attack,risk,defensive,style_switch}_rate_p40` là tỉ lệ cờ trên các nước mình đi có `ply ≤ 40`. Mọi ván đều có
tiền tố này, nên feature không bị thiếu. Độ dài của tiền tố chỉ khác nhau khi ván dưới 40 ply.

## Kiểm tra thời điểm

| Kiểm tra | Kết quả |
|---|---|
| Ván lịch sử kết thúc trước khi ván hiện tại bắt đầu | 0 vi phạm / 72.575 |
| Thứ tự kích hoạt lịch sử | khóa (`end_upper_ms`, `game_id`), so sánh chặt `<`, giống `PriorHistory` |
| `risk/attack/style_switch_z_personal` so với `deviation_*_rate_z` | 36.493 dòng có cả hai, sai khác tối đa 0,0. Không dòng nào chỉ một bên có giá trị |
| Phủ của nhóm A | 97,3% dòng aligned. Dòng train có nhãn bị thiếu: 5 (by_player), 15 (by_time) |

## Audit rò rỉ (train)

Dùng nguyên các hàm `audit_outcome_proxies` và `audit_lf_proxies` trong `model_features.py`, chỉ trỏ chúng vào 17
feature mới. Ngưỡng giữ nguyên:

- AUC so với thua hoặc thua vì hết giờ > 0,70 thì loại;
- |ρ Spearman| với một đại lượng LF ≥ 0,6, xét trên dạng observed, imputed hoặc missing, thì loại.

Bảng dưới lấy giá trị lớn nhất của hai split.

| Feature | Audit cơ học | \|ρ\| LF, giá trị | \|ρ\| LF, chỉ báo thiếu | AUC kết quả ván |
|---|---|---|---|---|
| `attack_delta_personal` | loại | 0,455 | 1,000 | 0,665 |
| `attack_z_personal` | loại | 0,448 | 1,000 | 0,663 |
| `risk_delta_personal` | loại | 0,150 | 1,000 | 0,540 |
| `risk_z_personal` | loại | 0,149 | 1,000 | 0,541 |
| `defensive_delta_personal` | loại | 0,391 | 1,000 | 0,602 |
| `defensive_z_personal` | loại | 0,383 | 1,000 | 0,601 |
| `style_switch_delta_personal` | loại | 0,154 | 1,000 | 0,525 |
| `style_switch_z_personal` | loại | 0,152 | 1,000 | 0,526 |
| `attack_trend_3w` | qua | 0,428 | 0,545 | 0,663 |
| `risk_volatility_3w` | qua | 0,356 | 0,545 | 0,597 |
| `style_entropy` | loại (by_player) | 0,467 | 0,624 | 0,584 |
| `behavior_change_point` | qua | 0,187 | 0,518 | 0,573 |
| `behavior_persistence` | loại | 0,301 | 0,660 | 0,605 |
| `attack_rate_p40` | qua | 0,305 | không thiếu | 0,565 |
| `risk_rate_p40` | qua | 0,169 | không thiếu | 0,554 |
| `defensive_rate_p40` | qua | 0,255 | không thiếu | 0,545 |
| `style_switch_rate_p40` | qua | 0,168 | không thiếu | 0,543 |

Giải thích các trường hợp bị loại. Tương quan không tự chứng minh rò rỉ, nên dưới đây ghi rõ cơ chế:

- **Nhóm A.** Chỉ báo thiếu có nghĩa là "chưa đủ 5 ván trước". Nó trùng hoàn toàn với chỉ báo thiếu của
  `baseline_mean_accuracy_median` và `deviation_mean_cpl_z`, là input của LF. Đây đúng là trường hợp Phase 0 đã gặp
  với 13 feature lịch sử, xếp loại "coverage, cần xem xét". Phần giá trị không chạm ngưỡng.
- **`style_entropy`, `behavior_persistence`.** Chỉ báo thiếu (ván rất ngắn) tương quan 0,62/0,66 với
  `last_adverse_distance__missing`. Ở by_time, `style_entropy` chỉ 0,589 nên qua. Theo nguyên tắc fail closed của
  pipeline, feature vẫn bị loại nếu một split loại.

## Độ dài ván

η² theo thập phân vị của feature so với `lf_input__plies`, trên train. Chỉ ghi lại, không dùng để loại. Để so sánh,
`defensive_rate` của M3 có η² 0,156.

| Feature | η² mọi ván | η² ván ≥ 40 ply | Dòng có nhãn bị thiếu → tỉ lệ TILT |
|---|---|---|---|
| `risk_volatility_3w` | **0,221** | 0,123 | 127 → 100% |
| `style_entropy` | 0,137 | 0,089 | 67 → 100% |
| `attack_delta_personal` / `_z` | 0,123 / 0,116 | 0,075 / 0,078 | 5 → 80% |
| `defensive_z_personal` | 0,110 | 0,061 | 5 → 80% |
| `behavior_persistence` | 0,103 | 0,052 | 79 → 100% |
| `behavior_change_point` | 0,088 | 0,060 | 141 → 100% |
| `attack_trend_3w` | 0,040 | 0,022 | 127 → 100% |
| 4 tỉ lệ `*_p40` | 0,028–0,072 | **0,003–0,016** | không thiếu |

Số dòng ở cột cuối là của by_player; by_time cho cùng kết luận (xem `dynamics_missing.json`). Ván dài nhất trong các
dòng thiếu là 17–31 ply, nên các dòng này đều dưới 40 ply. Phase 1 đã cho thấy mọi dòng có nhãn dưới 40 ply đều là
TILT.

Như vậy, giá trị của nhóm B vẫn mang một phần độ dài, rõ nhất là `risk_volatility_3w`. Chỉ báo thiếu của nhóm B mang
**trọn vẹn** đường tắt độ dài, kể cả 3 feature mà audit cơ học cho qua. Imputer của mô hình (`add_indicator=True`) sẽ
đưa chỉ báo này vào mô hình.

## Trùng lặp với M3

Spearman lớn nhất với 8 feature của M3, trên train:

- nhóm A: 0,90–0,95 với tỉ lệ thô tương ứng (ví dụ `risk_delta_personal` ~ `risk_rate` 0,954). Lệch so với median cá
  nhân gần như chỉ là tỉ lệ thô dịch đi một khoảng;
- nhóm D: 0,60–0,77;
- nhóm B: 0,31–0,77; trong đó `style_entropy` ~ `defensive_rate` là 0,773.

## Liên hệ với nhãn yếu

Chỉ ghi lại: max(AUC, 1 − AUC) của từng feature riêng lẻ, trên train có nhãn. Số này **không** dùng để chọn feature.

| | Mọi ván | Ván ≥ 40 ply |
|---|---|---|
| `attack_delta_personal` / `_z` | 0,648 | 0,578 |
| `style_entropy` | 0,606 | 0,538 |
| `risk_volatility_3w`, `defensive_*_personal` | 0,59 | 0,52–0,55 |
| Các feature còn lại | 0,50–0,57 | 0,50–0,53 |

## Không làm, và lý do

| Đề xuất trong plan | Lý do không đủ điều kiện |
|---|---|
| lệch cá nhân của `unsound_attack` | cờ cần đánh giá engine (token `unsound`) |
| lệch cá nhân của `sacrifice` | `sacrifice_rate` dùng bộ lọc eval bằng nhau / CPL (bị cấm theo tên) |
| đổi phong cách sau sự kiện bất lợi | sự kiện là adverse event của engine (`post_event`, `adverse`) |
| biến thể theo sự kiện mất quân | mất quân là đại diện cho kết quả ván (`material`) |
| attack × áp lực thời gian | đọc đồng hồ (`clock_fraction`, `think`); đồng hồ cuối ván là đại diện cho kết quả |
| risk_delta × thua ván trước | thua ván trước chính là input LF `previous_result_score` |
| style_switch × tiến độ phiên | `games_in_session_before` bị chặn ở chế độ strict; khoảng nghỉ trong phiên là input LF |

Không feature mới nào lặp lại công thức nhãn yếu. Feature không đọc input của LF nào. Với các đại lượng LF, phần giá
trị đều có |ρ| ≤ 0,47.

## Đối chiếu tiêu chí chấp nhận

| Tiêu chí | Kết quả |
|---|---|
| Feature tính đúng thời điểm | đạt: 0 vi phạm, trùng khớp với pipeline |
| Baseline không dùng dữ liệu tương lai | đạt: `end_upper_ms < start_ms`, có test |
| Unit test cho cold start và giá trị thiếu | đạt: 8 test |
| Không feature mới nào lặp công thức nhãn yếu | đạt về giá trị. Chỉ báo thiếu của nhóm A trùng chỉ báo thiếu của input LF, xem phần audit |
| Mỗi feature mới báo η² so với độ dài ván | đạt: có cả mọi ván và ván ≥ 40 ply |

## Cần quyết định trước Phase 3

Phase 2 dừng ở đây. Các điểm dưới đây là lựa chọn cho Phase 3, chưa áp dụng:

1. **Nhóm A.** Có hai lựa chọn:
   - theo audit cơ học thì loại;
   - hoặc xử lý như 13 feature lịch sử ở Phase 1: đưa vào một biến thể đã đăng ký trước, kèm ghi chú "coverage".

   Lưu ý khi chọn:
   - Phase 1 đã loại lịch sử (M2 − M1 = +0,008 / −0,012);
   - nhóm A gần như trùng tỉ lệ thô đã có trong M3.
2. **Chỉ báo thiếu của nhóm B.** Có ba lựa chọn:
   - giữ, và chấp nhận rằng chỉ báo này mã hóa "ván dưới khoảng 9 nước", tức 100% TILT;
   - bỏ chỉ báo riêng cho nhóm B (imputer `add_indicator=False` cho các cột này);
   - chỉ đánh giá nhóm B trên ván ≥ 40 ply.

   Cả hai lựa chọn sau đều là thay đổi cách đánh giá, cần duyệt.
3. **Nhóm D** qua mọi audit và ít phụ thuộc độ dài nhất. Biến thể tự nhiên là M3 + D.

   Vì M3 đã chứa tỉ lệ cả ván, cần quyết định giữ cả hai hay thay tỉ lệ cả ván bằng tỉ lệ p40. Thay thế sẽ giảm η² của
   M3: `defensive_rate` có η² 0,156, còn `defensive_rate_p40` có 0,028.
4. Chỉ số phụ đã đăng ký là PR-AUC trên ván ≥ 40 ply, theo đề xuất đã duyệt. Phase 3 sẽ báo chỉ số này cạnh PR-AUC
   chính cho mọi biến thể.

## Bổ sung sau Phase 3 (2026-11-14)

Nhóm D có lỗi cấu tạo, phát hiện ở Phase 3 (xem `phase3_evaluation.md`, mục "Thay đổi sau đăng ký"):

- Với ván dưới 40 ply, tỉ lệ p40 bằng đúng tỉ lệ cả ván ở 100% dòng train; với ván dài thì khoảng 2%.
- Với ván ≥ 40 ply, mọi tỉ lệ p40 là bội của 1/20; với ván ngắn thì 18%.

Như vậy, khi đi cùng tỉ lệ cả ván, nhóm D mã hóa "ván dưới 40 ply". Nhận định "sạch nhất" ở trên là sai. Nhóm D đã bị
rút khỏi danh sách ứng viên. Các số liệu audit ở trên không đổi.
