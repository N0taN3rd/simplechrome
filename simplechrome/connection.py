# -*- coding: utf-8 -*-

from cripy.client import Client, TargetSession, connect

__all__ = ["Client", "TargetSession", "createForWebSocket"]


async def createForWebSocket(url: str) -> Client:
    return await connect(url, remote=True)
