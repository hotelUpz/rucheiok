from __future__ import annotations

import asyncio
import sys

from consts import _CFG
from CORE.bot import ScreenerBot
from c_log import UnifiedLogger

logger = UnifiedLogger("main")

async def _main() -> None:
    if not _CFG:
        logger.error("Ошибка: конфиг cfg.json не загружен или пуст! Остановка.")
        sys.exit(1)

    bot = ScreenerBot(_CFG)
    
    try:
        await bot.run()
    except asyncio.CancelledError:
        logger.info("Получен сигнал отмены работы скринера.")
    except Exception as e:
        logger.exception(f"Аварийная остановка скринера: {e}")
    finally:
        await bot.aclose()
        logger.info("API коннекты закрыты. Скринер остановлен.")

if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n[!] Скринер остановлен пользователем (Ctrl+C).")


# chmod 600 ssh_key.txt
# eval "$(ssh-agent -s)"
# ssh-add ssh_key.txt
# source .ssh-autostart.sh
# ssh -T git@github.com
# git log -1  