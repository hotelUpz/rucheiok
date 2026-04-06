from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING
import pytz
from decimal import Decimal, ROUND_DOWN

from API.PHEMEX.client import PhemexPrivateClient
from c_log import UnifiedLogger
from consts import TIME_ZONE
from dotenv import load_dotenv

if TYPE_CHECKING:
    from API.PHEMEX.symbol import SymbolInfo

load_dotenv()

logger = UnifiedLogger(name="bot")

TZ = pytz.timezone(TIME_ZONE)
ERRORS_FILE = "oi_errors.json"


def round_step(value: float, step: float) -> float:
    if not step or step <= 0:
        return value
    val_d = Decimal(str(value))
    step_d = Decimal(str(step))
    rounded = (val_d / step_d).quantize(Decimal("1"), rounding=ROUND_DOWN) * step_d
    return float(rounded)


class OpenInterestDefender:
    def __init__(self, config: dict):
        self.config = config

        self.pos_mode = "hedged"
        self.api_key = os.getenv("api_key") or ""
        self.api_secret = os.getenv("api_secret") or ""

        self.pos_side = self.config.get("pos_side", "").upper() or "LONG"
        self.leverage = self.config.get("leverage", 10)
        self.margin_amount = self.config.get("margin_amount", 3.5)
        self.indentation_pct = self.config.get("order_indentation_pct", 25)

        self.client = PhemexPrivateClient(self.api_key, self.api_secret)

    async def is_oil(self, symbol: str, price: float, sym_info: "SymbolInfo"):
        if not price:
            logger.warning(f"[{symbol}] Пропуск: нет цены.")
            return "ERR_NO_PRICE"

        tick_size = sym_info.tick_size
        lot_size = sym_info.lot_size

        if tick_size is None or lot_size is None:
            logger.warning(
                f"[{symbol}] Пропуск: отсутствует спецификация "
                f"tick_size={tick_size}, lot_size={lot_size}"
            )
            return "ERR_NO_SPEC"

        if self.pos_side == "LONG":
            order_price = price * (1 - self.indentation_pct / 100.0)
            side = "Buy"
        else:
            order_price = price * (1 + self.indentation_pct / 100.0)
            side = "Sell"

        phemex_pos_side = self.pos_side.capitalize()
        order_price = round_step(order_price, tick_size)

        if order_price <= 0:
            logger.warning(f"[{symbol}] Пропуск: некорректная цена ордера {order_price}")
            return "ERR_BAD_PRICE"

        notional_value = self.margin_amount * self.leverage
        actual_notional = max(6.0, notional_value)

        qty = max(lot_size, actual_notional / order_price)
        qty = round_step(qty, lot_size)

        if qty <= 0:
            logger.warning(f"[{symbol}] Пропуск: некорректный qty {qty}")
            return "ERR_BAD_QTY"

        try:
            resp = await self.client.place_order(symbol, side, qty, order_price, phemex_pos_side)
            code = resp.get("code", -1)

            if code == 0:
                data_dict = resp.get("data") or {}
                order_id = data_dict.get("orderID") or data_dict.get("orderId")

                if order_id:
                    cancel_resp = await self.client.cancel_order(symbol, order_id, phemex_pos_side)
                    if cancel_resp.get("code", -1) == 0:
                        logger.info(f"[{symbol}] 🗑️ Ордер {order_id} моментально отменен.")
                    else:
                        logger.error(f"[{symbol}] ❌ ОШИБКА ОТМЕНЫ ОРДЕРА! {cancel_resp}")
                else:
                    logger.error(f"[{symbol}] code=0, но order_id не найден в ответе: {resp}")

                logger.info(f"[{symbol}] OIL: False.")
                return False

            if code == 11150:
                logger.info(f"[{symbol}] OIL: True.")
                return True

            return f"ERR_{code}"

        except asyncio.TimeoutError:
            logger.warning(f"[{symbol}] Таймаут ожидания ответа от биржи!")
            return "ERR_TIMEOUT"

        except Exception as e:
            logger.error(f"[{symbol}] Исключение при отправке/отмене: {e}")
            return "ERR_EXCEPTION"