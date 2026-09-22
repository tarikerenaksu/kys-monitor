# Contributing

Thanks for your interest in KYS Monitor.

## Before opening an issue

- Check existing issues first.
- Confirm that the problem is reproducible on a supported ESP32-S3 setup.
- Do not include passwords, session cookies, Wi-Fi credentials, personal application data or other secrets.

## Pull requests

Please keep pull requests focused and include:

- a clear description of the change;
- the hardware and MicroPython version used for testing;
- reproduction steps for bug fixes;
- any relevant memory, Flash or network impact.

Before submitting, verify that:

- no credentials or device-specific JSON files are included;
- `main.py` remains valid Python/MicroPython syntax;
- unrelated formatting changes are avoided.

## Scope

Changes should preserve the project's lightweight ESP32-S3 design and avoid adding desktop/server dependencies unless there is a clear reason to do so.
