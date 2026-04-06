# ============================================================
# FILE: CORE/funding_pattern2.py
# ROLE: Валидатор разницы фандингов (Binance vs Phemex)
# ============================================================
from __future__ import annotations

import asyncio
import time
from typing import Set, Any, TYPE_CHECKING, Dict
from c_log import UnifiedLogger

if TYPE_CHECKING:
    from API.PHEMEX.funding import PhemexFunding
    from API.BINANCE.funding import BinanceFunding

logger = UnifiedLogger("bot")

class FundingFilter2:
    """
    Инварианты расчета:
    val = abs(phm_funding - binance_funding)
    """
    def __init__(self, cfg: dict[str, Any], phemex_api: 'PhemexFunding', binance_api: 'BinanceFunding'):
        self.cfg = cfg
        self.phemex_api = phemex_api
        self.binance_api = binance_api
        self.enable: bool = cfg.get("enable", False)
        self.interval: int = cfg.get("check_interval_sec", 60)
        self.diff_threshold: float = cfg.get("diff_threshold_pct", 0.05) / 100.0
        self.skip_sec: int = cfg.get("skip_before_counter_sec", 1800)
        
        self._blocked_symbols: Set[str] = set()
        self._last_blocked_funding: Set[str] = set()
        self.last_diffs: Dict[str, float] = {}
        self.is_running: bool = False

    async def run(self) -> None:
        if not self.enable: 
            return
            
        self.is_running = True
        logger.info(f"⚖️ Чекер Diff-Фандинга (Binance vs Phemex) запущен. Порог: {self.diff_threshold*100}%, Скип за: {self.skip_sec}с.")
        
        while self.is_running:
            try:
                # Параллельно дергаем обе биржи
                phm_task = asyncio.create_task(self.phemex_api.get_all())
                bin_task = asyncio.create_task(self.binance_api.get_all())
                
                phm_rows, bin_rows = await asyncio.gather(phm_task, bin_task)
                now_ms = time.time() * 1000
                current_blocked: Set[str] = set()
                
                # Собираем словарь для быстрого O(1) поиска по Бинансу (он отдается без суффикса)
                bin_dict = {r.symbol.upper(): r for r in bin_rows}
                
                for p_row in phm_rows:
                    sym = p_row.symbol.upper()
                    b_row = bin_dict.get(sym)
                    
                    if b_row:
                        diff = abs(p_row.funding_rate - b_row.funding_rate)
                        self.last_diffs[sym] = diff
                        
                        # Берем минимальное время до фандинга из двух (чтобы быть в безопасности на любой бирже)
                        time_left_p = (p_row.next_funding_time_ms - now_ms) / 1000.0
                        time_left_b = (b_row.next_funding_time_ms - now_ms) / 1000.0
                        min_time_left = min(time_left_p, time_left_b)
                        
                        if 0 < min_time_left <= self.skip_sec:
                            if diff >= self.diff_threshold:
                                current_blocked.add(sym)
                
                self._blocked_symbols = current_blocked
                
                if current_blocked != self._last_blocked_funding:
                    if current_blocked:
                        logger.info(f"⚖️ Фандинг-Diff блок! Под запретом {len(current_blocked)} монет: {', '.join(list(current_blocked)[:5])}...")
                    elif self._last_blocked_funding:
                        logger.info("⚖️ Фандинг-Diff блок снят со всех монет.")
                    self._last_blocked_funding = current_blocked

            except Exception as e:
                logger.error(f"❌ Ошибка обновления фандинга Binance-Phemex (diff): {e}")
                
            await asyncio.sleep(self.interval)
            
    def stop(self) -> None:
        self.is_running = False
        
    def is_trade_allowed(self, symbol: str) -> bool:
        if not self.enable:
            return True
        return symbol not in self._blocked_symbols