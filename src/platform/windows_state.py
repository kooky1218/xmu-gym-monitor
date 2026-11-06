from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Any


USER32 = ctypes.WinDLL("user32", use_last_error=True)
KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _process_names() -> dict[int, str]:
    snapshot = KERNEL32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    names: dict[int, str] = {}
    try:
        success = KERNEL32.Process32FirstW(snapshot, ctypes.byref(entry))
        while success:
            names[int(entry.th32ProcessID)] = entry.szExeFile
            success = KERNEL32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        KERNEL32.CloseHandle(snapshot)
    return names


def _window_records(process_names: dict[int, str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        length = USER32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        USER32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if not any(token in title for token in ("微信", "厦大体育")):
            return True
        process_id = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(
            hwnd,
            ctypes.byref(process_id),
        )
        records.append(
            {
                "title": title,
                "visible": bool(USER32.IsWindowVisible(hwnd)),
                "minimized": bool(USER32.IsIconic(hwnd)),
                "process_id": int(process_id.value),
                "process_name": process_names.get(
                    int(process_id.value),
                    "unknown",
                ),
            }
        )
        return True

    USER32.EnumWindows(callback, 0)
    return records


def _workstation_locked() -> bool:
    hdesk = USER32.OpenInputDesktop(0, False, 0x0001)
    if not hdesk:
        return True
    try:
        needed = wintypes.DWORD()
        USER32.GetUserObjectInformationW(
            hdesk,
            2,
            None,
            0,
            ctypes.byref(needed),
        )
        if needed.value == 0:
            return True
        buffer = ctypes.create_unicode_buffer(needed.value // 2 + 1)
        success = USER32.GetUserObjectInformationW(
            hdesk,
            2,
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(needed),
        )
        if not success:
            return True
        return buffer.value.lower() not in {"default"}
    finally:
        USER32.CloseDesktop(hdesk)


def snapshot_windows_state() -> dict[str, Any]:
    if os.name != "nt":
        return {
            "platform": os.name,
            "workstation_locked": None,
            "wechat_process_count": None,
            "wechat_appex_count": None,
            "wechat_windows": [],
        }

    names = _process_names()
    lowered = [name.lower() for name in names.values()]
    windows = _window_records(names)
    logon_ui_running = lowered.count("logonui.exe") > 0
    main_windows = [
        item
        for item in windows
        if item["process_name"].lower() == "weixin.exe"
        and item["title"] == "微信"
    ]
    return {
        "platform": "windows",
        "workstation_locked": _workstation_locked() or logon_ui_running,
        "logon_ui_running": logon_ui_running,
        "wechat_process_count": lowered.count("weixin.exe"),
        "wechat_appex_count": lowered.count("wechatappex.exe"),
        "wechat_windows": windows,
        "wechat_main_visible": any(
            item["visible"] and not item["minimized"]
            for item in main_windows
        ),
        "wechat_main_minimized": any(
            item["minimized"] for item in main_windows
        ),
    }
