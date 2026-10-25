"""비트겟 BTCUSDT 무기한 선물 멀티 타임프레임 분석 + 매수/매도 신호.

사용법: python3 btc_signals.py
표준 라이브러리만 사용. 비트겟 공개 API(인증 불필요)에서 데이터를 받는다.
투자 조언이 아니라 규칙 기반 신호다. 최종 판단과 주문은 직접 한다.
"""
import json
import time
import urllib.request

BASE = "https://api.bitget.com/api/v2/mix/market"
SYM = "BTCUSDT"
PT = "USDT-FUTURES"
TAKER_FEE = 0.0006  # 비트겟 기본 테이커 수수료 0.06%
MMR = 0.004  # BTC 유지증거금률 근사치(1구간)

# 스타일별 (신호 타임프레임, 상위 추세 필터 타임프레임)
STYLES = {
    "스캘핑": ("5m", "1H"),
    "데이트레이딩": ("15m", "4H"),
    "스윙": ("4H", "1D"),
}


def get(path, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    for attempt in range(6):
        try:
            with urllib.request.urlopen(f"{BASE}/{path}?{q}", timeout=15) as r:
                d = json.load(r)
            break
        except urllib.error.HTTPError as e:  # 429(요청 과다)는 기다렸다가 재시도
            if e.code != 429 and e.code < 500 or attempt == 5:
                raise
            time.sleep(2 ** attempt)
    if d.get("code") != "00000":
        raise RuntimeError(d)
    return d["data"]


def candles(tf, n=600):
    """오래된 것 -> 최신 순 [ts, o, h, l, c, vol]."""
    rows = get("candles", symbol=SYM, productType=PT, granularity=tf, limit=min(n, 1000))
    out = {int(r[0]): r for r in rows}
    while len(out) < n:
        oldest = min(out)
        more = get("history-candles", symbol=SYM, productType=PT, granularity=tf,
                   endTime=oldest - 1, limit=200)
        if not more:
            break
        for r in more:
            out[int(r[0])] = r
        time.sleep(0.1)
    rows = [out[k] for k in sorted(out)][-n:]
    return [[int(r[0])] + [float(x) for x in r[1:6]] for r in rows]


# ---------- 지표 ----------
def ema(xs, n):
    k = 2 / (n + 1)
    out, e = [], xs[0]
    for x in xs:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi(xs, n=14):
    out = [50.0] * len(xs)
    gain = loss = 0.0
    for i in range(1, len(xs)):
        d = xs[i] - xs[i - 1]
        g, l = max(d, 0), max(-d, 0)
        if i <= n:
            gain += g / n
            loss += l / n
        else:
            gain = (gain * (n - 1) + g) / n
            loss = (loss * (n - 1) + l) / n
        if i >= n:
            out[i] = 100 - 100 / (1 + gain / loss) if loss else 100
    return out


def atr(h, l, c, n=14):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
                          for i in range(1, len(c))]
    out, a = [], tr[0]
    for i, t in enumerate(tr):
        a = t if i == 0 else (a * (n - 1) + t) / n
        out.append(a)
    return out


def bbands(xs, n=20, k=2):
    up, lo = [], []
    for i in range(len(xs)):
        w = xs[max(0, i - n + 1): i + 1]
        m = sum(w) / len(w)
        sd = (sum((x - m) ** 2 for x in w) / len(w)) ** 0.5
        up.append(m + k * sd)
        lo.append(m - k * sd)
    return up, lo


def indicators(cs):
    o, h, l, c, v = ([r[i] for r in cs] for i in range(1, 6))
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    macd = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    sig = ema(macd, 9)
    hist = [a - b for a, b in zip(macd, sig)]
    bu, bl = bbands(c)
    vavg = [sum(v[max(0, i - 20):i]) / max(1, len(v[max(0, i - 20):i])) for i in range(len(v))]
    return dict(o=o, h=h, l=l, c=c, v=v, e20=e20, e50=e50, e200=e200, rsi=rsi(c),
                hist=hist, atr=atr(h, l, c), bu=bu, bl=bl, vavg=vavg)


def trend(ind, i=-1):
    c, e20, e50, e200 = ind["c"][i], ind["e20"][i], ind["e50"][i], ind["e200"][i]
    if c > e50 and e20 > e50 > e200:
        return 1
    if c < e50 and e20 < e50 < e200:
        return -1
    return 0


def signal_at(ind, i, htf_trend):
    """i번째 봉 마감 기준 신호. (방향, 종류, 근거) 반환. 방향 0 = 관망."""
    c, h, l = ind["c"], ind["h"], ind["l"]
    a, r, hs = ind["atr"][i], ind["rsi"], ind["hist"]
    t = trend(ind, i)
    hi20 = max(h[i - 20:i])
    lo20 = min(l[i - 20:i])
    vol_spike = ind["v"][i] > 1.5 * ind["vavg"][i]

    # 1) 추세 눌림목: 상위·현재 추세 같은 방향, EMA20~50 구간 터치 후 RSI 회복 + MACD 히스토그램 반전
    if htf_trend == 1 and t == 1:
        touched = min(l[i - 3:i + 1]) <= ind["e20"][i] + 0.3 * a
        if touched and r[i - 1] < 50 <= r[i] and hs[i] > hs[i - 1]:
            return 1, "추세 눌림목 롱", "상위·현재 상승추세, EMA20 눌림 후 RSI 50 회복, MACD 반등"
    if htf_trend == -1 and t == -1:
        touched = max(h[i - 3:i + 1]) >= ind["e20"][i] - 0.3 * a
        if touched and r[i - 1] > 50 >= r[i] and hs[i] < hs[i - 1]:
            return -1, "추세 되돌림 숏", "상위·현재 하락추세, EMA20 반등 후 RSI 50 이탈, MACD 하락"
    # 2) 돌파: 20봉 고/저점을 거래량 동반 종가 돌파, 상위 추세가 반대가 아닐 때
    if c[i] > hi20 and vol_spike and htf_trend >= 0 and r[i] < 75:
        return 1, "거래량 돌파 롱", f"20봉 고점 {hi20:,.0f} 종가 돌파, 거래량 평균의 1.5배 이상"
    if c[i] < lo20 and vol_spike and htf_trend <= 0 and r[i] > 25:
        return -1, "거래량 이탈 숏", f"20봉 저점 {lo20:,.0f} 종가 이탈, 거래량 평균의 1.5배 이상"
    # 3) 횡보 평균회귀: 추세 없음, 볼린저 밴드 밖에서 안으로 복귀
    if t == 0 and htf_trend == 0:
        if c[i - 1] < ind["bl"][i - 1] and c[i] > ind["bl"][i] and r[i - 1] < 30:
            return 1, "횡보 하단 반등 롱", "볼린저 하단 이탈 후 복귀, RSI 과매도"
        if c[i - 1] > ind["bu"][i - 1] and c[i] < ind["bu"][i] and r[i - 1] > 70:
            return -1, "횡보 상단 반락 숏", "볼린저 상단 이탈 후 복귀, RSI 과매수"
    return 0, "관망", ""


def levels(ind, i, d):
    """진입/손절/목표: 손절은 최근 5봉 스윙 너머 또는 1.5ATR 중 먼 쪽, 목표 1.5R / 3R."""
    entry, a = ind["c"][i], ind["atr"][i]
    if d == 1:
        stop = min(min(ind["l"][i - 5:i + 1]) - 0.2 * a, entry - 1.5 * a)
    else:
        stop = max(max(ind["h"][i - 5:i + 1]) + 0.2 * a, entry + 1.5 * a)
    risk = abs(entry - stop)
    return entry, stop, entry + d * 1.5 * risk, entry + d * 3 * risk


def backtest(ind, htf_ind, htf_map):
    """같은 규칙을 과거에 적용. 다음 봉 시가 진입, 손절 또는 2R 익절, 최대 48봉 보유.
    결과는 수수료(왕복 테이커) 반영 R 단위."""
    res, fees, by_kind, i, n = [], [], {}, 210, len(ind["c"])
    while i < n - 2:
        j = htf_map[i]
        d, kind, _ = signal_at(ind, i, trend(htf_ind, j) if j is not None and j >= 200 else 0)
        if not d:
            i += 1
            continue
        _, stop, _, _ = levels(ind, i, d)
        entry = ind["o"][i + 1]
        risk = abs(entry - stop)
        if risk <= 0 or (stop - entry) * d > 0:
            i += 1
            continue
        tp = entry + d * 2 * risk
        fee_r = 2 * TAKER_FEE * entry / risk
        out, k = None, i + 1
        for k in range(i + 1, min(n, i + 49)):
            hit_stop = ind["l"][k] <= stop if d == 1 else ind["h"][k] >= stop
            hit_tp = ind["h"][k] >= tp if d == 1 else ind["l"][k] <= tp
            if hit_stop:  # 같은 봉에서 둘 다 닿으면 보수적으로 손절 처리
                out = -1
                break
            if hit_tp:
                out = 2
                break
        if out is None:
            out = (ind["c"][k] - entry) * d / risk
        res.append(out - fee_r)
        fees.append(fee_r)
        by_kind.setdefault(kind, []).append(out - fee_r)
        i = k + 1
    if not res:
        return None
    wins = sum(1 for x in res if x > 0)
    return dict(n=len(res), win=wins / len(res), exp=sum(res) / len(res), total=sum(res),
                fee=sum(fees) / len(fees),
                kinds={k: (len(v), sum(v) / len(v)) for k, v in by_kind.items()})


def map_htf(ts, htf_ts, tf_ms, htf_ms):
    """각 하위봉 마감 시점에 이미 마감된 상위봉 인덱스(미래 참조 방지)."""
    out, j = [], -1
    for t in ts:
        close_t = t + tf_ms
        while j + 1 < len(htf_ts) and htf_ts[j + 1] + htf_ms <= close_t:
            j += 1
        out.append(j if j >= 0 else None)
    return out


# 백테스트 표본: 5m 약 35일, 15m 약 104일, 1H 약 1년, 4H 약 2년, 1D 약 3년
BARS = {"5m": 10000, "15m": 10000, "1H": 9000, "4H": 4400, "1D": 1100}
TF_MS = {"5m": 3e5, "15m": 9e5, "1H": 3.6e6, "4H": 1.44e7, "1D": 8.64e7}


def liq_distance(lev):
    return 1 / lev - MMR


def main():
    tk = get("ticker", symbol=SYM, productType=PT)[0]
    price = float(tk["lastPr"])
    fr = float(tk["fundingRate"])
    oi = float(tk["holdingAmount"])
    ls_acc = get("account-long-short", symbol=SYM, period="1h")[-1]
    ls_pos = get("position-long-short", symbol=SYM, period="1h")[-1]
    tbs = get("taker-buy-sell", symbol=SYM, period="1h")[-24:]
    buy = sum(float(x["buyVolume"]) for x in tbs)
    sell = sum(float(x["sellVolume"]) for x in tbs)

    print(f"=== 비트겟 {SYM} 무기한 선물 | {time.strftime('%Y-%m-%d %H:%M')} ===")
    print(f"현재가 {price:,.1f}  24h 고/저 {float(tk['high24h']):,.0f} / {float(tk['low24h']):,.0f}"
          f"  24h 변동 {float(tk['change24h'])*100:+.2f}%")
    print(f"펀딩비 {fr*100:+.4f}%/8h  미결제약정 {oi:,.0f} BTC")
    print(f"롱/숏 계정비 {float(ls_acc['longShortAccountRatio']):.2f}"
          f"  롱/숏 포지션비 {float(ls_pos['longShortPositionRatio']):.2f}"
          f"  24h 테이커 매수/매도 {buy/sell:.2f}")

    cache = {}
    for tf in {tf for pair in STYLES.values() for tf in pair}:
        cache[tf] = candles(tf, BARS[tf])
    inds = {tf: indicators(cs) for tf, cs in cache.items()}

    print("\n--- 타임프레임별 추세 ---")
    names = {1: "상승", -1: "하락", 0: "횡보"}
    for tf in ["5m", "15m", "1H", "4H", "1D"]:
        ind = inds[tf]
        print(f"{tf:>4}: {names[trend(ind, -2)]:<3} RSI {ind['rsi'][-2]:5.1f}  "
              f"EMA20 {ind['e20'][-2]:,.0f}  EMA50 {ind['e50'][-2]:,.0f}  EMA200 {ind['e200'][-2]:,.0f}"
              f"  ATR {ind['atr'][-2]:,.0f}")

    report = {"price": price, "funding": fr, "styles": []}
    for style, (tf, htf) in STYLES.items():
        ind, hind = inds[tf], inds[htf]
        i = len(ind["c"]) - 2  # 마지막 '마감된' 봉
        ht = trend(hind, len(hind["c"]) - 2)
        d, kind, why = signal_at(ind, i, ht)
        hmap = map_htf([r[0] for r in cache[tf]], [r[0] for r in cache[htf]], TF_MS[tf], TF_MS[htf])
        bt = backtest(ind, hind, hmap)
        print(f"\n--- {style} ({tf}, 상위 필터 {htf} {names[ht]}) ---")
        if d:
            e, s, t1, t2 = levels(ind, i, d)
            stop_pct = abs(e - s) / e
            print(f"신호: {kind}  ({why})")
            print(f"진입 {e:,.1f}  손절 {s:,.1f} ({stop_pct*100:.2f}%)  1차 {t1:,.1f}  2차 {t2:,.1f}")
            for lev in (10, 20, 50):
                ok = "OK" if stop_pct < liq_distance(lev) * 0.8 else "위험: 손절 전에 청산될 수 있음"
                print(f"  {lev}배: 청산까지 약 {liq_distance(lev)*100:.1f}%  -> {ok}")
            print(f"  계좌 1% 리스크 기준 포지션 = 계좌 x {0.01/stop_pct:.2f}배 명목가")
        else:
            # 최근 신호 찾기
            last = None
            for k in range(i - 1, 210, -1):
                j = hmap[k]
                dd, kk, _ = signal_at(ind, k, trend(hind, j) if j and j >= 200 else 0)
                if dd:
                    last = (k, kk)
                    break
            print("신호: 관망 (조건 충족 없음)")
            if last:
                ago = i - last[0]
                print(f"  마지막 신호: {last[1]} ({ago}봉 전, {ind['c'][last[0]]:,.0f})")
        if bt:
            print(f"백테스트({len(ind['c'])}봉): 거래 {bt['n']}회  승률 {bt['win']*100:.0f}%"
                  f"  평균 {bt['exp']:+.2f}R  합계 {bt['total']:+.1f}R  (수수료가 거래당 평균 {bt['fee']:.2f}R 차지)")
            for k, (cnt, ex) in sorted(bt["kinds"].items(), key=lambda x: -x[1][1]):
                print(f"    {k}: {cnt}회 평균 {ex:+.2f}R")
        report["styles"].append(dict(style=style, tf=tf, htf=htf, htf_trend=ht, signal=d,
                                     kind=kind, why=why, bt=bt))
    with open("btc_signal_latest.json", "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
