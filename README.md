# SSD-health

Công cụ dòng lệnh viết bằng Python 3 (chỉ dùng thư viện chuẩn) để kiểm tra sức khỏe ổ SSD, NVMe và HDD trên Debian. Công cụ đọc dữ liệu S.M.A.R.T. thông qua `smartctl` của gói `smartmontools`.

## Tính năng

- Tự quét mọi ổ đĩa, hoặc chỉ kiểm tra một ổ bạn chỉ định.
- Hỗ trợ ổ SATA/SSD (thuộc tính ATA) và ổ NVMe (health log).
- Hiển thị model, serial, firmware, dung lượng, nhiệt độ, giờ hoạt động, tuổi thọ còn lại và tổng dung lượng đã ghi.
- Phát hiện sector hỏng, sector chờ xử lý, lỗi đọc/ghi/xóa, lỗi cáp, nhiệt độ cao, dự phòng NVMe xuống thấp.
- Xuất kết quả dạng văn bản hoặc JSON (để đưa vào script giám sát).
- Mã thoát rõ ràng, tiện dùng trong cron hoặc systemd timer.

## Cài đặt

```bash
sudo apt update
sudo apt install -y smartmontools git
git clone https://github.com/anhtuanng98/ssd-health.git
cd ssd-health
```

Không cần cài thêm thư viện Python nào. Cần Python 3 (đã có sẵn trên Debian).

## Cách dùng

```bash
# Quét và kiểm tra mọi ổ
sudo python3 ssd_health.py

# Chỉ kiểm tra một ổ
sudo python3 ssd_health.py -d /dev/sda
sudo python3 ssd_health.py -d /dev/nvme0

# Xuất JSON
sudo python3 ssd_health.py --json > suc-khoe.json
```

Cần quyền root vì `smartctl` đọc thông tin phần cứng trực tiếp từ ổ.

### Mã thoát

| Mã | Ý nghĩa |
|----|---------|
| 0  | Tốt, không phát hiện vấn đề |
| 1  | Cảnh báo, nên theo dõi và sao lưu |
| 2  | Nguy hiểm, nên sao lưu ngay và cân nhắc thay ổ |
| 3  | Có ổ không đọc được hoặc thiếu smartmontools |

## Ví dụ kết quả

```
================================================================
Ổ: /dev/nvme0
  Model        : Samsung SSD 970 EVO Plus 1TB
  Serial       : S4EWNX0N123456    Firmware: 2B2QEXM7
  Dung lượng   : 1000 GB
  SMART chung  : PASSED
  Nhiệt độ     : 41 °C
  Giờ hoạt động: 8120 giờ    Số lần bật nguồn: 312
  Tuổi thọ còn : 84 %
  Đã ghi (ước) : 38.5 TB
  Vấn đề:
    [CẢNH BÁO] Đã dùng 16% tuổi thọ định mức
  Kết luận     : CẢNH BÁO
================================================================
Tổng kết: CẢNH BÁO
```

(Số liệu trên chỉ là ví dụ minh họa.)

## Ngưỡng cảnh báo

| Chỉ số | Cảnh báo | Nguy hiểm |
|--------|----------|-----------|
| Nhiệt độ | ≥ 70 °C | ≥ 80 °C |
| NVMe `percentage_used` | ≥ 80 % | ≥ 100 % |
| NVMe dự phòng (`available_spare`) | — | ≤ ngưỡng của firmware |
| ATA sector hỏng (5, 196) | có lỗi | — |
| ATA sector chờ / không sửa được (197, 198, 187) | — | có lỗi |
| ATA lỗi cáp CRC (199) | có lỗi | — |
| ATA tuổi thọ còn lại (169, 177, 233) | ≤ 20 % | ≤ 10 % hoặc ≤ ngưỡng nhà sản xuất |

## Lưu ý

- Kết quả "TỐT" không có nghĩa ổ chắc chắn không hỏng. S.M.A.R.T. chỉ là dấu hiệu sớm. Hãy luôn sao lưu dữ liệu quan trọng.
- Tên thuộc tính S.M.A.R.T. và cách tính tuổi thọ khác nhau giữa các hãng. Công cụ dùng các ID phổ biến nên có thể chưa bao phủ hết mọi dòng ổ.
- "Đã ghi (ước)" lấy từ thuộc tính tổng số sector đã ghi (ATA 241) hoặc `data_units_written` (NVMe), chỉ mang tính tham khảo.
- Ổ gắn qua hộp USB có thể cần thêm tham số `-d sat` của smartctl. Nếu công cụ không đọc được, hãy thử chạy `sudo smartctl -a -d sat /dev/sdX` để kiểm tra.
- Một số ổ phải bật S.M.A.R.T. trong BIOS/UEFI hoặc dùng `sudo smartctl -s on /dev/sdX`.

## Giấy phép

Chưa khai báo.
