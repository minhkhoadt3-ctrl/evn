"""Button platform for EVN VN integration."""

import logging
from homeassistant.components.button import ButtonEntity
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_CUSTOMER_ID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up EVN VN buttons from a config entry."""
    customer_id = config_entry.data[CONF_CUSTOMER_ID]

    # Get coordinator from hass.data
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    # Add force resync button
    button_unique_id = f"{customer_id}_force_resync"
    async_add_entities([EVNResyncButton(coordinator, customer_id, button_unique_id)])

    return True


class EVNResyncButton(ButtonEntity):
    """Button to force resync all EVN data."""

    def __init__(self, coordinator, customer_id, unique_id):
        """Initialize the button."""
        self.coordinator = coordinator
        self._customer_id = customer_id
        self._attr_unique_id = unique_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, customer_id)},
            "name": f"EVN VN Device ({customer_id})",
            "manufacturer": "EVN VN",
            "model": "EVN VN",
            "sw_version": "2026.4.7",
        }
        self._attr_name = f"Force Resync ({customer_id})"
        self._attr_icon = "mdi:refresh"

    async def async_press(self) -> None:
        """Handle the button press."""
        try:
            _LOGGER.info(f"Force resync button pressed for {self._customer_id}")
            # Force resync by deleting all data and triggering refresh
            await self.coordinator.hass.async_add_executor_job(self.coordinator.force_resync_all_data)
            await self.coordinator.async_refresh()
            _LOGGER.info(f"Force resync completed for {self._customer_id}")
        except Exception as e:
            _LOGGER.error(f"Error during force resync for {self._customer_id}: {e}", exc_info=True)