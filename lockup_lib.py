"""IPO 의무보유확약(락업) 해제 일정 수집 라이브러리.

ipostock.co.kr의 공개 페이지에서 종목별 상장일과 기간별 확약 지분율을 수집해
해제 이벤트 목록을 만든다. 개인 투자 참고용.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

import requests
from bs4 import BeautifulSoup

LIST_URL = (
    "http://www.ipostock.co.kr/sub03/ipo08.asp"
    "?page={page}&str1=&str2=&str3=&str4={year}&str5=all"
)
DETAIL_URL = "http://www.ipostock.co.kr/view_pg/view_02.asp?code={code}&schk=3"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

PERIOD_OFFSETS = {
    "15일": ("days", 15),
    "1개월": ("months", 1),
    "2개월": ("months", 2),
    "3개월": ("months", 3),
    "6개월": ("months", 6),
}


@dataclass(slots=True)
class LockupEvent:
    company: str
    listing_date: str  # ISO
    period: str
    release_date: str  # ISO (상장일 + 확약기간)
    tradable_date: str  # ISO (주말이면 다음 평일)
    ratio_pct: float  # 공모 후 지분율 합 (%)

    def to_dict(self) -> dict:
        return asdict(self)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Referer": "http://www.ipostock.co.kr/"})
    return session


def fetch_html(session: requests.Session, url: str, sleep_seconds: float = 0.05) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    if sleep_seconds:
        time.sleep(sleep_seconds)
    return response.text


def iter_ipo_codes(session: requests.Session, years) -> list[str]:
    seen: set[str] = set()
    codes: list[str] = []
    for year in sorted(set(years)):
        for page in range(1, 40):
            html = fetch_html(session, LIST_URL.format(page=page, year=year))
            soup = BeautifulSoup(html, "html.parser")
            page_codes = []
            for anchor in soup.find_all("a", href=True):
                match = re.search(r"/view_pg/view_05\.asp\?code=([^&]+)", anchor["href"])
                if match:
                    page_codes.append(match.group(1))
            page_codes = list(dict.fromkeys(page_codes))
            if not page_codes:
                break
            new_codes = [code for code in page_codes if code not in seen]
            if not new_codes:
                break
            for code in new_codes:
                seen.add(code)
                codes.append(code)
    return codes


def _normalize_space(value) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def extract_company_name(page_text: str) -> str | None:
    match = re.search(r"기업상세정보\s+(.+?)\s+[A-Z0-9]{4,6}\s+\[상장\]", page_text)
    return _normalize_space(match.group(1)) if match else None


def extract_listing_date(page_text: str) -> date | None:
    match = re.search(r"상장일\s+(\d{4}\.\d{2}\.\d{2})", page_text)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y.%m.%d").date()


def normalize_period_label(text: str) -> str | None:
    cleaned = _normalize_space(text).replace(" ", "")
    match = re.search(r"(15일|1개월|2개월|3개월|6개월)", cleaned)
    return match.group(1) if match else None


def parse_period_ratios(soup: BeautifulSoup) -> dict[str, float]:
    """주주 보호예수 테이블에서 기간별 공모 후 지분율 합을 구한다."""
    target = None
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header = [_normalize_space(c.get_text(" ", strip=True)) for c in rows[0].find_all(["th", "td"])]
        if header[:4] == ["구 분", "보유주식", "공모 후 보통주지분율", "보호예수기간"]:
            target = table
            break
    if target is None:
        return {}
    ratios: dict[str, float] = {}
    for row in target.find_all("tr"):
        cells = [_normalize_space(c.get_text(" ", strip=True)) for c in row.find_all(["th", "td"])]
        if len(cells) == 6:
            _, _, _, _, ratio_text, period_text = cells
        elif len(cells) == 5:
            _, _, _, ratio_text, period_text = cells
        else:
            continue
        period = normalize_period_label(period_text)
        if not period:
            continue
        match = re.search(r"-?\d+(?:\.\d+)?", ratio_text.replace(",", ""))
        if not match:
            continue
        ratios[period] = ratios.get(period, 0.0) + float(match.group(0))
    return {k: round(v, 2) for k, v in ratios.items() if v > 0}


def add_months(base: date, months: int) -> date:
    month = base.month - 1 + months
    year = base.year + month // 12
    month = month % 12 + 1
    day = base.day
    while day > 28:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, day)


def release_date_for(listing: date, period: str) -> date:
    kind, amount = PERIOD_OFFSETS[period]
    if kind == "days":
        return listing + timedelta(days=amount)
    return add_months(listing, amount)


def next_weekday(value: date) -> date:
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def collect_events(years, *, min_release: date, max_release: date, session=None) -> list[LockupEvent]:
    session = session or make_session()
    events: list[LockupEvent] = []
    for code in iter_ipo_codes(session, years):
        try:
            html = fetch_html(session, DETAIL_URL.format(code=code))
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        company = extract_company_name(page_text)
        listing = extract_listing_date(page_text)
        if not company or not listing:
            continue  # 미상장 종목
        for period, ratio in parse_period_ratios(soup).items():
            release = release_date_for(listing, period)
            if not (min_release <= release <= max_release):
                continue
            events.append(
                LockupEvent(
                    company=company,
                    listing_date=listing.isoformat(),
                    period=period,
                    release_date=release.isoformat(),
                    tradable_date=next_weekday(release).isoformat(),
                    ratio_pct=ratio,
                )
            )
    events.sort(key=lambda e: (e.release_date, -e.ratio_pct, e.company))
    return events
