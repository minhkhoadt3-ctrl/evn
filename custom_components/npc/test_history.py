import asyncio
import os
import sys
from datetime import datetime

# Thêm đường dẫn để import npc_api từ thư mục hiện tại
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from npc_api import EVNAPI
except ImportError:
    print("❌ Không tìm thấy file npc_api.py. Vui lòng chạy file này trong cùng thư mục với npc_api.py")
    sys.exit(1)

# =================================================================
# THÔNG TIN ĐĂNG NHẬP (Anh điền thông tin của anh vào đây)
# =================================================================
USERNAME = "0979542510"
PASSWORD = "Quenmatroi@2412"
CUSTOMER_ID = "PA01XT0004676" # Thường giống Username, VD: PA12...
# =================================================================

async def test_history():
    if USERNAME == "MÃ_KHÁCH_HÀNG":
        print("⚠️ Vui lòng mở file này lên và điền USERNAME/PASSWORD của anh vào trước khi chạy nhé!")
        return

    # Khởi tạo API với đầy đủ tham số: hass, region, username, password, customer_id
    api = EVNAPI(None, "NPC", USERNAME, PASSWORD, CUSTOMER_ID)
    
    print(f"\n--- Đang đăng nhập cho tài khoản {USERNAME} ---")
    try:
        if not await api.login():
            print("❌ Đăng nhập thất bại. Vui lòng kiểm tra lại Username/Password.")
            return
    except Exception as e:
        print(f"❌ Lỗi trong quá trình đăng nhập: {e}")
        return

    print("✅ Đăng nhập thành công!")
    print("-" * 60)

    # 1. TEST TRA CỨU HÓA ĐƠN / CHỈ SỐ THÁNG
    print("\n[1] Kiểm tra dữ liệu tổng tháng (History Monthly):")
    
    # Quét ngược từ 2025 về tận 2000
    current_year = datetime.now().year
    consecutive_empty_years = 0
    
    for year in range(current_year, 1999, -1):
        print(f"\n--- Kiểm tra năm {year} ---")
        found_any = False
        
        # Chỉ kiểm tra tháng 1 và tháng 12 để đại diện cho cả năm
        for month in [1, 12]:
            if year == current_year and month > datetime.now().month:
                continue
                
            try:
                res = await api.get_chisothang(month, year)
                if res and res.get("success") and res.get("data") and len(res["data"]) > 0:
                    item = res["data"][0]
                    sl = item.get('DIEN_TTHU') or item.get('SAN_LUONG') or "N/A"
                    print(f"   ✅ Tháng {month:02d}/{year}: {sl} kWh")
                    found_any = True
                else:
                    print(f"   ❌ Tháng {month:02d}/{year}: Không có dữ liệu")
            except Exception as e:
                print(f"   ❌ Tháng {month:02d}/{year}: Lỗi gọi API")
        
        if found_any:
            consecutive_empty_years = 0
        else:
            consecutive_empty_years += 1
            
        # Nếu 2 năm liên tiếp không có dữ liệu thì dừng
        if consecutive_empty_years >= 2:
            print(f"\n=> Đã dừng lại ở năm {year} vì không tìm thấy dữ liệu cũ hơn.")
            break

    print("\n" + "="*60)
    print("KẾT THÚC KIỂM TRA")
    print("Dữ liệu tổng tháng lấy được đến năm nào thì biểu đồ so sánh sẽ vẽ được đến đó.")
    print("="*60)
    
    # Đóng session để tránh lỗi cảnh báo
    await api.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_history())
