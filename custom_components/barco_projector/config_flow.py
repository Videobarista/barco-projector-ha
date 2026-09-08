"""Config flow for the Barco Cinema Projector integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from .const import (
    CONF_MEDIA_BLOCK,
    CONF_MEDIA_BLOCK_HOST,
    CONF_MEDIA_BLOCK_PORT,
    CONF_SCAN_INTERVAL_SECONDS,
    DEFAULT_ICMP_PORT,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MEDIA_BLOCK_ICMP,
    MEDIA_BLOCK_NONE,
    MIN_SCAN_INTERVAL,
)
from .icmp import IcmpClient, IcmpError
from .protocol import BarcoClient, BarcoError, BarcoProjector

MEDIA_BLOCK_OPTIONS = [MEDIA_BLOCK_NONE, MEDIA_BLOCK_ICMP]

PORT_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, "Barco projector")): TextSelector(),
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): PORT_SELECTOR,
            vol.Required(
                CONF_MEDIA_BLOCK, default=defaults.get(CONF_MEDIA_BLOCK, MEDIA_BLOCK_NONE)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=MEDIA_BLOCK_OPTIONS,
                    translation_key="media_block",
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _media_block_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_MEDIA_BLOCK_HOST, default=defaults.get(CONF_MEDIA_BLOCK_HOST, "")
            ): TextSelector(),
            vol.Required(
                CONF_MEDIA_BLOCK_PORT,
                default=defaults.get(CONF_MEDIA_BLOCK_PORT, DEFAULT_ICMP_PORT),
            ): PORT_SELECTOR,
        }
    )


async def _async_test_projector(host: str, port: int) -> str | None:
    """Return an error key when the projector cannot be reached."""
    client = BarcoClient(host=host, port=port, timeout=6.0)
    projector = BarcoProjector(client)
    try:
        await projector.async_get_lamp()
    except BarcoError:
        return "cannot_connect"
    finally:
        await projector.async_close()
    return None


async def _async_test_icmp(host: str, port: int) -> str | None:
    """Return an error key when the ICMP cannot be reached."""
    client = IcmpClient(host=host, port=port, timeout=6.0)
    try:
        await client.async_connect()
    except IcmpError:
        return "cannot_connect_icmp"
    finally:
        await client.async_close()
    return None


class BarcoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the configuration of a projector."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the projector connection details."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            error = await _async_test_projector(host, port)
            if error:
                errors["base"] = error
            else:
                self._data = {
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_MEDIA_BLOCK: user_input[CONF_MEDIA_BLOCK],
                }
                if user_input[CONF_MEDIA_BLOCK] == MEDIA_BLOCK_ICMP:
                    return await self.async_step_media_block()
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=self._data
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_media_block(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the ICMP automation connection details."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = (user_input.get(CONF_MEDIA_BLOCK_HOST) or "").strip()
            port = int(user_input[CONF_MEDIA_BLOCK_PORT])
            error = await _async_test_icmp(host or self._data[CONF_HOST], port)
            if error:
                errors["base"] = error
            else:
                self._data[CONF_MEDIA_BLOCK_HOST] = host
                self._data[CONF_MEDIA_BLOCK_PORT] = port
                return self.async_create_entry(
                    title=self._data[CONF_NAME], data=self._data
                )

        return self.async_show_form(
            step_id="media_block",
            data_schema=_media_block_schema(user_input or {}),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return BarcoOptionsFlow()


class BarcoOptionsFlow(OptionsFlow):
    """Handle the options of an existing entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        current = {**self.config_entry.data, **self.config_entry.options}

        if user_input is not None:
            options = {
                CONF_SCAN_INTERVAL_SECONDS: int(
                    user_input[CONF_SCAN_INTERVAL_SECONDS]
                ),
                CONF_MEDIA_BLOCK: user_input[CONF_MEDIA_BLOCK],
                CONF_MEDIA_BLOCK_HOST: (
                    user_input.get(CONF_MEDIA_BLOCK_HOST) or ""
                ).strip(),
                CONF_MEDIA_BLOCK_PORT: int(user_input[CONF_MEDIA_BLOCK_PORT]),
            }
            return self.async_create_entry(data=options)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL_SECONDS,
                    default=current.get(
                        CONF_SCAN_INTERVAL_SECONDS, DEFAULT_SCAN_INTERVAL
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=600,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement="s",
                    )
                ),
                vol.Required(
                    CONF_MEDIA_BLOCK,
                    default=current.get(CONF_MEDIA_BLOCK, MEDIA_BLOCK_NONE),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=MEDIA_BLOCK_OPTIONS,
                        translation_key="media_block",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_MEDIA_BLOCK_HOST,
                    default=current.get(CONF_MEDIA_BLOCK_HOST, ""),
                ): TextSelector(),
                vol.Required(
                    CONF_MEDIA_BLOCK_PORT,
                    default=current.get(CONF_MEDIA_BLOCK_PORT, DEFAULT_ICMP_PORT),
                ): PORT_SELECTOR,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
