# AI Coach trên Lichess

Nhánh `feature/coach` bổ sung chế độ học cờ cùng máy trực tiếp trên bàn đấu Lichess. Người chơi có thể xin gợi ý trước khi đi, đọc giải thích sau nước đi và thử phương án khác trên bàn luyện. Cuối buổi, Coach tổng hợp những thời điểm đáng xem lại và đề xuất nội dung luyện tập dựa trên dữ kiện đã phân tích.

## Bắt đầu buổi học

1. Từ trang chủ, chọn **Learn with your coach** hoặc mở `/ai-coach`.
2. Chọn Trắng, Đen hoặc ngẫu nhiên, cấp độ máy từ 1 đến 8 và mức hỗ trợ.
3. Bấm **Bắt đầu học**. Ván dùng luật cờ tiêu chuẩn, chơi từ thế xuất phát, không tính rating và không có đồng hồ. Người chơi có thể dùng tài khoản hoặc chơi với tư cách khách.

Ở chế độ **Chủ động**, Coach hiển thị hướng dẫn đầu buổi và nhận xét sau các nước của người học khi kết quả đã sẵn sàng. Ở chế độ **Chỉ khi tôi hỏi**, giao diện trả lời theo yêu cầu, còn các nước của người học vẫn được phân tích để chuẩn bị tổng kết.

| Thao tác | Kết quả |
|---|---|
| **Gợi ý** | Khi đến lượt mình ở thế hiện tại, người chơi có thể xin tối đa ba nấc cho thế đó. Coach lần lượt nêu điều cần xem xét, chỉ quân nên chú ý và đưa một nước ứng viên kèm biến tham khảo. |
| **Giải thích nước của bạn** | Coach phân tích nước gần nhất của người học và giải thích tác dụng hoặc hệ quả bằng tiếng Việt. |
| **Đối thủ đang đe dọa gì?** | Khi máy đã đáp và đến lượt người học, Coach có thể chỉ ra tình huống cần xử lý như đang bị chiếu, nguy cơ chiếu hết hoặc mất quân. |
| **Thử lại từ thế này** | Khi thẻ có phương án cải thiện, nút mở bàn luyện tại thế trước nước đang được giải thích. Người học có thể đi cho cả hai bên, lùi bước hoặc xem biến gợi ý. Các nước thử chỉ tác động đến bàn luyện. |
| **Tổng kết buổi học** | Hiển thị số nước đã phân tích, tối đa ba thời điểm đáng xem lại và hướng luyện tập nếu có đủ dữ kiện. Tổng kết có thể hiển thị dữ liệu đã xử lý trong khi một số nước chưa có kết quả. |

Có thể tải lại trang hoặc mở lại ván để tìm phiên còn hạn bằng cùng tài khoản hoặc phiên khách. Khi phiên đã kết thúc, chọn **Buổi học mới** để quay lại màn hình thiết lập.

## Luồng xử lý

1. **Tạo buổi học.** Trang `/ai-coach` gửi cấu hình đến `AiCoach.create`. `Creator.create` quản lý phiên, còn `Processor.prepareCoach` chuẩn bị ván đấu với máy. Fishnet xử lý nước đáp của máy theo luồng ván cờ Lichess.
2. **Ghi nhận nước đi và câu hỏi.** `Runtime.reconcile` tạo tác vụ phân tích cho các nước của người học từ trạng thái ván trên server. `Runtime.question` xử lý yêu cầu gợi ý, giải thích hoặc hỏi đe dọa. Lila lưu phiên và tác vụ trong MongoDB. Mỗi thế cờ được định danh từ FEN ban đầu và toàn bộ lịch sử đến thế đó để gắn kết quả với đúng vị trí.
3. **Phân tích và soạn nhận xét.** Worker Python nhận `POST /analyse` qua kết nối nội bộ có bearer token. `questions.execute` kiểm tra và dựng lại thế cờ, dùng python-chess và Stockfish để xác định dữ kiện, rồi tạo nhận xét từ các mẫu tiếng Việt. Khi bật LLM, worker có thể dùng nó để chọn cách diễn đạt từ các câu đã kiểm. Lỗi provider hoặc phản hồi không hợp lệ sẽ dùng câu mẫu.
4. **Hiển thị và tổng kết.** Lila kiểm quyền sở hữu phiên, xác thực kết quả và cung cấp snapshot qua API. Trình duyệt dùng SSE để nhận cập nhật và hiển thị thẻ theo thế đang xem. Khi ván kết thúc, `Summary.build` tổng hợp mức độ phân tích và các mốc đáng xem lại.

| Thành phần | Mã nguồn |
|---|---|
| Trang thiết lập và API buổi học | [`AiCoach.scala`](lila/app/controllers/AiCoach.scala), [`lobby.coach.ts`](lila/ui/lobby/src/lobby.coach.ts) |
| Tạo phiên và quản lý tác vụ | [`Creator.scala`](lila/modules/aicoach/src/main/Creator.scala), [`Runtime.scala`](lila/modules/aicoach/src/main/Runtime.scala), [`MongoStore.scala`](lila/modules/aicoach/src/main/MongoStore.scala) |
| Khung Coach và bàn luyện | [`coach.ts`](lila/ui/round/src/coach.ts), [`view/coach.ts`](lila/ui/round/src/view/coach.ts), [`coachPractice.ts`](lila/ui/round/src/coachPractice.ts) |
| Worker phân tích và soạn nhận xét | [`server.py`](services/coach/server.py), [`questions.py`](services/coach/questions.py), [`review.py`](services/coach/review.py), [`engine.py`](services/chess_analysis/engine.py) |
| Tổng kết buổi học | [`Summary.scala`](lila/modules/aicoach/src/main/Summary.scala) |

## Cài đặt và chạy

### 1. Chuẩn bị Lichess

Dùng checkout `feature/coach`. Chuẩn bị Java, sbt, Node.js, pnpm và các dịch vụ nền của Lichess, gồm MongoDB, Redis, lila-ws và fishnet để máy có thể đáp nước. Hướng dẫn cài Lila dẫn đến quy trình thiết lập môi trường phát triển của dự án gốc. [Cài đặt Lila](lila/README.md#installation) · [lila-ws](lila-ws/README.md) · [lila-fishnet](lila-fishnet/README.md)

### 2. Chạy worker Coach

Cần Python 3.10 trở lên và Stockfish có trên `PATH`. Nếu Stockfish được cài ở vị trí khác, đặt `STOCKFISH_PATH` trỏ đến tệp thực thi. Tạo một token nội bộ dài ít nhất 32 ký tự và cung cấp cùng giá trị qua biến môi trường `COACH_INTERNAL_TOKEN` cho cả Lila và worker. Có thể tạo token bằng `openssl rand -hex 32`.

Từ thư mục gốc của repo, chạy:

```sh
cd services
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
COACH_LLM_PROVIDER=off .venv/bin/python -m coach.server --host 127.0.0.1 --port 8137
```

Giữ worker trên địa chỉ nội bộ. Cấu hình mặc định chạy với một tác vụ phân tích đồng thời. Ví dụ trên dùng Stockfish và nhận xét theo mẫu, nên có thể thử Coach mà không cần API key của dịch vụ LLM.

### 3. Bật Coach trên Lila

Trong `lila/conf/application.conf`, cập nhật các khóa sau. Nếu tệp chưa tồn tại, tạo từ `lila/conf/application.conf.default`.

```hocon
aiCoach.enabled = true
aiCoach.workerUrl = "http://127.0.0.1:8137"
aiCoach.internalToken = ${?COACH_INTERNAL_TOKEN}
```

Từ `lila/`, cài và build đầy đủ UI để sinh asset manifest. Sau đó chạy Lila với cùng token nội bộ đã cấp cho worker.

```sh
pnpm install --frozen-lockfile
./ui/build
./lila.sh
```

Trong console sbt, nhập `run`. Mở `/ai-coach` trên địa chỉ Lila vừa chạy. [Cấu hình mặc định](lila/conf/application.conf.default)

### Tùy chọn diễn đạt bằng LLM

Để bật lớp diễn đạt, đặt `COACH_LLM_PROVIDER=openai-compatible` cùng `COACH_LLM_BASE_URL`, `COACH_LLM_MODEL` và `COACH_LLM_API_KEY` theo dịch vụ sử dụng. URL cơ sở trỏ đến tiền tố API, vì worker tự nối `/chat/completions`. Cấu hình được đọc lúc worker khởi động. Giữ API key và token nội bộ trong môi trường phía server. [Cấu hình provider](services/coach/provider.py)

## Kiểm tra trên trình duyệt

1. Mở `/ai-coach`, bắt đầu buổi học với quân Trắng và bấm **Gợi ý**.
2. Đi `e4`, đợi máy đáp, rồi chọn **Giải thích nước của bạn**. Kiểm tra lời giải thích gắn với nước vừa đi.
3. Tải lại trang và kiểm tra khung Coach vẫn mở đúng phiên. Khi có thẻ **Thử lại từ thế này**, thử một biến và kiểm tra bàn đấu chính vẫn giữ nguyên.
4. Kết thúc ván và kiểm tra **Tổng kết buổi học**, gồm số nước đã phân tích và các mốc được chọn nếu có.

## Tài liệu của nhóm

Nhánh này kế thừa ba chức năng chung từ `main`. Hướng dẫn từng chức năng nằm trong [Ưu thế Trắng–Đen](docs/win-probability/README.md), [Mục tiêu luyện tập hằng ngày](docs/daily-goal/README.md) và [Bình luận viên tiếng Việt](docs/commentary/README.md). Xem [mục lục tài liệu](docs/README.md) và [README của nhánh main](https://github.com/trantrien1/Lichess-workspace/blob/main/README.md) để dựng các dịch vụ dùng chung.

## Giấy phép

Lila sử dụng [GNU AGPL v3](lila/LICENSE). Các dự án đi kèm có giấy phép trong thư mục tương ứng.
