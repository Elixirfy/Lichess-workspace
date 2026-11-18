# Bình luận viên tiếng Việt v2 — ba giọng và VieNeu Nano

## Thông tin phiên bản và mục đích tài liệu

- Branch: `feature/commentary-v2`.
- Mã nguồn khảo sát: [`7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea`](https://github.com/trantrien1/Lichess-workspace/commit/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea).
- Ngày tổng hợp: **18/11/2026**. Tài liệu này phục vụ mô tả/so sánh trong báo cáo; không phải một benchmark mới.
- Bản phát triển tiếp từ bình luận Piper: có Mạnh Dũng, Hữu Quân và Anh Khôi; dùng VieNeu v3 Nano trên CPU trong cấu hình được mô tả. Snapshot này vẫn chứa tùy chọn Gemini TTS; main đã bỏ lựa chọn đó sau này. TTS không đồng nghĩa với dùng LLM để phân tích nước đi.

## 1. Bài toán và mục tiêu

Làm trải nghiệm nghe đa dạng hơn và theo kịp tốc độ ván cờ: chọn BLV, có câu chào riêng, phụ đề đồng bộ và loại lời bình đến muộn.

## 2. Chức năng đã có trên nhánh

Người chơi standard, gồm khách, bật bình luận và chọn tên BLV. Mạnh Dũng mặc định; lựa chọn cũ không hợp lệ trở về mặc định. Đổi giọng dừng âm thanh hiện tại và phát câu chào. Câu nước đi, câu lúc chờ và kết thúc dùng dữ liệu ván chính thức; chơi nhanh có thể bỏ qua câu đã lỗi thời.

## 3. Kiến trúc và cách triển khai

```text
Snapshot/SAN từ Lila → python-chess + Stockfish → thông tin thế cờ/khung câu tiếng Việt → tiến trình Nano đã nạp model → WAV 24 kHz → SSE → phụ đề/âm thanh theo revision và hạn sử dụng.
```

Bộ câu có cơ chế tránh lặp; khi nước đi sát nhau thì chọn câu ngắn. Nano chạy bằng ONNX trên CPU, một câu tổng hợp tại một thời điểm, cache tối đa 64 cặp giọng-văn bản. Model có revision/checksum; môi trường Nano tách khỏi worker HTTP. Cấu hình mô tả 16 bước, một thread; tốc độ hiệu lực 1,20 cho Mạnh Dũng/Hữu Quân và 1,38 cho Anh Khôi. Frontend/Scala kiểm tra whitelist giọng; deadline, hủy chờ và stale guards giới hạn backlog.

## 4. Ưu điểm so với tính năng có sẵn

| Bản có sẵn / bản Piper | Mở rộng v2 | Ưu điểm và bằng chứng |
|---|---|---|
| Một preset Piper | Ba tên BLV, câu chào riêng, lưu lựa chọn | Đã có UI/catalogue; chưa chứng minh ba giọng có chất lượng cảm nhận cao hơn bằng thử nghiệm mù |
| Phát câu dài theo từng sự kiện | Câu ngắn khi chơi nhanh, chống lặp, câu lúc chờ | Thiết kế giảm backlog và đơn điệu; có thể chủ động bỏ lời bình muộn |
| TTS nạp/chạy rời cho từng tác vụ | Nano process giữ model và cache | Tránh nạp lại model mỗi câu; chưa có benchmark so tốc độ trực tiếp với Piper trên cùng máy |
| Phụ thuộc lựa chọn cloud khi cấu hình | Cấu hình Nano chạy CPU local | Không cần cloud TTS khi chọn Nano; nhánh vẫn có tùy chọn Gemini, cần ghi rõ provider khi đo |

Các nhận định “ít thao tác”, “thêm kênh nghe”, “dùng chung công việc” mô tả thiết kế/hành vi có trong code. Không chuyển chúng thành số liệu tăng năng suất, độ chính xác hoặc chất lượng học tập khi chưa có phép đo đối chứng.

## 5. Kết quả kiểm thử và bằng chứng

Task list ghi nhận 66 test Python bình luận, 7 test launcher, build UI và Scala stage; đây là bằng chứng lịch sử do tác giả lưu. Full UI được ghi là **283/285**, hai lỗi thiếu module coach, không phải toàn bộ suite xanh. Các log `/tmp/...` được nhắc trong tasks không nằm trong Git clone này nên chưa kiểm chứng độc lập lại. Không chạy model Nano/Gemini và không thay cấu hình API trong lần viết README.

## 6. Cách dựng và thử lại

Xem `services/commentary/README.md` để tạo riêng môi trường HTTP và Nano, tải đúng revision model và export biến cấu hình. Với provider Nano cần `BLV_TTS_PROVIDER=vieneu`, `BLV_NANO_DIR` và `BLV_NANO_PYTHON`. Worker ví dụ bind 127.0.0.1:9666; Lila cần cấu hình endpoint/token tương ứng.

```sh
cd lila
./ui/build
./lila.sh --server --batch stage
```

README cũ nhắc `./lichess-local` và `LOCAL.md`, nhưng hai tệp này không có trong tree snapshot đã khảo sát. Không coi launcher đó là bước tái lập có sẵn sau clone; cần tự cấu hình/start Lila theo checkout và README dịch vụ. Chưa bổ sung launcher trong thay đổi tài liệu này.

## 7. Giới hạn và điểm chưa hoàn thành

Nội dung bình luận hiện theo thông tin engine và khung câu; không phải một huấn luyện viên LLM tự suy luận mọi nước đi. Nghe dễ chịu hơn là giả thuyết cần đánh giá người dùng. CPU/độ trễ phụ thuộc máy, số bước và tốc độ chọn; không bảo đảm đọc đủ mọi nước. Cấu hình Gemini tùy chọn có phụ thuộc riêng; không đưa API key vào README. Hai lỗi coach và thiếu launcher không được che bằng các test bình luận đã qua.

## 8. Hướng phát triển và điểm cần đối chiếu

Đo p50/p95 tổng hợp và tỷ lệ câu bị bỏ khi chơi nhanh; khảo sát độ tự nhiên/dễ hiểu với nhiều người nghe; so sánh Piper và Nano trên cùng văn bản. Nếu cần giải thích sâu sau trận, đó là bài toán khác với phát bình luận live hiện tại.

## 9. Tệp nguồn quan trọng ở đúng revision

- [`services/commentary/app.py`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/services/commentary/app.py)
- [`services/commentary/nano_worker.py`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/services/commentary/nano_worker.py)
- [`services/commentary/nano_audio.py`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/services/commentary/nano_audio.py)
- [`services/commentary/voices.py`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/services/commentary/voices.py)
- [`services/commentary/nano-assets.json`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/services/commentary/nano-assets.json)
- [`services/commentary/tests/test_commentary.py`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/services/commentary/tests/test_commentary.py)
- [`docs/binh-luan-vien-tieng-viet.md`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/docs/binh-luan-vien-tieng-viet.md)
- [`openspec/changes/local-commentary-stack/tasks.md`](https://github.com/trantrien1/Lichess-workspace/blob/7aa154dc56cdfa96fc3c8a616ac4d850d4db54ea/openspec/changes/local-commentary-stack/tasks.md)

## 10. Dùng tài liệu này khi viết báo cáo

Có thể dùng mục 1–2 cho bài toán/phạm vi, mục 3 cho thiết kế, mục 4 cho đóng góp và so sánh, mục 5 cho thực nghiệm, mục 7–8 cho hạn chế/hướng phát triển. Khi trích số đo, giữ nguyên tên branch, snapshot, tập kiểm thử và điều kiện máy; phân biệt số đã lưu với số vừa chạy. Không cộng các lần kiểm thử lặp thành số mẫu độc lập.

README này được tổng hợp với sự hỗ trợ của Codex. Tài liệu không suy đoán tác giả của mọi phần mã nguồn hoặc việc đã đóng góp lên upstream. Đối chiếu Lichess tại revision đã ghim thay vì khẳng định phiên bản hiện tại hoàn toàn chưa có tính năng tương tự.

- [Thiết kế bình luận v2](../binh-luan-vien-tieng-viet.md)
- [Cài worker/model](../../services/commentary/README.md)
- [Lịch sử kiểm thử và tồn tại](../../openspec/changes/local-commentary-stack/tasks.md)
