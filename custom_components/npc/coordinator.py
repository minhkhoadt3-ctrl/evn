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

            # 3. Fetch power outage schedule FIRST.
            # This must not be blocked by the much heavier historical sync below.
            today = datetime.now()
            outage_from = today.strftime("%d/%m/%Y")
            outage_to = (today + timedelta(days=30)).strftime("%d/%m/%Y")
            try:
                _LOGGER.debug(
                    f"Fetching power outage schedule for {self.customer_id}: "
                    f"{outage_from} -> {outage_to}"
                )
                outage_data = await self.api.get_ngungcapdien(outage_from, outage_to)
                if outage_data is not None and isinstance(outage_data.get("data"), list):
                    await self._save_outage_data(outage_data["data"])
                    _LOGGER.debug(
                        f"Power outage sync completed for {self.customer_id}: "
                        f"{len(outage_data['data'])} records"
                    )
                else:
                    _LOGGER.debug(
                        f"Power outage API returned no usable data for {self.customer_id}: "
                        f"{outage_data!r}"
                    )
            except Exception as outage_err:
                # Do not let outage API problems prevent the rest of EVN data from updating.
                _LOGGER.error(
                    f"Power outage sync failed for {self.customer_id}: {outage_err}",
                    exc_info=True,
                )

            # 4. Fetch monthly history data (History from 2016 to now) - ƯU TIÊN ĐẦU TIÊN
            # Dữ liệu chisothang từ API cũng chính xác, ưu tiên trước daily data
            # Chỉ lấy các tháng chưa có trong database
            _LOGGER.debug(f"Syncing monthly history for {self.customer_id}")

            # Use executor to check missing data
            missing_periods = await self.hass.async_add_executor_job(self._get_missing_monthly_periods)

            if len(missing_periods) > 0:
                _LOGGER.info(f"Found {len(missing_periods)} missing monthly periods for {self.customer_id}")

                for month, year in missing_periods:
                    _LOGGER.debug(f"Fetching missing monthly data for {month}/{year}")
                    m_data = await self.api.get_chisothang(month, year)
                    if m_data and m_data.get("data"):
                        await self._save_monthly_data(m_data["data"], month, year)
                        _LOGGER.debug(f"Successfully saved monthly data for {month}/{year}")
                    else:
                        _LOGGER.warning(f"Failed to fetch monthly data for {month}/{year}")
            else:
                _LOGGER.debug(f"No missing monthly periods found for {self.customer_id}, skipping API calls")

            # 5. Fetch bill data (hóa đơn) - ƯU TIÊN THỨ HAI
            # Dữ liệu hóa đơn từ API là chính xác nhất, ưu tiên trước daily data
            # Chạy sau monthly history để không làm ảnh hưởng việc sync lịch sử
            bill_data = await self.api.get_hoadon()
            if bill_data and bill_data.get("data"):
                _LOGGER.debug(f"Bill data received: {len(bill_data.get('data', []))} records")
                await self._save_bill_data(bill_data["data"])
                await self._save_hoadon_to_monthly_bill(bill_data["data"])
                _LOGGER.debug(f"Bill data sync completed for {self.customer_id}")

            # Use executor to check missing data
            missing_periods = await self.hass.async_add_executor_job(self._get_missing_monthly_periods)

            if len(missing_periods) > 0:
                _LOGGER.info(f"Found {len(missing_periods)} missing monthly periods for {self.customer_id}")

                for month, year in missing_periods:
                    _LOGGER.debug(f"Fetching missing monthly data for {month}/{year}")
                    m_data = await self.api.get_chisothang(month, year)
                    if m_data and m_data.get("data"):
                        await self._save_monthly_data(m_data["data"], month, year)
                        _LOGGER.debug(f"Successfully saved monthly data for {month}/{year}")
                    else:
                        _LOGGER.warning(f"Failed to fetch monthly data for {month}/{year}")
            else:
                _LOGGER.debug(f"No missing monthly periods found for {self.customer_id}, skipping API calls")

            # 6. Fetch daily data by month (từng tháng một) để tránh lỗi date calculation
            # Dữ liệu ngày chỉ dùng để hiển thị chi tiết, không ảnh hưởng đến tổng tháng
            # Chỉ lấy những ngày chưa có trong database

            # Tạm thời disable cleanup retention để tránh mất dữ liệu
            # await self.hass.async_add_executor_job(self._cleanup_history_retention)

            # Check missing daily periods
            missing_daily_periods = await self.hass.async_add_executor_job(self._get_missing_daily_periods)

            if len(missing_daily_periods) > 0:
                _LOGGER.info(f"Found {len(missing_daily_periods)} missing daily periods for {self.customer_id}")

                # Group missing dates by month (từng tháng một)
                from collections import defaultdict
                missing_by_month = defaultdict(list)
                
                for date_str in missing_daily_periods:
                    try:
                        date_obj = datetime.strptime(date_str, "%d-%m-%Y")
                        month_key = (date_obj.year, date_obj.month)
                        missing_by_month[month_key].append(date_str)
                    except:
                        continue
                
                all_daily_data = []
                batch_count = 0
                failed_batches = 0
                
                # Sort by month to process chronologically
                for (year, month), dates in sorted(missing_by_month.items()):
                    if not dates:
                        continue
                    
                    batch_count += 1
                    
                    # Get first and last day of the month
                    from calendar import monthrange
                    _, last_day = monthrange(year, month)
                    from_date = f"01/{month:02d}/{year}"
                    to_date = f"{last_day:02d}/{month:02d}/{year}"
                    
                    _LOGGER.debug(f"Fetching daily data batch {batch_count}: {from_date} -> {to_date} ({len(dates)} dates in {month:02d}/{year})")
                    daily_data = await self.api.get_chisongay(from_date, to_date)

                    if daily_data and daily_data.get("data"):
                        batch_records = len(daily_data["data"])
                        all_daily_data.extend(daily_data["data"])
                    else:
                        failed_batches += 1

                if all_daily_data:
                    _LOGGER.info(f"Daily data sync completed: {len(all_daily_data)} records collected, {failed_batches} batches failed")
                    await self._save_daily_data(all_daily_data)
                else:
                    _LOGGER.warning(f"No daily data collected for {self.customer_id}, skipping daily data save (failed batches: {failed_batches})")
            else:
                _LOGGER.debug(f"No missing daily periods found for {self.customer_id}, skipping API calls")

            # 7. Power outage was synchronized at the start of this update cycle.

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
        
        # Xóa các record rỗng trong daily_consumption (không có chi_so và dien_tieu_thu_kwh)
        cursor.execute("""
            DELETE FROM daily_consumption 
            WHERE chi_so IS NULL AND dien_tieu_thu_kwh IS NULL
        """)
        deleted_count = cursor.rowcount
        if deleted_count > 0:
            _LOGGER.debug(f"Cleaned up {deleted_count} empty records from daily_consumption")
        
        conn.commit()
        conn.close()

    def _cleanup_history_retention(self):
        """Keep only records from 2025 onward."""
        today = datetime.now()
        cutoff = datetime(2025, 1, 1)
        cutoff_month = cutoff.year * 12 + cutoff.month
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # daily_consumption stores dates as DD-MM-YYYY.
        cutoff_daily = cutoff.strftime("%d-%m-%Y")
        cursor.execute(
            "DELETE FROM daily_consumption WHERE userevn = ? AND substr(ngay, 7, 4) || '-' || substr(ngay, 4, 2) || '-' || substr(ngay, 1, 2) < ?",
            (self.customer_id, cutoff.strftime("%Y-%m-%d"))
        )

        # monthly_bill stores month/year separately.
        cursor.execute(
            "DELETE FROM monthly_bill WHERE userevn = ? AND (nam * 12 + thang) < ?",
            (self.customer_id, cutoff_month)
        )

        conn.commit()
        conn.close()
        _LOGGER.debug(
            f"History retention cleanup for {self.customer_id}: "
            f"kept records from {cutoff.strftime('%d/%m/%Y')} onward"
        )

    def _get_missing_monthly_periods(self):
        """Identify missing monthly periods only from 2025 to now.
        Tìm tháng gần nhất có dữ liệu và lấy từ tháng tiếp theo để tránh lấy trùng.
        Nếu có tháng 1,2,5,6 thì tháng gần nhất là tháng 6, sẽ lấy từ tháng 7.
        Chỉ lấy đến tháng trước tháng hiện tại (tháng hiện tại chưa hết kỳ).
        """
        missing = []
        today = datetime.now()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Lấy tháng gần nhất có dữ liệu (tháng cuối cùng trong database có san_luong_kwh)
        cursor.execute(
            "SELECT MAX(nam * 12 + thang) as month_num, MAX(nam) as max_year, MAX(thang) as max_month FROM monthly_bill WHERE userevn = ? AND san_luong_kwh IS NOT NULL AND san_luong_kwh > 0",
            (self.customer_id,)
        )
        result = cursor.fetchone()
        
        if result and result[0]:
            _LOGGER.debug(f"Latest month in database for {self.customer_id}: {result}")
        else:
            _LOGGER.debug(f"No existing monthly data found for {self.customer_id}, starting from 01/2025")

        if not result or not result[0]:
            # Không có dữ liệu nào, bắt đầu từ tháng 1/2025
            first_month = datetime(2025, 1, 1)
            _LOGGER.debug(f"No existing monthly data found, starting from {first_month.strftime('%m/%Y')}")
        else:
            # Có dữ liệu, bắt đầu từ tháng tiếp theo của tháng gần nhất
            month_num = result[0]  # nam * 12 + thang
            next_month_num = month_num + 1
            next_year = (next_month_num - 1) // 12
            next_month = (next_month_num - 1) % 12 + 1
            first_month = datetime(next_year, next_month, 1)
            _LOGGER.debug(f"Starting monthly data sync from {first_month.strftime('%m/%Y')} (after latest data)")

        # Tính tháng trước tháng hiện tại (tháng hiện tại chưa hết kỳ nên không lấy)
        if today.month == 1:
            last_month = datetime(today.year - 1, 12, 1)
        else:
            last_month = datetime(today.year, today.month - 1, 1)

        # Đảm bảo không lùi về năm trước 2025
        if first_month.year < 2025:
            first_month = datetime(2025, 1, 1)

        month_cursor = first_month
        while month_cursor <= last_month:
            month = month_cursor.month
            year = month_cursor.year

            # Double-check tháng này thực sự chưa có dữ liệu (để tránh race condition)
            cursor.execute(
                "SELECT san_luong_kwh, tien_dien FROM monthly_bill WHERE userevn = ? AND thang = ? AND nam = ?",
                (self.customer_id, month, year)
            )
            row = cursor.fetchone()
            
            should_add = False
            if not row:
                should_add = True
            else:
                san_luong = row[0]
                tien_dien = row[1]
                if san_luong is None and tien_dien is None:
                    should_add = True
                elif san_luong is None or san_luong == 0:
                    should_add = True
            
            if should_add:
                missing.append((month, year))

            if month_cursor.month == 12:
                month_cursor = datetime(month_cursor.year + 1, 1, 1)
            else:
                month_cursor = datetime(month_cursor.year, month_cursor.month + 1, 1)

        conn.close()
        return missing

    def _get_missing_daily_periods(self):
        """Identify missing daily periods only from 2025 to now.
        Tìm ngày gần nhất có dữ liệu và lấy từ ngày tiếp theo để tránh lấy trùng.
        Nếu có ngày 1,2,5,6 thì ngày gần nhất là ngày 6, sẽ lấy từ ngày 7.
        """
        missing = []
        today = datetime.now()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Lấy ngày gần nhất có dữ liệu thực sự (có chi_so hoặc dien_tieu_thu_kwh)
        cursor.execute(
            "SELECT MAX(ngay) FROM daily_consumption WHERE userevn = ? AND (chi_so IS NOT NULL OR dien_tieu_thu_kwh IS NOT NULL)",
            (self.customer_id,)
        )
        result = cursor.fetchone()
        latest_date_str = result[0] if result and result[0] else None
        
        _LOGGER.debug(f"Database path = {self.db_path}")
        _LOGGER.debug(f"Latest date in database for {self.customer_id}: {latest_date_str}")
        
        # Debug: Count total records and records with actual data
        cursor.execute(
            "SELECT COUNT(*) FROM daily_consumption WHERE userevn = ?",
            (self.customer_id,)
        )
        total_count = cursor.fetchone()[0]
        
        cursor.execute(
            "SELECT COUNT(*) FROM daily_consumption WHERE userevn = ? AND (chi_so IS NOT NULL OR dien_tieu_thu_kwh IS NOT NULL)",
            (self.customer_id,)
        )
        data_count = cursor.fetchone()[0]
        
        if total_count != data_count:
            _LOGGER.debug(f"Total records for {self.customer_id}: {total_count}, records with data: {data_count}")

        if not latest_date_str:
            # Không có dữ liệu nào, bắt đầu từ 01/01/2025
            first_date = datetime(2025, 1, 1)
            _LOGGER.debug(f"No existing daily data found, starting from {first_date.strftime('%d/%m/%Y')}")
        else:
            # Có dữ liệu, bắt đầu từ ngày tiếp theo của ngày gần nhất
            latest_date = datetime.strptime(latest_date_str, "%d-%m-%Y")
            first_date = latest_date + timedelta(days=1)
            _LOGGER.debug(f"Starting daily data sync from {first_date.strftime('%d/%m/%Y')} (after latest data {latest_date_str})")

        current_date = today

        date_cursor = first_date
        while date_cursor <= current_date:
            ngay = date_cursor.strftime("%d-%m-%Y")

            cursor.execute(
                "SELECT 1 FROM daily_consumption WHERE userevn = ? AND ngay = ?",
                (self.customer_id, ngay)
            )
            if not cursor.fetchone():
                missing.append(ngay)

            date_cursor += timedelta(days=1)

        conn.close()
        return missing

    def _get_missing_bill_months(self):
        """Identify months that are missing bill data (tien_dien)."""
        missing = []
        today = datetime.now()

        # Chỉ lấy từ tháng 1/2025 đến hiện tại
        first_month = datetime(2025, 1, 1)
        current_month = datetime(today.year, today.month, 1)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        month_cursor = first_month
        while month_cursor <= current_month:
            month = month_cursor.month
            year = month_cursor.year

            # Đảm bảo không lùi về năm trước 2025
            if year < 2025:
                if month_cursor.month == 12:
                    month_cursor = datetime(month_cursor.year + 1, 1, 1)
                else:
                    month_cursor = datetime(month_cursor.year, month_cursor.month + 1, 1)
                continue

            cursor.execute(
                "SELECT 1 FROM monthly_bill WHERE userevn = ? AND thang = ? AND nam = ? AND tien_dien IS NOT NULL",
                (self.customer_id, month, year)
            )
            if not cursor.fetchone():
                missing.append((month, year))

            if month_cursor.month == 12:
                month_cursor = datetime(month_cursor.year + 1, 1, 1)
            else:
                month_cursor = datetime(month_cursor.year, month_cursor.month + 1, 1)

        conn.close()
        return missing

    def force_resync_all_data(self):
        """Force resync all data from 2025 to now (tạm thời để khôi phục dữ liệu)."""
        # Xóa toàn bộ dữ liệu để sync lại từ đầu
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM daily_consumption WHERE userevn = ?", (self.customer_id,))
        cursor.execute("DELETE FROM monthly_bill WHERE userevn = ?", (self.customer_id,))
        cursor.execute("DELETE FROM power_outage_schedule WHERE userevn = ?", (self.customer_id,))
        cursor.execute("DELETE FROM tien_no_evn WHERE userevn = ?", (self.customer_id,))

        conn.commit()
        conn.close()
        _LOGGER.warning(f"Force resync: Deleted all data for {self.customer_id}, will sync from scratch")
        
        # Reset coordinator state để đảm bảo sync lại từ đầu
        self.data = {}

    async def _save_daily_data(self, data: list):
        """Save daily consumption data to database."""
        if not data:
            _LOGGER.warning(f"No daily data to save for {self.customer_id}")
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
            
            _LOGGER.debug(f"Processing {len(sorted_data)} daily records for {self.customer_id}")
            
            prev_chi_so = None
            prev_ngay = None
            saved_count = 0
            skipped_count = 0
            
            for record in sorted_data:
                # Parse date from record (format may vary)
                ngay = self._parse_date(record)
                
                if not ngay:
                    _LOGGER.debug(f"Skipping record without valid date: {record}")
                    skipped_count += 1
                    continue
                    
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
                

                # Chỉ lưu khi có ít nhất một trong hai giá trị không phải NULL
                if chi_so is not None or dien_tieu_thu is not None:
                    cursor.execute("""
                        INSERT OR REPLACE INTO daily_consumption 
                        (userevn, ngay, chi_so, dien_tieu_thu_kwh)
                        VALUES (?, ?, ?, ?)
                    """, (self.customer_id, ngay, chi_so, dien_tieu_thu))
                    
                    saved_count += 1
                    prev_chi_so = chi_so
                    prev_ngay = ngay
                else:
                    _LOGGER.debug(f"Skipping record {ngay}: no data (chi_so={chi_so}, dien_tieu_thu={dien_tieu_thu})")
                    skipped_count += 1

            conn.commit()
            conn.close()
            _LOGGER.debug(f"Saved {saved_count} daily records for {self.customer_id}, skipped {skipped_count}")
            
            # DEBUG: Verify data was actually saved
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM daily_consumption WHERE userevn = ?",
                (self.customer_id,)
            )
            count = cursor.fetchone()[0]
            _LOGGER.debug(f"After save, total records in DB for {self.customer_id}: {count}")
            conn.close()

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
                
                # Điện tiêu thụ từ DIEN_TTHU hoặc ChiSoThang
                san_luong = self._parse_float(
                    record.get("DIEN_TTHU") or
                    record.get("dien_tthu") or
                    record.get("SAN_LUONG") or
                    record.get("san_luong") or
                    record.get("ChiSoThang") or
                    record.get("chiSoThang")
                )
                
                # Nếu không có, tính từ CHISO_MOI - CHISO_CU
                if san_luong is None:
                    chi_so_moi = self._parse_float(
                        record.get("CHISO_MOI") or 
                        record.get("chi_so_moi") or
                        record.get("ChiSoCuoi") or
                        record.get("chiSoCuoi")
                    )
                    chi_so_cu = self._parse_float(
                        record.get("CHISO_CU") or 
                        record.get("chi_so_cu") or
                        record.get("ChiSoDau") or
                        record.get("chiSoDau")
                    )
                    if chi_so_moi is not None and chi_so_cu is not None:
                        san_luong = chi_so_moi - chi_so_cu
                
                # Tiền điện không có trong chisothang, sẽ lấy từ hoadon
                # Chỉ lưu san_luong ở đây

            if san_luong is not None and san_luong > 0:
                # INSERT OR REPLACE: tạo hoặc cập nhật hàng (giữ nguyên tien_dien nếu đã có)
                # Sử dụng UPSERT pattern: INSERT nếu chưa có, UPDATE nếu đã có
                cursor.execute("""
                    INSERT INTO monthly_bill (userevn, thang, nam, tien_dien, san_luong_kwh)
                    VALUES (?, ?, ?, NULL, ?)
                    ON CONFLICT(userevn, thang, nam) 
                    DO UPDATE SET san_luong_kwh = excluded.san_luong_kwh,
                                  tien_dien = COALESCE(monthly_bill.tien_dien, excluded.tien_dien)
                """, (self.customer_id, month, year, san_luong))
                
                _LOGGER.debug(f"Saved monthly data for {self.customer_id}, {month}/{year}: san_luong={san_luong}")
            else:
                _LOGGER.debug(f"Invalid san_luong for {self.customer_id}, {month}/{year}: {san_luong}")

            conn.commit()
            conn.close()

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

            # Xóa tiền cũ trong monthly_bill trước khi đồng bộ lại hóa đơn thực tế.
            # Các bản cũ có thể đã được tự ước tính từ kWh (ví dụ ~2017 VND) và
            # INSERT OR IGNORE sẽ giữ lại chúng nếu không làm sạch trước.
            # san_luong_kwh vẫn được giữ nguyên; chỉ reset cột tiền.
            cursor.execute("UPDATE monthly_bill SET tien_dien = NULL WHERE userevn = ?", (self.customer_id,))

            # Save từng hóa đơn thực tế vào monthly_bill
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
            _LOGGER.debug(f"Saved {len(data)} hóa đơn records to monthly_bill for {self.customer_id}")

        except Exception as e:
            _LOGGER.error(f"Error saving hóa đơn to monthly_bill: {e}", exc_info=True)

    async def _save_outage_data(self, data: list):
        """Replace the customer's outage snapshot with the latest API response."""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

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

            # API response is a snapshot for the requested 30-day window.
            # Remove the old snapshot first so cancelled/removed schedules disappear.
            cursor.execute(
                "DELETE FROM power_outage_schedule WHERE userevn = ?",
                (self.customer_id,),
            )

            saved = 0
            for outage in (data or []):
                if not isinstance(outage, dict):
                    continue

                ngay_bat_dau = (
                    outage.get("NGAY_BAT_DAU")
                    or outage.get("ngay_bat_dau")
                    or outage.get("NGAY")
                    or outage.get("ngay")
                )
                ngay_ket_thuc = (
                    outage.get("NGAY_KET_THUC")
                    or outage.get("ngay_ket_thuc")
                    or outage.get("NGAY")
                    or outage.get("ngay")
                )
                thoi_gian_bat_dau = (
                    outage.get("THOI_GIAN_BAT_DAU")
                    or outage.get("thoi_gian_bat_dau")
                    or outage.get("THOI_GIAN")
                    or outage.get("thoi_gian")
                    or outage.get("THOI_DIEM")
                    or outage.get("thoi_diem")
                    or ""
                )
                thoi_gian_ket_thuc = (
                    outage.get("THOI_GIAN_KET_THUC")
                    or outage.get("thoi_gian_ket_thuc")
                    or ""
                )
                ly_do = (
                    outage.get("LY_DO")
                    or outage.get("ly_do")
                    or outage.get("NOI_DUNG")
                    or outage.get("noi_dung")
                    or ""
                )
                khu_vuc = (
                    outage.get("KHU_VUC")
                    or outage.get("khu_vuc")
                    or outage.get("PHAM_VI")
                    or outage.get("pham_vi")
                    or outage.get("KHUVUCMATDIEN")
                    or outage.get("khuvucmatdien")
                    or ""
                )

                # Defensive fallback for raw NPC responses: "15/09/2026 07:30".
                if not ngay_bat_dau:
                    raw_start = outage.get("TGIAN_BDAU") or outage.get("tgian_bdau")
                    if raw_start:
                        parts = str(raw_start).strip().split(None, 1)
                        ngay_bat_dau = parts[0]
                        if len(parts) == 2 and not thoi_gian_bat_dau:
                            thoi_gian_bat_dau = parts[1].strip()
                if not ngay_ket_thuc:
                    raw_end = outage.get("TGIAN_KTHUC") or outage.get("tgian_kthuc")
                    if raw_end:
                        parts = str(raw_end).strip().split(None, 1)
                        ngay_ket_thuc = parts[0]
                        if len(parts) == 2 and not thoi_gian_ket_thuc:
                            thoi_gian_ket_thuc = parts[1].strip()

                if ngay_bat_dau:
                    ngay_bat_dau = self._parse_date({"NGAY": ngay_bat_dau})
                if ngay_ket_thuc:
                    ngay_ket_thuc = self._parse_date({"NGAY": ngay_ket_thuc})

                if not ngay_bat_dau:
                    _LOGGER.debug(f"Skipping outage record without start date: {outage}")
                    continue

                cursor.execute("""
                    INSERT OR REPLACE INTO power_outage_schedule
                    (userevn, ngay_bat_dau, ngay_ket_thuc, thoi_gian_bat_dau,
                     thoi_gian_ket_thuc, ly_do, khu_vuc)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.customer_id, ngay_bat_dau, ngay_ket_thuc,
                    str(thoi_gian_bat_dau), str(thoi_gian_ket_thuc),
                    str(ly_do), str(khu_vuc)
                ))
                saved += 1

            conn.commit()
            conn.close()
            _LOGGER.info(
                f"Saved outage snapshot for {self.customer_id}: "
                f"{saved}/{len(data or [])} records"
            )

        except Exception as e:
            _LOGGER.error(f"Error saving outage data: {e}", exc_info=True)

    def _parse_date(self, record: Dict) -> str:
        """Parse date from record to dd-mm-yyyy format."""
        # Try different date fields (priority order)
        # NPC API returns "NGAY" field with format "dd/mm/yyyy"
        date_fields = [
            "NGAY", "ngay",  # Most common for NPC API
            "ngayFull", "ngay_full",  # HCMC format
            "strTime", "str_time",  # SPC format
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
                    continue
        
        # Default to today
        return datetime.now().strftime("%d-%m-%Y")

    def _parse_date_for_sort(self, record: Dict) -> datetime:
        """Parse date for sorting purposes."""
        # Try to extract date from various fields
        date_fields = [
            "NGAY", "ngay", "ngayFull", "ngay_full", "strTime", "str_time",
            "NGAY_DO", "ngay_do", "NGAY_DO_CS", "ngay_do_cs",
            "THOI_DIEM", "thoi_diem", "THOI_GIAN", "thoi_gian",
            "NGAY_BAT_DAU", "ngay_bat_dau", "NGAY_KET_THUC", "ngay_ket_thuc"
        ]
        
        for field in date_fields:
            if field in record:
                date_str = str(record[field]).strip()
                if not date_str or date_str.lower() in ['null', 'none', '']:
                    continue
                
                try:
                    # Handle THOI_DIEM format: "24/01/2026 00:33" -> extract date part
                    if field in ["THOI_DIEM", "thoi_diem"] and ' ' in date_str:
                        date_str = date_str.split(' ')[0]
                    
                    # Try dd/mm/yyyy (most common for NPC API)
                    if len(date_str) == 10 and date_str[2] == '/':
                        return datetime.strptime(date_str, "%d/%m/%Y")
                    # Try yyyy-mm-dd
                    elif len(date_str) == 10 and date_str[4] == '-':
                        return datetime.strptime(date_str, "%Y-%m-%d")
                    # Already dd-mm-yyyy
                    elif len(date_str) == 10 and date_str[2] == '-':
                        return datetime.strptime(date_str, "%d-%m-%Y")
                    # Try yyyymmdd
                    elif len(date_str) == 8 and date_str.isdigit():
                        return datetime.strptime(date_str, "%Y%m%d")
                except Exception as e:
                    continue
        
        # Default to today if parsing fails
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
