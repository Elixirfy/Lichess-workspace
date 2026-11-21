# Tài liệu

Tài liệu các tính năng nhóm bổ sung vào Lichess. Cách cài đặt và chạy toàn bộ hệ
thống ở [README gốc](../README.md).

```text
docs/
├── README.md                  Mục lục (tệp này)
├── win-probability/           Ưu thế Trắng/Đen (Win%)
│   ├── README.md
│   └── human-model-v1/        Model card và số liệu của mô hình thử nghiệm
├── commentary/                Bình luận viên tiếng Việt
│   └── README.md
├── daily-goal/                Mục tiêu hằng ngày và chuỗi ngày
│   ├── README.md
│   ├── kien-truc.md
│   ├── giao-dien.md
│   ├── luong-xu-ly.md
│   └── images/
└── branches.md                Danh sách nhánh
```

## Ưu thế Trắng/Đen (Win%)

| Tài liệu | Nội dung |
|---|---|
| [README](win-probability/README.md) | Luồng xử lý, công thức hiển thị, so sánh với Lichess có sẵn, kết quả, hạn chế, các tệp chính |
| [Model card](win-probability/human-model-v1/model-card.md) | Mô hình thử nghiệm dự đoán kết quả theo rating và đồng hồ: dữ liệu, cách đánh giá, giới hạn. Không dùng cho Win% đang hiển thị |

## Bình luận viên tiếng Việt

| Tài liệu | Nội dung |
|---|---|
| [README](commentary/README.md) | Trải nghiệm người dùng, kiến trúc, cách tạo lời bình, tổng hợp giọng, hàng chờ, quyền truy cập, các tệp chính |
| [Cài đặt dịch vụ](../services/commentary/README.md) | Cài worker và model, cấu hình, chạy, kiểm thử |

## Mục tiêu hằng ngày và chuỗi ngày

| Tài liệu | Nội dung |
|---|---|
| [README](daily-goal/README.md) | Tổng quan, phạm vi, kiểm thử, giới hạn |
| [Kiến trúc](daily-goal/kien-truc.md) | Sơ đồ thành phần, vai trò từng tệp, dữ liệu MongoDB, quyết định thiết kế |
| [Giao diện](daily-goal/giao-dien.md) | Ảnh chụp, các trạng thái của thẻ trang chủ, trang cài đặt |
| [Luồng xử lý](daily-goal/luong-xu-ly.md) | Đặt mục tiêu, ghi nhận bài tập và ván, tính chuỗi, trường hợp biên |

## Khác

- [Danh sách nhánh](branches.md)
