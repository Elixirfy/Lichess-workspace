# Lichess Workspace

Bản Lichess chạy local, được nhóm bổ sung ba tính năng: **ưu thế Trắng/Đen
theo thời gian thực**, **bình luận viên tiếng Việt** và **mục tiêu luyện tập
hằng ngày**. Repo gom mã nguồn [Lichess](https://github.com/lichess-org/lila),
các dự án đi kèm và các dịch vụ Python của nhóm vào một chỗ, để dựng và chạy
toàn bộ hệ thống trên một máy.

## Tính năng của nhóm

| Tính năng | Người dùng thấy ở đâu | Thành phần chính |
|---|---|---|
| Ưu thế Trắng/Đen | Thanh ngang khi chơi và khi xem ván, thanh dọc khi xem lại | `lila/ui`, `services/prediction` |
| Bình luận viên tiếng Việt | Nút **Bình luận tiếng Việt** trong ván cờ tiêu chuẩn | `lila/modules/round`, `services/commentary` |
| Mục tiêu hằng ngày | Thẻ trên trang chủ, trang `/account/daily-goal` | `lila/modules/dailyGoal` |

### 1. Ưu thế Trắng/Đen (Win%)

Trong ván cờ tiêu chuẩn, thanh ngang trên giao diện chơi cho biết tỷ lệ ưu thế
của hai bên. Người chơi (khi đấu máy hoặc đấu người) và người xem đều thấy
thanh này. Khi xem lại ván, thanh dọc cạnh bàn cờ cho biết tỷ lệ tại nước đang
chọn.

Điểm Stockfish (centipawn, giới hạn trong ±1000) được đổi sang phần trăm theo
công thức [Win% của Lichess](https://lichess.org/page/accuracy):
`Trắng = round(100 / (1 + exp(-0.00368208 × cp)))`, `Đen = 100 − Trắng`.
Dịch vụ `services/prediction` chạy Stockfish trong worker riêng. Kết quả được
lưu đệm theo ván, nên nhiều người xem cùng một ván chỉ cần tính một lần.

Tài liệu: [kiến trúc, công thức và kết quả](docs/win-probability/README.md) ·
[model card của mô hình thử nghiệm theo rating](docs/win-probability/human-model-v1/model-card.md)

### 2. Bình luận viên tiếng Việt

Người chơi bật **Bình luận tiếng Việt** trong ván cờ tiêu chuẩn và chọn một
trong ba bình luận viên: Mạnh Dũng, Hữu Quân hoặc Anh Khôi. Sau mỗi nước đi,
người chơi nghe lời bình kèm phụ đề.

Lila gửi trạng thái ván tới một worker Python. Worker dùng python-chess và
Stockfish để rút ra diễn biến, ghép câu từ kho câu tiếng Việt viết sẵn (không
dùng mô hình ngôn ngữ), rồi đọc thành giọng nói bằng VieNeu v3 Nano trên CPU.
Lời bình của một thế cờ đã qua sẽ bị bỏ, để không đọc trễ.

Tài liệu: [thiết kế và luồng xử lý](docs/commentary/README.md) ·
[cài đặt dịch vụ](services/commentary/README.md)

### 3. Mục tiêu hằng ngày và chuỗi ngày luyện tập

Người chơi đặt số bài tập và số ván cần hoàn thành mỗi ngày tại
`/account/daily-goal`. Mỗi ngày đạt đủ mục tiêu thì chuỗi ngày tăng một; bỏ lỡ
một ngày thì chuỗi về 0. Ngày được tính theo múi giờ của người chơi. Thẻ tiến
độ nằm trên trang chủ.

Module nghe sự kiện hoàn thành bài tập và kết thúc ván có sẵn trong Lichess,
nên không phải sửa luồng xử lý gốc. Mỗi người chơi có một bản ghi trong
MongoDB.

Tài liệu: [tổng quan và kiểm thử](docs/daily-goal/README.md) ·
[kiến trúc](docs/daily-goal/kien-truc.md) ·
[giao diện](docs/daily-goal/giao-dien.md) ·
[luồng xử lý](docs/daily-goal/luong-xu-ly.md)

## Cấu trúc thư mục

```text
.
├── lila/                      Máy chủ web Lichess (Scala 3, Play), nơi tích hợp các tính năng của nhóm
│   ├── app/                   Controller, route, view
│   ├── modules/               Các module nghiệp vụ (có dailyGoal)
│   └── ui/                    Frontend TypeScript
├── lila-ws/                   Máy chủ WebSocket
├── lila-fishnet/              Trung gian giao việc chơi và phân tích cho fishnet
├── fishnet/                   Worker chạy Stockfish
├── scalachess/                Thư viện luật cờ (Scala)
├── chessground/               Thư viện bàn cờ phía trình duyệt
├── services/
│   ├── prediction/            Dịch vụ đánh giá thế cờ cho Win% (FastAPI, Stockfish)
│   └── commentary/            Dịch vụ bình luận viên tiếng Việt (FastAPI, python-chess, VieNeu)
├── patches/                   Bản vá bình luận viên trên lila gốc, giữ để tham khảo
└── docs/                      Tài liệu các tính năng của nhóm
```

`lila/`, `lila-ws/`, `lila-fishnet/`, `fishnet/`, `scalachess/` và
`chessground/` là mã nguồn Lichess được đưa thẳng vào repo. Mỗi thư mục giữ
README và giấy phép riêng.

## Công nghệ

| Phần | Công nghệ |
|---|---|
| Backend | Scala 3, Play Framework, MongoDB, Redis |
| Frontend | TypeScript, Snabbdom, Sass |
| Dịch vụ của nhóm | Python 3, FastAPI, python-chess, Stockfish |
| Giọng nói | VieNeu v3 Nano (ONNX Runtime, CPU) |

## Cài đặt và chạy

Cần Java, sbt, Node.js, pnpm, MongoDB, Redis và lila-ws, cài theo
[hướng dẫn phát triển của Lichess](https://github.com/lichess-org/lila/wiki/Lichess-Development-Onboarding).
Phần Python cần Python 3.12, [uv](https://docs.astral.sh/uv/) và Stockfish.

**1. Dựng lila**

```sh
cd lila
pnpm install --frozen-lockfile
./ui/build
./lila.sh --server --batch stage
```

`./ui/build` phải chạy đầy đủ, không kèm tên package, để sinh asset manifest
mới.

**2. Chạy dịch vụ Win%**

```sh
cd services/prediction
uv sync --frozen
STOCKFISH_PATH=/usr/games/stockfish uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 9667
```

Rồi bật tính năng trong `lila/conf/application.conf`:

```hocon
winProbability.enabled = true
winProbability.url = "http://127.0.0.1:9667"
```

**3. Chạy dịch vụ bình luận viên**

Cài worker, model giọng và token theo
[README dịch vụ bình luận](services/commentary/README.md). Worker chạy ở
`127.0.0.1:9666`. Thêm vào `lila/conf/application.conf`:

```hocon
commentary.enabled = true
commentary.endpoint = "http://127.0.0.1:9666"
commentary.token = ${?BLV_TOKEN}
```


## Kiểm thử

| Phạm vi | Lệnh |
|---|---|
| Win%: dịch vụ | trong `services/prediction`: `uv run --frozen --group ml pytest` |
| Win%: giao diện | trong `lila/`: `node ui/test winProbability.test.ts winningChances.test.ts advantage.test.ts` |
| Bình luận viên: dịch vụ | trong `services/commentary`: `python -m unittest discover -s tests` |
| Bình luận viên: giao diện | trong `lila/`: `node ui/test commentary.test.ts` |
| Mục tiêu hằng ngày | trong `lila/`: `sbt 'dailyGoal/Test/testOnly lila.dailyGoal.*'` |

## Tài liệu

Mục lục đầy đủ ở [docs/README.md](docs/README.md).

## Nhánh

`main` là bản chung của nhóm, gồm ba tính năng ở trên. Ngoài ra, mỗi thành
viên phát triển một phần riêng trên nhánh của mình. Các nhánh dưới đây đã hoàn
thành; mỗi nhánh có README và tài liệu riêng.

| Nhánh | Tính năng | Thực hiện |
|---|---|---|
| [feature/tilt-and-ai-coach](https://github.com/trantrien1/Lichess-workspace/tree/feature/tilt-and-ai-coach) | **Tilt:** nhận biết dấu hiệu chơi mất bình tĩnh qua các ván blitz và nhắc người chơi nghỉ trên trang chủ; chỉ người chơi đó thấy kết quả. **AI Coach:** hỏi đáp bằng tiếng Việt về ván vừa kết thúc, dựa trên phân tích Stockfish | [trantrien1](https://github.com/trantrien1) |
| [feature/coach](https://github.com/trantrien1/Lichess-workspace/tree/feature/coach) | Huấn luyện khi chơi: phiên luyện tập có hướng dẫn, phân tích từng nước bằng Stockfish, gợi ý có giới hạn và nhận xét tiếng Việt ngay trên giao diện ván | [LeHuy2109](https://github.com/LeHuy2109) |
| [feature/webmcp](https://github.com/trantrien1/Lichess-workspace/tree/feature/webmcp) | Hai công cụ WebMCP trong trang Lichess cho trợ lý AI: tìm ván theo bộ lọc nâng cao và trả các bước ngoặt của ván từ đánh giá engine có sẵn, đều dạng JSON | [Elixirfy](https://github.com/Elixirfy) |
| [codex/vietnamese-voice-input](https://github.com/trantrien1/Lichess-workspace/tree/codex/vietnamese-voice-input) | Chơi cờ bằng giọng nói tiếng Việt: Vosk nhận dạng ngay trên trình duyệt, PhoWhisper chạy local khi Vosk chưa nhận ra; lệnh được đối chiếu với các nước hợp lệ trước khi đi quân | [ceokon1](https://github.com/ceokon1) |

Danh sách đầy đủ các nhánh: [docs/branches.md](docs/branches.md).

## Giấy phép

Lila và các dự án Lichess đi kèm dùng giấy phép riêng ghi trong từng thư mục
(lila dùng [GNU AGPL v3](lila/LICENSE)). Phần nhóm bổ sung vào lila theo cùng
giấy phép đó. Model giọng VieNeu v3 Nano dùng giấy phép Apache-2.0.

Cảm ơn [Lichess](https://lichess.org), [Stockfish](https://stockfishchess.org)
và [VieNeu-TTS](https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano).
