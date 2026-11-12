#!/usr/bin/env python3
"""
ssd_health.py - Kiểm tra sức khỏe ổ SSD/NVMe/HDD trên Debian bằng smartctl.

Yêu cầu:  sudo apt install smartmontools
Chạy:     sudo python3 ssd_health.py              # quét và kiểm tra mọi ổ
          sudo python3 ssd_health.py -d /dev/sda  # chỉ kiểm tra một ổ
          sudo python3 ssd_health.py --json       # xuất kết quả dạng JSON

Mã thoát: 0 = tốt, 1 = cảnh báo, 2 = nguy hiểm, 3 = có ổ không đọc được
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

OK, WARN, CRIT, ERR = 0, 1, 2, 3
LEVEL_TEXT = {OK: "TỐT", WARN: "CẢNH BÁO", CRIT: "NGUY HIỂM", ERR: "KHÔNG ĐỌC ĐƯỢC"}

# ATA: thuộc tính đếm lỗi. Raw > 0 nghĩa là ổ đã từng gặp lỗi đó.
ATA_ERROR_ATTRS = {
    5:   "Reallocated_Sector_Ct (sector đã được thay thế)",
    181: "Program_Fail_Count (lỗi ghi)",
    182: "Erase_Fail_Count (lỗi xóa)",
    187: "Reported_Uncorrect (lỗi đọc không sửa được)",
    196: "Reallocated_Event_Count (sự kiện thay thế sector)",
    197: "Current_Pending_Sector (sector đang chờ xử lý)",
    198: "Offline_Uncorrectable (sector hỏng, không đọc được)",
    199: "UDMA_CRC_Error_Count (lỗi truyền dữ liệu, thường do cáp/kết nối)",
}
ATA_CRITICAL_ATTRS = {187, 197, 198}      # các lỗi này mức nguy hiểm
ATA_LIFE_ATTRS = {169, 177, 233}          # tuổi thọ còn lại (100 = mới, giảm dần)
ATA_WRITTEN_ATTR = 241                    # Total_LBAs_Written (sector 512 byte)

TEMP_WARN, TEMP_CRIT = 70, 80             # °C
NVME_USED_WARN, NVME_USED_CRIT = 80, 100  # % tuổi thọ định mức đã dùng


def smartctl_json(args):
    """Chạy smartctl -j, trả về (dict, None) hoặc (None, thông_báo_lỗi)."""
    try:
        p = subprocess.run(["smartctl", "-j", *args],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return None, "smartctl quá thời gian chờ"
    if not p.stdout.strip():
        return None, p.stderr.strip() or "smartctl không trả về dữ liệu"
    try:
        return json.loads(p.stdout), None
    except json.JSONDecodeError:
        return None, "không đọc được đầu ra JSON của smartctl"


def scan_devices():
    """Trả về danh sách tên thiết bị (ví dụ /dev/sda). Loại thiết bị từ --scan
    không được dùng vì có thể sai (ví dụ ổ SATA báo là 'scsi')."""
    data, err = smartctl_json(["--scan"])
    if data is None:
        return [], err
    names = []
    for d in data.get("devices", []):
        name = d.get("name")
        if name and name not in names:
            names.append(name)
    return names, None


# Thử lần lượt: tự nhận dạng, rồi ép kiểu SAT (ổ SATA qua USB/bộ chuyển đổi).
SMART_ATTEMPTS = [[], ["-d", "sat"]]


def has_smart_data(data):
    return any(k in data for k in
               ("model_name", "ata_smart_attributes", "nvme_smart_health_information_log"))


def read_smart(name):
    """Trả về (data, None) nếu đọc được SMART, hoặc (None, [thông điệp lỗi])."""
    messages = []
    for extra in SMART_ATTEMPTS:
        data, err = smartctl_json(["-a", *extra, name])
        if data is None:
            messages.append(err)
            continue
        if has_smart_data(data):
            return data, None
        messages.extend(m.get("string", "")
                        for m in data.get("smartctl", {}).get("messages", [])
                        if m.get("string"))
    return None, messages


def check_device(name):
    data, messages = read_smart(name)
    if data is None:
        return {"device": name, "level": ERR,
                "error": "; ".join(dict.fromkeys(messages)) or "không có dữ liệu SMART"}

    info = {
        "device": name,
        "model": data.get("model_name", "không rõ"),
        "serial": data.get("serial_number", "không rõ"),
        "firmware": data.get("firmware_version", "không rõ"),
        "capacity_gb": round(data.get("user_capacity", {}).get("bytes", 0) / 1e9),
        "smart_passed": data.get("smart_status", {}).get("passed"),
        "temperature_c": data.get("temperature", {}).get("current"),
        "power_on_hours": data.get("power_on_time", {}).get("hours"),
        "power_cycles": data.get("power_cycle_count"),
        "written_tb": None,
        "life_left_pct": None,
        "level": OK,
        "issues": [],
    }

    def flag(level, msg):
        info["issues"].append({"level": LEVEL_TEXT[level], "msg": msg})
        info["level"] = max(info["level"], level)

    if info["smart_passed"] is False:
        flag(CRIT, "SMART tự đánh giá: FAILED. Hãy sao lưu dữ liệu ngay và cân nhắc thay ổ.")

    t = info["temperature_c"]
    if t is not None:
        if t >= TEMP_CRIT:
            flag(CRIT, f"Nhiệt độ {t}°C quá cao")
        elif t >= TEMP_WARN:
            flag(WARN, f"Nhiệt độ {t}°C khá cao")

    if "nvme_smart_health_information_log" in data:
        check_nvme(data["nvme_smart_health_information_log"], info, flag)
    elif "ata_smart_attributes" in data:
        check_ata(data["ata_smart_attributes"].get("table", []), info, flag)
    else:
        flag(WARN, "Thiết bị không cung cấp thuộc tính SMART chi tiết")

    return info


def check_nvme(log, info, flag):
    used = log.get("percentage_used")
    if used is not None:
        info["life_left_pct"] = max(0, 100 - used)
        if used >= NVME_USED_CRIT:
            flag(CRIT, f"Đã dùng {used}% tuổi thọ định mức")
        elif used >= NVME_USED_WARN:
            flag(WARN, f"Đã dùng {used}% tuổi thọ định mức")

    spare = log.get("available_spare")
    spare_thr = log.get("available_spare_threshold")
    if spare is not None and spare_thr is not None and spare <= spare_thr:
        flag(CRIT, f"Dung lượng dự phòng {spare}% đã xuống dưới ngưỡng {spare_thr}%")

    if log.get("critical_warning", 0):
        flag(CRIT, f"Firmware báo critical_warning = {log['critical_warning']}")
    if log.get("media_errors", 0):
        flag(WARN, f"Lỗi phương tiện lưu trữ: {log['media_errors']}")

    units = log.get("data_units_written")  # 1 đơn vị = 1000 sector 512 byte
    if units is not None:
        info["written_tb"] = units * 512_000 / 1e12


def check_ata(table, info, flag):
    for a in table:
        aid = a.get("id")
        name = a.get("name", "")
        raw = a.get("raw", {}).get("value", 0)
        val = a.get("value")
        thr = a.get("thresh", 0)

        if aid in ATA_ERROR_ATTRS and raw > 0:
            level = CRIT if aid in ATA_CRITICAL_ATTRS else WARN
            flag(level, f"{ATA_ERROR_ATTRS[aid]}: {raw}")

        if aid in ATA_LIFE_ATTRS and val is not None:
            if info["life_left_pct"] is None:
                info["life_left_pct"] = val
            if (thr and val <= thr) or val <= 10:
                flag(CRIT, f"{name} = {val} (ngưỡng {thr})")
            elif val <= 20:
                flag(WARN, f"{name} = {val}: tuổi thọ còn lại thấp")

        if aid == ATA_WRITTEN_ATTR:
            info["written_tb"] = raw * 512 / 1e12


def fmt(value, unit=""):
    return "không rõ" if value is None else f"{value}{unit}"


def print_report(results):
    for r in results:
        print("=" * 64)
        print(f"Ổ: {r['device']}")
        if "error" in r:
            print(f"  Lỗi        : {r['error']}")
            print(f"  Trạng thái : {LEVEL_TEXT[ERR]}")
            continue

        passed = r["smart_passed"]
        smart_text = "PASSED" if passed else "FAILED" if passed is False else "không rõ"
        written = None if r["written_tb"] is None else round(r["written_tb"], 1)

        print(f"  Model        : {r['model']}")
        print(f"  Serial       : {r['serial']}    Firmware: {r['firmware']}")
        print(f"  Dung lượng   : {r['capacity_gb']} GB")
        print(f"  SMART chung  : {smart_text}")
        print(f"  Nhiệt độ     : {fmt(r['temperature_c'], ' °C')}")
        print(f"  Giờ hoạt động: {fmt(r['power_on_hours'], ' giờ')}    "
              f"Số lần bật nguồn: {fmt(r['power_cycles'])}")
        print(f"  Tuổi thọ còn : {fmt(r['life_left_pct'], ' %')}")
        print(f"  Đã ghi (ước) : {fmt(written, ' TB')}")
        if r["issues"]:
            print("  Vấn đề:")
            for i in r["issues"]:
                print(f"    [{i['level']}] {i['msg']}")
        else:
            print("  Không phát hiện vấn đề.")
        print(f"  Kết luận     : {LEVEL_TEXT[r['level']]}")
    print("=" * 64)


def main():
    ap = argparse.ArgumentParser(description="Kiểm tra sức khỏe SSD/NVMe/HDD bằng smartctl.")
    ap.add_argument("-d", "--device", action="append", metavar="/dev/sdX",
                    help="chỉ kiểm tra ổ này (có thể lặp lại); mặc định quét tất cả")
    ap.add_argument("--json", action="store_true", help="xuất kết quả dạng JSON")
    args = ap.parse_args()

    if not shutil.which("smartctl"):
        print("Thiếu smartmontools. Cài bằng: sudo apt install smartmontools", file=sys.stderr)
        return ERR
    if os.geteuid() != 0:
        print("Gợi ý: hãy chạy bằng sudo để đọc được thông tin SMART.", file=sys.stderr)

    if args.device:
        devices = args.device
    else:
        devices, err = scan_devices()
        if err:
            print(f"Không quét được ổ đĩa: {err}", file=sys.stderr)
            return ERR
    if not devices:
        print("Không tìm thấy ổ đĩa nào.", file=sys.stderr)
        return ERR

    results = [check_device(d) for d in devices]
    # Mã thoát: 3 nếu có ổ không đọc được, ngược lại là mức nghiêm trọng cao nhất.
    code = max(r["level"] for r in results)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print_report(results)
        readable = [r["level"] for r in results if r["level"] != ERR]
        summary = LEVEL_TEXT[max(readable)] if readable else LEVEL_TEXT[ERR]
        failed = len(results) - len(readable)
        if failed:
            summary += f" ({failed} ổ không đọc được)"
        print(f"Tổng kết: {summary}")
    return code


if __name__ == "__main__":
    sys.exit(main())
