"""Data update coordinator for EVN VN"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import sqlite3
import os

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .npc_api import EVNAPI
from .const import SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class EVNDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordinator for EVN data updates."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: EVNAPI,
        customer_id: str,
        ngaydauky: int = 1,
    ):
        """Initialize coordinator."""
        super().__init__(hass, _LOGGER, name=f"{DOMAIN}_{customer_id}", update_interval=timedelta(seconds=SCAN_INTERVAL))  # type: ignore
        self.api = api
        self.customer_id = customer_id
        self.ngaydauky = ngaydauky
        self.data: Dict[str, Any] = {}
        # Dynamic DB path
        self.db_path = hass.config.path("evnvn", "evndata.db")

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API and save to database."""
        try:
            # 1. Ensure database directory and tables exist FIRST
            await self.hass.async_add_executor_job(self._ensure_database_setup)

            # 2. Login if needed
            if not self.api.access_token:
                if not await self.api.login():
                    raise UpdateFailed("Failed to login")

            # 3. Fetch daily data in batches of 15 days
            today = datetime.now()
            start_date_daily = datetime(2025, 1, 1)
            batch_days = 15
            
            all_daily_data = []
            current_start = start_date_daily
            
            while current_start < today:
                current_end = min(current_start + timedelta(days=batch_days - 1), today)
                from_date_str = current_start.strftime("%d/%m/%Y")
                to_date_str = current_end.strftime("%d/%m/%Y")
                
                _LOGGER.debug(f"Fetching daily data from {from_date_str} to {to_date_str}")
                daily_data = await self.api.get_chisongay(from_date_str, to_date_str)
                
                if daily_data and daily_data.get("data"):
                    all_daily_data.extend(daily_data["data"])
                
                current_start = current_end + timedelta(days=1)
            
            if all_daily_data:
                await self._save_daily_data(all_daily_data)

            # 4. Fetch monthly history data (History from 2016 to now)
            _LOGGER.info(f"Syncing monthly history for {self.customer_id}")
            
            # Use executor to check missing data
            missing_periods = await self.hass.async_add_executor_job(self._get_missing_monthly_periods)
            
            for month, year in missing_periods:
                _LOGGER.debug(f"Fetching missing monthly data for {month}/{year}")
                m_data = await self.api.get_chisothang(month, year)
                if m_data and m_data.get("data"):
                    await self._save_monthly_data(m_data["data"], month, year)

            # 5. Fetch bill data (hóa đơn)
            bill_data = await self.api.get_hoadon()
            if bill_data and bill_data.get("data"):
                await self._save_bill_data(bill_data["data"])
                await self._save_hoadon_to_monthly_bill(bill_data["data"])

            # 6. Fetch power outage schedule
            outage_from = start_date_daily.strftime("%d/%m/%Y")
            outage_to = today.strftime("%d/%m/%Y")
            outage_data = await self.api.get_ngungcapdien(outage_from, outage_to)
            if outage_data and outage_data.get("data"):
                await self._save_outage_data(outage_data["data"])

            return {
                "last_update": datetime.now().isoformat(),
                "customer_id": self.customer_id,
            }

        except Exception as err:
            _LOGGER.error(f"Error updating EVN data: {err}", exc_info=True)
            raise UpdateFailed(f"Error updating EVN data: {err}") from err

    def _ensure_database_setup(self):
        """Ensure database and tables exist (Synchronous)."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_bill (
                userevn TEXT, thang INTEGER, nam INTEGER, 
                tien_dien REAL, san_luong_kwh REAL,
                PRIMARY KEY (userevn, thang, nam)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_consumption (
                userevn TEXT, ngay TEXT, chi_so REAL, 
                dien_tieu_thu_kwh REAL,
                PRIMARY KEY (userevn, ngay)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS power_outage_schedule (
                userevn TEXT, ngay_bat_dau TEXT, ngay_ket_thuc TEXT,
                thoi_gian_bat_dau TEXT, thoi_gian_ket_thuc TEXT,
                ly_do TEXT, khu_vuc TEXT,
                PRIMARY KEY (userevn, ngay_bat_dau, thoi_gian_bat_dau)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tien_no_evn (
                userevn TEXT, tien_no REAL, ngay_cap_nhat TEXT,
                PRIMARY KEY (userevn)
            )
        """)
        conn.commit()
        conn.close()

    def _get_missing_monthly_periods(self):
        """Identify which month/year periods are missing from DB (Synchronous)."""
        missing = []
        today = datetime.now()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for year in range(2016, today.year + 1):
            max_month = today.month if year == today.year else 12
            for month in range(1, max_month + 1):
                # Always fetch current year and last year to keep them up to date
                if year >= today.year - 1:
                    missing.append((month, year))
                    continue
                
                cursor.execute(
                    "SELECT 1 FROM monthly_bill WHERE userevn = ? AND thang = ? AND nam = ? AND san_luong_kwh IS NOT NULL",
                    (self.customer_id, month, year)
                )
                if not cursor.fetchone():
                    missing.append((month, year))
        
        conn.close()
        return missing

    async def _save_daily_data(self, data: list):
        """Save daily consumption data to database."""
        if not data:
            return

        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_consumption (
                    userevn TEXT,
                    ngay TEXT,
                    chi_so REAL,
                    dien_tieu_thu_kwh REAL,
                    PRIMARY KEY (userevn, ngay)
                )
            """)

            # API returns data from newest to oldest (index 0 is newest)
            # But we need to process from oldest to newest to calculate daily consumption
            # So reverse the list first, then sort by date to be safe
            sorted_data = sorted(data, key=lambda x: self._parse_date_for_sort(record=x))
            
            prev_chi_so = None
            prev_ngay = None
            
            for record in sorted_data:
                # Parse date from record (format may vary)
                ngay = self._parse_date(record)
                # Try multiple field names for chi_so
                chi_so = self._parse_float(
                    record.get("CHISO_MOI") or 
                    record.get("chi_so_moi") or
                    record.get("CHISO") or 
                    record.get("chi_so") or
                    record.get("CHI_SO") or
                    record.get("chiSo")
                )
                
                # Calculate daily consumption
                # Priority: Use DIEN_TIEU_THU from API if available (HCMC, SPC provide this)
                # Otherwise, calculate from meter readings
                dien_tieu_thu = self._parse_float(
                    record.get("dien_tieu_thu") or 
                    record.get("DIEN_TIEU_THU") or
                    record.get("SAN_LUONG") or
                    record.get("san_luong") or
                    record.get("DIEN_TIEU_THU_KWH")
                )
                
                # If not provided by API, calculate from meter readings
                # Only calculate if prev_ngay is the previous day (not many days ago)
                if dien_tieu_thu is None and prev_chi_so is not None and chi_so is not None:
                    # Check if prev_ngay is the previous day
                    can_calculate = False
                    if prev_ngay:
                        try:
                            from datetime import datetime
                            prev_date = datetime.strptime(prev_ngay, "%d-%m-%Y").date()
                            current_date = datetime.strptime(ngay, "%d-%m-%Y").date()
                            # Only calculate if prev_date is exactly 1 day before current_date
                            if (current_date - prev_date).days == 1:
                                can_calculate = True
                            else:
                                _LOGGER.debug(
                                    f"Không tính tiêu thụ từ chỉ số cho {ngay}: "
                                    f"ngày trước ({prev_ngay}) không phải ngày liền trước "
                                    f"(cách {(current_date - prev_date).days} ngày)"
                                )
                        except Exception as e:
                            _LOGGER.debug(f"Lỗi parse ngày để kiểm tra: {e}")
                            # Fallback: allow calculation if dates are close (within 2 days)
                            can_calculate = True
                    else:
                        # No previous day, cannot calculate
                        can_calculate = False
                    
                    if can_calculate and chi_so >= prev_chi_so:
                        dien_tieu_thu = chi_so - prev_chi_so
                    elif chi_so < prev_chi_so:
                        # Chỉ số giảm (có thể reset hoặc lỗi), không tính
                        _LOGGER.debug(
                            f"Chỉ số giảm tại {ngay}: {chi_so} < {prev_chi_so}, "
                            f"bỏ qua tính tiêu thụ từ chỉ số"
                        )
                        dien_tieu_thu = None
                


                cursor.execute("""
                    INSERT OR REPLACE INTO daily_consumption 
                    (userevn, ngay, chi_so, dien_tieu_thu_kwh)
                    VALUES (?, ?, ?, ?)
                """, (self.customer_id, ngay, chi_so, dien_tieu_thu))
                
                prev_chi_so = chi_so
                prev_ngay = ngay

            conn.commit()
            conn.close()
            _LOGGER.debug(f"Saved {len(data)} daily records for {self.customer_id}")

        except Exception as e:
            _LOGGER.error(f"Error saving daily data: {e}", exc_info=True)

    async def _save_monthly_data(self, data: list, month: int, year: int):
        """Save monthly bill data to database."""
        if not data:
            return

        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monthly_bill (
                    userevn TEXT,
                    thang INTEGER,
                    nam INTEGER,
                    tien_dien REAL,
                    san_luong_kwh REAL,
                    PRIMARY KEY (userevn, thang, nam)
                )
            """)

            # Extract monthly totals from data
            # API response structure: data is a list with one record
            # Record contains: CHISO_MOI, CHISO_CU, DIEN_TTHU
            tien_dien = None
            san_luong = None
            
            if isinstance(data, list) and len(data) > 0:
                # Get from first record
                record = data[0]
                
                # Điện tiêu thụ từ DIEN_TTHU
                san_luong = self._parse_float(
                    record.get("DIEN_TTHU") or
                    record.get("dien_tthu") or
                    record.get("SAN_LUONG") or
                    record.get("san_luong")
                )
                
                # Nếu không có, tính từ CHISO_MOI - CHISO_CU
                if san_luong is None:
                    chi_so_moi = self._parse_float(
                        record.get("CHISO_MOI") or 
                        record.get("chi_so_moi")
                    )
                    chi_so_cu = self._parse_float(
                        record.get("CHISO_CU") or 
                        record.get("chi_so_cu")
                    )
                    if chi_so_moi is not None and chi_so_cu is not None:
                        san_luong = chi_so_moi - chi_so_cu
                
                # Tiền điện không có trong chisothang, sẽ lấy từ hoadon
                # Chỉ lưu san_luong ở đây

            if san_luong is not None:
                # INSERT OR IGNORE: chỉ tạo hàng mới nếu chưa tồn tại (giữ nguyên tien_dien)
                cursor.execute("""
                    INSERT OR IGNORE INTO monthly_bill 
                    (userevn, thang, nam, tien_dien, san_luong_kwh)
                    VALUES (?, ?, NULL, ?)
                """, (self.customer_id, month, year, san_luong))
                # UPDATE riêng san_luong_kwh: không bao giờ xóa tien_dien đã có từ hoadon
                cursor.execute("""
                    UPDATE monthly_bill SET san_luong_kwh = ?
                    WHERE userevn = ? AND thang = ? AND nam = ?
                """, (san_luong, self.customer_id, month, year))

            conn.commit()
            conn.close()
            _LOGGER.debug(f"Saved monthly data for {self.customer_id}, {month}/{year}")

        except Exception as e:
            _LOGGER.error(f"Error saving monthly data: {e}", exc_info=True)

    async def _save_bill_data(self, data: list):
        """Save bill data (tiền nợ) to database."""
        if not data or not isinstance(data, list):
            return

        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tien_no_evn (
                    userevn TEXT,
                    tien_no REAL,
                    ngay_cap_nhat TEXT,
                    PRIMARY KEY (userevn)
                )
            """)

            # Tìm hóa đơn chưa thanh toán
            tien_no = 0.0
            found_chuatt = False
            for bill in data:
                if bill.get("TTRANG_TTOAN") == "CHUATT":
                    tien_no = self._parse_float(bill.get("TONG_TIEN", 0)) or 0.0
                    found_chuatt = True
                    break

            # Ghi vào database (cả khi có hoặc không có hóa đơn CHUATT)
            ngay_cap_nhat = datetime.now().strftime("%d-%m-%Y")
            cursor.execute("""
                INSERT OR REPLACE INTO tien_no_evn 
                (userevn, tien_no, ngay_cap_nhat)
                VALUES (?, ?, ?)
            """, (self.customer_id, tien_no, ngay_cap_nhat))

            conn.commit()
            conn.close()
            _LOGGER.debug(f"Saved bill data (tiền nợ = {tien_no}) for {self.customer_id}")

        except Exception as e:
            _LOGGER.error(f"Error saving bill data: {e}", exc_info=True)

    async def _save_hoadon_to_monthly_bill(self, data: list):
        """Save hóa đơn data to monthly_bill table."""
        if not data or not isinstance(data, list):
            return

        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monthly_bill (
                    userevn TEXT,
                    thang INTEGER,
                    nam INTEGER,
                    tien_dien REAL,
                    san_luong_kwh REAL,
                    PRIMARY KEY (userevn, thang, nam)
                )
            """)

            # Save each bill to monthly_bill
            for bill in data:
                thang = bill.get("THANG")
                nam = bill.get("NAM")
                tien_dien = self._parse_float(bill.get("TONG_TIEN"))
                san_luong = self._parse_float(bill.get("DIEN_TTHU"))  # DIEN_TTHU = điện tiêu thụ
                
                if thang is not None and nam is not None:
                    cursor.execute("""
                        INSERT OR REPLACE INTO monthly_bill 
                        (userevn, thang, nam, tien_dien, san_luong_kwh)
                        VALUES (?, ?, ?, ?, ?)
                    """, (self.customer_id, thang, nam, tien_dien, san_luong))
                    _LOGGER.debug(f"Saved hóa đơn: thang={thang}, nam={nam}, tien={tien_dien}, sl={san_luong}")

            conn.commit()
            conn.close()
            _LOGGER.info(f"Saved {len(data)} hóa đơn records to monthly_bill for {self.customer_id}")

        except Exception as e:
            _LOGGER.error(f"Error saving hóa đơn to monthly_bill: {e}", exc_info=True)

    async def _save_outage_data(self, data: list):
        """Save power outage schedule to database."""
        if not data:
            return

        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS power_outage_schedule (
                    userevn TEXT,
                    ngay_bat_dau TEXT,
                    ngay_ket_thuc TEXT,
                    thoi_gian_bat_dau TEXT,
                    thoi_gian_ket_thuc TEXT,
                    ly_do TEXT,
                    khu_vuc TEXT,
                    PRIMARY KEY (userevn, ngay_bat_dau, thoi_gian_bat_dau)
                )
            """)

            for outage in data:
                # Try multiple field names for NPC API
                ngay_bat_dau = (
                    outage.get("NGAY_BAT_DAU") or 
                    outage.get("ngay_bat_dau") or
                    outage.get("NGAY") or
                    outage.get("ngay")
                )
                ngay_ket_thuc = (
                    outage.get("NGAY_KET_THUC") or 
                    outage.get("ngay_ket_thuc") or
                    outage.get("NGAY") or
                    outage.get("ngay")
                )
                thoi_gian_bat_dau = (
                    outage.get("THOI_GIAN_BAT_DAU") or 
                    outage.get("thoi_gian_bat_dau") or
                    outage.get("THOI_GIAN") or
                    outage.get("thoi_gian") or
                    outage.get("THOI_DIEM") or
                    outage.get("thoi_diem") or
                    ""
                )
                thoi_gian_ket_thuc = (
                    outage.get("THOI_GIAN_KET_THUC") or 
                    outage.get("thoi_gian_ket_thuc") or
                    ""
                )
                ly_do = (
                    outage.get("LY_DO") or 
                    outage.get("ly_do") or
                    outage.get("NOI_DUNG") or
                    outage.get("noi_dung") or
                    ""
                )
                khu_vuc = (
                    outage.get("KHU_VUC") or 
                    outage.get("khu_vuc") or
                    outage.get("DIA_CHI") or
                    outage.get("dia_chi") or
                    ""
                )
                
                # Parse dates to dd-mm-yyyy format if needed
                if ngay_bat_dau:
                    ngay_bat_dau = self._parse_date({"NGAY": ngay_bat_dau})
                if ngay_ket_thuc:
                    ngay_ket_thuc = self._parse_date({"NGAY": ngay_ket_thuc})

                cursor.execute("""
                    INSERT OR REPLACE INTO power_outage_schedule 
                    (userevn, ngay_bat_dau, ngay_ket_thuc, thoi_gian_bat_dau, 
                     thoi_gian_ket_thuc, ly_do, khu_vuc)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (self.customer_id, ngay_bat_dau, ngay_ket_thuc, 
                      thoi_gian_bat_dau, thoi_gian_ket_thuc, ly_do, khu_vuc))

            conn.commit()
            conn.close()
            _LOGGER.debug(f"Saved {len(data)} outage records for {self.customer_id}")

        except Exception as e:
            _LOGGER.error(f"Error saving outage data: {e}", exc_info=True)

    def _parse_date(self, record: Dict) -> str:
        """Parse date from record to dd-mm-yyyy format."""
        # Try different date fields (priority order)
        # NPC API returns "NGAY" field with format "dd/mm/yyyy"
        date_fields = [
            "NGAY", "ngay",  # Most common for NPC API
            "NGAY_DO", "ngay_do", "NGAY_DO_CS", "ngay_do_cs",
            "THOI_DIEM", "thoi_diem",  # NPC also has THOI_DIEM field
            "THOI_GIAN", "thoi_gian",
            "NGAY_BAT_DAU", "ngay_bat_dau",
            "NGAY_KET_THUC", "ngay_ket_thuc"
        ]
        
        for field in date_fields:
            if field in record:
                date_str = str(record[field]).strip()
                if not date_str or date_str.lower() in ['null', 'none', '']:
                    continue
                
                # Handle THOI_DIEM format: "24/01/2026 00:33" -> extract date part
                if field in ["THOI_DIEM", "thoi_diem"] and ' ' in date_str:
                    date_str = date_str.split(' ')[0]
                    
                # Handle HCMC/SPC date ranges: "04/11/2025 đến 06/11/2025" or "04/11 đến 06/11"
                if "đến" in date_str:
                    try:
                        # Take the end date part
                        parts = date_str.split("đến")
                        end_date_part = parts[-1].strip()
                        
                        # Recursive call with cleaned string
                        # But prevent infinite loop by creating a temporary record
                        temp_record = {field: end_date_part}
                        return self._parse_date(temp_record)
                    except Exception as e:
                        _LOGGER.debug(f"Error parsing date range {date_str}: {e}")

                # Handle date without year: "06/11" (often seen in ranges like "04/11 đến 06/11")
                if len(date_str) == 5 and date_str[2] == '/':
                    try:
                        # Append current year. 
                        # This isn't perfect but handles the "04/11 đến 06/11" case where year is implicit
                        current_year = datetime.now().year
                        date_with_year = f"{date_str}/{current_year}"
                        dt = datetime.strptime(date_with_year, "%d/%m/%Y")
                        return dt.strftime("%d-%m-%Y")
                    except:
                        pass

                # Try to parse and format
                try:
                    # Try dd/mm/yyyy (most common for NPC API)
                    if len(date_str) == 10 and date_str[2] == '/':
                        dt = datetime.strptime(date_str, "%d/%m/%Y")
                        return dt.strftime("%d-%m-%Y")
                    # Try yyyy-mm-dd
                    elif len(date_str) == 10 and date_str[4] == '-':
                        dt = datetime.strptime(date_str, "%Y-%m-%d")
                        return dt.strftime("%d-%m-%Y")
                    # Already dd-mm-yyyy
                    elif len(date_str) == 10 and date_str[2] == '-':
                        return date_str
                    # Try yyyymmdd
                    elif len(date_str) == 8 and date_str.isdigit():
                        dt = datetime.strptime(date_str, "%Y%m%d")
                        return dt.strftime("%d-%m-%Y")
                    # Try ddmmYYYY (without separators)
                    elif len(date_str) == 8 and (date_str[0] + date_str[1]).isdigit() and (date_str[2] + date_str[3]).isdigit():
                        try:
                            dt = datetime.strptime(date_str, "%d%m%Y")
                            return dt.strftime("%d-%m-%Y")
                        except:
                            pass
                except Exception as e:
                    _LOGGER.debug(f"Error parsing date {date_str} from field {field}: {e}")
                    continue
        
        # Default to today
        _LOGGER.debug(f"Could not parse date from record: {record}, using today")
        return datetime.now().strftime("%d-%m-%Y")

    def _parse_date_for_sort(self, record: Dict) -> datetime:
        """Parse date for sorting purposes."""
        date_str = self._parse_date(record)
        try:
            return datetime.strptime(date_str, "%d-%m-%Y")
        except:
            return datetime.now()

    def _parse_float(self, value: Any) -> Optional[float]:
        """Parse float value from various formats."""
        if value is None:
            return None
        
        if isinstance(value, (int, float)):
            return float(value)
        
        if isinstance(value, str):
            # Remove spaces and replace comma with dot
            value = value.strip().replace(',', '.').replace(' ', '')
            try:
                return float(value)
            except (ValueError, TypeError):
                return None
        
        return None
