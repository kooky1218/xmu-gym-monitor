# Changelog

All notable changes to this project are documented here.

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
