"""신호판 규칙(4시간봉 돈치안 돌파)의 지금 상태를 한 줄로. 금액·시드 같은 개인 정보 없이 가격만.

아침 경제 브리핑이 암호화폐 부분에서 참고한다: python3 rule_status.py
"""
import btc_signals as bs
import strategy as stg


def main():
    cs = bs.candles("4H", 1200)
    ind = bs.indicators(cs)
    ind["ts"] = [r[0] for r in cs]
    trades = stg.replay(ind, live=True)
    t = trades[-1] if trades else None
    k = len(ind["c"]) - 2
    hi, lo = max(ind["h"][k - stg.BREAK_N + 1:k + 1]), min(ind["l"][k - stg.BREAK_N + 1:k + 1])
    if not t or t["state"] == "closed":
        print(f"신호판 규칙: 포지션 없음 · 4시간봉이 {hi:,.0f} 위(EMA200 {ind['e200'][k]:,.0f} 위일 때)로 마감하면 롱, "
              f"{lo:,.0f} 아래(EMA200 아래일 때)로 마감하면 숏 신호")
        return
    side = "롱" if t["d"] == 1 else "숏"
    if t["state"] == "pending":
        print(f"신호판 규칙: {side} 신호 · 다음 4시간봉에서 진입")
        return
    add = "추가 진입 완료" if t["added"] else f"추가 진입가 {t['add_px']:,.0f}"
    tp = " · 30% 익절 완료" if t["tp"] else ""
    print(f"신호판 규칙: {side} 진행 중 · 진입 {t['entry']:,.0f} · 손절선 {t['stop']:,.0f} · {add}{tp}")


if __name__ == "__main__":
    main()
