"""락업 해제 이벤트를 수집해 events.json / lockup.ics / README.md 를 갱신한다."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from lockup_lib import LockupEvent, collect_events

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def build_ics(events: list[LockupEvent], generated_at: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ipo-lockup-calendar//KR",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:IPO 락업 해제",
        "X-WR-TIMEZONE:Asia/Seoul",
    ]
    stamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    for event in events:
        release = date.fromisoformat(event.release_date)
        summary = f"🔓 {event.company} {event.period} 락업해제 ({event.ratio_pct:.1f}%)"
        description = (
            f"상장일 {event.listing_date} + {event.period} 확약 만료\\n"
            f"해제 지분율: 공모 후 {event.ratio_pct:.2f}%\\n"
            f"매도 가능(추정): {event.tradable_date}"
        )
        uid = f"{event.company}-{event.listing_date}-{event.period}@ipo-lockup-calendar"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{release.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(release + timedelta(days=1)).strftime('%Y%m%d')}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def build_readme(events: list[LockupEvent], generated_at: datetime) -> str:
    today = generated_at.astimezone(KST).date()
    upcoming = [e for e in events if today <= date.fromisoformat(e.release_date) <= today + timedelta(days=30)]
    lines = [
        "# IPO 락업(의무보유확약) 해제 캘린더",
        "",
        "국내 신규상장 종목의 기간별 확약 해제 일정을 매일 자동 갱신합니다.",
        "",
        "**구글캘린더 구독**: 캘린더 → 다른 캘린더 추가 → URL로 추가 →",
        "`https://raw.githubusercontent.com/jjh0796-svg/ipo-lockup-calendar/main/lockup.ics`",
        "",
        f"_마지막 갱신: {generated_at.astimezone(KST).strftime('%Y-%m-%d %H:%M KST')}_",
        "",
        "## 향후 30일 해제 일정",
        "",
        "| 해제일 | 종목 | 기간 | 해제 지분율 | 상장일 |",
        "|--------|------|------|------------|--------|",
    ]
    for event in upcoming:
        release = date.fromisoformat(event.release_date)
        label = f"{release.strftime('%m/%d')}({WEEKDAYS[release.weekday()]})"
        lines.append(
            f"| {label} | {event.company} | {event.period} | {event.ratio_pct:.2f}% | {event.listing_date} |"
        )
    if not upcoming:
        lines.append("| - | 30일 이내 해제 예정 없음 | | | |")
    lines.extend(
        [
            "",
            "- 해제일 = 상장일 + 확약기간 (달력 기준). 주말이면 다음 평일부터 매도 가능.",
            "- 출처: ipostock.co.kr 공개 페이지. 개인 투자 참고용이며 정확성을 보장하지 않습니다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    generated_at = datetime.now(timezone.utc)
    today = generated_at.astimezone(KST).date()
    years = sorted({today.year, (today - timedelta(days=250)).year})
    events = collect_events(
        years,
        min_release=today - timedelta(days=7),
        max_release=today + timedelta(days=250),
    )
    (ROOT / "events.json").write_text(
        json.dumps([e.to_dict() for e in events], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (ROOT / "lockup.ics").write_text(build_ics(events, generated_at), encoding="utf-8")
    (ROOT / "README.md").write_text(build_readme(events, generated_at), encoding="utf-8")
    print(f"events: {len(events)}")


if __name__ == "__main__":
    main()
