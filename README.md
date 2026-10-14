# Barco Cinema Projector for Home Assistant

[![Hassfest](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hassfest.yml/badge.svg?branch=main)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hassfest.yml)
[![HACS validation](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hacs.yml/badge.svg?branch=main)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hacs.yml)
[![CodeQL](https://github.com/Videobarista/barco-projector-ha/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/codeql.yml)
[![Ruff](https://github.com/Videobarista/barco-projector-ha/actions/workflows/ruff.yml/badge.svg?branch=main)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/ruff.yml)
[![Tests](https://github.com/Videobarista/barco-projector-ha/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/tests.yml)

[![HACS custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Quality scale: Bronze (aligned)](https://img.shields.io/badge/quality%20scale-bronze%20(aligned)-cd7f32.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
[![Home Assistant 2025.10+](https://img.shields.io/badge/Home%20Assistant-2025.10%2B-41BDF5.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Release](https://img.shields.io/github/v/release/Videobarista/barco-projector-ha?display_name=tag)](https://github.com/Videobarista/barco-projector-ha/releases)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Videobarista&repository=barco-projector-ha&category=integration)

Control a Barco digital cinema projector (DP2K, DP4K, and the older DP series) from Home
Assistant over the network, without Communicator or any cloud service.

The projector is exposed as a media player: turn it on and off, and pick a macro as if it
were an input. The dowser is a switch, and lamp, dowser position, error counters and the
last executed macro are polled from the projector itself.

If the projector holds a Barco **ICMP** or **ICMP-X**, the player can be controlled as a
second device through the "Automation over IP" protocol. An IMB, IMS or any other media
block is simply left alone; projector control works the same either way.

## Status feedback

Worth being precise about, because the two protocols are not equal:

- **Projector (binary Barco protocol).** Every poll reads the real state out of the
  projector controller: lamp on/off, dowser position, error counters, last executed macro.
  This is measured state, not an assumption about what was last commanded.
- **ICMP (Automation over IP).** This protocol has no read commands at all, by design; see
  the scope section of Barco's own specification. The ICMP media player and its switches are
  therefore optimistic: they show what was last sent. Acknowledgement is enabled on the
  socket, but an ACK only confirms that a command was parsed.

## When the projector is switched off

A projector that is powered down stops answering, which is expected rather than an error.
The integration treats it as a normal state: the entities go unavailable, the connectivity
sensor goes off, and the "Last seen" sensor keeps the timestamp of the last answer. One line
at info level is logged when it stops answering and one when it returns, so a power cycle
does not fill the log with errors.

The integration remembers what the projector reported: its macros and which optional
commands it answers. A Home Assistant restart while the projector is off therefore sets it up
from that memory, with the same entities as before. Only a projector that has never answered
keeps the entry waiting until it does.

The entities go *unavailable*, not *off*. Losing contact says nothing about the lamp: a
switch reboot looks exactly the same as a projector at the wall socket, so the integration
does not guess.

## Entities

**Projector - Barco LCD/DLP protocol, TCP 43728 (series 2) or 43680 (series 1)**

| Entity | Type | Notes |
| --- | --- | --- |
| Projector | `media_player` | On/off switches the light source; the source list holds the macros bound to the keypad buttons |
| Macro | `select` | Dropdown with every macro on the keypad; picking one runs it |
| Dowser | `switch` | On means open |
| Sleep mode | `switch` | Only on models that support it (DP2K-10S / 10Sx); unavailable otherwise |
| Lamp | `binary_sensor` | Light source running |
| Connectivity | `binary_sensor` | Stays available during an outage |
| Last macro | `sensor` | Name of the last executed macro |
| Dowser position | `sensor` | `closed`, `open` or `undetermined` |
| Errors, Warnings, Notifications | `sensor` | Series 2 only |
| Last seen | `sensor` | Timestamp of the last successful poll. **Disabled by default**: it changes on every poll, so enabled it stores a new state in the recorder every 30 seconds |
| Lens focus / zoom / shift | `button` | Eight buttons, one step per press |

**ICMP - Automation over IP, TCP 43748**

| Entity | Type | Notes |
| --- | --- | --- |
| ICMP | `media_player` | Play, pause, resume, stop, next, previous |
| Schedule, Repeat | `switch` | |
| Play scheduled show, Emergency stop, Jump to clip end, Recover, Recover and play, Ignore recovery, Clear | `button` | |

## Switching inputs and formats

The Barco protocol has no command to select an input or an aspect ratio. Source, format,
lens position and processing all live inside a macro, which is why the integration reads the
macros off the keypad and offers them as a dropdown. Running the macro that belongs to an
input is how you switch to HDMI, DVI, SDI or the media block. Which macros exist depends
entirely on how the projector was commissioned; nothing about them is standardised.

## Actions

All actions target a media player of this integration. The projector actions go to the
projector's media player, the ICMP actions to the ICMP media player; sending one to the other
raises an error that says so.

| Action | Target | What it does |
| --- | --- | --- |
| `barco_projector.execute_macro` | projector or ICMP media player | Runs a macro by name. Through the ICMP it is relayed to the projector. |
| `barco_projector.send_raw` | projector media player | Sends any Barco command; framing, escaping and checksum are handled. |
| `barco_projector.send_automation` | ICMP media player | Sends a raw Automation over IP command. |
| `barco_projector.gpio_pulse` | ICMP media player | Pulses one of the ICMP GPIO outputs. |
| `barco_projector.gpio_set` | ICMP media player | Sets one or more ICMP GPIO outputs. |

| Action | Field | Required | Description |
| --- | --- | --- | --- |
| `execute_macro` | `macro` | yes | Macro name, exactly as stored on the projector, e.g. `2D_FLAT`. |
| `send_raw` | `command` | yes | Command bytes as hex, e.g. `76 9a`, `0x761a` or `\x76\x1a`. |
| `send_raw` | `data` | no | Data bytes as hex, e.g. `01`. |
| `send_automation` | `command` | yes | For example `PLAYER.Pause (seconds),10`; the closing `;` is added for you. |
| `gpio_pulse` | `output` | yes | Output number, 1 to 8. |
| `gpio_pulse` | `duration` | no | Pulse length in milliseconds, 1 to 60000. Default 500. |
| `gpio_pulse` | `direction` | no | `up` or `down`. Default `up`. |
| `gpio_set` | `mask` | yes | Outputs and states, e.g. `1=Up,2=Down,3=Down`. |

Example: switch to a format and open the dowser.

```yaml
actions:
  - action: barco_projector.execute_macro
    target:
      entity_id: media_player.dp2k_6e
    data:
      macro: "DCI 239"
  - action: switch.turn_on
    target:
      entity_id: switch.dp2k_6e_dowser
```

## Installation

1. HACS -> Custom repositories -> add this repository URL with category **Integration**.
2. Install, then restart Home Assistant.
3. Settings -> Devices & services -> Add integration -> **Barco Cinema Projector**.

Manual install: copy `custom_components/barco_projector` into your `config/custom_components`
folder and restart.

## Configuration

When you add the integration it first sends a UDP discovery broadcast and lists the
projectors that answer, with their model and hostname. Pick one and the address is filled
in for you, and the model is stored so the device page shows "DP2K-6E" rather than a
generic name. Nothing answering is not an error: the flow drops straight through to manual
entry. Entries created before discovery existed can pick the model up by opening the
integration options and saving.

- **Host**: IP address of the projector controller. On series 1 projectors this is the main
  controller address, not the Texas Instruments front end.
- **Port**: `43728` for series 2 (DP2K, DP4K), `43680` for series 1.
- **Media block**: `Barco ICMP or ICMP-X` adds the player device. Its host defaults to the
  projector address; an ICMP LAN port can be used instead.
- **Poll interval** (options): 30 seconds by default. The Barco protocol is blocking - one
  request at a time - so do not go below 10 seconds.

## Known limitations

- The source list is built from the macros bound to keypad buttons 1-32. Macros that are not
  bound to a button do not appear; use the `execute_macro` service for those.
- Formats and inputs are not separate commands in the Barco protocol; they live inside
  macros. That is why macros are the source list.
- Error, warning and notification counters are series 2 features. On a series 1 projector
  these commands are not acknowledged and the sensors are skipped automatically.
- The projector reports that the lamp is on before the picture is stable. After an on/off or
  dowser command the integration re-polls at 2, 10, 30 and 60 seconds.
- Series 2 projectors close an idle socket after 15 minutes. The client reconnects
  transparently, so keep the poll interval well below that.
- Discovery is a broadcast to port 0xA001, so it does not cross VLANs or reach a projector
  behind a router. On a segmented network, enter the address by hand.
- A projector stops answering for several seconds while the lamp ignites. The read timeout
  is 15 seconds and a timed-out request is retried once on a fresh connection.
- Barco's documentation contains one example frame with a miscalculated checksum (lamp write
  on, where the projector address is left out of the sum). The implementation follows the
  documented formula; incoming frames with a bad checksum are logged, not discarded.

## Removal

1. Go to **Settings -> Devices & services** and open **Barco Cinema Projector**.
2. Open the menu (three dots) next to the projector entry and choose **Delete**. What the
   integration remembered about the projector is deleted with it.
3. To remove the files as well: in HACS, open **Barco Cinema Projector** and choose
   **Remove**, or delete `custom_components/barco_projector` for a manual installation.
   Restart Home Assistant afterwards.

Nothing is changed on the projector itself: macros, keypad bindings and settings stay as
they are.

## Branding

Barco logos are not included: the manufacturer holds the rights to them and has not released
them for third-party use. The icon in `custom_components/barco_projector/brand/` is a
generic, self-drawn projector symbol. See [Brand/](Brand/) if you have artwork you are
allowed to distribute.

## Quality scale

This integration is aligned with the **Bronze** tier of the
[Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
Home Assistant only grades integrations that ship with Home Assistant itself, so this is a
self-assessment, not an official rating. The status per rule is recorded in
[`quality_scale.yaml`](custom_components/barco_projector/quality_scale.yaml).

## Development

The tests use [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
and run on every push. To run them locally (Python 3.14):

```bash
pip install -r requirements_test.txt
pytest --cov --cov-report=term-missing
```

## License

MIT (c) Videobarista
