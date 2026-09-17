import asyncio
import os
import sys
from datetime import datetime

# Thêm đường dẫn để import npc_api từ thư mục hiện tại
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from npc_api import EVNAPI
except ImportError:
    print(f"❌ Không tìm thấy file npc_api.py. Đường dẫn hiện tại: {current_dir}")
    print(f"Các file trong thư mục: {os.listdir(current_dir)}")
    sys.exit(1)

# =================================================================
# THÔNG TIN ĐĂNG NHẬP (Anh điền thông tin của anh vào đây)
# =================================================================
USERNAME = "0979542510"
PASSWORD = "Quenmatroi@2412"
CUSTOMER_ID = "PA01XT0004676"  # Thường giống Username, VD: PA12...
REGION = "NPC"  # HN, NPC, CPC, SPC, HCMC
# =================================================================

async def test_hoadon_params():
    if USERNAME == "MÃ_KHÁCH_HÀNG":
        print("⚠️ Vui lòng mở file này lên và điền USERNAME/PASSWORD của anh vào trước khi chạy nhé!")
        return

    # Khởi tạo API với đầy đủ tham số: hass, region, username, password, customer_id
    api = EVNAPI(None, REGION, USERNAME, PASSWORD, CUSTOMER_ID)
    
    print(f"\n--- Đang đăng nhập cho tài khoản {USERNAME} (Region: {REGION}) ---")
    try:
        if not await api.login():
            print("❌ Đăng nhập thất bại. Vui lòng kiểm tra lại Username/Password.")
            return
    except Exception as e:
        print(f"❌ Lỗi trong quá trình đăng nhập: {e}")
        return

    print("✅ Đăng nhập thành công!")
    print("-" * 60)

    session = await api._get_session()
    
    # Test 1: Gọi mặc định (không có tham số)
    print("\n[1] Test mặc định (không có tham số):")
    url = f"{api.base_url}/api/evn/tracuu/hoadon"
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "user-agent": "okhttp/4.9.2",
        "authorization": f"Bearer {api.access_token}",
    }
    
    try:
        async with session.post(url, headers=headers) as resp:
            print(f"   Status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"   Response type: {type(data)}")
                if isinstance(data, dict):
                    print(f"   Keys: {data.keys()}")
                    if "data" in data:
                        print(f"   Data type: {type(data['data'])}")
                        if isinstance(data["data"], list):
                            print(f"   Số lượng hóa đơn: {len(data['data'])}")
                            if len(data["data"]) > 0:
                                print(f"   Hóa đơn đầu tiên: {data['data'][0]}")
                                if len(data["data"]) > 1:
                                    print(f"   Hóa đơn cuối cùng: {data['data'][-1]}")
                elif isinstance(data, list):
                    print(f"   Số lượng hóa đơn: {len(data)}")
                    if len(data) > 0:
                        print(f"   Hóa đơn đầu tiên: {data[0]}")
                        if len(data) > 1:
                            print(f"   Hóa đơn cuối cùng: {data[-1]}")
            else:
                error_text = await resp.text()
                print(f"   Error: {error_text[:500]}")
    except Exception as e:
        print(f"   Lỗi: {e}")

    # Test 2: Thử với tham số MA_DVIQLY và MA_DDO
    print("\n[2] Test với tham số MA_DVIQLY và MA_DDO:")
    ma_dviqly, ma_ddo = api._get_ma_dviqly_and_ma_ddo()
    print(f"   MA_DVIQLY: {ma_dviqly}, MA_DDO: {ma_ddo}")
    
    payload = {
        "MA_DVIQLY": ma_dviqly,
        "MA_DDO": ma_ddo,
    }
    
    try:
        async with session.post(url, json=payload, headers=headers) as resp:
            print(f"   Status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"   Response type: {type(data)}")
                if isinstance(data, dict):
                    print(f"   Keys: {data.keys()}")
                    if "data" in data:
                        print(f"   Data type: {type(data['data'])}")
                        if isinstance(data["data"], list):
                            print(f"   Số lượng hóa đơn: {len(data['data'])}")
                elif isinstance(data, list):
                    print(f"   Số lượng hóa đơn: {len(data)}")
            else:
                error_text = await resp.text()
                print(f"   Error: {error_text[:500]}")
    except Exception as e:
        print(f"   Lỗi: {e}")

    # Test 3: Thử với tham số thời gian
    print("\n[3] Test với tham số thời gian (from_date, to_date):")
    from_date = "01/01/2023"
    to_date = datetime.now().strftime("%d/%m/%Y")
    
    payload_time = {
        "MA_DVIQLY": ma_dviqly,
        "MA_DDO": ma_ddo,
        "TU_NGAY": from_date,
        "DEN_NGAY": to_date,
    }
    
    try:
        async with session.post(url, json=payload_time, headers=headers) as resp:
            print(f"   Status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"   Response type: {type(data)}")
                if isinstance(data, dict):
                    print(f"   Keys: {data.keys()}")
                    if "data" in data:
                        print(f"   Data type: {type(data['data'])}")
                        if isinstance(data["data"], list):
                            print(f"   Số lượng hóa đơn: {len(data['data'])}")
                elif isinstance(data, list):
                    print(f"   Số lượng hóa đơn: {len(data)}")
            else:
                error_text = await resp.text()
                print(f"   Error: {error_text[:500]}")
    except Exception as e:
        print(f"   Lỗi: {e}")

    # Test 4: Thử với GET request thay vì POST
    print("\n[4] Test với GET request:")
    try:
        async with session.get(url, headers=headers) as resp:
            print(f"   Status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                print(f"   Response type: {type(data)}")
                if isinstance(data, dict):
                    print(f"   Keys: {data.keys()}")
                    if "data" in data:
                        print(f"   Data type: {type(data['data'])}")
                        if isinstance(data["data"], list):
                            print(f"   Số lượng hóa đơn: {len(data['data'])}")
                elif isinstance(data, list):
                    print(f"   Số lượng hóa đơn: {len(data)}")
            else:
                error_text = await resp.text()
                print(f"   Error: {error_text[:500]}")
    except Exception as e:
        print(f"   Lỗi: {e}")

    # Test 5: Thử endpoint khác có thể có lịch sử
    print("\n[5] Test endpoint lịch sử (nếu có):")
    history_urls = [
        f"{api.base_url}/api/evn/tracuu/hoadon/history",
        f"{api.base_url}/api/evn/tracuu/hoadon/all",
        f"{api.base_url}/api/evn/hoadon/all",
    ]
    
    for test_url in history_urls:
        try:
            async with session.post(test_url, headers=headers) as resp:
                print(f"   Testing {test_url}: Status {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"   ✅ Success! Response type: {type(data)}")
                    if isinstance(data, dict) and "data" in data:
                        if isinstance(data["data"], list):
                            print(f"   Số lượng hóa đơn: {len(data['data'])}")
                    elif isinstance(data, list):
                        print(f"   Số lượng hóa đơn: {len(data)}")
                else:
                    print(f"   ❌ Failed")
        except Exception as e:
            print(f"   ❌ Error: {e}")

    print("\n" + "="*60)
    print("KẾT THÚC TEST")
    print("="*60)
    
    # Đóng session
    await api.close()

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_hoadon_params())