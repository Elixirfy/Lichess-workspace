# Bình luận viên tiếng Việt

Phiên bản đang vận hành dùng **VieNeu v3 Nano trên CPU**, ba giọng **Mạnh Dũng
(mặc định), Hữu Quân, Anh Khôi**. Lila lấy dữ liệu ván cờ chính thức; Python
kiểm tra thế cờ, chọn câu tiếng Việt viết sẵn và tổng hợp WAV. Người chơi bật
bình luận, chọn trực tiếp tên BLV và nghe câu chào mang tên người đó.

Tài liệu thiết kế, luồng dữ liệu, hàng chờ, quyền truy cập và các giới hạn:
[Chức năng bình luận viên tiếng Việt](../../docs/binh-luan-vien-tieng-viet.md).

## Cài worker và model

Cần Python 3.10 trở lên và Stockfish. Từ thư mục này:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
python3 -m venv .venv-nano
.venv-nano/bin/pip install -r requirements-vieneu.lock
.venv-nano/bin/hf download pnnbao-ump/VieNeu-TTS-v3-Nano --revision aba295eb96a6fa6003ebe417cc1f2802a7adc1dc --local-dir /path/to/nano --include text_encoder.onnx duration_predictor.onnx vector_estimator.onnx codec_decoder.onnx config.json constants.npz
```

`nano-assets.json` ghi revision, URL và SHA256 của sáu tệp model. Model được
khai báo theo Apache-2.0. Môi trường Nano được tách khỏi môi trường HTTP worker.

## Cấu hình

Tạo `.env` theo `.env.example`. `BLV_TOKEN` là bí mật dùng chung giữa Lila và
worker; `BLV_STOCKFISH` là đường dẫn engine. Cấu hình giọng đang dùng:

```dotenv
BLV_TTS_PROVIDER=vieneu
BLV_NANO_DIR=/absolute/path/to/nano
BLV_NANO_PYTHON=/absolute/path/to/services/commentary/.venv-nano/bin/python
BLV_NANO_STEPS=16
BLV_NANO_THREADS=1
BLV_NANO_SPEED=1.2
BLV_NANO_TIMEOUT=7
```

Tốc độ nền 1,2 áp dụng cho Mạnh Dũng và Hữu Quân. Anh Khôi dùng thêm hệ số
1,15, tức tốc độ hiệu lực 1,38. WAV giữ tần số 24 kHz. Model nạp một lần, chỉ
một câu Nano được tổng hợp tại một thời điểm; cache tối đa 64 câu theo giọng và
văn bản. Kết quả lỗi thời không được phát lại cho thế cờ mới.

## Chạy local

Từ gốc workspace:

```sh
./lichess-local
```

Mở URL launcher in ra, tạo ván tiêu chuẩn và bật bình luận. Khi sửa cấu hình,
chạy `./lichess-local stop` rồi khởi động lại. Chỉ dùng `--no-build` khi bản
UI và Scala đã được build theo code hiện tại.

Khi tự build từ `lila/`, dùng `./ui/build` **không kèm tên package** để sinh
asset manifest, rồi `./lila.sh --server --batch stage`. Sau đó restart stack và
kiểm tra bộ chọn trên trình duyệt thật.

Worker bind `127.0.0.1:9666`, yêu cầu bearer token. Nếu chạy `uvicorn` trực
tiếp, phải export cấu hình trước; launcher mới tự đọc `.env`. Không commit
`.env`, không đưa token xuống browser. Chi tiết stack ở [LOCAL.md](../../LOCAL.md).

## Kiểm thử

```sh
.venv/bin/pip install -r requirements-test.txt
BLV_NANO_DIR=/path/to/nano .venv/bin/python -m unittest discover -s tests
```

Test tổng hợp thật cần model và môi trường Nano đã cài; test adapter HTTP dùng
server giả lập, không gọi dịch vụ bên ngoài. Test UI từ `lila/`:

```sh
node ui/test commentary.test.ts
```

Kiểm tra thủ công: đúng ba tên, Mạnh Dũng được chọn mặc định, đổi BLV phát lời
chào riêng, phụ đề theo lời đang đọc và không đọc lại thế cờ lỗi thời. Chất âm,
độ rõ và độ trễ cần đánh giá trên máy thực tế; Nano vẫn có giới hạn chất lượng.
