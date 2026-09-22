# Implementation Notes

This document records implementation details that are useful when maintaining the project.

## RGB LED

The current implementation targets the ESP32-S3 DevKit v1.3 integrated RGB LED on GPIO48. The LED output uses an SPI-based WS2812 encoding instead of the standard NeoPixel module. Brightness is reduced and repeated writes of the same colour are skipped.

The LED implementation is hardware-dependent and should be treated as a board-specific component.

## Flash storage

State is stored as JSON files in the device filesystem. The implementation uses temporary files and conditional state saves in several places to reduce unnecessary writes and avoid constructing large JSON strings in RAM where practical.

Flash endurance remains a system-level limitation. New features should avoid periodic writes unless persistent state actually changed.

## Memory

The application explicitly calls garbage collection around memory-intensive operations and avoids desktop/server dependencies. This is important because the target device has significantly fewer resources than a conventional Python host.

## Network behaviour

The monitor maintains its own T3 session, handles CSRF/session cookies, and contains retry/error handling for network operations. T3 KYS server-side changes may still require application changes.
