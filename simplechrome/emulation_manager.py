"""Emulation Manager module."""
from typing import Any, Dict, List, Optional, Set

from ._typings import Number
from .connection import ClientType
from .helper import Helper

__all__ = ["EmulationManager"]


class EmulationManager:
    """This domain emulates different environments for the page"""

    __slots__: List[str] = [
        "_client",
        "_emulatingMedia",
        "_emulatingMobile",
        "_hasTouch",
        "_injectedTouchScriptId",
        "_scriptExecutionDisabled",
        "_supportedMedia",
    ]

    def __init__(self, client: ClientType) -> None:
        """Initialize a new instance of EmulationManager

        :param client: The client to be used to communicate with the remote browser
        """
        self._client: ClientType = client
        self._emulatingMobile: bool = False
        self._injectedTouchScriptId: Optional[str] = None
        self._supportedMedia: Set[str] = {"screen", "print", ""}
        self._emulatingMedia: str = ""
        self._hasTouch: bool = False
        self._scriptExecutionDisabled: bool = False

    @property
    def emulatingMobile(self) -> bool:
        """Is mobile emulating currently active"""
        return self._emulatingMobile

    @property
    def emulatingTouch(self) -> bool:
        """Is touch emulating currently active"""
        return self._hasTouch

    @property
    def isScriptExecutionDisabled(self) -> bool:
        """Is JS allowed to run"""
        return self._scriptExecutionDisabled

    @property
    def emulatedMedia(self) -> str:
        """The media type being emulated"""
        return self._emulatingMedia

    async def isEmulationSupported(self) -> bool:
        """Tells whether emulation is supported"""
        results = await self._client.send("Emulation.canEmulate", {})
        return results.get("result")

    async def clearDeviceMetricsOverride(self) -> None:
        """Clears the overridden device metrics"""
        await self._client.send("Emulation.clearDeviceMetricsOverride", {})

    async def clearGeolocationOverride(self) -> None:
        """Clears the overridden Geolocation Position and Error"""
        await self._client.send("Emulation.clearGeolocationOverride", {})

    async def setPageScaleFactor(self, factor: Number) -> None:
        """Sets a specified page scale factor. Experimental

        :param factor: Page scale factor
        """
        if not Helper.is_number(factor):
            raise Exception(f"The factor argument must be a string got {type(factor)}")
        await self._client.send(
            "Emulation.setPageScaleFactor", {"pageScaleFactor": factor}
        )

    async def setScrollbarsHidden(self, hidden: bool) -> None:
        """Experimental

        :param hidden: Whether scrollbars should be always hidden.
        """
        if not Helper.is_number(hidden):
            raise Exception(f"The hidden argument must be a string got {type(hidden)}")
        await self._client.send(
            "Emulation.setScrollbarsHidden", {"hidden": hidden}
        )

    async def setDocumentCookieDisabled(self, disabled: bool) -> None:
        """Experimental

        :param disabled: Whether document.coookie API should be disabled.
        """
        if not Helper.is_number(disabled):
            raise Exception(f"The disabled argument must be a string got {type(disabled)}")
        await self._client.send(
            "Emulation.setDocumentCookieDisabled", {"disabled": disabled}
        )

    async def setGeolocation(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        """Overrides the Geolocation Position or Error.
        Omitting any of the parameters emulates position unavailable.

        Options:
          - latitude: Mock latitude
          - longitude: Mock longitude
          - accuracy: Mock accuracy

        :param options: Geolocation emulation options supplied as a dict
        :param kwargs: Geolocation emulation options supplied a kwargs
        """
        geo = Helper.merge_dict(options, kwargs)
        await self._client.send("Emulation.setGeolocation", geo)

    async def setUserAgentOverride(
        self,
        userAgent: str,
        platform: Optional[str] = None,
        acceptLanguage: Optional[str] = None,
    ) -> None:
        """Allows overriding user agent with the given string.

        :param userAgent: User agent to use
        :param platform: Optional Browser language to emulate
        :param acceptLanguage: Optional The platform navigator.platform should return
        """
        if not Helper.is_string(userAgent):
            raise Exception(
                f"The userAgent argument must be a string got {type(userAgent)}"
            )
        overrides = {"userAgent": userAgent}
        if Helper.is_string(platform):
            overrides["platform"] = platform
        if Helper.is_string(acceptLanguage):
            overrides["acceptLanguage"] = acceptLanguage
        await self._client.send("Emulation.setUserAgentOverride", overrides)

    async def setNavigatorPlatformOverride(self, platForm: str) -> None:
        """Allows overriding the value returned by navigator.platform

        :param platForm: The platform navigator.platform should return
        """
        if not Helper.is_string(platForm):
            raise Exception(
                f"The platForm argument must be a string got {type(platForm)}"
            )
        version = await self._client.send("Browser.getVersion", {})
        await self.setUserAgentOverride(version["userAgent"], platform=platForm)

    async def setAcceptLanguageOverride(self, language: str) -> None:
        """Allows overriding the value of the Accept-Language HTTP header

        :param language: The language to use
        """
        if not Helper.is_string(language):
            raise Exception(
                f"The language argument must be a string got {type(language)}"
            )
        version = await self._client.send("Browser.getVersion", {})
        await self.setUserAgentOverride(version["userAgent"], acceptLanguage=language)

    async def setScriptExecutionDisabled(self, disabled: bool) -> None:
        """Switches script execution in the page

        :param disabled: Whether script execution should be disabled in the page
        """
        if not Helper.is_boolean(disabled):
            raise Exception(
                f"The disabled argument must be a bool got {type(disabled)}"
            )
        await self._client.send(
            "Emulation.setScriptExecutionDisabled", {"disabled": disabled}
        )
        self._scriptExecutionDisabled = disabled

    async def setEmulatedMedia(self, media: str = "") -> None:
        """Emulates the given media for CSS media queries

        :param media: Media type to emulate. Empty string disables the override
        """
        if not Helper.is_string(media):
            raise Exception(f"The media argument must be a string got {type(media)}")
        if media not in self._supportedMedia:
            raise Exception(f"Unsupported media type: {media}")
        await self._client.send("Emulation.setEmulatedMedia", {"media": media})
        self._emulatingMedia = media

    async def setDeviceMetricsOverride(
        self, options: Optional[Dict] = None, **kwargs: Any
    ) -> bool:
        """Overrides the values of device screen dimensions:
            - window.screen.width
            - window.screen.height
            - window.innerWidth
            - window.innerHeight
            - "device-width"/"device-height"-related CSS media query results

        :param options: Override options supplied as a dict
        :param kwargs: Override options supplied as a kwargs
        :return: T/F indicating if a page reload is required
        """
        overrides = Helper.merge_dict(options, kwargs)
        if not Helper.is_number(overrides.get("width")):
            raise Exception("The width override is required")
        if not Helper.is_number(overrides.get("height")):
            raise Exception("The height override is required")
        if not Helper.is_number(overrides.get("deviceScaleFactor")):
            raise Exception("The deviceScaleFactor override is required")
        mobile = overrides.get("mobile", False)
        reloadNeeded = self._emulatingMobile != mobile
        self._emulatingMobile = mobile
        overrides["mobile"] = mobile
        await self._client.send("Emulation.setDeviceMetricsOverride", options)
        return reloadNeeded

    async def emulateViewport(
        self, viewport: Optional[Dict] = None, **kwargs: Any
    ) -> bool:
        """Evaluate viewport.
        :param viewport: Viewport emulation options supplied as a dict
        :param kwargs: Viewport emulation options supplied a kwargs
        :return: T/F indicating if a page reload is required
        """
        options = Helper.merge_dict(viewport, kwargs)
        mobile = options.get("isMobile", False)
        hasTouch = options.get("hasTouch", False)
        maxTouchPoints = options.get("maxTouchPoints", 1)
        deviceScaleFactor = options.get("deviceScaleFactor", 1)
        options["mobile"] = mobile
        options["deviceScaleFactor"] = deviceScaleFactor

        if options.get("isLandscape"):
            options["screenOrientation"] = {"angle": 90, "type": "landscapePrimary"}
        else:
            options["screenOrientation"] = {"angle": 0, "type": "portraitPrimary"}

        Helper.remove_dict_keys(options, "isLandscape", "hasTouch", "maxTouchPoints")

        await self._client.send("Emulation.setDeviceMetricsOverride", options)
        await self._client.send(
            "Emulation.setTouchEmulationEnabled",
            {"enabled": hasTouch, "maxTouchPoints": maxTouchPoints},
        )

        reloadNeeded = self._emulatingMobile != mobile or self._hasTouch != hasTouch
        self._hasTouch = hasTouch
        self._emulatingMobile = mobile
        return reloadNeeded
