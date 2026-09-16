"""EVN VN Integration"""

import logging
from pathlib import Path
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_CUSTOMER_ID,
    CONF_REGION,
    CONF_NGAYDAUKY,
)
from .npc_api import EVNAPI
from .coordinator import EVNDataUpdateCoordinator
from .views import EVNStaticView, EVNPingView, EVNOptionsView, EVNMonthlyDataView, EVNDailyDataView, EVNCurrentPeriodView, EVNSyncHistoryView, EVNDebugDataView
from .utils import set_db_path

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up EVN VN from yaml configuration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EVN VN from a config entry."""
    region = entry.data[CONF_REGION]
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    customer_id = entry.data[CONF_CUSTOMER_ID]
    ngaydauky = entry.data.get(CONF_NGAYDAUKY, 1)

    # Set database path for utils
    set_db_path(hass.config.path("evnvn", "evndata.db"))

    # Create API client
    api = EVNAPI(hass, region, username, password, customer_id)

    # Create coordinator
    coordinator = EVNDataUpdateCoordinator(hass, api, customer_id, ngaydauky)

    # Register webui views (only once)
    hass.data.setdefault(DOMAIN, {})
    if "api_registered" not in hass.data[DOMAIN]:
        webui_path = str(Path(__file__).parent / "webui")
        hass.http.register_view(EVNStaticView(webui_path, hass))
        hass.http.register_view(EVNPingView(hass))
        hass.http.register_view(EVNOptionsView(hass))
        hass.http.register_view(EVNMonthlyDataView(hass))
        hass.http.register_view(EVNDailyDataView(hass))
        hass.http.register_view(EVNCurrentPeriodView(hass))
        hass.http.register_view(EVNSyncHistoryView(hass))
        hass.http.register_view(EVNDebugDataView(hass))
        hass.data[DOMAIN]["api_registered"] = True
        _LOGGER.info("Registered NPC API endpoints and WebUI at %s", webui_path)

    # Register WebUI panel (only once)
    if "panel_registered" not in hass.data[DOMAIN]:
        try:
            from homeassistant.components import frontend

            frontend.async_register_built_in_panel(
                hass,
                component_name="iframe",
                sidebar_title="EVN Monitor",
                sidebar_icon="mdi:lightning-bolt",
                frontend_url_path="npc_monitor",
                config={"url": "/npc-monitor/index.html"},
                require_admin=True,
            )
            hass.data[DOMAIN]["panel_registered"] = True
            _LOGGER.info("Registered EVN Monitor panel")
        except Exception as ex:
            _LOGGER.debug("Could not register panel: %s", str(ex))

    # Fetch initial data
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as ex:
        _LOGGER.warning("Initial data refresh failed: %s. Integration will retry in background.", ex)

    # Store coordinator
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "api": api,
        "customer_id": customer_id,
        "ngaydauky": ngaydauky,
    }

    # Forward to sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Close API session
    if entry.entry_id in hass.data.get(DOMAIN, {}):
        api = hass.data[DOMAIN][entry.entry_id].get("api")
        if api:
            await api.close()

    # Unload sensor platform
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "sensor")
    
    if unload_ok and entry.entry_id in hass.data.get(DOMAIN, {}):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
