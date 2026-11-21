# Luồng xử lý — Mục tiêu hằng ngày

[Tổng quan](README.md) · [Kiến trúc](kien-truc.md) · [Giao diện](giao-dien.md)

## 1. Đặt hoặc sửa mục tiêu

```mermaid
sequenceDiagram
    actor N as Người chơi
    participant T as Trình duyệt
    participant C as controllers.DailyGoal
    participant A as DailyGoalApi
    participant M as MongoDB daily_goal
    N->>T: Mở /account/daily-goal
    T->>C: GET /account/daily-goal
    C->>A: get(người chơi)
    A->>M: tìm theo _id
    M-->>A: tài liệu hoặc không có
    C-->>T: Trang cài đặt (form điền theo mục tiêu cũ, hoặc mặc định 10 bài, 1 ván)
    Note over T: Mục tiêu mới: user.account.ts chọn sẵn múi giờ của trình duyệt
    N->>T: Chọn số bài, số ván, múi giờ rồi bấm Start/Save
    T->>C: POST /account/daily-goal
    alt Dữ liệu không hợp lệ
        C-->>T: 400, trang cài đặt kèm lỗi
    else Hợp lệ
        C->>A: setGoal(người chơi, dữ liệu)
        A->>M: đọc tài liệu cũ
        Note over A: Chưa có thì tạo mới, có rồi thì đổi chỉ tiêu, múi giờ và xét lại hôm nay
        A->>M: upsert tài liệu
        C-->>T: Chuyển về trang cài đặt, báo thành công
    end
```

Biểu mẫu chỉ nhận giá trị có trong danh sách lựa chọn (0, 3, 5, 10, 15, 20, 30
bài tập; 0, 1, 2, 3, 5 ván), một múi giờ hợp lệ, và tổng hai chỉ tiêu lớn hơn 0.

Sau khi đổi chỉ tiêu, hệ thống xét lại hôm nay ngay. Nếu tiến độ hiện có đã đủ
chỉ tiêu mới thì hôm nay được tính là đạt luôn.

## 2. Ghi nhận bài tập và ván

```mermaid
sequenceDiagram
    participant P as Module puzzle / xử lý ván
    participant B as Bus của lila
    participant E as dailyGoal.Env
    participant A as DailyGoalApi
    participant M as MongoDB daily_goal
    P->>B: Puzzle.UserResult (lần đầu xong bài) / FinishGame (ván kết thúc)
    B->>E: sự kiện
    Note over E: FinishGame bỏ qua ván bị hủy,<br/>ghi cho từng người chơi có tài khoản trong ván
    E->>A: record(người chơi, bài tập hoặc ván)
    Note over A: Xếp hàng theo người chơi, chạy lần lượt
    A->>M: đọc tài liệu
    alt Chưa đặt mục tiêu
        A-->>E: dừng, không ghi gì
    else Có mục tiêu
        Note over A: DailyGoal.record: cộng một, xét đạt, cập nhật chuỗi
        A->>M: upsert tài liệu mới
    end
```

- **Bài tập:** module puzzle chỉ phát `Puzzle.UserResult` ở lần đầu người chơi
  hoàn thành bài đó, nên làm lại một bài cũ không được tính thêm. Giải đúng hay
  sai đều tính.
- **Ván:** mọi ván kết thúc mà không bị hủy đều được tính cho từng người chơi có
  tài khoản trong ván. Ván với máy chỉ tính cho người chơi, vì máy không có tài
  khoản.

## 3. Tính ngày, tiến độ và chuỗi

Tất cả nằm trong `DailyGoal.record`, chạy mỗi lần có một bài tập hoặc ván mới:

1. Đổi thời điểm hiện tại sang ngày địa phương theo múi giờ của người chơi (gọi
   là "hôm nay").
2. Lấy tiến độ của hôm nay. Nếu ngày đang lưu không phải hôm nay thì tiến độ coi
   như 0, nên không cần tác vụ nào chạy lúc nửa đêm để đặt lại.
3. Cộng một vào số bài tập hoặc số ván, và đặt ngày đang đếm là hôm nay.
4. Xét hôm nay đạt hay chưa theo sơ đồ dưới.

```mermaid
flowchart TD
    S["Sau khi cộng một"] --> Q1{"Hôm nay (hoặc ngày sau đó)<br/>đã được tính là đạt?"}
    Q1 -- "Có" --> K["Giữ nguyên<br/>(không cộng chuỗi hai lần)"]
    Q1 -- "Chưa" --> Q2{"Đủ cả số bài tập<br/>và số ván?"}
    Q2 -- "Chưa" --> K2["Chỉ lưu tiến độ"]
    Q2 -- "Đủ" --> Q3{"Hôm qua có đạt không?"}
    Q3 -- "Có" --> U1["Chuỗi + 1"]
    Q3 -- "Không" --> U2["Chuỗi = 1"]
    U1 --> R["Cập nhật chuỗi dài nhất,<br/>ngày đạt gần nhất,<br/>thêm hôm nay vào danh sách ngày đạt (tối đa 31)"]
    U2 --> R
```

Khi hiển thị, chuỗi được tính lại theo hôm nay: nếu ngày đạt gần nhất là hôm nay
hoặc hôm qua thì hiện chuỗi đã lưu, còn cũ hơn thì hiện 0.

Ví dụ với mục tiêu 2 bài tập và 1 ván:

| Ngày | Đã làm | Kết quả |
|---|---|---|
| Thứ Hai | 2 bài, 1 ván | Đạt, chuỗi 1 |
| Thứ Ba, lúc 9 giờ | chưa làm gì | Chuỗi vẫn hiện 1, vì còn cả ngày để nối |
| Thứ Ba | 2 bài, 1 ván | Đạt, chuỗi 2 |
| Thứ Tư | không làm | — |
| Thứ Năm, lúc 9 giờ | chưa làm gì | Chuỗi hiện 0, vì đã bỏ lỡ thứ Tư |
| Thứ Năm | 2 bài, 1 ván | Đạt, chuỗi bắt đầu lại từ 1; chuỗi dài nhất vẫn là 2 |

## 4. Hiển thị trang chủ

1. Khi dựng trang chủ cho người đã đăng nhập (không phải bot), `Preload` đọc
   mục tiêu song song với truy vấn lớp học có sẵn.
2. Chưa có mục tiêu thì thẻ là lời mời đặt mục tiêu.
3. Có mục tiêu thì `DailyGoalUi.home` tính hôm nay theo múi giờ người chơi, rồi
   hiện chuỗi, tiến độ hôm nay và dòng trạng thái (đã đạt / giữ chuỗi / bắt đầu
   chuỗi).

## 5. Tắt mục tiêu và xóa tài khoản

- **Tắt:** nút **Turn off and reset my streak** hiện hộp xác nhận, rồi gửi
  `POST /account/daily-goal/off`. `DailyGoalApi.disable` xóa tài liệu của người
  chơi (qua cùng hàng đợi tuần tự), rồi trang tải lại ở trạng thái tạo mục tiêu
  mới. Chuỗi và lịch sử mất hẳn.
- **Xóa tài khoản:** lila phát `UserDelete` trên Bus, module gọi cùng hàm
  `disable` để xóa tài liệu.

## 6. Trường hợp biên

| Tình huống | Cách xử lý |
|---|---|
| Một bài tập và một ván kết thúc cùng lúc | Hai lần cập nhật xếp hàng theo người chơi, chạy lần lượt, nên không mất lần đếm nào |
| Làm thêm sau khi đã đạt | Tiến độ vẫn tăng, nhưng chuỗi không tăng lần nữa |
| Hạ chỉ tiêu giữa ngày khi tiến độ đã đủ | Hôm nay được tính là đạt ngay lúc lưu |
| Nâng chỉ tiêu sau khi đã đạt | Hôm nay vẫn giữ là đạt |
| Đổi sang múi giờ làm ngày địa phương lùi lại | Ngày đạt gần nhất đang ở "sau" hôm nay, nên một ngày không bị tính hai lần |
| Ván kết thúc lúc 23:30 và 0:30 giờ Việt Nam | Được tính vào hai ngày khác nhau theo giờ Việt Nam, dù cả hai đều là cùng một ngày UTC |
| Ván bị hủy | Không tính |
| Người chơi chưa đặt mục tiêu | Sự kiện chỉ tạo một lần đọc, không ghi gì |
| Danh sách ngày đạt dài | Chỉ giữ 31 ngày gần nhất; lịch trên trang chỉ cần 7 ngày |
