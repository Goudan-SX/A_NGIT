"""Windows 单实例互斥量：托盘只允许一个进程。"""
from __future__ import annotations

import ctypes

TRAY_MUTEX = "Local\\GuardianAI-Tray-Singleton"
_SYNCHRONIZE = 0x00100000
_ERROR_ALREADY_EXISTS = 183


def exists(name: str = TRAY_MUTEX) -> bool:
    try:
        handle = ctypes.windll.kernel32.OpenMutexW(_SYNCHRONIZE, False, name)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def acquire(name: str = TRAY_MUTEX):
    """成功返回保持引用的句柄；已有实例返回 None。"""
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, True, name)
        if not handle:
            return None
        if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            ctypes.windll.kernel32.CloseHandle(handle)
            return None
        return handle
    except Exception:  # noqa: BLE001
        return None
