# Gói Python Tilt

Gói này xây dựng và chạy mô hình Tilt: thu thập ván Lichess, phân tích bằng
Stockfish, tính đặc trưng, gán nhãn bằng bộ luật, huấn luyện, và worker chấm điểm
các ván blitz cho lila. Phần hiển thị trong lila nằm ở `lila/modules/tilt`.

Tài liệu đầy đủ (tiếng Việt) ở [`docs/`](docs/README.md):

- [Tổng quan](docs/tong-quan.md): Tilt làm gì, người chơi thấy gì.
- [Xây dựng mô hình](docs/xay-dung-mo-hinh.md): dữ liệu, bộ luật, đặc trưng, huấn luyện.
- [Vận hành](docs/van-hanh.md): luồng chấm điểm, cách chạy worker, quay về mô hình cũ.
- [Kết quả](docs/ket-qua.md): số đo trên phần đánh giá cuối.
- [Mã nguồn](docs/ma-nguon.md): cấu trúc thư mục, các lệnh, mã bị khóa hash, kiểm thử.
- [Dữ liệu Lichess](docs/du-lieu-lichess.md): ý nghĩa các trường API, công thức.

## Cài đặt

Chạy tại gốc repo:

```bash
python3.12 -m venv tilt/.venv
tilt/.venv/bin/pip install -r tilt/requirements-lock.txt
tilt/.venv/bin/pip install -e 'tilt[test,lila]'
```

Cần Stockfish ở `/usr/games/stockfish` và một salt riêng lưu ngoài git, ví dụ
`~/.tilt-salt` (xem [Salt](docs/ma-nguon.md#salt)).

## Chạy

```bash
tilt/scripts/start-lichess.sh                       # cả hệ thống, gồm worker
TILT_SALT="$(cat ~/.tilt-salt)" tilt/.venv/bin/python -m tilt lila-worker   # chỉ worker
```

Worker cần mô hình đã huấn luyện trong `tilt/data/processed/models/`. Thư mục
`tilt/data/` chứa dữ liệu riêng tư nên không nằm trong git.

## Cấu trúc

```text
src/tilt/
├── common/       Công thức Lichess, Stockfish
├── data/         Thu thập, chuẩn hóa, lưu trữ ván
├── features/     Đặc trưng
├── labels/       Bộ luật v3, nhãn yếu, nhãn người
├── training/     Huấn luyện
├── evaluation/   Đánh giá
└── service/      Worker và chấm điểm trực tiếp cho lila
```

## Kiểm thử

```bash
tilt/.venv/bin/python -m pytest tilt/tests -q
```

Mã port công thức ghi đường dẫn tới mã gốc của Lichess ngay cạnh từng hàm. Gói
dùng giấy phép AGPL như Lichess (`LICENSE`, `NOTICE`).
