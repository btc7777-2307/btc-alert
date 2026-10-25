"""4시간봉 돈치안 돌파 전략(strategy.py)의 신호·추가 진입·손절 갱신·청산을 텔레그램으로 보낸다.

GitHub Actions가 몇 분~30분마다 실행한다. 매번 4시간봉으로 규칙을 처음부터 재현해 지금 포지션 상태를 구하고,
아직 보내지 않은 일만 보낸다. 환경변수:
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
import strategy as stg

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
KST = 9 * 3600
TF = "4H"
BAR_MS = bs.TF_MS[TF]
# 이보다 오래된 일은 처음 실행할 때 보내지 않고 기록만 (실행이 늦어져도 놓치지 않을 만큼 넉넉히)
LOOKBACK_MS = 3 * BAR_MS
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
    # 붙여넣을 때 섞여 들어간 빈칸·줄바꿈·"bot" 접두어는 정리
    token = "".join(os.environ["TELEGRAM_TOKEN"].split())
    if token.lower().startswith("bot") and ":" in token[3:]:
        token = token[3:]
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=15) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            sys.exit("텔레그램 토큰이 맞지 않습니다. BotFather의 토큰(숫자:영문 형태)을 전부 복사해 "
                     "GitHub의 TELEGRAM_TOKEN을 다시 등록하세요.")
        if e.code == 400 and method == "sendMessage":
            sys.exit("텔레그램 채팅 번호가 맞지 않거나, 내 봇에서 '시작'을 누르지 않았습니다.")
        raise
    if not d.get("ok"):
        raise RuntimeError(f"텔레그램 오류: {d.get('description')}")
    return d["result"]


_chat = {}


def find_chat_id():
    # 공개 저장소에 남지 않도록 채팅 id는 state.json이나 실행 기록에 남기지 않는다
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if cid:
        return cid
    if "id" not in _chat:
        # 봇에서 '시작'을 누른 지 24시간 안이면 텔레그램이 그 대화를 알려 준다
        updates = telegram("getUpdates")
        chats = [u["message"]["chat"]["id"] for u in updates if "message" in u]
        if not chats:
            sys.exit("받을 채팅을 못 찾았습니다. 텔레그램에서 내 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
        _chat["id"] = chats[-1]
        # 처음 한 번은 채팅 번호를 텔레그램으로 알려 줘서 GitHub에 등록하게 한다
        telegram("sendMessage", chat_id=_chat["id"], text=(
            f"내 채팅 번호: {_chat['id']}\n"
            "이 숫자를 GitHub 저장소 Settings → Secrets and variables → Actions에 "
            "TELEGRAM_CHAT_ID라는 이름으로 등록하세요. 등록하지 않으면 24시간 뒤부터 알림이 멈춥니다."))
    return _chat["id"]


def ensure_menu_button(st):
    """내 봇 대화방 왼쪽 아래에 '신호판' 버튼(텔레그램 안에서 대시보드 열기)을 한 번 설정한다."""
    url = os.environ.get("DASHBOARD_URL")
    if not url or not os.environ.get("TELEGRAM_TOKEN") or st.get("menu") == url:
        return
    telegram("setChatMenuButton", chat_id=find_chat_id(),
             menu_button=json.dumps({"type": "web_app", "text": "신호판", "web_app": {"url": url}}))
    st["menu"] = url


def send(st, text):
    if not os.environ.get("TELEGRAM_TOKEN"):
        print("[미리보기]\n" + text + "\n")
        return
    telegram("sendMessage", chat_id=find_chat_id(), text=text)


def kst(ts_ms, fmt="%m/%d %H:%M"):
    return time.strftime(fmt, time.gmtime(ts_ms / 1000 + KST))


DIR = {1: "롱", -1: "숏"}


def fmt(x):
    return f"{x:,.1f}"


def usdt_krw():
    """업비트 USDT 원화 시세 (실패하면 1,400원)."""
    try:
        with urllib.request.urlopen("https://api.upbit.com/v1/ticker?markets=KRW-USDT", timeout=10) as r:
            return float(json.load(r)[0]["trade_price"])
    except Exception:
        return 1400.0


def order_guide(price, stop_pct):
    """손절 시 시드의 RISK_PCT%만 잃도록 계획 물량을 잡고, 1차(40%)·추가(60%) 증거금을 안내."""
    seed = float(os.environ.get("SEED_KRW") or 200000)
    risk = float(os.environ.get("RISK_PCT") or 2) / 100
    lev = float(os.environ.get("LEVERAGE") or 30)
    fx = usdt_krw()
    loss = seed * risk
    notional = loss / stop_pct            # 계획 물량 전체(원)
    first, add = notional * stg.FIRST, notional * (1 - stg.FIRST)
    btc = lambda krw: max(0.0001, round(krw / fx / price, 4))
    liq = 1 / lev - 0.004
    lines = [
        f"주문 안내 · 시드 {seed:,.0f}원, 손절 시 {risk * 100:g}%({loss:,.0f}원)만 잃는 크기, {lev:g}배",
        f"1차: 증거금 {first / lev:,.0f}원 (시드의 {first / lev / seed * 100:.1f}%) · 수량 {btc(first):.4f} BTC",
        f"추가(1R 도달): 증거금 {add / lev:,.0f}원 (시드의 {add / lev / seed * 100:.1f}%) · 수량 {btc(add):.4f} BTC",
    ]
    if stop_pct >= liq * 0.9:
        lines.append(f"⚠ {lev:g}배는 손절({stop_pct * 100:.1f}%)보다 청산({liq * 100:.1f}%)이 먼저 올 수 있어요 → 이번엔 {max_safe_leverage(stop_pct)}배 이하로")
    return lines


def max_safe_leverage(stop_pct):
    """격리 마진에서 손절보다 청산이 먼저 오지 않는 최대 배율 (유지증거금 0.4%, 여유 20%)."""
    return max(1, int(0.8 / (stop_pct + 0.004)))


def signal_message(ind, t):
    k, d = t["sig_k"], t["d"]
    c, a = ind["c"][k], ind["atr"][k]
    lvl = max(ind["h"][k - stg.BREAK_N:k]) if d == 1 else min(ind["l"][k - stg.BREAK_N:k])
    e = t["entry"]
    risk = stg.STOP_ATR * a
    stop, add = e - d * risk, e + d * risk
    stop_pct = risk / e
    lines = [
        f"{'🟢' if d == 1 else '🔴'} 4시간봉 돌파 {DIR[d]} 신호",
        f"이유: 종가 {fmt(c)}가 직전 20봉 {'최고가' if d == 1 else '최저가'} {fmt(lvl)}를 {'넘었고' if d == 1 else '깼고'}, "
        f"EMA200 {fmt(ind['e200'][k])} {'위' if d == 1 else '아래'}",
        f"진입: {'다음 봉 시가 근처' if t['state'] == 'pending' else '봉 시가'} {fmt(e)} · 계획 물량의 40%",
        f"손절: {fmt(stop)} ({stop_pct * 100:.2f}%, ATR x2)",
        f"추가 진입: {fmt(add)} 도달 시 나머지 60%, 손절은 본전으로",
        "이후 손절은 진입 후 최고가에서 ATR x3 뒤로 따라 올라감" if d == 1 else "이후 손절은 진입 후 최저가에서 ATR x3 위로 따라 내려감",
        f"배율: 손절 {stop_pct * 100:.1f}%면 격리 기준 {max_safe_leverage(stop_pct)}배 이하여야 손절 전에 청산되지 않음",
        "",
        *order_guide(e, stop_pct),
        "※ 참고용. 주문은 직접 판단해서 하세요.",
    ]
    return "\n".join(lines)


def event_message(ind, t, kind, m, px):
    d, e, risk = t["d"], t["entry"], t["risk"]
    if kind == "add":
        g = order_guide(e, risk / e)
        return "\n".join([
            f"💰 4시간봉 돌파 {DIR[d]} · 1R 도달 {fmt(px)}",
            "추가 진입: 계획 물량의 나머지 60%",
            g[2],
            f"손절을 본전 {fmt(e)}로 올림" if d == 1 else f"손절을 본전 {fmt(e)}로 내림",
        ])
    if kind == "trail":
        locked = (px - e) * d / risk
        return "\n".join([
            f"↕ 4시간봉 돌파 {DIR[d]} · 손절가 갱신 {fmt(px)}",
            f"진입 {fmt(e)} · 이 손절에 걸려도 {locked:+.1f}R (처음 손절폭 기준)",
        ])
    if kind == "exit":
        legs = t.get("legs") or [(e, stg.FIRST)]
        r = sum(w * ((px - p) * d / risk - (stg.FEE_IN + stg.FEE_OUT) * p / risk) for p, w in legs)
        pct = sum(w * (px - p) * d / p for p, w in legs) / sum(w for _, w in legs) * 100
        return "\n".join([
            f"{'✅' if r > 0 else '❌'} 4시간봉 돌파 {DIR[d]} 청산 · {fmt(px)}",
            f"결과: {r:+.2f}R (계획 물량 기준, 수수료 포함) · 가격 {pct:+.2f}%",
            f"진입 {fmt(e)} · {'추가 진입 포함' if len(legs) > 1 else '처음 40%만'} · {m - t['entry_k'] + 1}봉 보유",
        ])
    return ""


def status_line(ind, trades):
    t = trades[-1] if trades else None
    if not t or t["state"] == "closed":
        k = len(ind["c"]) - 2
        hi, lo = max(ind["h"][k - stg.BREAK_N + 1:k + 1]), min(ind["l"][k - stg.BREAK_N + 1:k + 1])
        return f"포지션 없음 · 롱 조건 종가 > {fmt(hi)} (EMA200 {fmt(ind['e200'][k])} 위) / 숏 조건 종가 < {fmt(lo)}"
    if t["state"] == "pending":
        return f"{DIR[t['d']]} 신호 · 다음 봉 시가 진입 대기"
    now = ind["c"][-1]
    return (f"{DIR[t['d']]} 진행 중 · 진입 {fmt(t['entry'])} · 손절 {fmt(t['stop'])} · "
            f"{'추가 진입 완료' if t['added'] else '추가 진입가 ' + fmt(t['add_px'])} · 지금 {(now - t['entry']) * t['d'] / t['risk']:+.1f}R")


def main():
    if os.environ.get("GITHUB_ACTIONS") and not os.environ.get("TELEGRAM_TOKEN"):
        # 토큰 등록 전에는 아무것도 기록하지 않는다 (안 보낸 알림을 보냈다고 남기지 않도록)
        print("TELEGRAM_TOKEN이 아직 등록되지 않아 건너뜁니다.")
        return
    st = load_state()
    st.setdefault("trail_sent", {})
    now_ms = time.time() * 1000
    cs = bs.candles(TF, 1200)
    ind = bs.indicators(cs)
    ind["ts"] = [r[0] for r in cs]
    trades = stg.replay(ind, live=True)

    if os.environ.get("TEST_MESSAGE") == "true":
        st.pop("menu", None)  # 수동 실행 때는 신호판 버튼도 다시 설정
    ensure_menu_button(st)

    if os.environ.get("TEST_MESSAGE") == "true":
        # 가장 최근 거래의 신호를 지금 형식으로 다시 보내 본다
        t = next((x for x in reversed(trades) if x.get("events")), None)
        send(st, f"🔔 테스트 알림 · {kst(now_ms)}\n" + (
            "아래는 최근 신호를 지금 형식으로 다시 보낸 예시입니다.\n\n" + signal_message(ind, t) + "\n\n지금 상태: " + status_line(ind, trades)
            if t else "이 메시지가 보이면 알림 설정이 끝난 것입니다."))

    sent_any = False
    for t in trades[-3:]:
        sig_ts = ind["ts"][t["sig_k"]]
        tkey = str(sig_ts)
        for kind, m, px in t["events"]:
            if kind == "entry":
                continue
            bar_ts = ind["ts"][m]
            key = f"{kind}|{sig_ts}|{bar_ts}"
            if key in st["sent"]:
                continue
            # 봉이 끝나는 시각(진행 중인 봉이면 지금) 기준으로 오래된 일은 기록만
            when = min(bar_ts + BAR_MS, now_ms)
            if now_ms - when > LOOKBACK_MS:
                st["sent"].append(key)
                if kind == "trail":
                    st["trail_sent"][tkey] = px
                continue
            if kind == "trail":
                # 손절가는 마감된 봉마다 조금씩 움직이므로, 처음 손절폭의 1/4 이상 움직였을 때만 알림
                last = st["trail_sent"].get(tkey, t["entry"] - t["d"] * t["risk"])
                if abs(px - last) < 0.25 * t["risk"]:
                    st["sent"].append(key)
                    continue
                st["trail_sent"][tkey] = px
            text = signal_message(ind, t) if kind == "signal" else event_message(ind, t, kind, m, px)
            send(st, text)
            st["sent"].append(key)
            sent_any = True

    today = kst(now_ms, "%Y-%m-%d")
    if st.get("heartbeat") != today and int(kst(now_ms, "%H")) >= HEARTBEAT_HOUR_KST:
        lines = [f"✅ 신호 알림 작동 중 · {kst(now_ms)}", f"현재가 {fmt(cs[-1][4])}", status_line(ind, trades)]
        if os.environ.get("DASHBOARD_URL"):
            lines.append(f"신호판: {os.environ['DASHBOARD_URL']}")
        send(st, "\n".join(lines))
        st["heartbeat"] = today
        sent_any = True

    st["trail_sent"] = dict(list(st["trail_sent"].items())[-20:])
    save_state(st)
    print(f"{kst(now_ms)} 확인 완료 · 새 알림 {'있음' if sent_any else '없음'} · {status_line(ind, trades)}")


if __name__ == "__main__":
    main()
