from __future__ import annotations

from typing import Protocol


class CredentialStoreError(Exception):
    """Raised when secure credential storage is unavailable."""


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None:
        ...

    def set_password(
        self,
        service_name: str,
        username: str,
        password: str,
    ) -> None:
        ...

    def delete_password(self, service_name: str, username: str) -> None:
        ...


class BarkCredentialStore:
    SERVICE_NAME = "xmuty-gym-monitor"
    ACCOUNT_NAME = "bark-device-key"

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        if backend is None:
            try:
                import keyring
            except ImportError as exc:
                raise CredentialStoreError(
                    "缺少 keyring，无法使用 Windows 凭据管理器"
                ) from exc
            backend = keyring
        self.backend = backend

    def get_key(self) -> str | None:
        try:
            value = self.backend.get_password(
                self.SERVICE_NAME,
                self.ACCOUNT_NAME,
            )
        except Exception as exc:
            raise CredentialStoreError("读取 Bark Key 失败") from exc
        return value.strip() if value else None

    def set_key(self, value: str) -> None:
        key = value.strip()
        if not key:
            raise CredentialStoreError("Bark Key 不能为空")
        try:
            self.backend.set_password(
                self.SERVICE_NAME,
                self.ACCOUNT_NAME,
                key,
            )
        except Exception as exc:
            raise CredentialStoreError("保存 Bark Key 失败") from exc

    def delete_key(self) -> None:
        try:
            self.backend.delete_password(
                self.SERVICE_NAME,
                self.ACCOUNT_NAME,
            )
        except Exception as exc:
            name = exc.__class__.__name__.lower()
            if "notfound" not in name and "passworddeleteerror" not in name:
                raise CredentialStoreError("删除 Bark Key 失败") from exc

    def has_key(self) -> bool:
        return bool(self.get_key())
