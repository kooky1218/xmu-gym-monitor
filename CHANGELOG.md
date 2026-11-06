# Changelog

All notable changes to this project are documented here.

## [1.0.1] - 2026-11-06

### Fixed

- Manual dashboard refresh now immediately runs availability matching and Bark
  delivery instead of waiting for the next background interval.
- SQLite connections are closed deterministically on Windows, preventing test
  and temporary-database file locks.
- Bark availability, test, and system notifications no longer include URLs.
- Bark requests no longer inherit an invalid system proxy by default.

### Verified

- Real Windows lock-screen monitoring with `LogonUI.exe` active.
- Minimized mini-program monitoring.
- Pillow-free multi-resolution Windows icon generation and circular masking.

## [1.0.0] - 2026-11-06

### Added

- Read-only XMU gym availability monitoring from the logged-in WeChat
  mini-program through Windows UI Automation.
- Automatic date and time-slot parsing, including multi-date slot collection.
- PySide6 desktop dashboard with automatic refresh and system-tray mode.
- SQLite-backed change detection, notification de-duplication, and cooldowns.
- Bark notifications with credentials stored in Windows Credential Manager.
- Windows login daemon for automatic five-minute checks.
- Desktop shortcut installer with a circular custom icon.
- Chinese setup, diagnostic, feasibility, and test documentation.

### Safety

- No booking or order submission.
- No CAPTCHA handling.
- No WeChat Cookie, Token, or password extraction.
- Cache and mock data never trigger formal availability notifications.
