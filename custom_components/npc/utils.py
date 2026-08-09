import logging
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Any, Optional
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Global DB Path
DB_PATH = None


def set_db_path(path: str):
    """Set the database path globally."""
    global DB_PATH
    DB_PATH = path
    _LOGGER.info(f"Database path set to: {DB_PATH}")


def get_db_conn():
    """Get a database connection and ensure tables exist."""
    global DB_PATH
    if DB_PATH is None:
        # Fallback logic if not set
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        path = os.path.join(base_dir, "evnvn", "evndata.db")
        set_db_path(path)

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    return conn


def set_lancapnhapcuoi(hass, userevn, dt=None):
    """Set the last update time for an account."""
    if dt is None:
        dt = datetime.now()
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if userevn not in hass.data[DOMAIN]:
        hass.data[DOMAIN][userevn] = {}
    hass.data[DOMAIN][userevn]['lancapnhapcuoi'] = dt


def get_lancapnhapcuoi(hass, userevn):
    try:
        return hass.data[DOMAIN][userevn]['lancapnhapcuoi']
    except Exception:
        return None


def tinhngaydauky(ngaydauky: int, today: Optional[datetime] = None):
    if today is None:
        today = datetime.now()
    day = today.day
    month = today.month
    year = today.year

    if ngaydauky == 1:
        start = today.replace(day=1)
    else:
        if day < ngaydauky:
            if month == 1:
                start = today.replace(year=year-1, month=12, day=ngaydauky)
            else:
                start = today.replace(month=month-1, day=ngaydauky)
        else:
            start = today.replace(day=ngaydauky)
    end = today
    if start.month == 12:
        next_month = 1
        next_year = start.year + 1
    else:
        next_month = start.month + 1
        next_year = start.year
    try:
        next_start = start.replace(year=next_year, month=next_month, day=ngaydauky)
    except ValueError:
        last_day_next_month = (start.replace(year=next_year, month=next_month+1, day=1) - timedelta(days=1)).day
        next_start = start.replace(year=next_year, month=next_month, day=last_day_next_month)
    end_ky = next_start - timedelta(days=1)
    prev_end_ky = start - timedelta(days=1)
    return start, end, end_ky, prev_end_ky


def tinhtiendien(kwh):
    if kwh is None or kwh <= 0:
        return None, {}
    tiers = [
        {"limit": 50, "price": 1984}, {"limit": 50, "price": 2050}, {"limit": 100, "price": 2380},
        {"limit": 100, "price": 2998}, {"limit": 100, "price": 3350}, {"limit": float("inf"), "price": 3460}
    ]
    total_cost = 0
    remaining_kwh = kwh
    tier_details = []
    for i, tier in enumerate(tiers, 1):
        kwh_in_tier = min(remaining_kwh, tier["limit"])
        cost = kwh_in_tier * tier["price"]
        total_cost += cost
        tier_details.append({f"Bậc thang {i}": {"VNĐ/kWh": tier["price"], "kWh": kwh_in_tier, "Tính Tiền": cost}})
        remaining_kwh -= kwh_in_tier
        if remaining_kwh <= 0:
            break
    tax = total_cost * 0.08
    total_with_tax = total_cost + tax
    return total_with_tax, {"Tiền trước thuế": total_cost, "Thuế 8%": tax, "Chi tiết bậc thang": tier_details}


def chuyen_doi_so(value):
    """Chuyển đổi số từ format Việt Nam (dấu phẩy) sang format Python (dấu chấm)"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip().replace(',', '.')
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    return None


def dinhdangngay(date_str):
    if isinstance(date_str, str) and len(date_str) == 10 and date_str[4] == "-":
        y, m, d = date_str.split("-")
        return f"{d}-{m}-{y}"
    if isinstance(date_str, str) and len(date_str) == 10 and date_str[2] == "/" and date_str[5] == "/":
        d, m, y = date_str.split("/")
        return f"{d}-{m}-{y}"
    return date_str


def laychisongay(userevn, date_str):
    date_str = dinhdangngay(date_str)
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT chi_so FROM daily_consumption WHERE userevn=? AND ngay=?",
        (userevn, date_str)
    )
    row = cursor.fetchone()
    conn.close()
    if not row or row[0] is None or str(row[0]).strip().lower() == "không có dữ liệu":
        return None
    return chuyen_doi_so(row[0])


def laydientieuthungay(userevn, date_str):
    date_str = dinhdangngay(date_str)
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT dien_tieu_thu_kwh FROM daily_consumption WHERE userevn=? AND ngay=?",
        (userevn, date_str)
    )
    row = cursor.fetchone()
    conn.close()
    if not row or row[0] is None or str(row[0]).strip().lower() == "không có dữ liệu":
        return None
    return chuyen_doi_so(row[0])


def laydientieuthuthang(userevn, month, year):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tien_dien, san_luong_kwh FROM monthly_bill WHERE userevn=? AND thang=? AND nam=?",
        (userevn, month, year)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return chuyen_doi_so(row[0]), chuyen_doi_so(row[1])
    return None, None


def laychisongaygannhat(userevn, date_str, reverse=False):
    if not date_str or not isinstance(date_str, str) or len(date_str) != 10:
        return None, None
    if date_str[4] == '-':  # yyyy-mm-dd
        y, m, d = date_str.split('-')
        date_str_db = f"{d}-{m}-{y}"
    elif date_str[2] == '-':  # dd-mm-yyyy
        date_str_db = date_str
    else:
        return None, None
    try:
        d, m, y = date_str_db.split("-")
    except Exception:
        return None, None
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        date_order = "DESC" if reverse else "ASC"
        day_condition_after = (
            f"AND (substr(ngay,7,4) > '{y}' OR "
            f"(substr(ngay,7,4) = '{y}' AND "
            f"substr(ngay,4,2) > '{m}') OR "
            f"(substr(ngay,7,4) = '{y}' AND "
            f"substr(ngay,4,2) = '{m}' AND "
            f"substr(ngay,1,2) >= '{d}'))"
        )
        day_condition_before = (
            f"AND (substr(ngay,7,4) < '{y}' OR "
            f"(substr(ngay,7,4) = '{y}' AND "
            f"substr(ngay,4,2) < '{m}') OR "
            f"(substr(ngay,7,4) = '{y}' AND "
            f"substr(ngay,4,2) = '{m}' AND "
            f"substr(ngay,1,2) <= '{d}'))"
        )
        day_condition = day_condition_before if reverse else day_condition_after
        query = (
            "SELECT ngay, chi_so FROM daily_consumption "
            "WHERE userevn=? "
            f"{day_condition} "
            "AND chi_so IS NOT NULL AND chi_so != '' "
            "AND lower(chi_so) != 'không có dữ liệu' AND chi_so != 'Khôngcódữliệu' "
            f"ORDER BY substr(ngay,7,4) {date_order}, substr(ngay,4,2) {date_order}, substr(ngay,1,2) {date_order} "
            "LIMIT 1"
        )
        cursor.execute(query, (userevn,))
        row = cursor.fetchone()
        if not row:
            query_month = (
                "SELECT ngay, chi_so FROM daily_consumption "
                "WHERE userevn=? "
                "AND substr(ngay,4,2)=? AND substr(ngay,7,4)=? "
                "AND chi_so IS NOT NULL AND chi_so != '' "
                "AND lower(chi_so) != 'không có dữ liệu' AND chi_so != 'Khôngcódữliệu' "
                f"ORDER BY substr(ngay,1,2) {date_order} "
                "LIMIT 1"
            )
            cursor.execute(query_month, (userevn, m, y))
            row = cursor.fetchone()
            if not row:
                query_alt = (
                    "SELECT ngay, chi_so FROM daily_consumption "
                    "WHERE userevn=? "
                    "AND chi_so IS NOT NULL AND chi_so != '' "
                    "AND lower(chi_so) != 'không có dữ liệu' AND chi_so != 'Khôngcódữliệu' "
                    f"ORDER BY substr(ngay,7,4) {date_order}, substr(ngay,4,2) {date_order}, "
                    f"substr(ngay,1,2) {date_order} "
                    "LIMIT 1"
                )
                cursor.execute(query_alt, (userevn,))
                row = cursor.fetchone()
        conn.close()
        if row and row[1] is not None:
            try:
                ngay = row[0]
                chi_so_value = row[1]
                if isinstance(chi_so_value, str):
                    if chi_so_value == "Khôngcódữliệu" or chi_so_value.lower() == "không có dữ liệu":
                        return None, None
                chi_so = chuyen_doi_so(chi_so_value)
                if chi_so is None:
                    return None, None
                return chi_so, ngay
            except Exception:
                return None, None
        else:
            return None, None
    except Exception:
        return None, None


def laykhoangtieuthukynay(userevn, start_date, end_date):
    start_date = dinhdangngay(start_date)
    end_date = dinhdangngay(end_date)
    from datetime import datetime
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT ngay, chi_so, dien_tieu_thu_kwh FROM daily_consumption WHERE userevn=? ORDER BY ngay ASC",
        (userevn,)
    )
    rows = cursor.fetchall()
    conn.close()
    result = []
    try:
        start_dt = datetime.strptime(start_date, "%d-%m-%Y").date()
        end_dt = datetime.strptime(end_date, "%d-%m-%Y").date()
    except Exception:
        return []
    for row in rows:
        try:
            ngay_dt = datetime.strptime(row[0], "%d-%m-%Y").date()
            if start_dt <= ngay_dt <= end_dt:
                result.append(row)
        except Exception:
            continue
    return result


def layhoadon(userevn, year):
    conn = get_db_conn()
    cursor = conn.cursor()
    if year == "all":
        cursor.execute(
            "SELECT thang, tien_dien, san_luong_kwh, nam FROM monthly_bill WHERE userevn=? ORDER BY nam ASC, thang ASC",
            (userevn,)
        )
    else:
        cursor.execute(
            "SELECT thang, tien_dien, san_luong_kwh, nam FROM monthly_bill WHERE userevn=? AND nam=? ORDER BY thang ASC",
            (userevn, year)
        )
    rows = cursor.fetchall()
    conn.close()
    return rows


def laylichcatdien(userevn):
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT ngay_bat_dau, ngay_ket_thuc, thoi_gian_bat_dau,
                   thoi_gian_ket_thuc, ly_do, khu_vuc
            FROM power_outage_schedule
            WHERE userevn=?
            ORDER BY ngay_bat_dau DESC
            """,
            (userevn,)
        )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for row in rows:
            if row[0]:
                result.append({
                    "Ngày": str(row[0]),
                    "Thời gian từ": str(row[2]),
                    "Thời gian đến": str(row[3]),
                    "Lý do": str(row[4]),
                    "Khu vực": str(row[5])
                })
        return result
    except Exception:
        return []


def lay_tien_no_evn(userevn):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT tien_no, ngay_cap_nhat FROM tien_no_evn WHERE userevn=? ORDER BY ngay_cap_nhat DESC LIMIT 1",
        (userevn,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return chuyen_doi_so(row[0]), row[1]
    return None, None


def lay_ky_hien_tai(userevn):
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tieu_thu, tien_dien, ngay_dau_ky, ngay_cap_nhat 
            FROM current_period 
            WHERE userevn = ?
        """, (userevn,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0], row[1], row[2], row[3]
        return None, None, None, None
    except Exception:
        return None, None, None, None


def luu_ky_hien_tai(userevn, tieu_thu, tien_dien, ngay_dau_ky):
    try:
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS current_period (
                userevn TEXT PRIMARY KEY,
                tieu_thu REAL,
                tien_dien INTEGER,
                ngay_dau_ky TEXT,
                ngay_cap_nhat TEXT
            )
        """)
        cursor.execute("SELECT tieu_thu, tien_dien FROM current_period WHERE userevn = ?", (userevn,))
        row = cursor.fetchone()
        final_tieu_thu = tieu_thu
        final_tien_dien = tien_dien
        if row:
            if tieu_thu <= 0 and row[0] and row[0] > 0:
                final_tieu_thu = row[0]
            if tien_dien <= 0 and row[1] and row[1] > 0:
                final_tien_dien = row[1]
        ngay_cap_nhat = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        cursor.execute("""
            INSERT OR REPLACE INTO current_period 
            (userevn, tieu_thu, tien_dien, ngay_dau_ky, ngay_cap_nhat)
            VALUES (?, ?, ?, ?, ?)
        """, (userevn, final_tieu_thu, final_tien_dien, ngay_dau_ky, ngay_cap_nhat))
        conn.commit()
        conn.close()
    except Exception:
        pass
