# Phát hiện tilt trong cờ blitz: báo cáo tổng kết

Ngày 2026-11-17. Phạm vi: module Tilt của dự án Lichess, từ thu thập dữ liệu tới chạy trên web.

## 1. Tóm tắt

- **Mục tiêu.** Hệ thống ước tính, cho từng ván blitz, khả năng người chơi đang "tilt": chơi kém đi rõ rệt so với
  chính mình, ngay sau các ván thua trong cùng phiên chơi. Kết quả là điểm 0–100 và một trong ba mức Thấp, Đáng
  chú ý, Cao.
- **Dữ liệu.**
  - 404 người chơi blitz trên Lichess, chọn phân tầng theo rating từ 400 tới 3000;
  - 67.014 lượt người–ván (mỗi hàng là một người chơi trong một ván);
  - toàn bộ nước đi có đánh giá Stockfish và thời gian suy nghĩ.
- **Nhãn.** Bộ luật tất định gồm 5 luật ngữ cảnh trong phiên và 7 luật bằng chứng hành vi. Luật cho ra TILT, NOT
  hoặc bỏ phiếu trắng khi chưa đủ dấu hiệu.
- **Mô hình M-v3.** XGBoost có hiệu chỉnh xác suất. Mô hình chỉ dùng thông tin đã có trước ván và 20 nửa nước đầu
  của ván, tức là đoán trước kết luận mà bộ luật sẽ đưa ra khi ván xong.
- **Kết quả trên hai tập giữ riêng chưa từng dùng khi xây dựng:**
  - PR-AUC 0,458 (người chơi mới) và 0,451 (giai đoạn thời gian về sau). Tỉ lệ TILT nền chỉ khoảng 0,075.
  - Mô hình tốt nhất trong các mốc so sánh chỉ đạt 0,267 / 0,253.
  - M-v3 hơn mọi mốc so sánh ở cả ván ≥ 40 lẫn < 40 nửa nước, với khoảng tin cậy 95% nằm hẳn trên 0 ở cả 16 ô so
    sánh.
  - Sai số hiệu chỉnh (ECE) 0,006 / 0,005.
- **Triển khai.** Mô hình chạy trên site lila local:
  - tab "Tilt" trong trang ván, chỉ người chơi ván đó thấy;
  - trang `/account/tilt` có thống kê;
  - banner gợi ý nghỉ ngắn ở trang chủ;
  - giao diện song ngữ Việt/Anh.
- **Kiểm thử.**
  - 626 test Python, 14 test Scala;
  - 52/52 kiểm tra trình duyệt (Playwright) trên web local;
  - đường chấm điểm trực tiếp khớp tuyệt đối với kết quả lúc huấn luyện.

## 2. Bài toán

### 2.1 Định nghĩa
"Tilt" ở đây là một **mẫu hành vi**, không phải cảm xúc: một ván được chơi trong ngữ cảnh thua liên tiếp trong
phiên, và trong ván đó người chơi có nhiều dấu hiệu chơi kém hoặc vội so với mức thường lệ của chính họ. Hệ thống
không đo cảm xúc. Giao diện cũng nói rõ điều đó với người chơi.

### 2.2 Cách tiếp cận: chưng cất luật theo mốc thời gian
- **Bộ luật** (mục 4) kết luận sau khi ván kết thúc. Nó được xem toàn bộ ván, kết quả, cách kết thúc và cả việc
  người chơi có vào ván mới ngay hay không.
- **Mô hình** (mục 6) chỉ được dùng những gì đã biết tại thời điểm dự đoán:
  - mọi ván trước đó của người chơi (chỉ những ván chắc chắn đã kết thúc);
  - ngữ cảnh phiên chơi;
  - mức thường lệ của người chơi;
  - thể thức, rating, màu quân;
  - 20 nửa nước đầu của ván đang xét.
- Nhờ vậy mô hình cho tín hiệu sớm, ngay sau 20 nửa nước, thay vì phải chờ hết ván. Bộ luật là "giáo viên", mô hình
  học cách đoán trước kết luận của giáo viên.

### 2.3 Hai thời điểm dự đoán
| Đầu mô hình | Khi nào | Dùng gì |
|---|---|---|
| `pre` | đầu ván, áp dụng cho mọi ván | chỉ thông tin trước ván (73 đặc trưng) |
| `p20` | khi đã đi đủ 20 nửa nước | thêm 31 đặc trưng từ 20 nửa nước đầu (tổng 104) |

Điểm cuối cùng của một ván lấy từ đầu `p20` nếu ván có ít nhất 20 nửa nước, ngược lại lấy từ đầu `pre`. Ván ngắn
không bao giờ nhận giá trị giả hay cờ đánh dấu "ván ngắn", để mô hình không học lối tắt từ độ dài ván.

## 3. Dữ liệu

### 3.1 Chọn người chơi
- Nguồn: bản dump tháng 10/2026 của Lichess (database.lichess.org), đọc dạng stream, không giải nén ra đĩa.
- Phân tầng: 13 dải rating blitz rộng 200 điểm, từ 400 tới 3000. Trong mỗi dải, người chơi được chọn theo hash với
  seed cố định. Hai nhóm người chơi được chọn theo cùng cách này.
- Nhóm 2 còn được sàng lọc thêm:
  - loại tài khoản BOT, tài khoản vi phạm điều khoản (`tosViolation`) và tài khoản đã đóng (qua API công khai);
  - loại mọi người đã có trong nhóm 1;
  - mỗi người cần ít nhất 60 ván blitz, người không đủ được thay bằng người dự phòng cùng dải.
- Lấy các ván blitz gần nhất của mỗi người qua API export của Lichess: nhóm 1 tới 300 ván, nhóm 2 tối đa 150 ván.
  Cách tải:
  - mỗi lúc chỉ có một request;
  - gặp 429 thì chờ đủ 60 s;
  - lưu nguyên response gzip theo người chơi;
  - có cursor để tải tiếp khi bị ngắt.

| Nhóm | Người chơi | Lượt người–ván |
|---|---:|---:|
| Nhóm 1 | 196 | 36.401 |
| Nhóm 2 (không trùng nhóm 1) | 208 | 30.613 |
| **Tổng** | **404** | **67.014** |

### 3.2 Phân tích bằng Stockfish
- Mọi thế cờ được phân tích với ngân sách cố định: 5.000 node, MultiPV 2, hash 32 MB, 1 luồng, engine reset cho
  từng thế cờ.
- Với từng nước, hệ thống tính centipawn loss (CPL) và phân loại inaccuracy/mistake/blunder theo công thức của
  Lichess.
- Cache khóa bằng FEN đầy đủ + cấu hình engine, nên chạy lại cho kết quả giống hệt mà không phải tìm kiếm lại.
- Nhóm 2 có 1.874.225 thế cờ. Phân tích lại 500 thế cờ trên ba máy khác nhau cho kết quả trùng khớp 500/500.
- Độ phủ:
  - 100% nửa nước có đánh giá engine;
  - 96,2% nước đi của người chơi có thời gian suy nghĩ (lấy từ đồng hồ).

### 3.3 Phiên chơi và mức thường lệ
- **Phiên chơi.** Phiên mới bắt đầu khi khoảng nghỉ giữa lúc kết thúc ván trước và lúc bắt đầu ván sau lớn hơn
  30 phút.
- **Lịch sử hợp lệ.** Với ván g, chỉ dùng các ván của cùng người chơi đã kết thúc trước lúc g bắt đầu. Thời điểm
  kết thúc lấy theo cận trên bảo thủ.
- **Mức thường lệ (baseline).** Lấy tối đa 200 ván blitz gần nhất thỏa điều kiện trên. Mỗi chỉ số được so bằng
  z-score bền vững: `z = (x − trung vị) / max(1,4826 × MAD, sàn)`. Sàn là một ngưỡng tối thiểu cố định cho từng
  chỉ số, tránh chia cho số quá nhỏ. Cần ít nhất 5 ván có giá trị, nếu không thì để trống, không điền trung bình
  quần thể.

### 3.4 Chia dữ liệu
Có hai kiểu tách, áp dụng cả cho tập kiểm định lẫn tập đánh giá cuối:
- **theo người chơi**: người chơi chưa từng thấy;
- **theo thời gian**: các ván diễn ra sau.

Nhờ vậy kết quả cho biết mô hình có dùng được cho người mới và cho tương lai hay không.

| Phần | Người chơi | Lượt người–ván | Cách chọn | Dùng để |
|---|---:|---:|---|---|
| Train | 270 | 34.520 | phần còn lại | huấn luyện |
| V_A | 67 | 9.792 | 20% người chơi, theo hash | hiệu chỉnh xác suất, kiểm định |
| V_B | 271 | 7.961 | các phiên từ ván ở phân vị 85 thời gian trở đi | hiệu chỉnh xác suất, kiểm định |
| A′ | 65 | 9.665 | 30% người chơi nhóm 2 mỗi dải rating, theo hash | đánh giá cuối, người chơi mới |
| B′ | 143 | 4.989 | các phiên từ ván ở phân vị 80 thời gian trở đi (nhóm 2) | đánh giá cuối, thời gian về sau |

- Không phiên chơi nào bị cắt ngang ranh giới.
- Một ván có hai người chơi thuộc hai phần khác nhau thì hàng phía phát triển bị loại khỏi tập mục tiêu, để tránh rò
  rỉ.
- A′ và B′ được giữ kín tới bước đánh giá cuối: không gán nhãn, không dựng đặc trưng, không xem thống kê. Chúng
  được chấm đúng một lần.

## 4. Gán nhãn bằng luật

### 4.1 Luật ngữ cảnh trong phiên (C1–C5)
Chỉ dùng các ván trước đó trong cùng phiên.

| Luật | Kích hoạt khi |
|---|---|
| C1 chuỗi thua | thua liên tiếp ≥ 2 ván trong phiên (hòa bỏ qua, gặp ván thắng thì dừng đếm) |
| C2 thua dồn | thua ≥ 3 trong 5 ván gần nhất, hoặc ≥ 5 trong 10 ván gần nhất |
| C3 tải thua | `D = Σ thua_k · 0,5^((k−1)/2)` trên ≤ 10 ván gần nhất, D ≥ 2,0 (ván thua càng gần càng nặng) |
| C4 tụt rating | rating giảm ≥ 30 điểm so với đầu phiên |
| C5 vào ván vội | ván bắt đầu ≤ 120 s sau ván thua gần nhất, và khoảng nghỉ ngắn dần qua 3 ván |

Mức ngữ cảnh:
- **mạnh**: ≥ 2 luật C kích hoạt;
- **yếu**: 1 luật C, hoặc ván ngay trước bị thua;
- **cũ**: không luật C nào, ván trước không thua, nhưng có thua trong 5 ván gần nhất;
- **không**: không có ván thua gần đây, gồm cả ván đầu phiên.

### 4.2 Luật bằng chứng hành vi (E1–E7)
E1–E5 so với mức thường lệ của chính người chơi (mục 3.3).

| Luật | Chỉ số | Kích hoạt khi |
|---|---|---|
| E1 độ chính xác | CPL trung bình (cắt ở 300) | z ≥ 1 |
| E2 blunder | số blunder trên 20 nước | z ≥ 1 |
| E3 đi vội | trung vị thời gian nghĩ / (thời gian ban đầu + 40 × gia số) | z ≤ −1 |
| E4 nhịp thất thường | hệ số biến thiên của thời gian nghĩ | z ≥ 1 |
| E5 liều lĩnh | trung bình z của tỉ lệ nước mạo hiểm, nước tấn công, nước thí quân | ≥ 1 |
| E6 bỏ cuộc sớm | ván thua: xin thua khi còn ≥ 20% cơ hội thắng; bỏ ván; hoặc thua hết giờ dù ở nước cuối còn ≥ 20% thời gian ban đầu | một trong các điều kiện |
| E7 vào lại ngay | ván thua: ván kế tiếp cùng phiên bắt đầu sau ≤ min(phân vị 20 khoảng nghỉ của người đó, 60 s) | thỏa |

Mỗi luật E có ba trạng thái: kích hoạt, không kích hoạt, hoặc thiếu dữ liệu. Thiếu dữ liệu không bao giờ được tính là
kích hoạt.

### 4.3 Kết hợp
Một ván chỉ được xét khi có ≥ 5 nước của người chơi có đánh giá engine và có mức thường lệ.

| Kết luận | Điều kiện |
|---|---|
| **TILT** | CPL cao hơn mức thường lệ (z > 0), và: ngữ cảnh mạnh + ≥ 2 bằng chứng, hoặc ngữ cảnh yếu + ≥ 3 bằng chứng. Ván **thắng** cần ngữ cảnh mạnh, ≥ 3 bằng chứng, trong đó có E1 hoặc E2 |
| **NOT** | tổng số luật kích hoạt và thiếu dữ liệu ≤ 1, và (ngữ cảnh "không" hoặc CPL không cao hơn mức thường lệ) |
| **Bỏ phiếu trắng** | mọi trường hợp còn lại |

Nhờ có vùng bỏ phiếu trắng, các ván mơ hồ không bị gán nhãn ép. Mô hình chỉ học và chỉ được chấm trên các ván có
kết luận rõ. Bộ luật được viết thành một module duy nhất. Mọi hằng số nằm trong một dataclass đóng băng có hash
thiết kế, kèm 74 test đơn vị bao phủ từng ô của bảng kết hợp.

### 4.4 Thống kê nhãn (tập train)
| Chỉ số | Giá trị |
|---|---|
| Hàng có kết luận (TILT hoặc NOT) | 55,4% |
| Tỉ lệ TILT trong các hàng có kết luận | 7,6% (1.443 TILT, 17.659 NOT) |
| Ván thắng trong số TILT | 4,9% |
| Chênh tỉ lệ TILT giữa ván < 40, 40–79 và ≥ 80 nửa nước | 9,5 điểm phần trăm |

Hai nhóm người chơi cho số liệu gần như nhau: tỉ lệ có kết luận 55,6% và 54,9%, tỉ lệ TILT 7,7% và 7,3%.

## 5. Đặc trưng

### 5.1 Các nhóm đặc trưng
| Khối | Nhóm | Số cột | Nội dung |
|---|---|---:|---|
| trước ván | thông tin ván | 5 | thời gian ban đầu, gia số, rating, chênh rating với đối thủ, màu quân |
| trước ván | ngữ cảnh phiên | 20 | chuỗi thua, số thua trong 5/10 ván, D, chênh rating trong phiên, số ván và thời lượng phiên, các khoảng nghỉ, C1–C5, mức ngữ cảnh |
| trước ván | lịch sử | 4 | chuỗi tái đấu, chuỗi thua, thời gian nghỉ trước ván, phong độ gần đây |
| trước ván | ván ngay trước | 21 | chỉ số và z của E1–E5, trạng thái E1–E7, nhãn, độ dài, cách kết thúc của ván trước trong phiên |
| trước ván | hành vi trong phiên | 7 | trung bình z E1–E5 của 3 ván gần nhất, số ván TILT và số bằng chứng trung bình của 10 ván gần nhất |
| trước ván | mức thường lệ | 16 | trung vị và MAD của 7 chỉ số hành vi, số ván làm mốc |
| 20 nửa nước đầu | chất lượng | 6 | CPL, CPL lớn nhất, số inaccuracy/mistake/blunder, CPL của đối thủ |
| 20 nửa nước đầu | thời gian | 5 | trung vị và độ biến thiên thời gian nghĩ, lần nghĩ lâu nhất, phần đồng hồ đã dùng, thời gian nước đầu |
| 20 nửa nước đầu | phong cách | 8 | tỉ lệ nước mạo hiểm/tấn công/phòng thủ/đổi kiểu/thí quân, 3 chỉ số động lực |
| 20 nửa nước đầu | thế cờ | 5 | cơ hội thắng sau nửa nước 20 và thấp nhất trong đoạn, cân bằng quân, số nước hợp lệ, giai đoạn ván |
| 20 nửa nước đầu | so với thường lệ | 7 | z của CPL, thời gian và phong cách so với 20 nửa nước đầu của các ván trước |

Nhãn và trạng thái luật của các ván **trước** là đặc trưng hợp lệ, vì chúng chỉ phụ thuộc dữ liệu có trước khi ván
đang xét bắt đầu.

### 5.2 Chống rò rỉ
Danh sách đặc trưng được kiểm tra bằng 9 nhóm test tự động:
1. **Danh sách cho phép:** ma trận mô hình không chứa kết quả, cách kết thúc, độ dài, bất kỳ tổng hợp cả ván nào,
   hay giá trị luật E của chính ván đó.
2. **Nhiễu tương lai:** sửa nước đi sau nửa nước 20, kết quả, giờ kết thúc, hoặc xóa các ván sau; đặc trưng phải
   giữ nguyên từng byte.
3. **Cắt dữ liệu:** đặc trưng dựng từ dữ liệu đầy đủ bằng đặc trưng dựng từ dữ liệu đã cắt tại thời điểm dự đoán.
4. **Độc lập trước ván:** xóa toàn bộ nước đi của ván không làm đổi đặc trưng trước ván.
5. **Độc lập mức thường lệ:** đổi độ dài ván không làm đổi mức thường lệ.
6. **Đủ 20 nửa nước:** mọi hàng `p20` dùng đúng 20 nửa nước; ván ngắn hơn không có giá trị `p20` nào.
7. **Cách ly tập giữ riêng:** bộ dựng đặc trưng từ chối hàng thuộc A′/B′.
8. **Tất định:** hai lần dựng cho cùng hash.
9. **Hồi quy nhãn:** nhãn tính lại khớp 100% với bản gốc.

Ngoài ra có phép dò độ dài ván: đo xem từng đặc trưng một mình phân biệt ván ngắn tốt tới đâu, dùng để theo dõi lối
tắt từ độ dài.

## 6. Mô hình M-v3

- **Thuật toán.** XGBoost, cấu hình cố định: 100 cây, độ sâu 3, learning rate 0,06, subsample 0,85, colsample
  0,85, `reg_lambda` 3, seed 42. Không tìm siêu tham số, không dừng sớm, không chọn đặc trưng theo kết quả kiểm
  định, nên không có chỗ để "học thuộc" tập kiểm định.
- **Tiền xử lý.** Fit trên tập train rồi đóng băng:
  - điền trung vị kèm cột chỉ báo thiếu (một giá trị thiếu ở đây mang nghĩa thật, ví dụ "chưa có ván trước trong
    phiên");
  - sau đó chuẩn hóa.
- **Mất cân bằng lớp.** Trọng số mẫu `balanced`, chỉ dùng trong train.
- **Hiệu chỉnh xác suất.** Platt scaling cho từng đầu, fit trên V_A + V_B.
  - Khi đo trên tập kiểm định, mỗi hàng nhận xác suất từ mô hình Platt fit trên nửa người chơi còn lại (cross-fit 2
    phần theo người chơi), nên số đo không bị lạc quan.
  - Bản đóng gói cuối dùng một lần fit trên toàn bộ V_A + V_B, không huấn luyện lại sau đó.
- **Tái lập.** Toàn bộ huấn luyện và đánh giá chạy hai lần độc lập, cho dự đoán và chỉ số giống hệt (chênh 0,0).
  Bộ trọng số đóng gói có sha256 cố định.
- **Không học thuộc nhiều.** PR-AUC trên train và trên kiểm định khá gần nhau:

  | Đầu | Train | Kiểm định |
  |---|---:|---:|
  | `p20` | 0,545 | 0,487 |
  | `pre` | 0,405 | 0,299 |

## 7. Đánh giá

### 7.1 Chỉ số
- **PR-AUC** là chỉ số chính, vì TILT hiếm (khoảng 7,5%). Một bộ đoán ngẫu nhiên đạt PR-AUC bằng đúng tỉ lệ nền.
- **ROC-AUC** và **ECE** (sai số hiệu chỉnh: xác suất dự đoán lệch tần suất thật bao nhiêu).
- Khoảng tin cậy 95% bằng bootstrap ghép cặp, lấy mẫu lại theo người chơi, 1.000 lần.
- Báo cáo theo tầng độ dài: ≥ 40 và < 40 nửa nước.
- Quy tắc chấp nhận được viết và khóa **trước khi** có bất kỳ con số nào trên tập giữ riêng.

### 7.2 Các mốc so sánh
| Mốc | Mô tả |
|---|---|
| Ngữ cảnh luật (`R-pre`) | mức ngữ cảnh + D/4, không cần học; chính là phần "trước ván" của bộ luật |
| Chuỗi thua | số ván thua liên tiếp trước ván |
| Trình độ | 15 cột về trình độ (rating, mức CPL/blunder thường lệ…), cùng XGBoost |
| Hành vi cả ván | XGBoost trên 11 đặc trưng phong cách và thời gian tính trên **cả ván** (được xem nhiều hơn M-v3), huấn luyện trên cùng nhãn |
| Kết quả ván, độ dài ván | chỉ để tham khảo: dùng thông tin chỉ có sau ván |

### 7.3 Kết quả trên tập kiểm định (V_A + V_B, 10.011 hàng có nhãn, tỉ lệ nền 0,078)
| Mô hình | PR-AUC [95% CI] |
|---|---|
| **M-v3** | **0,486 [0,448; 0,526]** |
| Ngữ cảnh luật | 0,282 [0,255; 0,313] |
| Kết quả ván (tham khảo) | 0,190 |
| Hành vi cả ván | 0,161 |
| Chuỗi thua | 0,157 |
| Trình độ | 0,097 |

### 7.4 Kết quả trên hai tập giữ riêng (chấm một lần)
A′ có 5.361 hàng có nhãn (404 TILT). B′ có 2.934 hàng có nhãn (212 TILT).

| Mô hình | A′ (người chơi mới) | B′ (thời gian về sau) |
|---|---|---|
| **M-v3** | **0,458 [0,403; 0,520]** | **0,451 [0,385; 0,520]** |
| Ngữ cảnh luật | 0,267 [0,232; 0,312] | 0,253 [0,221; 0,292] |
| Kết quả ván (tham khảo) | 0,182 | 0,164 |
| Chuỗi thua | 0,150 | 0,136 |
| Hành vi cả ván | 0,139 | 0,148 |
| Trình độ | 0,096 | 0,083 |
| Độ dài ván (tham khảo) | 0,055 | 0,056 |
| Tỉ lệ nền | 0,075 | 0,072 |

- ROC-AUC của M-v3 là 0,918 (A′) và 0,916 (B′).
- ECE 0,0058 (A′) và 0,0050 (B′): xác suất dự đoán gần như trùng tần suất thật.
- Kết quả trên tập giữ riêng chỉ thấp hơn kiểm định một chút (khoảng tin cậy chồng nhau), nên mô hình tổng quát
  tốt cho người mới và cho giai đoạn sau.

**Mức chênh PR-AUC (M-v3 trừ mốc so sánh), 95% CI**, theo tầng độ dài ván:

| Tập · tầng | Hành vi cả ván | Ngữ cảnh luật | Chuỗi thua | Trình độ |
|---|---|---|---|---|
| A′ ≥ 40 (304 TILT) | +0,263 [0,215; 0,318] | +0,135 [0,084; 0,190] | +0,244 [0,197; 0,301] | +0,296 [0,247; 0,353] |
| A′ < 40 (100 TILT) | +0,526 [0,398; 0,621] | +0,373 [0,258; 0,463] | +0,530 [0,440; 0,607] | +0,584 [0,474; 0,677] |
| B′ ≥ 40 (159 TILT) | +0,262 [0,185; 0,341] | +0,144 [0,081; 0,217] | +0,264 [0,192; 0,350] | +0,318 [0,246; 0,401] |
| B′ < 40 (53 TILT) | +0,454 [0,307; 0,564] | +0,354 [0,235; 0,458] | +0,473 [0,343; 0,573] | +0,507 [0,383; 0,626] |

Cả 16 ô đều có cận dưới lớn hơn 0; thấp nhất là +0,081. Mỗi ô có ≥ 30 ván TILT và không lần bootstrap nào bị
bỏ. Mô hình được chấp nhận theo đúng quy tắc đã khóa trước.

### 7.5 Ba mức hiển thị
Ngưỡng được chốt trước khi chấm tập giữ riêng. Cột "tỉ lệ TILT" tính trên các ván có nhãn.

| Mức | Xác suất | Phần ván A′ / B′ | Tỉ lệ TILT A′ / B′ |
|---|---|---|---|
| Thấp | < 0,10 | 73,8% / 71,7% | 1,3% / 1,3% |
| Đáng chú ý | 0,10–0,30 | 17,0% / 17,8% | 18,6% / 17,5% |
| Cao | ≥ 0,30 | 9,2% / 10,5% | 45,3% / 42,7% |

Ở mức Cao, precision là 0,453 / 0,427 và recall 0,460 / 0,486. Ván ở mức Cao có tỉ lệ TILT cao hơn 30 lần so với ván
ở mức Thấp.

## 8. Triển khai lên web

### 8.1 Kiến trúc
```
ván kết thúc ──► lila (Scala) ghi yêu cầu vào MongoDB `tilt_queue` (mỗi người chơi một doc, kèm tốc độ ván)
                    │
                    ▼
            worker Python (`python -m tilt lila-worker`)
              1. bỏ qua ván không phải blitz (`skip: "speed"`)
              2. tải lịch sử blitz của người chơi qua API export của lila
              3. Stockfish với đúng cấu hình lúc huấn luyện (worker từ chối cấu hình khác)
              4. dựng đặc trưng trước ván + 20 nửa nước đầu, chấm bằng M-v3
              5. tính lý do (SHAP), lý do "đi nhanh", và kiểm tra theo luật sau ván
              6. ghi `response` vào doc
                    │
                    ▼
            lila hiển thị: tab Tilt trong ván, trang /account/tilt, banner ở trang chủ
```
- Mô hình nằm sau con trỏ `tilt/data/processed/models/deployed_v3.json`, kèm sha256 của bộ trọng số và danh sách
  đặc trưng. Worker từ chối chạy nếu hash lệch.
- **Quay lại bản trước:** xóa con trỏ rồi khởi động lại worker.
- Tới 2026-12-01, mô hình trước đó vẫn chạy ẩn song song để so sánh. Kết quả của nó không bao giờ hiển thị.

### 8.2 Worker
- Chỉ chấm ván blitz, đúng thể thức mô hình được huấn luyện.
- Ván ≥ 20 nửa nước mà 20 nửa nước đầu chỉ có nước của một bên thì bị bỏ qua (`skip: "incomplete"`).
- Lý do điểm số dùng SHAP (đóng góp của từng đặc trưng vào điểm của XGBoost), cộng theo nhóm đặc trưng:
  - hiện tối đa 3 nhóm, mỗi nhóm chiếm ≥ 10% phần đóng góp dương;
  - không lấy nhóm thông tin ván và nhóm trình độ làm lý do, dù chúng vẫn tính vào điểm.
- Lý do "đi nhanh hơn thường lệ" chỉ hiện khi đủ cả ba điều kiện:
  - z thời gian nghĩ ở đầu ván ≤ −1,5;
  - có ≥ 20 ván blitz làm mốc;
  - sau khi bỏ 4 nước đầu của người chơi (thường là nước khai cuộc thuộc lòng), z vẫn ≤ −1.
- Kiểm tra theo luật sau ván hiện kết luận và các luật đã kích hoạt. E7 phụ thuộc ván kế tiếp, nên được cập nhật
  lại khi người chơi chơi ván sau.
- Ngay sau khi khởi động, lila trả 503 cho API export trong khoảng 20 s. Gặp lỗi 5xx như vậy, worker giữ yêu cầu
  trong hàng đợi để thử lại.
- Chấm một ván (dựng đặc trưng, luật, SHAP) mất trung vị 3,7 s, tối đa 6,1 s, chưa tính thời gian Stockfish.

### 8.3 Giao diện (lila, song ngữ Việt/Anh theo ngôn ngữ trang)
- **Tab "Tilt" trong trang ván.** Chỉ người chơi của ván đó thấy, và chỉ sau khi ván kết thúc. Nội dung gồm:
  - mức, điểm 0–100 và thanh mức;
  - "Điểm này chủ yếu đến từ", với tối đa 3 lý do bằng lời thường, ví dụ "kết quả các ván trước trong phiên", "cách
    dùng thời gian ở đầu ván";
  - "Xét lại sau ván", với kết luận (có dấu hiệu tilt / không có dấu hiệu tilt / chưa đủ dấu hiệu để kết luận) và
    các dấu hiệu đã thấy;
  - ván không phải blitz thì ghi "Chỉ ván blitz mới được chấm điểm".
- **Trang `/account/tilt`:**
  - thống kê 30 ngày qua và 50 ván gần nhất: tỉ lệ từng mức, lý do thường gặp, số ván có dấu hiệu tilt;
  - danh sách ván gần đây;
  - công tắc tắt/bật gợi ý nghỉ;
  - lời mở đầu nói rõ "Điểm chỉ là ước tính, không đo cảm xúc".
- **Banner gợi ý nghỉ ngắn ở trang chủ.** Banner hiện khi 2 ván blitz liên tiếp trong phiên đều ở mức Cao, hoặc
  khi 1 ván Cao đi sau chuỗi thua (ngữ cảnh mạnh). Giới hạn:
  - tối đa 1 lần mỗi phiên, cách nhau ≥ 30 phút;
  - không bao giờ hiện khi đang chơi;
  - ẩn được bằng một nút;
  - tắt hẳn được trong trang tài khoản.
- Giao diện không dùng thuật ngữ kỹ thuật như "mô hình", "nửa nước", "z", hay phần trăm đóng góp. Có test tự động
  chặn các từ này.

### 8.4 Quyền riêng tư
- Chỉ người chơi thấy điểm của mình. Khách chưa đăng nhập không thấy tab Tilt.
- Xóa tài khoản thì xóa luôn yêu cầu chấm điểm và trạng thái banner của người đó.
- Dữ liệu thô, salt và thư mục `tilt/data` không rời máy chạy. Dữ liệu huấn luyện không bao giờ được commit.

### 8.5 Kiểm thử
| Loại | Kết quả |
|---|---|
| Test Python (pipeline, luật, đặc trưng, huấn luyện, worker) | 626 qua |
| Test Scala `lila.tilt.*` (đọc dữ liệu, mức, banner, thống kê, chữ hiển thị) | 14 qua |
| Đối chiếu đường chấm trực tiếp với kết quả huấn luyện (26 người chơi, 4.150 điểm) | khớp tuyệt đối, chênh 0 |
| Kiểm tra trình duyệt Playwright trên site local (Việt + Anh) | 52/52 qua |

Kiểm tra trình duyệt dùng tài khoản test tự tạo, chơi 3 ván (2 blitz, 1 rapid) qua Board API rồi kiểm tra:
- tab ván, trang thống kê;
- banner, nút ẩn banner, bật/tắt gợi ý nghỉ;
- khách chưa đăng nhập không thấy tab;
- không có lỗi console.

Tài khoản test và dữ liệu liên quan bị xóa sạch sau khi chạy.

## 9. Giới hạn
- **Nhãn là luật, không phải cảm xúc thật.** Điểm cao nghĩa là "ván này nhiều khả năng khớp mẫu hành vi tilt mà bộ
  luật mô tả", không phải người chơi chắc chắn đang bực bội. Hệ thống chưa được đối chiếu với tự báo cáo của người
  chơi.
- **Chỉ blitz.** Các thể thức khác không được chấm.
- **Nhãn nghiêng về ván ngắn.** Ván ngắn có tỉ lệ TILT cao hơn ván dài: độ dài ván một mình tách TILT/NOT với AUC
  khoảng 0,64. Phần lớn ván TILT có dấu hiệu E1 hoặc E2 (chất lượng nước đi).
- **Ván dưới 20 nửa nước** chỉ dùng đầu `pre`. Ở tầng này, số ván TILT trên tập giữ riêng quá ít (16 và 14) để
  khẳng định M-v3 hơn các mốc so sánh. Điểm của M-v3 vẫn phần nào nhận ra ván ngắn (AUC khoảng 0,74).
- **E7** cần ván kế tiếp, nên kết luận sau ván có thể thay đổi khi người chơi vào ván mới.
- Hai tập A′ và B′ đã được dùng cho đánh giá này. Mô hình sau này cần tập giữ riêng mới.

## 10. Chạy và tái lập

```bash
# chạy site local kèm worker (worker tự dùng M-v3 khi có deployed_v3.json)
tilt/scripts/start-lichess.sh          # mở http://localhost:9663

# test
python -m pytest tilt/tests -q
cd lila && sbt 'tilt/Test/testOnly lila.tilt.*'

# quay lại mô hình trước
rm tilt/data/processed/models/deployed_v3.json   # rồi khởi động lại worker
```

Mã nguồn chính:

| Phần | File |
|---|---|
| Thu thập, chuẩn hóa | `tilt/src/tilt/data/collect.py`, `normalize.py`, `cohort_v3.py` |
| Stockfish, công thức | `tilt/src/tilt/core/engine.py`, `formulas.py` |
| Đặc trưng | `tilt/src/tilt/features/features.py`, `prefix_v3.py` |
| Luật gán nhãn, chia dữ liệu | `tilt/src/tilt/labels/rules_v3.py`, `split_v3.py` |
| Huấn luyện, đánh giá | `tilt/src/tilt/evaluation/v3_train.py`, `v3_holdout.py` |
| Chấm trực tiếp, worker | `tilt/src/tilt/core/live_v3.py`, `tilt/src/tilt/workers/lila_worker.py` |
| lila | `lila/modules/tilt/` (`TiltGame`, `TiltBanner`, `TiltText`, `TiltApi`, `ui/TiltUi`), `lila/app/controllers/Tilt.scala` |

Tài liệu chi tiết trong `tilt/reports/`:
- `label_v3_preregistration.md`: định nghĩa luật và quy tắc đánh giá;
- `label_v3_deployment.md`: đặc tả triển khai;
- `final_model_comparison.md`: so sánh các mô hình trước v3, gồm P3-B đang chạy ẩn.
