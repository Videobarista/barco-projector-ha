# Barco Cinema Projector for Home Assistant

Control a Barco digital cinema projector (DP2K, DP4K, and the older DP series) from Home
Assistant over the network, without Communicator or any cloud service.

The projector is exposed as a media player: turn it on and off, and pick a macro as if it
were an input. The dowser is a switch, and lamp, dowser position, error counters and the
last executed macro are available as sensors.

If the projector holds a Barco **ICMP** or **ICMP-X**, the player can be controlled as a
second device through the "Automation over IP" protocol. An IMB, IMS or any other media
block is simply left alone; the projector control works the same either way.

## Entities

**Projector (Barco LCD/DLP protocol, TCP 43728 or 43680)**

| Entity | Type | Notes |
| --- | --- | --- |
| Projector | `media_player` | On/off switches the light source; the source list holds the macros bound to the keypad buttons |
| Dowser | `switch` | On means open |
| Sleep mode | `switch` | Only on models that support it (DP2K-10S / 10Sx); hidden otherwise |
| Lamp | `binary_sensor` | Light source running |
| Connectivity | `binary_sensor` | Stays available during an outage |
| Last macro | `sensor` | Name of the last executed macro |
| Dowser position | `sensor` | `closed`, `open` or `undetermined` |
| Errors, Warnings, Notifications | `sensor` | Series 2 only |
| Last seen | `sensor` | Timestamp of the last successful poll |
| Lens focus/zoom/shift | `button` | Eight buttons, **disabled by default** — enable them in the entity settings |

**ICMP (Automation over IP, TCP 43748)**

| Entity | Type | Notes |
| --- | --- | --- |
| ICMP | `media_player` | Play, pause, stop, next, previous |
| Schedule, Repeat | `switch` | |
| Play scheduled show, Emergency stop, Jump to clip end, Recover, Recover and play, Ignore recovery, Clear | `button` | |

## Services

| Service | Target | What it does |
| --- | --- | --- |
| `barco_projector.execute_macro` | projector or ICMP media player | Runs a macro by name |
| `barco_projector.send_raw` | projector media player | Sends any Barco command as hex; framing, escaping and checksum are handled |
| `barco_projector.send_automation` | ICMP media player | Sends a raw automation command, e.g. `PLAYER.Pause (seconds),10` |
| `barco_projector.gpio_pulse` | ICMP media player | Pulses a GPIO output |
| `barco_projector.gpio_set` | ICMP media player | Sets GPIO outputs, e.g. `1=Up,2=Down` |

## Installation

1. HACS → Custom repositories → add this repository URL with category **Integration**.
2. Install, then restart Home Assistant.
3. Settings → Devices & services → Add integration → **Barco Cinema Projector**.

Manual install: copy `custom_components/barco_projector` into your `config/custom_components`
folder and restart.

## Configuration

- **Host**: IP address of the projector controller. On series 1 projectors this is the main
  controller address, not the Texas Instruments front end.
- **Port**: `43728` for series 2 (DP2K, DP4K), `43680` for series 1.
- **Media block**: `Barco ICMP or ICMP-X` adds the player device. Its host defaults to the
  projector address; the ICMP LAN ports can be used instead.
- **Poll interval** (options): 30 seconds by default. The Barco protocol is blocking — one
  request at a time — so do not go below 10 seconds.

## Known limitations

- The Automation over IP protocol has **no status feedback**. The ICMP media player and its
  switches are optimistic: they show what was last commanded, not what the player is doing.
  Acknowledgement is enabled on the socket, but that only confirms the command was parsed.
- The source list is built from the macros bound to keypad buttons 1–16. Macros that are not
  bound to a button do not appear; use the `execute_macro` service for those.
- Error, warning and notification counters and `macro, read (2)` are series 2 features. On a
  series 1 projector these commands are not acknowledged and the sensors are skipped.
- The projector reports that the lamp is on before the picture is stable. After an on/off or
  dowser command the integration re-polls after a few seconds and again after 20 and 45
  seconds.
- Series 2 projectors close an idle socket after 15 minutes. The client reconnects
  transparently, so a poll interval well under 15 minutes is recommended.
- Formats and inputs are not separate commands in the Barco protocol; they live inside
  macros. That is why macros are the source list.

## License

MIT © VideoBarista
