# tests/test_clean.py
from src.ashare.clean import clean_html, empty_if_dash, normalize_number, normalize_date, extract_ascii

def test_clean_html_strips_link():
    assert clean_html("<a href='http://x'><u>平安银行</u></a>") == "平安银行"

def test_clean_html_plain_text_untouched():
    assert clean_html("万  科Ａ") == "万  科Ａ"

def test_empty_if_dash():
    assert empty_if_dash("-") == "" and empty_if_dash(None) == "" and empty_if_dash("  ") == ""
    assert empty_if_dash(" 900942 ") == "900942"

def test_normalize_number():
    assert normalize_number("363,558.55") == 363558.55
    assert normalize_number("27,816.47") == 27816.47
    assert normalize_number("-") is None and normalize_number("") is None and normalize_number(None) is None
    assert normalize_number(194.05) == 194.05

def test_normalize_date_formats():
    assert normalize_date("20210525") == "2021-05-25"
    assert normalize_date("1991-04-03") == "1991-04-03"
    assert normalize_date("2021-05-25 00:00:00") == "2021-05-25"
    assert normalize_date("-") == "" and normalize_date(None) == ""

def test_extract_ascii_url_with_chinese():
    assert extract_ascii("www.szwuye.com.cn　客服电话") == "www.szwuye.com.cn"
