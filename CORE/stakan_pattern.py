from __future__ import annotations
from c_log import UnifiedLogger

logger = UnifiedLogger("stakan_pattern")

class StakanPattern:
    def __init__(self, phemex_cfg: dict):
        self.cfg = phemex_cfg
        self.depth = self.cfg.get("depth", 8)
        self.min_first_row_usdt_notional = self.cfg.get("min_first_row_usdt_notional")

    def analyze(self, symbol: str, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> dict | None:
        if not self.cfg.get("enable", True):
            return None
        if len(bids) < self.depth or len(asks) < self.depth:
            return None

        long_signal = self._check_long(symbol, bids, asks)
        if long_signal:
            return long_signal

        short_signal = self._check_short(symbol, bids, asks)
        if short_signal:
            return short_signal

        return None

    def _check_long(self, symbol: str, bids: list, asks: list) -> dict | None:

        ask1, bid1 = asks[0][0], bids[0][0]
        ask2, ask3 = asks[1][0], asks[2][0]
        bottom = self.cfg["bottom"]

        ask1_vol_usdt = asks[0][1] * ask1

        if ask1_vol_usdt < self.min_first_row_usdt_notional: 
            return None
        
        spr2_pct = (ask2 - ask1) / ask1 * 100
        if spr2_pct < bottom["min_spread_between_two_row_pct"]: 
            return None

        spr3_pct = (ask3 - ask1) / ask1 * 100
        if spr3_pct < bottom["min_spread_between_three_row_pct"]: 
            return None

        dist_denom = ask2 - ask1
        if dist_denom <= 0: return None
        
        dist_rate = (ask1 - bid1) / dist_denom
        if dist_rate > self.cfg["max_bid_ask_distance_rate"]: 
            return None

        header, body = self.cfg["header"], self.cfg["body"]
        roc_window, roc_sma_window = header["roc_window"], body["roc_sma_window"]

        rocs = []
        for i in range(self.depth - 1, self.depth - 1 - roc_sma_window, -1):
            roc = (asks[i][0] - asks[i-1][0]) / asks[i-1][0] * 100
            rocs.append(roc)

        if any(r > header["max_one_roc_pct"] for r in rocs[:roc_window]):
            return None

        roc_sma = sum(rocs) / len(rocs) if rocs else 0.0
        roc_sma = max(roc_sma, 0.0)

        if not roc_sma: return None

        rate = spr3_pct / roc_sma
        
        # logger.debug(f"[{symbol} LONG] Анализ: spr3_pct={spr3_pct:.4f}, roc_sma={roc_sma:.4f}, rate={rate:.2f}")

        if rate < self.cfg["header_to_bottom_desired_rate"]: 
            return None

        return {
            "side": "LONG",
            "price": ask1,
            "spr2_pct": round(spr2_pct, 4),
            "spr3_pct": round(spr3_pct, 4),
            "rate": round(rate, 2),
            "row_vol_usdt": ask1_vol_usdt
        }

    def _check_short(self, symbol: str, bids: list, asks: list) -> dict | None:
        ask1, bid1 = asks[0][0], bids[0][0]
        bid2, bid3 = bids[1][0], bids[2][0]
        bottom = self.cfg["bottom"]

        bid1_vol_usdt = bids[0][1] * bid1

        if bid1_vol_usdt < self.min_first_row_usdt_notional: 
            return None
        
        spr2_pct = (bid1 - bid2) / bid1 * 100
        if spr2_pct < bottom["min_spread_between_two_row_pct"]: 
            return None

        spr3_pct = (bid1 - bid3) / bid1 * 100
        if spr3_pct < bottom["min_spread_between_three_row_pct"]: 
            return None

        dist_denom = bid1 - bid2
        if dist_denom <= 0: return None
        
        dist_rate = (ask1 - bid1) / dist_denom
        if dist_rate > self.cfg["max_bid_ask_distance_rate"]: 
            return None

        header, body = self.cfg["header"], self.cfg["body"]
        roc_window, roc_sma_window = header["roc_window"], body["roc_sma_window"]

        rocs = []
        for i in range(self.depth - 1, self.depth - 1 - roc_sma_window, -1):
            roc = (bids[i-1][0] - bids[i][0]) / bids[i-1][0] * 100
            rocs.append(roc)

        if any(r > header["max_one_roc_pct"] for r in rocs[:roc_window]):
            return None

        roc_sma = sum(rocs) / len(rocs) if rocs else 0.000001
        roc_sma = max(roc_sma, 0.000001)

        rate = spr3_pct / roc_sma
        
        # logger.debug(f"[{symbol} SHORT] Анализ: spr3_pct={spr3_pct:.4f}, roc_sma={roc_sma:.4f}, rate={rate:.2f}")

        if rate < self.cfg["header_to_bottom_desired_rate"]: 
            return None

        return {
            "side": "SHORT",
            "price": bid1, 
            "spr2_pct": round(spr2_pct, 4),
            "spr3_pct": round(spr3_pct, 4),
            "rate": round(rate, 2),
            "row_vol_usdt": bid1_vol_usdt
        }