# -*- coding: utf-8 -*-
"""Utitlity functions."""

from asyncio import AbstractEventLoop, get_event_loop
import gc
import socket
from typing import Dict, Optional, Any

__all__ = ["get_free_port", "merge_dict", "ensure_loop"]


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
    return get_event_loop()


def ensure_loop(loop: Optional[AbstractEventLoop] = None) -> AbstractEventLoop:
    """Helper method for checking if the loop is none and if so use asyncio.get_event_loop
    to retrieve it otherwise the loop is passed through
    """
    if loop is not None:
        return loop
    return get_event_loop()
