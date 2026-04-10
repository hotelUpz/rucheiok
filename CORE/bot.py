from __future__ import annotations

import asyncio
import time
import os
from typing import Dict, Any, Set, TYPE_CHECKING
from dotenv import load_dotenv

from API.PHEMEX.symbol import PhemexSymbols, SymbolInfo
from API.PHEMEX.stakan import PhemexStakanStream, DepthTop
from API.PHEMEX.ticker import PhemexTickerAPI
from API.PHEMEX.funding import PhemexFunding
from API.BINANCE.ticker import BinanceTickerAPI
from API.BINANCE.funding import BinanceFunding
from CORE.stakan_pattern import StakanPattern
from CORE.funding_manager import FundingManager

from CORE.oil_pattern import OpenInterestDefender
from tg_sender import TelegramSender
from c_log import UnifiedLogger

if TYPE_CHECKING:
    from API.PHEMEX.symbol import SymbolInfo
    from API.PHEMEX.stakan import DepthTop


load_dotenv()

logger = UnifiedLogger("bot")

class ScreenerBot:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.phemex_sym_api = PhemexSymbols()
        
        self.binance_ticker_api = BinanceTickerAPI()
        self.phemex_ticker_api = PhemexTickerAPI()

        self.funding_api = PhemexFunding()
        self.binance_funding_api = BinanceFunding()

        raw_black_list = self.cfg.get("black_list", [])
        self.black_list = {str(s).strip().upper() for s in raw_black_list if s and s.strip()}
        
        tg_cfg = cfg.get("tg", {})
        tg_enabled = tg_cfg.get("enable", False)
        
        token = os.getenv("token") or tg_cfg.get("token", "")
        chat_id = os.getenv("chat_id") or tg_cfg.get("chat_id", "")
        
        self.tg = TelegramSender(token, chat_id) if tg_enabled else None
        
        self.pattern_engine = StakanPattern(cfg["pattern"]["phemex"])
        
        # Единый менеджер фандингов
        self.funding_manager = FundingManager(cfg["pattern"], self.funding_api, self.binance_funding_api)
        self.oli_defender = OpenInterestDefender(cfg["pattern"]["oil"])
        
        self.funding1_enabled = cfg["pattern"]["funding_pattern1"]["enable"]
        self.funding2_enabled = cfg["pattern"]["funding_pattern2"]["enable"]
        self.oli_enabled = cfg["pattern"]["oil"]["enable"]
        
        self.cache: Dict[str, float] = {}
        self._processing: Set[str] = set()
        self.cache_ttl = self.cfg.get("app", {}).get("cache_flush_sec", 3600)  
        
        self._pattern_first_seen: Dict[str, float] = {}
        self._spread_first_seen: Dict[str, float] = {}
        
        self.binance_prices: Dict[str, float] = {}
        self.phemex_prices: Dict[str, float] = {}
        self.symbols_info_dict: Dict[str, SymbolInfo] = {}
        self.prices_cache_time = 0.0
        
        self.target_depth = self.cfg["pattern"]["phemex"].get("depth", 8)
        self.pattern_ttl = self.cfg["pattern"]["phemex"].get("pattern_ttl_sec", 0)
        
        self.binance_enabled = self.cfg["pattern"]["binance"].get("enable", True)
        self.update_prices_sec = self.cfg["pattern"]["binance"].get("update_prices_sec", 3)
        self.min_price_spread_rate = abs(self.cfg["pattern"]["binance"]["min_price_spread_rate"])
        self.spread_ttl = self.cfg["pattern"]["binance"].get("spread_ttl_sec", 0)
        
        self._stream: PhemexStakanStream | None = None

    async def aclose(self):
        if self._stream:
            self._stream.stop()
        self.funding_manager.stop()
            
        await self.phemex_sym_api.aclose()
        await self.binance_ticker_api.aclose()
        await self.phemex_ticker_api.aclose()
        await self.funding_api.aclose()
        await self.binance_funding_api.aclose()

    async def update_prices_cache(self):
        now = time.time()
        if now - self.prices_cache_time < self.update_prices_sec:
            return
            
        self.prices_cache_time = now 
        
        try:
            b_prices_task = asyncio.create_task(self.binance_ticker_api.get_all_prices())
            p_prices_task = asyncio.create_task(self.phemex_ticker_api.get_all_prices())
            
            self.binance_prices, self.phemex_prices = await asyncio.gather(b_prices_task, p_prices_task)
            logger.debug(f"Кэш горячих цен обновлен. Binance: {len(self.binance_prices)}, Phemex: {len(self.phemex_prices)}")
        except Exception as e:
            logger.error(f"Ошибка загрузки горячих цен: {e}")
            self.prices_cache_time = 0.0 

    async def check_binance_filter(self, symbol: str, side: str, spr2_pct: float) -> dict | None:
        if not self.binance_enabled:
            return {"passed": True, "b_price": 0.0, "p_price": 0.0, "spread": 0}
            
        await self.update_prices_cache()
        
        binance_hot_price = self.binance_prices.get(symbol)
        phemex_hot_price = self.phemex_prices.get(symbol)
        
        if not binance_hot_price or not phemex_hot_price:
            logger.debug(f"[{symbol}] Нет горячей цены для расчета спреда.")
            return None 
            
        spread_pct = (binance_hot_price - phemex_hot_price) / phemex_hot_price * 100  
        min_spread = abs(spr2_pct * self.min_price_spread_rate)  
        passed = (spread_pct >= min_spread) if side == "LONG" else (spread_pct <= -min_spread)
        
        if passed:
            return {"passed": True, "b_price": binance_hot_price, "p_price": phemex_hot_price, "spread": abs(spread_pct)}
        return None

    def _clean_cache(self):
        now = time.time()
        expired = [sym for sym, ts in self.cache.items() if now - ts > self.cache_ttl]
        for sym in expired:
            del self.cache[sym]

    async def _process_signal(self, snap: DepthTop, sym_info: SymbolInfo):
        symbol = snap.symbol

        if symbol in self.black_list:
            return

        now = time.time()
        
        if symbol in self.cache:
            if now - self.cache[symbol] < self.cache_ttl:
                return
        
        if symbol in self._processing:
            return
            
        self._processing.add(symbol)
        try:
            bids_sliced = snap.bids[:self.target_depth]
            asks_sliced = snap.asks[:self.target_depth]

            # 1. ПАТТЕРН СТАКАНА
            signal = self.pattern_engine.analyze(symbol, bids_sliced, asks_sliced)
            if not signal:
                self._pattern_first_seen.pop(symbol, None)
                self._spread_first_seen.pop(symbol, None)
                return

            logger.debug(f"[{symbol}] 🟢 Найден паттерн {signal['side']}! Переход к ценовому спреду...")

            # 2. ФИЛЬТР СПРЕДА ЦЕН
            binance_check = await self.check_binance_filter(symbol, signal["side"], signal["spr2_pct"])
            if not binance_check:
                logger.debug(f"[{symbol}] 🔴 Отбраковано: Не прошел фильтр ценового спреда (Binance vs Phemex).")
                self._spread_first_seen.pop(symbol, None)
                return
            
            logger.debug(f"[{symbol}] ✅ Спред пройден. Переход к фильтрам фандинга...")

            # 3. ФИЛЬТРЫ ФАНДИНГА
            funding1 = "OFF"
            if self.funding_manager.filter1.enable:
                if not self.funding_manager.filter1.is_allowed(symbol):
                    logger.debug(f"[{symbol}] 🔴 Отбраковано: Блокировка Funding 1 (Phemex).")
                    return 
                phemex_info = self.funding_manager.phemex_cache.get(symbol)
                funding1 = f"{round(phemex_info.funding_rate * 100, 4)}%" if phemex_info else "NONE"             

            diff_funding2 = "OFF" 
            if self.funding_manager.filter2.enable:
                if not self.funding_manager.filter2.is_allowed(symbol):
                    logger.debug(f"[{symbol}] 🔴 Отбраковано: Блокировка Funding 2 (Diff Binance/Phemex).")
                    return
                diff_val = self.funding_manager.last_diffs.get(symbol)
                diff_funding2 = f"{round(diff_val * 100, 4)}%" if diff_val is not None else "NONE"

            logger.debug(f"[{symbol}] ✅ Фандинги пройдены. Проверка TTL...")

            # 4. TTL ВЫДЕРЖКА СИГНАЛОВ
            if self.pattern_ttl > 0:
                first_seen_p = self._pattern_first_seen.setdefault(symbol, now)
                if now - first_seen_p < self.pattern_ttl:
                    logger.debug(f"[{symbol}] ⏳ Паттерн настаивается (TTL {self.pattern_ttl}с)...")
                    return 

            if self.spread_ttl > 0:
                first_seen_s = self._spread_first_seen.setdefault(symbol, now)
                if now - first_seen_s < self.spread_ttl:
                    logger.debug(f"[{symbol}] ⏳ Спред настаивается (TTL {self.spread_ttl}с)...")
                    return 
                
            # 5. OI DEFENDER (OIL)
            if not self.oli_enabled:
                oil_val = "OFF"
            else:
                improve_price = (bids_sliced[0][0] + asks_sliced[0][0]) / 2
                logger.debug(f"[{symbol}] 🕵️‍♂️ Запуск пробива OIL на цене {improve_price}...")
                
                # ... (остальной код OIL остается без изменений)
                oil_raw = await self.oli_defender.is_oil(
                    symbol=symbol,
                    price=improve_price,
                    sym_info=sym_info
                )

                if oil_raw is True:
                    oil_val = "True"
                elif oil_raw is False:
                    oil_val = "False"
                else:
                    oil_val = oil_raw  # string ERR_...

            # 6. ФОРМИРОВАНИЕ И ОТПРАВКА СИГНАЛА
            side_visual = "🟢 LONG 📈" if signal['side'] == "LONG" else "🔴 SHORT 📉"
            
            b_price = binance_check['b_price']
            p_price = binance_check['p_price']            

            msg = (
                f"Монета: <b>#{symbol}</b>\n"
                f"Направление: {side_visual}\n"
                f"Цена срабатывания (стакан): {signal['price']}\n"
                f"Spread (2 уровня): {signal['spr2_pct']}%\n"
                f"Spread (3 уровня): {signal['spr3_pct']}%\n"
                f"Множитель (Rate): {signal['rate']}x\n\n"
                f"Объем первого уровня в USDT: {round(signal.get('row_vol_usdt', 0), 2) or 'none'}\n\n"
                f"🔥 <b>Горячие цены:</b>\n"
                f"Binance: {b_price}\n"
                f"Phemex: {p_price}\n"                
                f"Binance/Phemex Spread_%: {round(binance_check.get('spread', 0), 4) or 'none'}\n\n"
                f"OIL: {oil_val}\n"
                f"Phemex Funding: {funding1}\n"
                f"Binance/Phemex diff Funding: {diff_funding2}\n"
            )
            
            # Ставим кулдаун
            self.cache[symbol] = now
            self._pattern_first_seen.pop(symbol, None)
            self._spread_first_seen.pop(symbol, None)
            
            if self.tg:
                await self.tg.send_message(msg)
            logger.info(f"[SIGNAL] {symbol} {signal['side']} rate={signal['rate']}")

        except Exception as e:
            logger.debug(f"Scan error {snap.symbol}: {e}")
        finally:
            self._processing.discard(symbol)

    async def _on_depth_received(self, snap: DepthTop):
        sym_info = self.symbols_info_dict.get(snap.symbol)
        if sym_info:
            asyncio.create_task(self._process_signal(snap, sym_info))
        else:
            logger.debug(f"[{snap.symbol}] Не найдена спецификация (SymbolInfo) для монеты!")

    async def run(self):
        logger.info("Скринер запущен. Получение символов Phemex...")
        symbols_info = await self.phemex_sym_api.get_all(quote="USDT", only_active=True)
        
        # Кэшируем информацию о монетах для быстрого доступа в коллбеке
        self.symbols_info_dict = {s.symbol: s for s in symbols_info}
        
        symbols = [s.symbol for s in symbols_info if s.symbol not in self.black_list]
        
        start_msg = (
            f"🤖 <b>Скринер активен (WSS)</b>\n"
            f"Биржа: Phemex Futures\n"
            f"Символов: {len(symbols)}\n"
            f"Паттерн: Ручеек (depth={self.target_depth})"
        )
        if self.tg:
            await self.tg.send_message(start_msg)
        logger.info(start_msg)

        await self.update_prices_cache()

        asyncio.create_task(self.funding_manager.run())
        await asyncio.sleep(1)

        self._stream = PhemexStakanStream(
            symbols=symbols,
            depth=10,
            chunk_size=40,
            throttle_ms=0
        )
        
        logger.info("Подключение к WSS Phemex и подписка на стаканы...")
        await self._stream.run(self._on_depth_received) # УБРАЛИ ЛИШНИЙ АРГУМЕНТ ЗДЕСЬ