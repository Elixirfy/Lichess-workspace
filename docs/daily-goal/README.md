# Mục tiêu hằng ngày và chuỗi ngày luyện tập

Người chơi tự đặt số bài tập và số ván muốn hoàn thành mỗi ngày. Lila tự đếm
khi bài tập hoặc ván kết thúc. Ngày nào đủ mục tiêu thì chuỗi ngày tăng thêm
một, bỏ lỡ một ngày thì chuỗi về 0, giống chuỗi ngày học của Duolingo.

| Tài liệu | Nội dung |
|---|---|
| [Kiến trúc](kien-truc.md) | Các thành phần, dữ liệu MongoDB, chỗ gắn vào lila, các quyết định thiết kế |
| [Giao diện](giao-dien.md) | Thẻ trên trang chủ, trang cài đặt, các trạng thái hiển thị |
| [Luồng xử lý](luong-xu-ly.md) | Đặt mục tiêu, ghi nhận bài tập và ván, sang ngày, tính chuỗi, tắt mục tiêu, trường hợp biên |

## Phạm vi và nguồn

Module nằm ở `lila/modules/dailyGoal`. Module vào kho chung ở commit `f5ce3c0`
(12/11/2026, nhánh `feature/daily-streak`) và có trong `main` từ mốc
`b8fc69b`. Lichess gốc có Puzzle Streak, nhưng chế độ đó chỉ đếm số bài giải
đúng liên tiếp trong một lượt chơi, không theo dõi việc luyện tập qua nhiều
ngày.

Module chỉ nghe sự kiện mà lila đã phát sẵn, nên không sửa code xử lý bài tập
hay ván đấu của Lichess.

## Chức năng

- Đặt mục tiêu tại `/account/daily-goal` (mục **Daily goal** trong menu tài
  khoản). Mỗi ngày chọn 0, 3, 5, 10, 15, 20 hoặc 30 bài tập và 0, 1, 2, 3 hoặc 5
  ván, ít nhất một chỉ tiêu lớn hơn 0. Mục tiêu mới mặc định là 10 bài tập và
  1 ván.
- Ngày kết thúc lúc nửa đêm theo múi giờ người chơi chọn. Khi tạo mục tiêu lần
  đầu, trình duyệt điền sẵn múi giờ của máy.
- Một bài tập được tính ở lần đầu người chơi hoàn thành bài đó, đúng hay sai đều
  tính. Một ván được tính khi kết thúc, trừ ván bị hủy.
- Ngày đạt khi đủ cả hai chỉ tiêu. Nếu hôm trước cũng đạt thì chuỗi tăng một,
  nếu không thì chuỗi bắt đầu lại từ 1. Chuỗi được giữ đến hết ngày kế tiếp ngày
  đạt gần nhất, nên hôm nay người chơi vẫn còn cả ngày để nối chuỗi.
- Hệ thống lưu chuỗi dài nhất từng đạt và tối đa 31 ngày đạt gần nhất.
- Trang chủ có thẻ tiến độ. Trang cài đặt hiện chuỗi hiện tại, chuỗi dài nhất
  và bảy ngày gần nhất.
- Tắt mục tiêu sẽ xóa cả chuỗi. Khi tài khoản bị xóa, dữ liệu mục tiêu cũng bị
  xóa theo.

## Kiểm thử

Bộ test đơn vị `DailyGoalTest` có 8 ca, dùng múi giờ `Asia/Ho_Chi_Minh`. Chạy
trong `lila/`:

```sh
sbt 'dailyGoal/Test/testOnly lila.dailyGoal.*'
```

Các ca kiểm tra:

- ngày chỉ đạt khi đủ cả hai chỉ tiêu;
- làm thêm sau khi đạt không làm chuỗi tăng hai lần;
- các ngày đạt liên tiếp làm chuỗi tăng dần;
- sang ngày mới thì đếm lại từ 0;
- chuỗi còn giữ trong ngày kế tiếp và mất khi bỏ lỡ một ngày;
- ngày kết thúc lúc nửa đêm giờ địa phương, không phải nửa đêm UTC;
- hạ chỉ tiêu thì ngày được hoàn thành ngay;
- lịch bảy ngày đánh dấu đúng các ngày đạt.

Lần chạy ngày 18/11/2026 cho kết quả 8/8 ca đạt.

Ngày 12/11/2026, nhóm chạy thêm một kịch bản đầu-cuối trên bản chạy local, dùng
hai tài khoản thử và chơi ván qua Board API. DB local không có sẵn bài tập, nên
bài tập thử phải chèn tạm vào DB; mỗi bài cần một ván nguồn có thật.

| Thao tác | Kết quả mong đợi | Kết quả |
|---|---|---|
| Mở trang chủ khi chưa đặt mục tiêu | Thẻ là lời mời đặt mục tiêu | Đạt |
| Mở `/account/daily-goal` | Trang ở trạng thái tạo mục tiêu mới | Đạt |
| Gửi 0 bài tập và 0 ván | Bị từ chối, báo cần ít nhất một chỉ tiêu | Đạt |
| Lưu 3 bài tập và 1 ván | Trang chủ hiện 0 / 3 bài tập | Đạt |
| Hoàn thành 3 bài tập | 3 / 3 bài tập, 0 / 1 ván, ngày chưa đạt | Đạt |
| Chơi xong 1 ván | Ngày đạt, chuỗi 1 ngày | Đạt |
| Mở lại trang cài đặt | Chuỗi hiện tại và dài nhất đều là 1 | Đạt |
| Nâng mục tiêu lên 5 bài tập | Ngày đã đạt vẫn được giữ | Đạt |

## Giới hạn và hướng phát triển

- Chữ giao diện của module viết thẳng bằng tiếng Anh, chưa qua hệ thống dịch
  của Lichess.
- Thẻ trang chủ chỉ cập nhật khi tải lại trang, chưa được đẩy qua WebSocket.
- Mọi ván kết thúc mà không bị hủy đều được tính, kể cả ván không xếp hạng và
  ván với máy.

Hướng tiếp theo: dịch giao diện, cập nhật thẻ theo thời gian thực, và cho người
chơi chọn loại ván được tính vào mục tiêu.
