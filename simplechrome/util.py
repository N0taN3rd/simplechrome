# -*- coding: utf-8 -*-
"""Utitlity functions."""
import asyncio
import gc
import socket
from asyncio import AbstractEventLoop
from typing import Any

__all__ = ["get_free_port", "noop"]


def get_free_port() -> int:
    """Get free port."""
    sock = socket.socket()
    sock.bind(("localhost", 0))
    port: int = sock.getsockname()[1]
    sock.close()
    del sock
    gc.collect()
    return port


def loop_factory() -> AbstractEventLoop:
    return asyncio.get_event_loop()


def noop(*args: Any, **kwargs: Any) -> None:
    """A simple no-operation function"""
    return None
