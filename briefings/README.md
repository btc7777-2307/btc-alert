# 아침 경제 브리핑

매일 05:30(한국시간) Claude 예약된 작업이 웹 검색으로 최신 데이터를 확인해 이 폴더에 씁니다.
GitHub 알림 실행(5분마다)이 새 브리핑을 찾아 텔레그램으로 보냅니다 (`send_briefing.py`).
신호 알림과 신호판은 `latest.json`의 오늘 일정·위험 요인을 함께 보여 줍니다.

## 파일
- `YYYY-MM-DD.json` — 그날 브리핑
- `latest.json` — 가장 최근 브리핑 (같은 내용)

## latest.json 형식
```json
{
  "date": "2026-10-26",
  "written_at": "2026-10-26T05:42:00+09:00",
  "text": "텔레그램으로 보낼 본문 (3분 분량, 3,800자 이하)",
  "summary": "한 줄 요약",
  "indices": [{"name": "S&P500", "pct": 0.52}, {"name": "NASDAQ", "pct": 0.80}, {"name": "DOW", "pct": 0.10},
              {"name": "KOSPI", "pct": -0.3}, {"name": "KOSDAQ", "pct": 0.4}],
  "macro": [{"name": "USD/KRW", "value": 1342.0, "pct": 0.1}, {"name": "US10Y", "value": 4.12, "pct": null},
            {"name": "WTI", "value": 61.2, "pct": -1.0}, {"name": "Gold", "value": 4100, "pct": 0.3}],
  "crypto_view": {"bias": "중립", "reason": "단기 견해 근거", "invalidate": "이 견해가 틀렸다고 볼 조건"},
  "risks": ["오늘 차트 볼 때 조심할 점"],
  "events": [{"time_kst": "2026-10-26T21:30:00+09:00", "name": "미국 9월 CPI", "importance": "high"}],
  "sources": ["https://..."]
}
```
확인 못 한 숫자는 `null`로 두고 본문에 "확인 불가"라고 씁니다.
