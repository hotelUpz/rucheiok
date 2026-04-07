# # git remote add origin git@github.com:hotelUpz/rucheiok3.git
# # git remote set-url origin git@github.com:hotelUpz/rucheiok3.git


# ## GOAL:

#    Нужно реализовать парсер по поиску монет паттерна "Дырявый стакан" по законам прописанным в конфигах. Биржа Phemex Futures. 
# 1. Символы берем из API/PHEMEX/symbol.py
# 2. По всем символам запускаем стрим парса стакана (ордер книги).

# 3. Ищем монеты и добавляем в список найденных, а после -- делаем пуш найденных монет в телеграм.
# Расшифровка конфигов:

# {
#     "app": {... сюда добавить служебные метрики},
#     "log": {...}
#     паттерн пхемекс касается исключительно ценовых показателей стакана, объемы не трогаем.
#     "pattern": {
#         "phemex": {
#             "enable": true,
#             "depth": 8, глубина стакана
#             попеременно проверяем наличее как лонгового паттерна так и шортового.
#             Для лонгового паттерна преимущественно оцениваем ситуацию в красной области стакана (аски), max_bid_ask_distance_rate проверяем как ((ближайший аск - ближайший бид) / ближайший бид) * 100
#             Для шортового -- нижнюю область стакана -- биды. max_bid_ask_distance_rate == abs((ближайший бид - ближайший ask) / ближайший ask) * 100
#             "header": {
#                 "roc_window": 3, -- берем верхние значение стакана (например аски для проверки на лонговыйй сценарий) и находим отношения одного аска к другому -- лесенкой до roc_window уровней вниз.
#                 "max_one_roc_pct": 0.5 -- то значение которое может быть максимальное для каждого из расчетных значений roc лесенки.
#             },
#             "body": {
#                 "roc_sma_window": 5 -- находим среднее арифметическое для roc_sma_window уровней стакана (сверху вниз, например для лонговой проверки от 8-го крайнего аска до 3-го вниз аска). Запоминаем это значение.
#             },
#             "bottom":{
#                 "min_spread_between_two_row_pct": 0.15, например для лонгового сценария -- процент между ближайшим, первым аском и вторым аском. Для шорта -- все то же только для бидов. Нужно чтобы была выполнена проверка что этот процент >= min_spread_between_two_row_pct
#                 "min_spread_between_three_row_pct": 0.3  например для лонгового сценария -- процент между ближайшим, первым аском и третьим аском. Для шорта -- все то же только для бидов. Нужно чтобы была выполнена проверка что этот процент >= min_spread_between_three_row_pct значения.              
#             },
#             "header_to_bottom_desired_rate": 4, отношение min_spread_between_three_row_pct к roc_sma_window (проценты к процентам). если выражаться не в процентах а в тиках, то например среднее количество тиков между каждым из асков от 8-го до 3-го уровней 2.5. Тогда минимум тиков для min_spread_between_three_row_pct спреда должно быть 10 то есть в 4 раза больше. Все то же только в процентах. header_to_bottom_desired_rate -- отношение, множитель.
#             "max_bid_ask_distance_rate": 0.5, максимально допустимая дистанция между ближайшими бидом и аском (без разницы для какого сценария лонгового или шортового). Формула: (ask1 - bid1) / (ask3 - ask1) <= max_bid_ask_distance_rate.
#             "pattern_ttl_sec": 0 -- период времени в секундах в течение которого паттерн должен соблюдаться. 0 -- отключена проверка.
#         },
#         "binance": {
#             "enable": true,
#             "min_price_spread_pct": 0.1, минимальный ценовой спред между ценой бинанса и пхемекс (по горячей цене). все фьючерсы. Для проверки лонгового сценария -- цена на бинанс выше чем на пхемекс. Для шортового наоборот. (Все это если вычислился основной паттерн). Не знаю запускать ли отдельно стрим или можно обойтись разовыми rest запросами через паузу (например каждые 2 секунды)
#             "spread_ttl_sec": 0 -- период времени в секундах в течение которого паттерн должен соблюдаться. 0 -- отключена проверка.
#         }
#     }
# }

# 4. Подправь consts.py под загрузку с .json

# 5. Найденные сигналы отправляй в канал через сендер. Сигналы кешируй. Кеш сбрасывай каждый час в секундах (установи этот параметр в конфигах). Символ помечай решеткой. К символу прикрепляй все ключевые расчетные метркики в моменте. также при первом запуске сканера отправляй список настроек (на понятном для юзера языке).



# ## CRITICAL:
# читай замечания в чате и в отденых модулях.








# ## IMPROVE


# 1. Добавить oil-показатель. OIL -- Open Interest Limit, специальный ответ после лимитного запроса (ошибка 11150). Уже есть. -- проверить.

# 2. Добавить фильтр фандинга ("funding_pattern1": {
#             "enable": true,
#             "check_interval_sec": 60,
#             "skip_before_counter_sec": 1800,
#             "threshold_pct": 2.0
#         },) -- граматно подключить файл funding_pattern1. Если > threshold_pct -- скип.
#         Уже есть. -- проверить.

# 3. Реализовать (
#         "funding_pattern2": {
#             "enable": true,
#             "check_interval_sec": 60,
#             "skip_before_counter_sec": 1800,
#             "diff_threshold_pct": 0.05
#         }
# ). Прицип работы: считаем дельту между фандингом бинанса и пхемекса (порядок не важен). Итоговое значение берем в abs(x) и сравниваем с пороговым diff_threshold_pct. если > diff_threshold_pct -- скип.

# И funding_pattern1 и funding_pattern2 можно калаборировать в некий блок_список, по истечение счетчика фандинга обнулять. Еще. При высчитывании фандинга между бинансом и пхемексом, естественно нужно чтобы их счетчики времени фандингов (лучше в секундах) совпадали. (Смотри Инварианты расчета)



# from __future__ import annotations

# class StakanPattern:
#     def __init__(self, phemex_cfg: dict):
#         self.cfg = phemex_cfg
#         self.depth = self.cfg.get("depth", 8)
#         self.min_first_row_usdt_notional = self.cfg.get("min_first_row_usdt_notional")

#     def analyze(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> dict | None:
#         if not self.cfg.get("enable", True):
#             return None
#         if len(bids) < self.depth or len(asks) < self.depth:
#             return None

#         # Проверяем лонг (работаем с асками)
#         long_signal = self._check_long(bids, asks)
#         if long_signal:
#             return long_signal

#         # Проверяем шорт (работаем с бидами)
#         short_signal = self._check_short(bids, asks)
#         if short_signal:
#             return short_signal

#         return None

#     def _check_long(self, bids: list, asks: list) -> dict | None:
#         # print(bids[:self.depth], asks[:self.depth])
#         ask1, bid1 = asks[0][0], bids[0][0]
#         ask2, ask3 = asks[1][0], asks[2][0]
#         bottom = self.cfg["bottom"]

#         ask1_vol_asset = asks[0][1]
#         ask1_vol_usdt = ask1_vol_asset * ask1
#         # print(ask1_vol_usdt)

#         if ask1_vol_usdt < self.min_first_row_usdt_notional: return None
        
#         # 1. Проценты между ближайшими асками (bottom)
#         spr2_pct = (ask2 - ask1) / ask1 * 100
#         if spr2_pct < bottom["min_spread_between_two_row_pct"]: return None

#         spr3_pct = (ask3 - ask1) / ask1 * 100
#         if spr3_pct < bottom["min_spread_between_three_row_pct"]: return None

#         # 2. Дистанция bid/ask (Используем формулу из конфига: (ask1 - bid1) / (ask3 - ask1))
#         dist_denom = ask3 - ask1
#         if dist_denom <= 0: return None # Защита от деления на ноль и аномалий стакана
        
#         dist_rate = (ask1 - bid1) / dist_denom
#         if dist_rate > self.cfg["max_bid_ask_distance_rate"]: return None

#         # 3. Лесенка ROC (header & body)
#         header, body = self.cfg["header"], self.cfg["body"]
#         roc_window, roc_sma_window = header["roc_window"], body["roc_sma_window"]

#         rocs = []
#         # От 8-го крайнего аска вниз (считаем разницу между соседями)
#         for i in range(self.depth - 1, self.depth - 1 - roc_sma_window, -1):
#             roc = (asks[i][0] - asks[i-1][0]) / asks[i-1][0] * 100
#             rocs.append(roc)

#         # Проверяем только верхние roc_window уровней на превышение
#         if any(r > header["max_one_roc_pct"] for r in rocs[:roc_window]):
#             return None

#         roc_sma = sum(rocs) / len(rocs) if rocs else 0.000001
#         roc_sma = max(roc_sma, 0.000001)
#         # print(f"ROC SMA: {roc_sma:.6f}, SPR3%: {spr3_pct:.4f}, Rate: {spr3_pct / roc_sma:.2f}")

#         # 4. Множитель (header_to_bottom_desired_rate)
#         rate = spr3_pct / roc_sma
#         if rate < self.cfg["header_to_bottom_desired_rate"]: return None

#         return {"side": "LONG", "price": ask1, "spr3_pct": round(spr3_pct, 4), "rate": round(rate, 2), "row_vol_usdt": ask1_vol_usdt}

#     def _check_short(self, bids: list, asks: list) -> dict | None:
#         ask1, bid1 = asks[0][0], bids[0][0]
#         bid2, bid3 = bids[1][0], bids[2][0]
#         bottom = self.cfg["bottom"]

#         bid1_vol_asset = bids[0][1]
#         bid1_vol_usdt = bid1_vol_asset * bid1
#         # print(bid1_vol_usdt)

#         if bid1_vol_usdt < self.min_first_row_usdt_notional: return None
        
#         # 1. Проценты между ближайшими бидами (bottom) - биды идут по убыванию
#         spr2_pct = (bid1 - bid2) / bid1 * 100
#         if spr2_pct < bottom["min_spread_between_two_row_pct"]: return None

#         spr3_pct = (bid1 - bid3) / bid1 * 100
#         if spr3_pct < bottom["min_spread_between_three_row_pct"]: return None

#         # 2. Дистанция bid/ask (Для шорта знаменатель: bid1 - bid3)
#         dist_denom = bid1 - bid3
#         if dist_denom <= 0: return None
        
#         dist_rate = (ask1 - bid1) / dist_denom
#         if dist_rate > self.cfg["max_bid_ask_distance_rate"]: return None

#         # 3. Лесенка ROC (header & body)
#         header, body = self.cfg["header"], self.cfg["body"]
#         roc_window, roc_sma_window = header["roc_window"], body["roc_sma_window"]

#         rocs = []
#         # От 8-го крайнего бида вверх (считаем разницу между соседями)
#         for i in range(self.depth - 1, self.depth - 1 - roc_sma_window, -1):
#             roc = (bids[i-1][0] - bids[i][0]) / bids[i-1][0] * 100
#             rocs.append(roc)

#         if any(r > header["max_one_roc_pct"] for r in rocs[:roc_window]):
#             return None

#         roc_sma = sum(rocs) / len(rocs) if rocs else 0.000001
#         roc_sma = max(roc_sma, 0.000001)

#         rate = spr3_pct / roc_sma
#         if rate < self.cfg["header_to_bottom_desired_rate"]: return None

#         return {"side": "SHORT", "price": bid1, "spr3_pct": round(spr3_pct, 4), "rate": round(rate, 2), "row_vol_usdt": bid1_vol_usdt}