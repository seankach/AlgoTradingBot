r"""Throwaway IBKR depth diagnostic — run against your live gateway, then delete.

Talks to ib_async directly (not qrp) so we see RAW IBKR behaviour: head timestamps, how
deep 1-minute history really goes for TRADES and BID_ASK, and how large a single request
IBKR will serve.

    .\.venv\Scripts\python.exe diagnose_ibkr.py
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ib_async import IB, Stock

HOST, PORT, CLIENT_ID = "127.0.0.1", 7497, 99  # match config/ibkr.yaml if you changed it


def main() -> None:
    """Connect, probe head timestamps, and sample 1-min depth for both series."""
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=30, readonly=True)
    print(f"connected={ib.isConnected()}  serverVersion={ib.client.serverVersion()}")

    contract = Stock("TSLA", "SMART", "USD", primaryExchange="NASDAQ")
    ib.qualifyContracts(contract)
    print("qualified:", contract.localSymbol, "conId", contract.conId)

    for wts in ("TRADES", "BID_ASK"):
        try:
            head = ib.reqHeadTimeStamp(contract, whatToShow=wts, useRTH=False, formatDate=2)
            print(f"reqHeadTimeStamp[{wts}] = {head!r}")
        except Exception as exc:
            print(f"reqHeadTimeStamp[{wts}] error: {exc}")

    now = datetime.now(UTC)
    # Sample both series at increasing depth to find the true 1-min floor (0 bars = gone).
    # ~365d per year; 5800d ~= back to the 2010 IPO.
    for wts in ("TRADES", "BID_ASK"):
        print(f"\n--- {wts} 1-min '1 D' windows ending N days ago ---")
        for days_ago in (1, 365, 1500, 3000, 4500, 5000, 5400, 5800):
            end = now - timedelta(days=days_ago)
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime=end,
                    durationStr="1 D",
                    barSizeSetting="1 min",
                    whatToShow=wts,
                    useRTH=False,
                    formatDate=2,
                    timeout=120,
                )
                first = bars[0].date if bars else None
                print(f"  end -{days_ago:>4}d ({end.date()}): {len(bars):>4} bars   first={first}")
            except Exception as exc:
                print(f"  end -{days_ago:>4}d ({end.date()}): error {exc}")

    print("\n--- single-request size (TRADES, 1 min, ending now) ---")
    for duration in ("1 D", "5 D", "10 D", "15 D"):
        try:
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=now,
                durationStr=duration,
                barSizeSetting="1 min",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=2,
                timeout=120,
            )
            print(f"  durationStr={duration:>5}: {len(bars):>6} bars")
        except Exception as exc:
            print(f"  durationStr={duration:>5}: error {exc}")

    ib.disconnect()


if __name__ == "__main__":
    main()
