# tests/test_httpclient.py
import pytest
from src.ashare.httpclient import strip_jsonp, HttpClient

def test_strip_jsonp_random_callback_name():
    text = 'jsonpCallback98088922({"pageHelp": {"total": 2359}});'
    assert strip_jsonp(text) == '{"pageHelp": {"total": 2359}}'

def test_strip_jsonp_plain_json_untouched():
    text = '[{"metadata": {"catalogid": "1110"}}]'
    assert strip_jsonp(text) == text

def test_get_jsonp_parses_response(monkeypatch):
    calls = []
    class FakeResp:
        text = 'cb123({"result": [{"A": 1}]});'
        def raise_for_status(self): pass
        def json(self): raise AssertionError("should not be called")
    def fake_get(url, **kw):
        calls.append(url); return FakeResp()
    monkeypatch.setattr("src.ashare.httpclient.requests.get", fake_get)
    c = HttpClient(referer="http://www.sse.com.cn/", min_interval=0)
    assert c.get_jsonp("http://q/x.do") == {"result": [{"A": 1}]}
    assert "http://q/x.do" in calls[0]

def test_get_sends_referer_and_extra_headers(monkeypatch):
    seen = {}
    class FakeResp:
        text = '{}'; encoding = 'utf-8'
        def raise_for_status(self): pass
        def json(self): return {}
    def fake_get(url, headers=None, **kw):
        seen['headers'] = headers; return FakeResp()
    monkeypatch.setattr("src.ashare.httpclient.requests.get", fake_get)
    HttpClient(referer="http://www.szse.cn/", extra_headers={"x-requested-with": "XMLHttpRequest"}, min_interval=0).get_json("http://s/x")
    assert seen['headers']['Referer'] == "http://www.szse.cn/"
    assert seen['headers']['x-requested-with'] == "XMLHttpRequest"

def test_retry_exhausted_raises(monkeypatch):
    import requests as real
    def fake_get(url, **kw): raise real.exceptions.Timeout("t")
    monkeypatch.setattr("src.ashare.httpclient.requests.get", fake_get)
    with pytest.raises(RuntimeError):
        HttpClient(referer="http://x/", retries=3, min_interval=0).get_json("http://x/")

def test_retry_then_success(monkeypatch):
    from requests.exceptions import Timeout
    n = {"i": 0}
    class FakeResp:
        text = '{"ok": true}'
        def raise_for_status(self): pass
        def json(self): return {"ok": True}
    def fake_get(url, **kw):
        n["i"] += 1
        if n["i"] < 3: raise Timeout("t")
        return FakeResp()
    monkeypatch.setattr("src.ashare.httpclient.requests.get", fake_get)
    c = HttpClient(referer="http://x/", retries=3, min_interval=0)
    assert c.get_json("http://x/") == {"ok": True} and n["i"] == 3

def test_http_error_status_triggers_retry(monkeypatch):
    from requests.exceptions import HTTPError
    n = {"i": 0}
    class BadResp:
        status_code = 404
        def raise_for_status(self): raise HTTPError("404")
        def json(self): raise AssertionError("4xx 响应不应被当作成功返回")
    class GoodResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"ok": True}
    def fake_get(url, **kw):
        n["i"] += 1
        return BadResp() if n["i"] == 1 else GoodResp()
    monkeypatch.setattr("src.ashare.httpclient.requests.get", fake_get)
    c = HttpClient(referer="http://x/", retries=3, min_interval=0)
    assert c.get_json("http://x/") == {"ok": True}
    assert n["i"] == 2  # 首次 404 未被当作成功，触发了重试

def test_download_streams_to_file(monkeypatch, tmp_path):
    seen = {}
    class FakeResp:
        def raise_for_status(self):
            pass
        def iter_content(self, chunk_size=8192):
            yield b"PK\x03\x04"; yield b"tail"
        def close(self):
            pass
    def fake_get(url, **kw):
        seen.update(kw); return FakeResp()
    monkeypatch.setattr("src.ashare.httpclient.requests.get", fake_get)
    dest = tmp_path / "stat.xlsx"
    result = HttpClient(referer="http://www.sse.com.cn/", min_interval=0).download("http://q/x.xlsx", dest)
    assert result == dest
    assert dest.read_bytes() == b"PK\x03\x04tail"
    assert seen["stream"] is True
