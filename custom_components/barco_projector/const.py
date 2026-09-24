"""Constants for the Barco Cinema Projector integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "barco_projector"

MANUFACTURER: Final = "Barco"
PROJECTOR_MODEL: Final = "Digital cinema projector"
MEDIA_BLOCK_MODEL: Final = "ICMP / ICMP-X"

# Barco LCD/DLP protocol (projector control)
CONF_SERIES: Final = "series"
SERIES_1: Final = "series1"
SERIES_2: Final = "series2"
PORT_SERIES_1: Final = 43680  # 0xAAA0
PORT_SERIES_2: Final = 43728  # 0xAAD0
DEFAULT_PORT: Final = PORT_SERIES_2

# Media block (Automation over IP)
CONF_MEDIA_BLOCK: Final = "media_block"
CONF_MEDIA_BLOCK_HOST: Final = "media_block_host"
CONF_MEDIA_BLOCK_PORT: Final = "media_block_port"
MEDIA_BLOCK_NONE: Final = "none"
MEDIA_BLOCK_ICMP: Final = "icmp"
DEFAULT_ICMP_PORT: Final = 43748

CONF_SCAN_INTERVAL_SECONDS: Final = "scan_interval_seconds"
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10

# How many polls between refreshes of the macro (source) list
MACRO_REFRESH_EVERY: Final = 20

# Highest macro button number probed when building the source list. Read as one
# range first; projectors that reject the range fall back to single reads.
MAX_MACRO_BUTTONS: Final = 32

SERVICE_EXECUTE_MACRO: Final = "execute_macro"
SERVICE_SEND_RAW: Final = "send_raw"
SERVICE_SEND_AUTOMATION: Final = "send_automation"
SERVICE_GPIO_PULSE: Final = "gpio_pulse"
SERVICE_GPIO_SET: Final = "gpio_set"

ATTR_MACRO: Final = "macro"
ATTR_COMMAND: Final = "command"
ATTR_DATA: Final = "data"
ATTR_OUTPUT: Final = "output"
ATTR_DURATION: Final = "duration"
ATTR_DIRECTION: Final = "direction"
ATTR_MASK: Final = "mask"

SHUTTER_CLOSED: Final = 0
SHUTTER_OPEN: Final = 1
SHUTTER_UNDETERMINED: Final = 2

SHUTTER_STATES: Final = {
    SHUTTER_CLOSED: "closed",
    SHUTTER_OPEN: "open",
    SHUTTER_UNDETERMINED: "undetermined",
}
