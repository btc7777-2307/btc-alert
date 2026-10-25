"""4시간봉 돈치안 돌파 전략 (신호판 index.html 과 같은 규칙).

진입  4시간봉 종가가 직전 20봉 최고가를 넘고 EMA200 위 → 롱 / 20봉 최저가를 깨고 EMA200 아래 → 숏.
      다음 봉 시가에 계획 물량의 40%로 진입.
손절  처음: 진입가 ∓ ATR(14) x 2. 이후 마감된 봉마다 (진입 후 최고가 - ATR x 3)으로 올림 (숏은 반대).
추가  가격이 1R(처음 손절폭만큼) 유리하게 가면 나머지 60% 추가, 손절은 최소 본전.
청산  손절(추적 손절)에 닿을 때. 익절 목표는 따로 없음 (추세를 끝까지 따라감).
검증  비트겟 선물 2022-01~2026-10: 255회, 연도별 모두 플러스, 최대 낙폭 7.1R (수수료 포함).
"""
BREAK_N = 20
STOP_ATR = 2.0
TRAIL_ATR = 3.0
FIRST = 0.4          # 처음 진입 비중
FEE_IN, FEE_OUT = 0.0002, 0.0006


def signal(ind, k):
    """마감된 봉 k에서의 진입 신호: 1 롱 / -1 숏 / 0."""
    if k < max(210, BREAK_N):
        return 0
    c = ind["c"][k]
    if c > max(ind["h"][k - BREAK_N:k]) and c > ind["e200"][k]:
        return 1
    if c < min(ind["l"][k - BREAK_N:k]) and c < ind["e200"][k]:
        return -1
    return 0


def replay(ind, start_k=210, live=True):
    """처음부터 규칙대로 거래를 재현. live=True면 마지막 봉은 진행 중으로 보고 손절·추가 판정만 한다.

    반환: 거래 목록. 각 거래는 d, sig_k, entry_k, entry, risk, stop, add_px, added, best,
    events [(종류, 봉, 가격)], exit_k, exit_px, r(계획 물량 기준 R, 수수료 포함), state('pending'|'open'|'closed').
    """
    n = len(ind["c"])
    last_closed = n - 2 if live else n - 1
    trades, k = [], start_k
    while k <= last_closed:
        d = signal(ind, k)
        if not d:
            k += 1
            continue
        if k + 1 >= n:  # 신호는 나왔고 다음 봉이 아직 안 열림
            trades.append(dict(d=d, sig_k=k, state="pending", events=[("signal", k, ind["c"][k])],
                               risk=STOP_ATR * ind["atr"][k], entry=ind["c"][k]))
            break
        e, a = ind["o"][k + 1], ind["atr"][k]
        risk = STOP_ATR * a
        t = dict(d=d, sig_k=k, entry_k=k + 1, entry=e, risk=risk, stop=e - d * risk, add_px=e + d * risk,
                 added=False, best=e, events=[("signal", k, ind["c"][k]), ("entry", k + 1, e)],
                 exit_k=None, exit_px=None, state="open")
        legs = [(e, FIRST)]
        m = k + 1
        while m < n:
            hi, lo = ind["h"][m], ind["l"][m]
            if (lo <= t["stop"]) if d == 1 else (hi >= t["stop"]):
                t.update(exit_k=m, exit_px=t["stop"], state="closed")
                t["events"].append(("exit", m, t["stop"]))
                break
            t["best"] = max(t["best"], hi) if d == 1 else min(t["best"], lo)
            if not t["added"] and (t["best"] - e) * d >= risk:
                t["added"] = True
                legs.append((t["add_px"], 1 - FIRST))
                t["events"].append(("add", m, t["add_px"]))
                be = max(t["stop"], e) if d == 1 else min(t["stop"], e)
                if be != t["stop"]:
                    t["stop"] = be
            if live and m == n - 1:
                break  # 진행 중인 봉으로는 추적 손절을 올리지 않음
            trail = t["best"] - d * TRAIL_ATR * ind["atr"][m]
            new = max(t["stop"], trail) if d == 1 else min(t["stop"], trail)
            if new != t["stop"]:
                t["stop"] = new
                t["events"].append(("trail", m, new))
            m += 1
        px_out = t["exit_px"] if t["exit_px"] is not None else ind["c"][n - 1]
        t["legs"] = legs
        t["r"] = sum(w * ((px_out - px) * d / risk - (FEE_IN + FEE_OUT) * px / risk) for px, w in legs)
        trades.append(t)
        if t["state"] != "closed":
            break
        k = t["exit_k"] + 1
    return trades
