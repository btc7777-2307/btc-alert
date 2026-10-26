"""briefings/latest.json(아침 경제 브리핑)을 텔레그램으로 보낸다. 하루에 한 번.

GitHub 알림 실행(5분마다)에서 btc_notify.py 앞에 실행된다.
그림 2장: ① 증시 등락률 막대 ② 비트코인 7일 가격(4시간봉, 비트겟). QuickChart(quickchart.io)가 그림을 그려 준다.
보낸 날짜는 state.json의 briefing_sent에 남겨 같은 브리핑을 두 번 보내지 않는다.
"""
import json
import os
import time
import urllib.parse

import btc_signals as bs
import btc_notify as bn

HERE = os.path.dirname(os.path.abspath(__file__))
LATEST = os.path.join(HERE, "briefings", "latest.json")


def chart_url(config, w=640, h=360):
    c = urllib.parse.quote(json.dumps(config, separators=(",", ":")))
    return f"https://quickchart.io/chart?w={w}&h={h}&bkg=white&c={c}"


def indices_chart(b):
    rows = [r for r in b.get("indices", []) if isinstance(r.get("pct"), (int, float))]
    if not rows:
        return None
    return chart_url({
        "type": "bar",
        "data": {"labels": [r["name"] for r in rows],
                 "datasets": [{"label": "%", "data": [round(r["pct"], 2) for r in rows],
                               "backgroundColor": ["#13896b" if r["pct"] >= 0 else "#cf4436" for r in rows]}]},
        "options": {"legend": {"display": False},
                    "title": {"display": True, "text": f"Stock indices daily change (%) - {b['date']}"},
                    "plugins": {"datalabels": {"display": True, "anchor": "end", "align": "end"}}},
    })


def btc_chart():
    cs = bs.candles("4H", 42)  # 7일
    labels = [time.strftime("%m/%d %H", time.gmtime(r[0] / 1000 + 9 * 3600)) for r in cs]
    closes = [round(r[4]) for r in cs]
    chg = (closes[-1] / closes[0] - 1) * 100
    return chart_url({
        "type": "line",
        "data": {"labels": labels, "datasets": [{"label": "BTCUSDT", "data": closes, "fill": False, "pointRadius": 0,
                                                 "borderColor": "#2f66c4", "borderWidth": 2}]},
        "options": {"legend": {"display": False},
                    "title": {"display": True, "text": f"BTCUSDT perp 7 days (4H close) {closes[-1]:,} ({chg:+.1f}%)"},
                    "scales": {"xAxes": [{"ticks": {"maxTicksLimit": 7}}]}},
    })


def split(text, n=3900):
    """텔레그램 한 메시지 4,096자 제한에 맞춰 문단 단위로 나눔."""
    parts, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > n and cur:
            parts.append(cur)
            cur = ""
        cur = (cur + "\n\n" + para) if cur else para
    if cur:
        parts.append(cur)
    return parts


def main():
    try:
        b = json.load(open(LATEST))
    except (FileNotFoundError, json.JSONDecodeError):
        print("브리핑 없음")
        return
    today = bn.kst(time.time() * 1000, "%Y-%m-%d")
    st = bn.load_state()
    if b.get("date") != today or st.get("briefing_sent") == today:
        print("보낼 브리핑 없음")
        return
    photos = [u for u in (indices_chart(b), btc_chart()) if u]
    if not os.environ.get("TELEGRAM_TOKEN"):
        print("[미리보기] 그림:", *photos, sep="\n")
        for p in split(b["text"]):
            print("[미리보기]\n" + p)
        return
    chat = bn.find_chat_id()
    if photos:
        try:
            bn.telegram("sendMediaGroup", chat_id=chat,
                        media=json.dumps([{"type": "photo", "media": u} for u in photos]))
        except Exception as e:  # 그림이 안 가도 글은 보낸다
            print("그림 전송 실패:", e)
    for p in split(b["text"]):
        bn.telegram("sendMessage", chat_id=chat, text=p, disable_web_page_preview="true")
    st["briefing_sent"] = today
    bn.save_state(st)
    print("브리핑 전송 완료", today)


if __name__ == "__main__":
    main()
