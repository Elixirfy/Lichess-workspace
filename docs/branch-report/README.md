# Bình luận viên tiếng Việt — phiên bản Piper

## Thông tin phiên bản và mục đích tài liệu

- Branch: `feature/commentary`.
- Mã nguồn khảo sát: [`02a6d4503d94e6c7cb42420e2993ff2100033087`](https://github.com/trantrien1/Lichess-workspace/commit/02a6d4503d94e6c7cb42420e2993ff2100033087).
- Ngày tổng hợp: **18/11/2026**. Tài liệu này phục vụ mô tả/so sánh trong báo cáo; không phải một benchmark mới.
- Mốc bình luận tiếng Việt ban đầu: dịch vụ Python phân tích thế cờ bằng Stockfish, tạo lời bình và tổng hợp giọng Piper. Hỗ trợ người chơi với máy, với người và khách. Nhánh này không có README gốc trước lần bổ sung tài liệu.

## 1. Bài toán và mục tiêu

Bổ sung lời bình tiếng Việt về diễn biến ván đấu thay vì yêu cầu người chơi chỉ theo dõi ký hiệu nước đi và điểm engine.

## 2. Chức năng đã có trên nhánh

Mỗi người chơi tự bật/tắt bình luận trên bàn standard. Tài khoản dùng phiên đăng nhập; khách dùng cookie người chơi của Lila. Người xem không mở được luồng bình luận này. Có lời giới thiệu, lời bình nước đi và kết thúc; giao diện nhận văn bản/âm thanh qua SSE.

## 3. Kiến trúc và cách triển khai

```text
Trạng thái ván từ Lila → snapshot/lịch sử được kiểm tra → worker Stockfish → nội dung tiếng Việt → Piper WAV → SSE → kiểm tra revision/expiry → phụ đề và phát âm thanh.
```

Scala kiểm tra quyền và gửi công việc có game/request/revision/FEN/hạn sử dụng tới worker. Python dùng python-chess dựng và xác minh lịch sử. Lời bình có đường dựng sẵn; endpoint LLM tương thích OpenAI là tùy chọn để chọn một câu hoàn chỉnh trong các phương án đã xác minh, kèm factIds được kiểm tra. Đây không phải bộ phân tích chiến thuật tự do và không phải điều kiện để Piper hoạt động. UI kiểm tra tính còn hiệu lực trước khi phát và phối hợp kênh âm thanh.

## 4. Ưu điểm so với tính năng có sẵn

| Có sẵn / cách đối chiếu | Mở rộng của nhánh | Ưu điểm có thể khẳng định |
|---|---|---|
| Danh sách SAN và đánh giá số | Lời bình tiếng Việt kèm âm thanh | Thêm kênh nghe để theo dõi diễn biến; chưa có nghiên cứu người dùng chứng minh cải thiện học cờ |
| Chức năng đọc nước đi | Diễn đạt sự kiện/thế cờ và lời mở/kết ván | Nội dung phong phú hơn việc đọc nguyên tên nước, nhưng vẫn có thể đơn giản hoặc sai heuristic |
| Tự kết nối dịch vụ TTS rời | Tích hợp trạng thái authoritative, SSE và kiểm tra stale | Hạn chế phát lời bình thuộc nước cũ |
| Chỉ hỗ trợ tài khoản | Quyền dành cho cả người chơi khách | Giảm yêu cầu đăng ký; vẫn phân biệt người chơi với người xem |

Các nhận định “ít thao tác”, “thêm kênh nghe”, “dùng chung công việc” mô tả thiết kế/hành vi có trong code. Không chuyển chúng thành số liệu tăng năng suất, độ chính xác hoặc chất lượng học tập khi chưa có phép đo đối chứng.

## 5. Kết quả kiểm thử và bằng chứng

Không tìm thấy log benchmark hoặc bộ test tự động cho bình luận được commit trong snapshot này. Có mã nguồn và README dịch vụ mô tả chức năng. Vì vậy tài liệu không gán số độ chính xác/độ trễ hoặc chép 66 test của bản v2 vào nhánh này. Kiểm tra lần viết tài liệu là đối chiếu tree, source và liên kết; không khởi động lại nhánh Piper trên stack hiện tại.

## 6. Cách dựng và thử lại

```sh
cd services/commentary
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
# Export cấu hình từ .env.example; cài Stockfish và model Piper trước.
uvicorn app:app --host 127.0.0.1 --port 9666 --workers 1
```

Trong cấu hình riêng của Lila đặt `commentary.enabled`, `commentary.endpoint` và token khớp worker; build UI/Scala theo checkout `lila/`. Hướng dẫn và tên biến chính xác ở README dịch vụ. Cổng Lila tùy cấu hình, không mặc định dùng cổng Docker 8080 của nhánh prediction.

## 7. Giới hạn và điểm chưa hoàn thành

Một preset `piper-vais1000`; chưa có bộ chọn ba BLV Nano của v2. Không có bằng chứng so sánh cảm nhận chất giọng hoặc hiệu quả học tập. Engine/template/LLM đều có thể tạo nhận xét chưa đúng; dữ liệu snapshot được kiểm tra không bảo đảm nội dung bình luận chính xác. Cần cài model và cấu hình worker; không có dịch vụ public được nghiệm thu.

## 8. Hướng phát triển và điểm cần đối chiếu

Có thể đánh giá bản Piper với bản Nano trên cùng bộ câu: thời gian tổng hợp, độ dễ nghe, lỗi phát âm và mức lặp. Cần cùng điều kiện phần cứng và người nghe; chưa có phép đo đối chứng này trong nhánh.

## 9. Tệp nguồn quan trọng ở đúng revision

- [`services/commentary/README.md`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/services/commentary/README.md)
- [`services/commentary/app.py`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/services/commentary/app.py)
- [`services/commentary/core.py`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/services/commentary/core.py)
- [`services/commentary/narrative.py`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/services/commentary/narrative.py)
- [`services/commentary/piper_worker.py`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/services/commentary/piper_worker.py)
- [`lila/app/controllers/Commentary.scala`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/lila/app/controllers/Commentary.scala)
- [`lila/modules/round/src/main/CommentaryRequests.scala`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/lila/modules/round/src/main/CommentaryRequests.scala)
- [`lila/ui/round/src/commentary.ts`](https://github.com/trantrien1/Lichess-workspace/blob/02a6d4503d94e6c7cb42420e2993ff2100033087/lila/ui/round/src/commentary.ts)

## 10. Dùng tài liệu này khi viết báo cáo

Có thể dùng mục 1–2 cho bài toán/phạm vi, mục 3 cho thiết kế, mục 4 cho đóng góp và so sánh, mục 5 cho thực nghiệm, mục 7–8 cho hạn chế/hướng phát triển. Khi trích số đo, giữ nguyên tên branch, snapshot, tập kiểm thử và điều kiện máy; phân biệt số đã lưu với số vừa chạy. Không cộng các lần kiểm thử lặp thành số mẫu độc lập.

README này được tổng hợp với sự hỗ trợ của Codex. Tài liệu không suy đoán tác giả của mọi phần mã nguồn hoặc việc đã đóng góp lên upstream. Đối chiếu Lichess tại revision đã ghim thay vì khẳng định phiên bản hiện tại hoàn toàn chưa có tính năng tương tự.

- [Hướng dẫn dịch vụ và cấu hình](../../services/commentary/README.md)
