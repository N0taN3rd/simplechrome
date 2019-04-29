"""Dialog module."""
from typing import ClassVar

from ._typings import CDPEvent
from .connection import ClientType

__all__ = ["Dialog", "DialogType"]


class DialogType:
    Alert: ClassVar[str] = "alert"
    BeforeUnload: ClassVar[str] = "beforeunload"
    Confirm: ClassVar[str] = "confirm"
    Prompt: ClassVar[str] = "prompt"


class Dialog:
    """Dialog class.

    Dialog objects are dispatched by page via the ``dialog`` event.
    """

    __slots__ = ["_client", "_dialog_event", "_handled"]

    def __init__(self, client: ClientType, event: CDPEvent) -> None:
        """Initialize a new Dialog instance

        :param client: The client to be used to communicate with the remote browser
        :param event: The CDP event dict received with Runtime.consoleAPICalled
        """
        self._client: ClientType = client
        self._dialog_event: CDPEvent = event
        self._handled: bool = False

    @property
    def type(self) -> str:
        """The type of the dialog"""
        return self._dialog_event.get("type")

    @property
    def message(self) -> str:
        """The dialog's message"""
        return self._dialog_event.get("message", "")

    @property
    def defaultValue(self) -> str:
        """Default dialog prompt"""
        return self._dialog_event.get("defaultPrompt", "")

    @property
    def url(self) -> str:
        """The URL of the Frame the dialog opened in"""
        return self._dialog_event.get("url", "")

    @property
    def hasBrowserHandler(self) -> bool:
        """True iff browser is capable showing or acting on the given dialog.
        When browser has no dialog handler for given target, calling alert
        while Page domain is engaged will stall the page execution.
        Execution can be resumed via calling either accept or dismiss
        """
        return self._dialog_event.get("hasBrowserHandler", "")

    @property
    def handled(self) -> bool:
        return self._handled

    async def accept(self, promptText: str = "") -> None:
        """Accept the dialog.

        * ``promptText`` (str): A text to enter in prompt. If the dialog's type
          is not prompt, this does not cause any effect.
        """
        self._handled = True
        await self._client.send(
            "Page.handleJavaScriptDialog", {"accept": True, "promptText": promptText}
        )

    async def dismiss(self) -> None:
        """Dismiss the dialog."""
        self._handled = True
        await self._client.send("Page.handleJavaScriptDialog", {"accept": False})

    def __str__(self) -> str:
        return f"Dialog(type={self.type}, handled={self._handled})"

    def __repr__(self) -> str:
        return self.__str__()
