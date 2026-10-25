"""btc_signals.py 규칙으로 새 신호를 찾아 텔레그램으로 보낸다.

GitHub Actions가 5분마다 실행한다. 환경변수:
  TELEGRAM_TOKEN    봇 토큰 (없으면 메시지를 보내지 않고 화면에만 출력)
  TELEGRAM_CHAT_ID  받을 채팅 id (없으면 봇에게 최근 24시간 안에 말을 건 채팅을 찾아 사용)
보낸 신호와 하루 한 번 상태 알림 기록은 state.json에 남겨 같은 알림을 두 번 보내지 않는다.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import btc_signals as bs

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
KST = 9 * 3600
CANDLES = {"5m": 1000, "15m": 1000, "1H": 1000, "4H": 1000, "1D": 400}
# 실행이 늦어져도 놓치지 않도록, 이 시간 안에 마감된 봉까지 거슬러 확인 (봉 길이의 2배와 60분 중 큰 값)
LOOKBACK_MS = {tf: max(2 * ms, 3.6e6) for tf, ms in bs.TF_MS.items()}
HEARTBEAT_HOUR_KST = 9
NAMES = {1: "상승", -1: "하락", 0: "횡보"}


def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sent": [], "heartbeat": ""}


def save_state(st):
    st["sent"] = st["sent"][-500:]
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def telegram(method, **params):
    token = os.environ["TELEGRAM_TOKEN"]
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=15) as r:
        d = json.load(r)
    if not d.get("ok"):
        raise RuntimeError(f"텔레그램 오류: {d.get('description')}")
    return d["result"]


def find_chat_id():
    # 공개 저장소에 남지 않도록 채팅 id는 state.json에 저장하지 않는다
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if cid:
        return cid
    updates = telegram("getUpdates")
    chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
    if not chats:
        sys.exit("받을 채팅을 못 찾았습니다. TELEGRAM_CHAT_ID를 등록하거나, 내 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
    return chats[-1]


def send(st, text):
    if not os.environ.get("TELEGRAM_TOKEN"):
        print("[미리보기]\n" + text + "\n")
        return
    telegram("sendMessage", chat_id=find_chat_id(), text=text)


def kst(ts_ms, fmt="%m/%d %H:%M"):
    return time.strftime(fmt, time.gmtime(ts_ms / 1000 + KST))


def signal_message(style, tf, kind, why, d, ind, k, now_ms):
    e, s, t1, t2 = bs.levels(ind, k, d)
    stop_pct = abs(e - s) / e
    close_ms = ind["ts"][k] + bs.TF_MS[tf]
    delay_min = max(0, (now_ms - close_ms) / 60000)
    lev_lines = []
    for lev in (10, 20, 50):
        ok = stop_pct < bs.liq_distance(lev) * 0.8
        lev_lines.append(f"{lev}배 {'안전' if ok else '손절 전 청산 위험'}")
    return "\n".join([
        f"{'🟢' if d == 1 else '🔴'} {style} {'롱' if d == 1 else '숏'} 신호 ({tf})",
        kind,
        f"진입 {e:,.1f}",
        f"손절 {s:,.1f} ({stop_pct * 100:.2f}%)",
        f"1차 익절 {t1:,.1f} · 2차 익절 {t2:,.1f}",
        " · ".join(lev_lines),
        f"봉 마감 {kst(close_ms)} · {delay_min:.0f}분 지연",
        f"근거: {why}",
        "※ 참고용. 백테스트에서 손실이었던 규칙입니다.",
    ])


EV_NAME = {"t1": "1차 익절 도달", "t2": "2차 익절 도달", "stop": "손절 도달"}


def trade_path(ind, k, d, lv, end):
    """신호 k 이후 손절·1차 익절·2차 익절에 처음 닿은 봉. 같은 봉이면 손절 먼저(보수적)."""
    entry, stop, t1, t2 = lv
    ev, t1_hit = [], False
    for m in range(k + 1, end + 1):
        hit_stop = ind["l"][m] <= stop if d == 1 else ind["h"][m] >= stop
        hit_t1 = ind["h"][m] >= t1 if d == 1 else ind["l"][m] <= t1
        hit_t2 = ind["h"][m] >= t2 if d == 1 else ind["l"][m] <= t2
        if hit_stop:
            ev.append((m, "stop"))
            break
        if not t1_hit and hit_t1:
            t1_hit = True
            ev.append((m, "t1"))
        if hit_t2:
            ev.append((m, "t2"))
            break
    return ev


def event_message(style, tf, d, ev, lv, sig_ms, ev_ms):
    entry, stop, t1, t2 = lv
    price = {"stop": stop, "t1": t1, "t2": t2}[ev]
    move = (price - entry) / entry * 100 * d
    return "\n".join([
        f"{'❌' if ev == 'stop' else '💰'} {style} {'롱' if d == 1 else '숏'} · {EV_NAME[ev]}",
        f"{price:,.1f} 도달 ({move:+.2f}%)",
        f"진입 {entry:,.1f} · 손절 {stop:,.1f}",
        f"1차 익절 {t1:,.1f} · 2차 익절 {t2:,.1f}",
        f"신호 {kst(sig_ms)} · 도달한 봉 {kst(ev_ms)}",
    ])


def main():
    st = load_state()
    now_ms = time.time() * 1000
    cache = {tf: bs.candles(tf, n) for tf, n in CANDLES.items()}
    inds = {tf: bs.indicators(cs) for tf, cs in cache.items()}
    for tf, cs in cache.items():
        inds[tf]["ts"] = [r[0] for r in cs]

    sent_any = False
    for style, (tf, htf) in bs.STYLES.items():
        ind, hind = inds[tf], inds[htf]
        hmap = bs.map_htf(ind["ts"], hind["ts"], bs.TF_MS[tf], bs.TF_MS[htf])
        last = len(ind["c"]) - 2  # 마지막으로 마감된 봉
        for k in range(max(211, last - 30), last + 1):
            close_ms = ind["ts"][k] + bs.TF_MS[tf]
            if now_ms - close_ms > LOOKBACK_MS[tf]:
                continue
            j = hmap[k]
            d, kind, why = bs.signal_at(ind, k, bs.trend(hind, j) if j is not None and j >= 200 else 0)
            key = f"{style}|{ind['ts'][k]}"
            if d and key not in st["sent"]:
                send(st, signal_message(style, tf, kind, why, d, ind, k, now_ms))
                st["sent"].append(key)
                sent_any = True

        # 최근 48봉 안의 신호가 손절·익절에 닿았는지 (진행 중인 봉의 고가·저가까지 확인)
        live = len(ind["c"]) - 1
        for k in range(max(211, last - 48), last + 1):
            j = hmap[k]
            d, _, _ = bs.signal_at(ind, k, bs.trend(hind, j) if j is not None and j >= 200 else 0)
            if not d:
                continue
            lv = bs.levels(ind, k, d)
            for m, ev in trade_path(ind, k, d, lv, live):
                key = f"{style}|{ind['ts'][k]}|{ev}"
                if key in st["sent"]:
                    continue
                if now_ms - (ind["ts"][m] + bs.TF_MS[tf]) > LOOKBACK_MS[tf]:
                    st["sent"].append(key)  # 오래전에 닿은 것은 보내지 않고 기록만
                    continue
                send(st, event_message(style, tf, d, ev, lv, ind["ts"][k] + bs.TF_MS[tf], ind["ts"][m]))
                st["sent"].append(key)
                sent_any = True

    today = kst(now_ms, "%Y-%m-%d")
    hour = int(kst(now_ms, "%H"))
    if st.get("heartbeat") != today and hour >= HEARTBEAT_HOUR_KST:
        price = cache["5m"][-1][4]
        lines = [f"✅ 신호 알림 작동 중 · {kst(now_ms)}", f"현재가 {price:,.1f}"]
        for tf in ["15m", "1H", "4H", "1D"]:
            lines.append(f"{tf} {NAMES[bs.trend(inds[tf], len(inds[tf]['c']) - 2)]}")
        send(st, "\n".join(lines))
        st["heartbeat"] = today
        sent_any = True

    save_state(st)
    print(f"{kst(now_ms)} 확인 완료 · 새 알림 {'있음' if sent_any else '없음'}")


if __name__ == "__main__":
    main()
