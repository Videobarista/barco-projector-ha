"""Constants for the Barco Cinema Projector integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "barco_projector"

MANUFACTURER: Final = "Barco"
DEFAULT_NAME: Final = "Barco projector"
MANUAL_ENTRY: Final = "manual"
PROJECTOR_MODEL: Final = "Digital cinema projector"
MEDIA_BLOCK_MODEL: Final = "ICMP / ICMP-X"

# Barco LCD/DLP protocol (projector control)
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
MAX_SCAN_INTERVAL: Final = 600

# How many polls between refreshes of the macro (source) list
MACRO_REFRESH_EVERY: Final = 20

# Highest macro button number probed when building the source list. Read as one
# range first; projectors that reject the range fall back to single reads.
MAX_MACRO_BUTTONS: Final = 32

# Extra polls after a command, in seconds: lamp and dowser need time to settle.
FOLLOWUP_REFRESH_DELAYS: Final = (2, 10, 30, 60)

# Minimum time between requested polls. Home Assistant's default of 10 seconds made
# a dowser change show up to 9 seconds late; the polls themselves take ~30 ms.
REQUEST_REFRESH_COOLDOWN: Final = 1.0

# What the projector reported on an earlier run, kept between restarts.
STORAGE_VERSION: Final = 1

# Optional read commands, and the entities that only exist when they are answered.
CAPABILITY_LAST_MACRO: Final = "last_macro"
CAPABILITY_ERRORS: Final = "errors"
CAPABILITY_SLEEP: Final = "sleep"
CAPABILITY_MACROS: Final = "macros"
CAPABILITY_ENTITIES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    CAPABILITY_LAST_MACRO: (("sensor", "last_macro"),),
    CAPABILITY_ERRORS: (
        ("sensor", "errors"),
        ("sensor", "warnings"),
        ("sensor", "notifications"),
    ),
    CAPABILITY_SLEEP: (("switch", "sleep"),),
}

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
