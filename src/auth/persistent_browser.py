from __future__ import annotations

import contextlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator, Mapping

import requests
import websocket


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "data" / "chrome_auth_profile"
LOGIN_URL = "https://xdty.xmu.edu.cn/"
DETAIL_URL = (
    "https://xdty.xmu.edu.cn/"
    "bdlp_h5_fitness_test/view/stadium/"
    "detail.html?id=16&category_id=8"
)
DETAILS_API_URL = (
    "https://xdty.xmu.edu.cn/"
    "bdlp_h5_fitness_test/public/index.php/"
    "index/Stadium/getStadiumDetails"
)


class PersistentBrowserError(Exception):
    """Raised when the persistent browser session cannot be used."""


def chrome_executable() -> str:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    for executable in ("chrome", "msedge"):
        found = shutil.which(executable)
        if found:
            return found
    raise PersistentBrowserError("未找到 Chrome 或 Edge")


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CdpClient:
    def __init__(self, websocket_url: str) -> None:
        self.ws = websocket.create_connection(
            websocket_url,
            timeout=10,
            origin="http://127.0.0.1",
        )
        self._next_id = 0

    def command(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float = 20,
    ) -> dict[str, Any]:
        self._next_id += 1
        message_id = self._next_id
        self.ws.send(
            json.dumps(
                {
                    "id": message_id,
                    "method": method,
                    "params": dict(params or {}),
                }
            )
        )
        self.ws.settimeout(timeout)
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == message_id:
                if "error" in message:
                    raise PersistentBrowserError(
                        f"Chrome DevTools 命令失败: {method}"
                    )
                return message.get("result", {})

    def evaluate(
        self,
        expression: str,
        *,
        timeout: float = 20,
    ) -> Any:
        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            raise PersistentBrowserError("浏览器页面脚本执行失败")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


class BrowserApiResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.status_code = int(payload.get("status", 0))
        self.headers = dict(payload.get("headers") or {})
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        value = self._payload.get("json")
        if value is None:
            raise ValueError("响应不是 JSON")
        return value


class BrowserRequestSession:
    """Requests-like adapter executed inside an authenticated Chrome page."""

    def __init__(self, page: CdpClient) -> None:
        self.page = page
        self.headers: dict[str, str] = {}

    def post(
        self,
        url: str,
        *,
        data: Mapping[str, Any] | None = None,
        timeout: float = 15.0,
        allow_redirects: bool = True,
    ) -> BrowserApiResponse:
        body = urllib.parse.urlencode(
            {
                str(key): str(value)
                for key, value in (data or {}).items()
                if value is not None
            }
        )
        url_json = json.dumps(url)
        body_json = json.dumps(body)
        expression = f"""
        (async () => {{
          try {{
            const response = await fetch({url_json}, {{
              method: "POST",
              credentials: "include",
              redirect: {json.dumps("follow" if allow_redirects else "manual")},
              headers: {{
                "Content-Type":
                  "application/x-www-form-urlencoded; charset=UTF-8"
              }},
              body: {body_json}
            }});
            const text = await response.text();
            let jsonValue = null;
            try {{ jsonValue = JSON.parse(text); }} catch (_) {{}}
            return {{
              status: response.status,
              headers: {{"content-type":
                response.headers.get("content-type") || ""}},
              json: jsonValue,
              text: text.slice(0, 2000)
            }};
          }} catch (error) {{
            return {{
              status: 0,
              headers: {{}},
              json: null,
              text: String(error)
            }};
          }}
        }})()
        """
        payload = self.page.evaluate(expression, timeout=timeout)
        if not isinstance(payload, dict) or int(payload.get("status", 0)) <= 0:
            raise requests.ConnectionError("浏览器会话请求失败")
        return BrowserApiResponse(payload)

    def navigate(self, url: str, *, timeout: float = 20) -> None:
        self.page.command("Page.navigate", {"url": url}, timeout=timeout)

    def wait_for_timeout(self, milliseconds: int) -> None:
        time.sleep(max(milliseconds, 0) / 1000)

    def is_logged_in(self, *, timeout: float = 15.0) -> bool:
        try:
            response = self.post(
                DETAILS_API_URL,
                data={"id": 16},
                timeout=timeout,
            )
            payload = response.json()
        except Exception:
            return False
        return (
            isinstance(payload, dict)
            and int(payload.get("status", 0)) == 1
            and isinstance(payload.get("data"), dict)
        )


class ChromeCdpProcess:
    def __init__(
        self,
        *,
        profile_dir: Path,
        headless: bool,
        start_url: str,
    ) -> None:
        self.profile_dir = profile_dir
        self.headless = headless
        self.start_url = start_url
        self.port = _available_port()
        self.process: subprocess.Popen | None = None
        self.client: CdpClient | None = None

    def _devtools_url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _wait_for_devtools(self, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                    self._devtools_url("/json/version"),
                    timeout=1,
                ) as response:
                    if response.status == 200:
                        return
            except Exception:
                time.sleep(0.25)
        raise PersistentBrowserError("Chrome DevTools 调试端口未就绪")

    def _page_websocket(self) -> str:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            with urllib.request.urlopen(
                self._devtools_url("/json/list"),
                timeout=2,
            ) as response:
                pages = json.load(response)
            for item in pages:
                if item.get("type") == "page":
                    return str(item["webSocketDebuggerUrl"])
            time.sleep(0.25)
        raise PersistentBrowserError("未找到 Chrome 页面调试目标")

    def start(self) -> BrowserRequestSession:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        command = [
            chrome_executable(),
            f"--remote-debugging-port={self.port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--disable-save-password-bubble",
            self.start_url,
        ]
        if self.headless:
            command.insert(1, "--headless=new")
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt" and self.headless
            else 0
        )
        try:
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise PersistentBrowserError("无法启动 Chrome") from exc
        self._wait_for_devtools()
        self.client = CdpClient(self._page_websocket())
        return BrowserRequestSession(self.client)

    def close(self) -> None:
        if self.client is not None:
            try:
                self.client.command("Browser.close", timeout=5)
            except Exception:
                pass
            self.client.close()
        if self.process is not None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    self.process.terminate()
                    self.process.wait(timeout=3)
                except Exception:
                    try:
                        self.process.kill()
                    except Exception:
                        pass


@contextlib.contextmanager
def open_persistent_browser(
    *,
    profile_dir: Path | str = DEFAULT_PROFILE_DIR,
    headless: bool,
) -> Iterator[BrowserRequestSession]:
    process = ChromeCdpProcess(
        profile_dir=Path(profile_dir),
        headless=headless,
        start_url=LOGIN_URL,
    )
    try:
        yield process.start()
    finally:
        process.close()
