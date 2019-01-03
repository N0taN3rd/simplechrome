# -*- coding: utf-8 -*-
"""Utitlity functions."""
import asyncio
from asyncio import AbstractEventLoop
import gc
import socket
from typing import Dict, Optional, Any

from aiohttp import AsyncResolver, ClientSession, TCPConnector

__all__ = ["get_free_port", "merge_dict", "ensure_loop", "make_aiohttp_session"]


def get_free_port() -> int:
    """Get free port."""
    sock = socket.socket()
    sock.bind(("localhost", 0))
    port: int = sock.getsockname()[1]
    sock.close()
    del sock
    gc.collect()
    return port


def merge_dict(dict1: Optional[Dict], dict2: Optional[Dict]) -> Dict[str, Any]:
    new_dict = {}
    if dict1:
        new_dict.update(dict1)
    if dict2:
        new_dict.update(dict2)
    return new_dict


def loop_factory() -> AbstractEventLoop:
    return asyncio.get_event_loop()


def ensure_loop(loop: Optional[AbstractEventLoop] = None) -> AbstractEventLoop:
    """Helper method for checking if the loop is none and if so use asyncio.get_event_loop
    to retrieve it otherwise the loop is passed through
    """
    if loop is not None:
        return loop
    return asyncio.get_event_loop()


def make_aiohttp_session(loop: Optional[AbstractEventLoop] = None) -> ClientSession:
    """Creates and returns a new aiohttp.ClientSession that uses AsyncResolver

    :param loop: Optional asyncio event loop to use. Defaults to asyncio.get_event_loop()
    :return: An instance of aiohttp.ClientSession
    """
    if loop is None:
        loop = asyncio.get_event_loop()
    return ClientSession(
        connector=TCPConnector(resolver=AsyncResolver(loop=loop), loop=loop), loop=loop
    )
