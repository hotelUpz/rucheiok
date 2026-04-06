# ============================================================
# FILE: CORE/funding_pattern1.py
# ROLE: Валидатор фандинга (Одиночный Phemex)
# ============================================================
from __future__ import annotations

import asyncio
import time
from typing import Set, Any, TYPE_CHECKING, Dict
from c_log import UnifiedLogger

if TYPE_CHECKING:
    from API.PHEMEX.funding import PhemexFunding, FundingInfo

logger = UnifiedLogger("bot")

class FundingFilter1:
    def __init__(self, cfg: dict[str, Any], funding_api: 'PhemexFunding'):
        self.cfg = cfg
        self.funding_api = funding_api
        self.enable: bool = cfg.get("enable", False)
        self.interval: int = cfg.get("check_interval_sec", 60)
        self.threshold: float = cfg.get("threshold_pct", 0.5) / 100.0
        self.skip_sec: int = cfg.get("skip_before_counter_sec", 1800)
        
        self._blocked_symbols: Set[str] = set()
        self._last_blocked_funding: Set[str] = set()
        self.last_funding_rates: Dict[str, float] = {}
        self.is_running: bool = False

    async def run(self) -> None:
        if not self.enable: 
            return
            
        self.is_running = True
        logger.info(f"⏱ Чекер фандинга Phemex запущен. Обновление каждые: {self.interval}с, Порог: {self.threshold*100}%, Скип за: {self.skip_sec}с.")
        
        while self.is_running:
            try:
                rows: list['FundingInfo'] = await self.funding_api.get_all()
                now_ms: float = time.time() * 1000
                current_blocked: Set[str] = set()
                
                for r in rows:
                    sym = r.symbol.upper()
                    self.last_funding_rates[sym] = r.funding_rate
                    time_left_sec = (r.next_funding_time_ms - now_ms) / 1000.0
                    
                    if 0 < time_left_sec <= self.skip_sec:
                        if abs(r.funding_rate) >= self.threshold:
                            current_blocked.add(sym)
                
                self._blocked_symbols = current_blocked
                
                if current_blocked != self._last_blocked_funding:
                    if current_blocked:
                        logger.info(f"💸 Фандинг-блок! Под запретом {len(current_blocked)} монет: {', '.join(list(current_blocked)[:5])}...")
                    elif self._last_blocked_funding:
                        logger.info("💸 Фандинг-блок снят со всех монет.")
                    self._last_blocked_funding = current_blocked

            except Exception as e:
                logger.error(f"❌ Ошибка обновления фандинга Phemex: {e}")
                
            await asyncio.sleep(self.interval)
            
    def stop(self) -> None:
        self.is_running = False
        
    def is_trade_allowed(self, symbol: str) -> bool:
        if not self.enable:
            return True
        return symbol not in self._blocked_symbols