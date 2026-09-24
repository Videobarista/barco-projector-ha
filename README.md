# Barco Cinema Projector for Home Assistant

[![Ruff](https://github.com/Videobarista/barco-projector-ha/actions/workflows/ruff.yml/badge.svg)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/ruff.yml)
[![HACS](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hacs.yml/badge.svg)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hacs.yml)
[![Hassfest](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hassfest.yml/badge.svg)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/hassfest.yml)
[![CodeQL](https://github.com/Videobarista/barco-projector-ha/actions/workflows/codeql.yml/badge.svg)](https://github.com/Videobarista/barco-projector-ha/actions/workflows/codeql.yml)
[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-41BDF5.svg)](https://www.home-assistant.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

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
| Last seen | `sensor` | Timestamp of the last successful poll |
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

## Services

| Service | Target | What it does |
| --- | --- | --- |
| `barco_projector.execute_macro` | projector or ICMP media player | Runs a macro by name |
| `barco_projector.send_raw` | projector media player | Sends any Barco command as hex; framing, escaping and checksum are handled |
| `barco_projector.send_automation` | ICMP media player | Sends a raw automation command, e.g. `PLAYER.Pause (seconds),10` |
| `barco_projector.gpio_pulse` | ICMP media player | Pulses a GPIO output |
| `barco_projector.gpio_set` | ICMP media player | Sets GPIO outputs, e.g. `1=Up,2=Down` |

## Installation

1. HACS -> Custom repositories -> add this repository URL with category **Integration**.
2. Install, then restart Home Assistant.
3. Settings -> Devices & services -> Add integration -> **Barco Cinema Projector**.

Manual install: copy `custom_components/barco_projector` into your `config/custom_components`
folder and restart.

## Configuration

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
- A projector stops answering for several seconds while the lamp ignites. The read timeout
  is 15 seconds and a timed-out request is retried once on a fresh connection.
- Barco's documentation contains one example frame with a miscalculated checksum (lamp write
  on, where the projector address is left out of the sum). The implementation follows the
  documented formula; incoming frames with a bad checksum are logged, not discarded.

## Branding

Barco logos are not included: the manufacturer holds the rights to them and has not released
them for third-party use. The icon in `custom_components/barco_projector/brand/` is a
generic, self-drawn projector symbol. See [Brand/](Brand/) if you have artwork you are
allowed to distribute.

Because this integration is published as a custom repository, it is not present in the
`home-assistant/brands` repository, so the HACS workflow runs with `ignore: brands`.

## License

MIT (c) Videobarista
