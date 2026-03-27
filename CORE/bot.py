import asyncio
import time
import os
from typing import Dict, Any, Set
from dotenv import load_dotenv

from API.PHEMEX.symbol import PhemexSymbols
from API.PHEMEX.stakan import PhemexStakanStream, DepthTop
from API.PHEMEX.ticker import PhemexTickerAPI
from API.BINANCE.ticker import BinanceTickerAPI
from CORE.pattern_math import StakanPattern
from tg_sender import TelegramSender
from c_log import UnifiedLogger

load_dotenv()

logger = UnifiedLogger("screener_bot")

class ScreenerBot:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.phemex_sym_api = PhemexSymbols()
        
        self.binance_ticker_api = BinanceTickerAPI()
        self.phemex_ticker_api = PhemexTickerAPI()

        # Нормализуем блек-лист для защиты от случайных пробелов и проблем с регистром
        raw_black_list = self.cfg.get("black_list", [])
        self.black_list = {str(s).strip().upper() for s in raw_black_list if s and s.strip()}
        
        tg_cfg = cfg.get("tg", {})
        tg_enabled = tg_cfg.get("enable", False)
        
        token = os.getenv("token") or tg_cfg.get("token", "")
        chat_id = os.getenv("chat_id") or tg_cfg.get("chat_id", "")
        
        self.tg = TelegramSender(token, chat_id) if tg_enabled else None
        
        self.pattern_engine = StakanPattern(cfg["pattern"]["phemex"])
        
        self.cache: Dict[str, float] = {}
        self._processing: Set[str] = set()
        self.cache_ttl = self.cfg.get("app", {}).get("cache_flush_sec", 3600)  
        
        # ⚡ Трекеры времени для выдержки сигналов (TTL)
        self._pattern_first_seen: Dict[str, float] = {}
        self._spread_first_seen: Dict[str, float] = {}
        
        self.binance_prices: Dict[str, float] = {}
        self.phemex_prices: Dict[str, float] = {}
        self.prices_cache_time = 0.0
        
        # Константы из конфига
        self.target_depth = self.cfg["pattern"]["phemex"].get("depth", 8)
        self.pattern_ttl = self.cfg["pattern"]["phemex"].get("pattern_ttl_sec", 0)
        
        self.binance_enabled = self.cfg["pattern"]["binance"].get("enable", True)
        self.update_prices_sec = self.cfg["pattern"]["binance"].get("update_prices_sec", 3)
        self.min_price_spread = abs(self.cfg["pattern"]["binance"]["min_price_spread_pct"])
        self.spread_ttl = self.cfg["pattern"]["binance"].get("spread_ttl_sec", 0)
        
        self._stream: PhemexStakanStream | None = None

    async def aclose(self):
        if self._stream:
            self._stream.stop()
        await self.phemex_sym_api.aclose()
        await self.binance_ticker_api.aclose()
        await self.phemex_ticker_api.aclose()

    async def update_prices_cache(self):
        now = time.time()
        if now - self.prices_cache_time < self.update_prices_sec:
            return
            
        self.prices_cache_time = now 
        
        try:
            b_prices_task = asyncio.create_task(self.binance_ticker_api.get_all_prices())
            p_prices_task = asyncio.create_task(self.phemex_ticker_api.get_all_prices())
            
            self.binance_prices, self.phemex_prices = await asyncio.gather(b_prices_task, p_prices_task)
        except Exception as e:
            logger.error(f"Ошибка загрузки горячих цен: {e}")
            self.prices_cache_time = 0.0 

    async def check_binance_filter(self, symbol: str, side: str) -> dict | None:
        if not self.binance_enabled:
            return {"passed": True, "b_price": 0.0, "p_price": 0.0, "spread": 0}
            
        await self.update_prices_cache()
        
        binance_hot_price = self.binance_prices.get(symbol)
        phemex_hot_price = self.phemex_prices.get(symbol)
        
        if not binance_hot_price or not phemex_hot_price:
            return None 
            
        spread_pct = (binance_hot_price - phemex_hot_price) / phemex_hot_price * 100       
        passed = (spread_pct >= self.min_price_spread) if side == "LONG" else (spread_pct <= -self.min_price_spread)
        
        if passed:
            return {"passed": True, "b_price": binance_hot_price, "p_price": phemex_hot_price, "spread": abs(spread_pct)}
        return None

    def _clean_cache(self):
        now = time.time()
        expired = [sym for sym, ts in self.cache.items() if now - ts > self.cache_ttl]
        for sym in expired:
            del self.cache[sym]

    async def _on_depth_received(self, snap: DepthTop):
        asyncio.create_task(self._process_depth(snap))

    async def _process_depth(self, snap: DepthTop):
        symbol = snap.symbol

        # --- ДОБАВЛЯЕМ ЭТУ ПРОВЕРКУ ---
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

            # ==========================================
            # 1. ЛОГИКА: ПРОВЕРКА ФАКТА (БЕЗ БЛОКИРОВОК)
            # ==========================================
            signal = self.pattern_engine.analyze(bids_sliced, asks_sliced)
            if not signal:
                # Если паттерн сломался хоть на тик - сбрасываем оба трекера
                self._pattern_first_seen.pop(symbol, None)
                self._spread_first_seen.pop(symbol, None)
                return

            binance_check = await self.check_binance_filter(symbol, signal["side"])
            if not binance_check:
                # Если спреда нет, сбрасываем только его трекер (паттерн может продолжать жить)
                self._spread_first_seen.pop(symbol, None)
                return

            # ==========================================
            # 2. ВЫДЕРЖКА: ПАРАЛЛЕЛЬНЫЙ ОТСЧЕТ
            # ==========================================
            # Теперь трекеры запускаются ОДНОВРЕМЕННО, так как код не прервался раньше времени
            if self.pattern_ttl > 0:
                first_seen_p = self._pattern_first_seen.setdefault(symbol, now)
                if now - first_seen_p < self.pattern_ttl:
                    return # Ждем, пока настоится паттерн

            if self.spread_ttl > 0:
                first_seen_s = self._spread_first_seen.setdefault(symbol, now)
                if now - first_seen_s < self.spread_ttl:
                    return # Ждем, пока настоится спред

            # ==========================================
            # 3. ВСЕ ПРОВЕРКИ И TTL ПРОЙДЕНЫ -> ОТПРАВЛЯЕМ
            # ==========================================
            if signal['side'] == "LONG":
                side_visual = "🟢 LONG 📈"
            else:
                side_visual = "🔴 SHORT 📉"
            
            b_price = binance_check['b_price']
            p_price = binance_check['p_price']            

            msg = (
                f"Монета: <b>#{symbol}</b>\n"
                f"Направление: {side_visual}\n"
                f"Цена срабатывания (стакан): {signal['price']}\n"
                f"Spread (3 уровня): {signal['spr3_pct']}%\n"
                f"Множитель (Rate): {signal['rate']}x\n\n"
                f"Объем первого уровня в USDT: {round(signal.get("row_vol_usdt", 0), 2) or "none"}\n\n"
                f"🔥 <b>Горячие цены:</b>\n"
                f"Binance: {b_price}\n"
                f"Phemex: {p_price}\n"                
                f"Binance/Phemex Spread_%: {round(binance_check.get("spread", 0), 4) or "none"}\n"
            )
            
            # Ставим глобальный кулдаун на монету
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

    async def run(self):
        logger.info("Скринер запущен. Получение символов Phemex...")
        symbols_info = await self.phemex_sym_api.get_all(quote="USDT", only_active=True)
        symbols = [s.symbol for s in symbols_info if s.symbol not in self.black_list]
        print(symbols)
        
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

        self._stream = PhemexStakanStream(
            symbols=symbols,
            depth=10,
            chunk_size=40,
            throttle_ms=0
        )
        
        logger.info("Подключение к WSS Phemex и подписка на стаканы...")
        await self._stream.run(self._on_depth_received)