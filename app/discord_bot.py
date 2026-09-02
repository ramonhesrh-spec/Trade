"""Discord bot die alleen luistert naar inkomende DM's. Geen serverrechten
nodig behalve View Channels en Read Message History op je eigen servertje,
zodat je de bot kan DM'en.

Elk binnengekomen DM bericht wordt opgeslagen met tijdstip en ruwe tekst.
Bijgevoegde afbeeldingen worden lokaal opgeslagen. Vanaf stap 3 wordt elk
nieuw bericht ook doorgegeven aan de verwerkingspijplijn.
"""
import asyncio
import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

import discord

from app import config

logger = logging.getLogger("discord_bot")

MessageHandler = Callable[[int, str, list[str]], Awaitable[None]]


def _build_intents() -> discord.Intents:
    intents = discord.Intents.none()
    intents.dm_messages = True
    intents.guilds = True  # nodig om lid te zijn van het eigen servertje
    intents.message_content = True  # vereist Message Content Intent aan te zetten
    return intents


class DMListenerBot(discord.Client):
    def __init__(self, on_dm: Optional[MessageHandler] = None):
        super().__init__(intents=_build_intents())
        self.on_dm = on_dm
        Path(config.IMAGE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)

    async def on_ready(self):
        logger.info("Discord bot ingelogd als %s, luistert naar DM's", self.user)

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return  # alleen DM's verwerken

        image_paths = await self._save_images(message)
        logger.info("DM ontvangen van %s: %r (%d afbeelding(en))",
                    message.author, message.content[:80], len(image_paths))

        # Late import om circulaire import met signal_processor te voorkomen.
        from app import repo
        message_id = repo.insert_message(message.content, image_paths)

        if self.on_dm is not None:
            try:
                await self.on_dm(message_id, message.content, image_paths)
            except Exception:
                logger.exception("Verwerking van bericht %s is mislukt", message_id)

    async def _save_images(self, message: discord.Message) -> list[str]:
        paths = []
        for i, attachment in enumerate(message.attachments):
            if not (attachment.content_type or "").startswith("image/"):
                continue
            filename = f"{message.id}_{i}_{attachment.filename}"
            dest = Path(config.IMAGE_STORAGE_PATH) / filename
            await attachment.save(dest)
            paths.append(str(dest))
        return paths


def run_bot(on_dm: Optional[MessageHandler] = None) -> None:
    if not config.DISCORD_BOT_TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN ontbreekt in .env")
    logging.basicConfig(level=logging.INFO)
    bot = DMListenerBot(on_dm=on_dm)
    bot.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    # Stap 2: alleen lezen en loggen, nog zonder interpretatie.
    run_bot(on_dm=None)
