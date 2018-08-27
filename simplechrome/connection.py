# -*- coding: utf-8 -*-
import logging

from cripy.client import Client, TargetSession

__all__ = ["Client", "TargetSession", "createForWebSocket"]

logger = logging.getLogger(__name__)


async def createForWebSocket(url: str) -> Client:
    return await Client(url)
