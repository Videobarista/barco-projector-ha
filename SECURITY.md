# Security Policy

## Supported versions

Only the latest released version of this integration receives fixes.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | No |

## Reporting a vulnerability

Please report security issues through GitHub:

1. Open a [private security advisory](https://github.com/Videobarista/barco-projector-ha/security/advisories/new), or
2. Open a regular [issue](https://github.com/Videobarista/barco-projector-ha/issues) if the problem is not sensitive.

Please include the Home Assistant version, the integration version, and the steps needed to reproduce the problem.

## Scope

This integration talks to a projector on the local network over an unauthenticated,
plaintext protocol that Barco designed for control rooms. Anyone with access to that
network segment can control the projector with or without this integration. Keeping the
projector on a separate VLAN is therefore recommended; it is not something this
integration can enforce.
