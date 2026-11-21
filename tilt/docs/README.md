# Tài liệu module Tilt

Tilt nhận diện dấu hiệu chơi mất bình tĩnh ("tilt") trong cờ blitz. Sau mỗi
ván, người chơi nhận điểm 0–100, lý do bằng lời thường, và lời gợi ý nghỉ khi
nhiều ván gần nhau đều có điểm cao. Điểm chỉ là ước tính dựa trên cách chơi,
không đo cảm xúc thật.

Nên đọc theo thứ tự dưới đây. Ai chỉ cần chạy hoặc sửa code thì đọc thẳng
[Vận hành](van-hanh.md) và [Mã nguồn](ma-nguon.md).

| Tài liệu | Nội dung |
|---|---|
| [Tổng quan](tong-quan.md) | Mục đích, các chức năng, ba mức điểm, giao diện |
| [Xây dựng mô hình](xay-dung-mo-hinh.md) | Dữ liệu, phân tích Stockfish, mức thường lệ, bộ luật gán nhãn, đặc trưng, chống rò rỉ, chia dữ liệu, huấn luyện, cách đánh giá |
| [Vận hành cùng Lichess](van-hanh.md) | Luồng chấm một ván, lý do của điểm, lời gợi ý nghỉ, cách chạy, cấu hình, quay về mô hình cũ |
| [Kết quả](ket-qua.md) | PR-AUC trên phần đánh giá cuối, khoảng tin cậy, ý nghĩa ba mức, kiểm thử |
| [Mã nguồn](ma-nguon.md) | Cấu trúc gói Python, thư mục dữ liệu, các lệnh, mã bị khóa hash, cách chạy test |
| [Dữ liệu Lichess](du-lieu-lichess.md) | Ghi chú kỹ thuật: ý nghĩa các trường API, đồng hồ, công thức, cách tính mức thường lệ |

## Thuật ngữ

| Từ | Nghĩa |
|---|---|
| Nửa nước | Một nước đi của một bên. 20 nửa nước là 10 nước của mỗi bên. |
| Lượt | Một người chơi trong một ván. Một ván giữa hai người trong dữ liệu tạo hai lượt. |
| Buổi chơi (phiên) | Chuỗi ván liền nhau của một người; nghỉ quá 30 phút thì sang buổi mới. |
| Mức thường lệ | Cách chơi quen thuộc của chính người đó, tính từ tối đa 200 ván blitz trước. |
| CPL | Lượng lợi thế (centipawn) mất đi so với nước tốt nhất của Stockfish. |
| Điểm z | Ván này lệch bao nhiêu so với mức thường lệ, tính theo trung vị và độ lệch tuyệt đối trung vị. |
| TILT / KHÔNG | Kết luận của bộ luật cho một lượt. Lượt mơ hồ không được gán nhãn. |
| M-v3 | Mô hình đang chạy: XGBoost học để đoán trước kết luận của bộ luật v3. |
| P3-B | Mô hình cũ, chạy ẩn song song tới 1/12/2026 để đối chiếu. |
| PR-AUC | Chỉ số chính để đánh giá. Đoán ngẫu nhiên đạt đúng bằng tỉ lệ TILT, khoảng 0,075. |

## Tài liệu gốc

Thư mục [`tilt/reports/`](../reports/) giữ các báo cáo gốc để đối chiếu:

- [`tilt_final_report.md`](../reports/tilt_final_report.md): báo cáo tổng kết (tiếng Việt).
- [`final_model_comparison.md`](../reports/final_model_comparison.md): so sánh các mô hình cũ, lý do chọn P3-B (tiếng Việt).
- [`label_v3_deployment.md`](../reports/label_v3_deployment.md): đặc tả triển khai M-v3 (tiếng Anh).
- [`label_v3_preregistration.md`](../reports/label_v3_preregistration.md): bộ luật v3 và quy tắc đánh giá, viết và khóa
  trước khi có kết quả (tiếng Anh). Tệp này bị khóa bằng hash nên không được sửa, kể cả đường dẫn cũ bên trong.
