"""HTTP views for EVN integration."""

import json
import logging
import mimetypes
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN, CONF_CUSTOMER_ID
from .utils import layhoadon, laykhoangtieuthukynay, lay_ky_hien_tai, get_db_conn, tinhtiendien

_LOGGER = logging.getLogger(__name__)




class EVNPingView(HomeAssistantView):
    """Simple ping endpoint to verify API is working."""

    url = "/api/npc/ping"
    name = "api:npc:ping"
    requires_auth = False

    def __init__(self, hass):
        """Initialize the view."""
        self.hass = hass

    async def get(self, request):
        """Handle GET request."""
        return web.json_response({
            "status": "ok",
            "message": "NPC API is running"
        })


class EVNStaticView(HomeAssistantView):
    """Serve static files from webui directory."""

    url = "/npc-monitor/{filename:.*}"
    name = "npc_monitor:static"
    requires_auth = False

    def __init__(self, webui_path: str, hass=None):
        """Initialize the static file server.
        
        Args:
            webui_path: Absolute path to the webui directory
            hass: Home Assistant instance for async operations
        """
        self.webui_path = Path(webui_path)
        self.hass = hass
        _LOGGER.info("EVNStaticView initialized with path: %s", self.webui_path)

    async def get(self, request, filename: str):
        """Serve a static file.
        
        Args:
            request: The HTTP request
            filename: Relative path to the file (e.g., "index.html" or "assets/js/main.js")
        """
        # Default to index.html if no filename or directory requested
        if not filename or filename.endswith('/'):
            filename = filename + 'index.html' if filename else 'index.html'

        # Construct full file path
        file_path = self.webui_path / filename
        
        # Security check: ensure the resolved path is within webui_path
        try:
            webui_root = self.webui_path.resolve()
            file_path = file_path.resolve()
            try:
                file_path.relative_to(webui_root)
            except ValueError:
                _LOGGER.debug("Attempted path traversal: %s", filename)
                return web.Response(status=403, text="Forbidden")
        except Exception as ex:
            _LOGGER.debug("Error resolving path %s: %s", filename, str(ex))
            return web.Response(status=400, text="Bad Request")

        # Check if file exists
        if not file_path.is_file():
            _LOGGER.debug("File not found: %s", file_path)
            return web.Response(status=404, text="Not Found")

        # Determine content type
        content_type, _ = mimetypes.guess_type(str(file_path))
        if content_type is None:
            content_type = "application/octet-stream"
        
        # Prepare headers
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
        
        # Add charset for text/* and application/javascript
        if content_type.startswith("text/") or content_type == "application/javascript":
            headers["Content-Type"] = f"{content_type}; charset=utf-8"
        else:
            headers["Content-Type"] = content_type

        # Read file asynchronously
        try:
            hass = request.app["hass"]
            content = await hass.async_add_executor_job(
                lambda: file_path.read_bytes()
            )
            
            return web.Response(
                body=content,
                headers=headers
            )
        except Exception as ex:
            _LOGGER.debug("Error reading file %s: %s", file_path, str(ex))
            return web.Response(status=500, text="Internal Server Error")


class EVNOptionsView(HomeAssistantView):
    """View to return available accounts."""

    url = "/api/npc/options"
    name = "api:npc:options"
    requires_auth = True

    def __init__(self, hass):
        """Initialize the view."""
        self.hass = hass

    async def get(self, request):
        """Get list of configured accounts."""
        try:
            hass = request.app["hass"]
            
            # Get all config entries for this domain
            entries = hass.config_entries.async_entries(DOMAIN)
            
            accounts = []
            for entry in entries:
                customer_id = entry.data.get(CONF_CUSTOMER_ID)
                if customer_id:
                    accounts.append({
                        "userevn": customer_id,
                        "id": customer_id,
                        "name": f"EVN {customer_id}",
                        "customer_id": customer_id,
                        "ngaydauky": entry.options.get("ngaydauky") or entry.data.get("ngaydauky") or 1
                    })
            
            _LOGGER.debug("EVNOptionsView returning %d configured accounts", len(accounts))
            
            # Return in format expected by WebUI
            return web.json_response({
                "accounts_json": json.dumps(accounts)
            })
        except Exception as ex:
            _LOGGER.debug("Error in EVNOptionsView: %s", str(ex), exc_info=True)
            return web.json_response({"error": "Internal server error"}, status=500)


class EVNMonthlyDataView(HomeAssistantView):
    """View to return monthly data for an account."""

    url = "/api/npc/monthly/{account}"
    name = "api:npc:monthly"
    requires_auth = True

    def __init__(self, hass):
        """Initialize the view."""
        self.hass = hass

    async def get(self, request, account):
        """Get monthly data for account."""
        try:
            hass = request.app["hass"]
            # Get data from database using utils
            
            # Get bills for current year
            # Get all bills from history
            bills = layhoadon(account, "all")
            
            # Format data for webui
            # layhoadon returns list of tuples: (thang, tien_dien, san_luong_kwh, nam)
            monthly_data = {
                "SanLuong": [],
                "TienDien": []
            }
            
            for bill in bills:
                try:
                    thang = bill[0]
                    tien_dien = bill[1]
                    san_luong = bill[2]
                    nam = bill[3] if len(bill) > 3 else datetime.now().year
                    
                    # Safely convert
                    thang_int = int(thang) if thang is not None else 0
                    san_luong_float = float(san_luong) if san_luong is not None else 0
                    # Chỉ trả tiền của hóa đơn thực tế đã lưu.
                    # Không được tự ước tính tiền từ sản lượng, vì như vậy các kỳ
                    # chưa có hóa đơn sẽ xuất hiện thành những khoản tiền giả.
                    try:
                        tien_dien_float = float(tien_dien) if tien_dien is not None else 0
                    except (TypeError, ValueError):
                        tien_dien_float = 0
                    nam_int = int(nam) if nam is not None else datetime.now().year
                    
                    monthly_data["SanLuong"].append({
                        "Tháng": thang_int,
                        "Năm": nam_int,
                        "Điện tiêu thụ (KWh)": san_luong_float
                    })
                    monthly_data["TienDien"].append({
                        "Tháng": thang_int,
                        "Năm": nam_int,
                        "Tiền Điện": tien_dien_float
                    })
                except Exception as bill_ex:
                    _LOGGER.debug("Error processing bill %s: %s", bill, str(bill_ex))
                    continue
            
            _LOGGER.info("EVNMonthlyDataView returning %d records for all years", len(monthly_data["SanLuong"]))
            return web.json_response(monthly_data)
            
        except Exception as ex:
            _LOGGER.debug("Error getting monthly data for %s: %s", account, str(ex), exc_info=True)
            return web.json_response(
                {"error": "Internal server error"},
                status=500
            )


class EVNDailyDataView(HomeAssistantView):
    """View to return daily data for an account."""

    url = "/api/npc/daily/{account}"
    name = "api:npc:daily"
    requires_auth = True

    def __init__(self, hass):
        """Initialize the view."""
        self.hass = hass

    async def get(self, request, account):
        """Get daily data for account."""
        try:
            hass = request.app["hass"]
            # Get data from 2025 to today (Server EVN limit)
            today = datetime.now()
            start_date = datetime(2025, 1, 1)
            
            # laykhoangtieuthukynay expects format dd/mm/yyyy and converts to dd-mm-yyyy
            # So we pass dd/mm/yyyy format
            rows = laykhoangtieuthukynay(
                account,
                start_date.strftime("%d/%m/%Y"),
                today.strftime("%d/%m/%Y")
            )
            
            # Format data for webui
            formatted_data = []
            for row in rows:
                try:
                    ngay = row[0] if row[0] else ""
                    # Safely convert to float
                    try:
                        chi_so = float(row[1]) if row[1] is not None else 0
                    except (ValueError, TypeError):
                        chi_so = 0
                    try:
                        tieu_thu = float(row[2]) if row[2] is not None else 0
                    except (ValueError, TypeError):
                        tieu_thu = 0
                    
                    # Calculate cost (simplified, you may need to adjust)
                    cost = tieu_thu * 2000  # Rough estimate
                    
                    formatted_data.append({
                        "Ngày": ngay,
                        "Điện tiêu thụ (kWh)": tieu_thu,
                        "Tiền điện (VND)": int(cost),
                        "CHISO": chi_so
                    })
                except Exception as row_ex:
                    _LOGGER.debug("Error processing row %s: %s", row, str(row_ex))
                    continue
            
            _LOGGER.info("EVNDailyDataView returning data for %s: %d days", account, len(formatted_data))
            return web.json_response(formatted_data)
            
        except Exception as ex:
            _LOGGER.debug("Error getting daily data for %s: %s", account, str(ex), exc_info=True)
            return web.json_response(
                {"error": "Internal server error"},
                status=500
            )


class EVNCurrentPeriodView(HomeAssistantView):
    """View to return current period data from database."""

    url = "/api/npc/current/{account}"
    name = "api:npc:current"
    requires_auth = True

    def __init__(self, hass):
        """Initialize the view."""
        self.hass = hass

    async def get(self, request, account):
        """Get current period data from database."""
        try:
            hass = request.app["hass"]
            # Lấy dữ liệu từ database
            tieu_thu, tien_dien, ngay_dau_ky, ngay_cap_nhat = lay_ky_hien_tai(account)
            
            _LOGGER.info("EVNCurrentPeriodView for %s: tieu_thu=%s, tien_dien=%s, ngay_dau_ky=%s", 
                         account, tieu_thu, tien_dien, ngay_dau_ky)
            
            return web.json_response({
                "account": account,
                "tieu_thu_ky_nay": tieu_thu or 0.0,
                "tien_dien_ky_nay": tien_dien or 0,
                "ngay_dau_ky": ngay_dau_ky,
                "ngay_cap_nhat": ngay_cap_nhat
            })
        except Exception as ex:
            _LOGGER.error("Error getting current period for %s: %s", account, str(ex), exc_info=True)
            return web.json_response(
                {"error": "Internal server error"},
                status=500
            )
class EVNSyncHistoryView(HomeAssistantView):
    """View to trigger manual history sync."""

    url = "/api/npc/sync_history"
    name = "api:npc:sync_history"
    requires_auth = True

    def __init__(self, hass):
        """Initialize the view."""
        self.hass = hass

    async def post(self, request):
        """Trigger history sync for all accounts."""
        try:
            # Trigger update for all coordinators in the domain
            coordinators = self.hass.data.get(DOMAIN, {})
            if not coordinators:
                return web.json_response({"success": False, "message": "No coordinators found"}, status=404)

            for entry_id, entry_data in coordinators.items():
                if entry_id == "api_registered" or entry_id == "panel_registered":
                    continue
                
                coordinator = entry_data.get("coordinator")
                if coordinator:
                    _LOGGER.info(f"Manual history sync triggered for {entry_data.get('customer_id')}")
                    await coordinator.async_refresh()

            return web.json_response({"success": True, "message": "History sync triggered for all accounts"})
            
        except Exception as ex:
            _LOGGER.error("Error triggering history sync: %s", str(ex), exc_info=True)
            return web.json_response(
                {"success": False, "message": "Internal server error"},
                status=500
            )


class EVNDebugDataView(HomeAssistantView):
    """View to debug monthly data in database."""

    url = "/api/npc/debug/{account}"
    name = "api:npc:debug"
    requires_auth = True

    def __init__(self, hass):
        """Initialize the view."""
        self.hass = hass

    async def get(self, request, account):
        """Debug monthly data for account."""
        try:
            hass = request.app["hass"]
            conn = await hass.async_add_executor_job(get_db_conn)
            cursor = conn.cursor()
            
            # Lấy tất cả dữ liệu từ monthly_bill
            cursor.execute(
                "SELECT thang, nam, tien_dien, san_luong_kwh FROM monthly_bill WHERE userevn=? ORDER BY nam ASC, thang ASC",
                (account,)
            )
            rows = cursor.fetchall()
            conn.close()
            
            monthly_data = []
            for row in rows:
                monthly_data.append({
                    "thang": row[0],
                    "nam": row[1],
                    "tien_dien": row[2],
                    "san_luong_kwh": row[3]
                })
            
            _LOGGER.info(f"Debug data for {account}: {len(monthly_data)} records")
            return web.json_response({
                "account": account,
                "total_records": len(monthly_data),
                "monthly_data": monthly_data
            })
            
        except Exception as ex:
            _LOGGER.error("Error getting debug data for %s: %s", account, str(ex), exc_info=True)
            return web.json_response(
                {"error": "Internal server error"},
                status=500
            )
