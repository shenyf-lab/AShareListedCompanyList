"""统一 HTTP 客户端：浏览器伪装头、请求限速、失败重试与 JSONP 剥壳。

本模块只关注 HTTP 层，不含任何业务解析逻辑。
"""

import json
import re
import time
from pathlib import Path
from typing import Any

import requests

# Chrome 稳定版 UA（所有请求统一伪装浏览器）
CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# JSONP 包装形如 任意回调名( ... );
_JSONP_HEAD = re.compile(r"^\s*[A-Za-z_$][\w$]*\(")
_JSONP_TAIL = re.compile(r"\)\s*;?\s*$", re.DOTALL)


def strip_jsonp(text: str) -> str:
    """剥掉 ``任意回调名(...);`` 包装，返回纯 JSON 文本；输入已是纯 JSON 则原样返回。"""
    text = _JSONP_HEAD.sub("", text, count=1)
    return _JSONP_TAIL.sub("", text, count=1)


class HttpClient:
    """带浏览器伪装头、限速与重试的 GET 客户端。

    - 固定头：Chrome UA + Referer，可叠加 extra_headers（如深交所的 x-requested-with）
    - 每次请求后 sleep(min_interval)，保证请求间隔 >= min_interval
    - Timeout / ConnectionError / HTTP 4xx 5xx（HTTPError）重试，耗尽抛 RuntimeError
    """

    def __init__(
        self,
        referer: str,
        extra_headers: dict | None = None,
        min_interval: float = 0.3,
        retries: int = 3,
        timeout: float = 10,
    ) -> None:
        self.referer = referer
        self.min_interval = min_interval
        self.retries = retries
        self.timeout = timeout
        self.headers = {"User-Agent": CHROME_UA, "Referer": referer}
        if extra_headers:
            self.headers.update(extra_headers)

    def _get(
        self, url: str, params: dict | None = None, stream: bool = False
    ) -> requests.Response:
        """模块级 requests.get 的包装：重试 + 限速；重试耗尽抛 RuntimeError。"""
        last_exc: Exception | None = None
        for _ in range(self.retries):
            try:
                resp = requests.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=self.timeout,
                    stream=stream,
                )
                resp.raise_for_status()  # 4xx/5xx 视为失败，进入重试
                return resp
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
                last_exc = exc
            finally:
                # 每次请求（无论成败）后限速，保证相邻请求间隔 >= min_interval
                time.sleep(self.min_interval)
        raise RuntimeError(f"{url} 重试 {self.retries} 次失败") from last_exc

    def get_json(self, url: str, params: dict | None = None) -> Any:
        """GET 并解析纯 JSON 响应（深交所用）。"""
        return self._get(url, params).json()

    def get_jsonp(self, url: str, params: dict | None = None) -> Any:
        """GET 并解析 JSONP 响应（上交所用）。"""
        return json.loads(strip_jsonp(self._get(url, params).text))

    def download(self, url: str, dest: Path, params: dict | None = None) -> Path:
        """流式下载二进制文件到 dest（上交所统计 xlsx 用），返回 dest。"""
        dest = Path(dest)
        resp = self._get(url, params, stream=True)
        try:
            with dest.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
        finally:
            resp.close()
        return dest
