"""Convenience entry point for running the BoxingBot CLI."""

import asyncio

from boxing_bot.bot import main


if __name__ == "__main__":
    asyncio.run(main())