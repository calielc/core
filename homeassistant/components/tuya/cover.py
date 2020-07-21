"""Support for Tuya covers."""
from homeassistant.components.cover import (
    ATTR_POSITION,
    DOMAIN as SENSOR_DOMAIN,
    ENTITY_ID_FORMAT,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_STOP,
    SUPPORT_SET_POSITION,
    CoverEntity,
)

from homeassistant.const import (
    CONF_PLATFORM,
    STATE_CLOSED,
    STATE_CLOSING,
    STATE_OPEN,
    STATE_OPENING,
    STATE_UNKNOWN,
)

from homeassistant.helpers.dispatcher import async_dispatcher_connect
import homeassistant.util.dt as dt

import logging
import time

from . import TuyaDevice
from .const import DOMAIN, TUYA_DATA, TUYA_DISCOVERY_NEW

PARALLEL_UPDATES = 0

STATE_ATTR_FULL_MOVIMENT_DURATON = "full_moviment_duration"
STATE_ATTR_CURRENT_POSITION = "current_position"

logger = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up tuya sensors dynamically through tuya discovery."""

    platform = config_entry.data[CONF_PLATFORM]

    async def async_discover_sensor(dev_ids):
        """Discover and add a discovered tuya sensor."""
        if not dev_ids:
            return
        entities = await hass.async_add_executor_job(
            _setup_entities, hass, dev_ids, platform,
        )
        async_add_entities(entities)

    async_dispatcher_connect(
        hass, TUYA_DISCOVERY_NEW.format(SENSOR_DOMAIN), async_discover_sensor
    )

    devices_ids = hass.data[DOMAIN]["pending"].pop(SENSOR_DOMAIN)
    await async_discover_sensor(devices_ids)


def _setup_entities(hass, dev_ids, platform):
    """Set up Tuya Cover device."""
    tuya = hass.data[DOMAIN][TUYA_DATA]
    entities = []
    for dev_id in dev_ids:
        device = tuya.get_device_by_id(dev_id)
        if device is None:
            continue
        entities.append(TuyaCover(device, platform))
    return entities


class TuyaCover(TuyaDevice, CoverEntity):
    """Tuya cover devices."""

    def __init__(self, tuya, platform):
        """Init tuya cover device."""
        super().__init__(tuya, platform)
        self.entity_id = ENTITY_ID_FORMAT.format(tuya.object_id())

        self._full_moviment_duration_in_seconds = 32.5
        
        self._status = STATE_UNKNOWN
        self._current_position = None

        self._current_moviment_start = None
        self._current_moviment_position = None

    def __set_current_position(self, value):
        if value is None:
            self._status = STATE_UNKNOWN
            self._current_position = None
        elif value <= 0:
            self._status = STATE_CLOSED
            self._current_position = 0
        elif value >= 100: 
            self._status = STATE_OPEN
            self._current_position = 100
        else:
            self._status = STATE_UNKNOWN
            self._current_position = value

        logger.debug(self.entity_id + "> Status: " + str(self._status))
        logger.debug(self.entity_id + "> CurrentPosition: " + str(self._current_position))

    def __do_open_cover(self):
        self._tuya.open_cover()

        self._status = STATE_OPENING
        self._current_position = None

    def __do_close_cover(self):
        self._tuya.close_cover()

        self._status = STATE_CLOSING
        self._current_position = None

    def __do_stop_cover(self):
        now = dt.now()

        self._tuya.stop_cover()

        if self._current_moviment_start is None or self._current_moviment_position is None:
            self._current_moviment_start = None
            self._current_moviment_position = None
            return

        duration = (now - self._current_moviment_start).total_seconds()
        logger.debug(self.entity_id + "> duration: " + str(duration))

        moviment_range = duration * 100 / self._full_moviment_duration_in_seconds
        logger.debug(self.entity_id + "> moviment_range: " + str(moviment_range))

        if self._status == STATE_OPENING:
            self.__set_current_position(self._current_moviment_position + moviment_range)
        elif self._status == STATE_CLOSING:
            self.__set_current_position(self._current_moviment_position - moviment_range)

        self._current_moviment_start = None
        self._current_moviment_position = None

    def __check_timeout_moviment(self):
        if self._status == STATE_UNKNOWN or self._current_moviment_start is None:
            self._current_moviment_start = None
            self._current_moviment_position = None
            return

        now = dt.now()
        duration = (now - self._current_moviment_start).total_seconds()
        logger.debug(self.entity_id + "> duration: " + str(duration))

        if duration < self._full_moviment_duration_in_seconds:
            return

        if self._status == STATE_OPENING or self._status == STATE_OPEN: 
            self.__set_current_position(100)
        elif self._status == STATE_CLOSING or self._status == STATE_CLOSED:
            self.__set_current_position(0)

        self._current_moviment_start = None
        self._current_moviment_position = None

    @property
    def full_moviment_duration_in_seconds(self):
        """Get full_moviment_duration_in_seconds."""
        return self._full_moviment_duration_in_seconds

    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = SUPPORT_OPEN | SUPPORT_CLOSE
        if self._tuya.support_stop():
            supported_features |= SUPPORT_STOP | SUPPORT_SET_POSITION

        return supported_features

    @property
    def state_attributes(self):
        """Return the state attributes of the sun."""
        return {
            STATE_ATTR_FULL_MOVIMENT_DURATON: self._full_moviment_duration_in_seconds,
            STATE_ATTR_CURRENT_POSITION: self._current_position
        }

    @property
    def is_opening(self):
        """Return if the cover is opening or not."""

        self.__check_timeout_moviment()
        return self._status == STATE_OPENING

    @property
    def is_closing(self):
        """Return if the cover is closing or not."""

        self.__check_timeout_moviment()
        return self._status == STATE_CLOSING

    @property
    def is_closed(self):
        """Return if the cover is closed or not."""

        self.__check_timeout_moviment()

        if self._current_position is None:
            return None
        return self._current_position == 0

    @property
    def current_cover_position(self):
        """Return the current position of cover shutter."""
        return self._current_position

    def open_cover(self, **kwargs):
        """Open the cover."""
        logger.info(self.entity_id + "> open_cover")

        self.__do_stop_cover()

        self._current_moviment_start = dt.now()
        self._current_moviment_position = self._current_position

        self.__do_open_cover()

    def close_cover(self, **kwargs):
        """Close cover."""
        logger.info(self.entity_id + "> close_cover")

        self.__do_stop_cover()
        
        self._current_moviment_start = dt.now()
        self._current_moviment_position = self._current_position

        self.__do_close_cover()

    def stop_cover(self, **kwargs):
        """Stop the cover."""
        logger.info(self.entity_id + "> stop_cover")

        self.__do_stop_cover()

    def set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        logger.info(self.entity_id + "> set_cover_position")

        self.__do_stop_cover()

        target_position = int(kwargs.get(ATTR_POSITION))
        if target_position == self._current_position:
            return

        if target_position <= 5 or (self._current_position is None and target_position < 60):
            self.__do_close_cover()

            time.sleep(self._full_moviment_duration_in_seconds)
            self._tuya.stop_cover()

            self.__set_current_position(0)

        elif target_position >= 95 or (self._current_position is None and target_position >= 60):
            self.__do_open_cover()

            time.sleep(self._full_moviment_duration_in_seconds)
            self._tuya.stop_cover()

            self.__set_current_position(100)

        distance = target_position - self._current_position
        logger.debug(self.entity_id + "> distance: " + str(distance))

        if distance >= -5 and distance <= 5:
            return

        moviment_duration_in_seconds = abs(distance * self._full_moviment_duration_in_seconds / 100.0)
        logger.debug(self.entity_id + "> moviment_duration_in_seconds: " + str(moviment_duration_in_seconds))

        if distance > 0:
            self.__do_open_cover()
        elif distance < 0:
            self.__do_close_cover()

        time.sleep(moviment_duration_in_seconds)
        self._tuya.stop_cover()

        self.__set_current_position(target_position)

        self._current_moviment_start = None
        self._current_moviment_position = None
