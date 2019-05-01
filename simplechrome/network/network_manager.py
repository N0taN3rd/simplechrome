"""Network Manager module."""

import asyncio
from typing import Awaitable, Dict, List, Optional, Set

from pyee2 import EventEmitterS

from simplechrome._typings import CDPEvent, HTTPHeaders, OptionalLoop, SlotsT
from simplechrome.connection import ClientType
from simplechrome.events import Events
from simplechrome.frame_manager import FrameManager
from simplechrome.helper import Helper
from .network_idle_monitor import NetworkIdleMonitor
from .request_response import Request, Response

__all__ = ["NetworkManager"]


class NetworkManager(EventEmitterS):
    """NetworkManager class."""

    __slots__: SlotsT = [
        "__weakref__",
        "_client",
        "_frameManager",
        "_requestIdToRequest",
        "_interceptionIdToRequest",
        "_requestIdToRequestWillBeSentEvent",
        "_extraHTTPHeaders",
        "_offline",
        "_credentials",
        "_offline",
        "_attemptedAuthentications",
        "_userRequestInterceptionEnabled",
        "_protocolRequestInterceptionEnabled",
        "_requestIdToInterceptionId",
        "_userCacheDisabled",
        "_sw_bypass",
        "_userAgent",
        "_ignoreHTTPSErrors",
    ]

    def __init__(
        self,
        client: ClientType,
        ignoreHTTPSErrors: bool = False,
        loop: OptionalLoop = None,
    ) -> None:
        """Make new NetworkManager."""
        super().__init__(loop=Helper.ensure_loop(loop))
        self._client: ClientType = client
        self._frameManager: Optional["FrameManager"] = None
        self._offline: bool = False
        self._userCacheDisabled: bool = False
        self._userRequestInterceptionEnabled: bool = False
        self._protocolRequestInterceptionEnabled: bool = False
        self._requestIdToRequest: Dict[str, Request] = {}
        self._interceptionIdToRequest: Dict[str, Request] = {}
        self._extraHTTPHeaders: HTTPHeaders = {}
        self._credentials: Optional[Dict[str, str]] = None
        self._attemptedAuthentications: Set[str] = set()
        self._requestIdToRequestWillBeSentEvent: Dict[str, Dict] = {}
        self._requestIdToInterceptionId: Dict[str, str] = {}
        self._userAgent: Optional[str] = None
        self._sw_bypass: bool = False
        self._ignoreHTTPSErrors: bool = ignoreHTTPSErrors

        self._client.on("Network.requestWillBeSent", self._onRequestWillBeSent)
        self._client.on(
            "Network.requestServedFromCache", self._onRequestSeveredFromCache
        )  # noqa: #501
        self._client.on("Network.responseReceived", self._onResponseReceived)
        self._client.on("Network.loadingFinished", self._onLoadingFinished)
        self._client.on("Network.loadingFailed", self._onLoadingFailed)
        self._client.on("Fetch.requestPaused", self._onRequestPaused)
        self._client.on("Fetch.authRequired", self._onAuthRequired)

    @property
    def service_workers_bypassed(self) -> bool:
        return self._sw_bypass

    def network_idle_promise(
        self, num_inflight: int = 2, idle_time: int = 2, global_wait: int = 60
    ) -> Awaitable[None]:
        return NetworkIdleMonitor.monitor(
            self._client,
            num_inflight=num_inflight,
            idle_time=idle_time,
            global_wait=global_wait,
            loop=self._loop,
        )

    def setFrameManager(self, frameManager: "FrameManager") -> None:
        self._frameManager = frameManager

    def extraHTTPHeaders(self) -> HTTPHeaders:
        """Get extra http headers."""
        return dict(**self._extraHTTPHeaders)

    async def initialize(self) -> None:
        await self._client.send("Network.enable")
        if self._ignoreHTTPSErrors:
            await self._client.send(
                "Security.setIgnoreCertificateErrors",
                {"ignore": self._ignoreHTTPSErrors},
            )

    async def enableNetworkCache(self) -> None:
        """Sets the network cache enabled state to true"""
        await self.setCacheEnabled(True)

    async def disableNetworkCache(self) -> None:
        """Sets the network cache enabled state to false"""
        await self.setCacheEnabled(False)

    async def authenticate(self, credentials: Dict[str, str]) -> None:
        """Provide credentials for http auth."""
        self._credentials = credentials
        await self._updateProtocolRequestInterception()

    async def clearBrowserCache(self) -> None:
        """Clears browser cache"""
        await self._client.send("Network.clearBrowserCache", {})

    async def clearBrowserCookies(self) -> None:
        """Clears browser cookies"""
        await self._client.send("Network.clearBrowserCookies", {})

    async def setBypassServiceWorker(self, bypass: bool) -> None:
        """Toggles ignoring of service worker for each request. Experimental

        :param bypass: Should service workers be bypassed
        """
        if self._sw_bypass == bypass:
            return
        self._sw_bypass = bypass
        await self._client.send("Network.setBypassServiceWorker", {"bypass": bypass})

    async def setCacheEnabled(self, enabled: bool) -> None:
        """Sets the enabled state of the network cache"""
        self._userCacheDisabled = not enabled
        await self._updateProtocolCacheDisabled()

    async def setExtraHTTPHeaders(self, extraHTTPHeaders: HTTPHeaders) -> None:
        """Set extra http headers."""
        self._extraHTTPHeaders = {}
        for k, v in extraHTTPHeaders.items():
            if not isinstance(v, str):
                raise TypeError(
                    f'Expected value of header "{k}" to be string, but "{type(v)}" is found.'
                )
            self._extraHTTPHeaders[k] = v
        await self._client.send(
            "Network.setExtraHTTPHeaders", {"headers": self._extraHTTPHeaders}
        )

    async def setOfflineMode(self, value: bool) -> None:
        """Change offline mode enable/disable."""
        if self._offline == value:
            return
        self._offline = value
        await self._client.send(
            "Network.emulateNetworkConditions",
            {
                "offline": self._offline,
                "latency": 0,
                "downloadThroughput": -1,
                "uploadThroughput": -1,
            },
        )

    async def setAcceptLanguage(self, language: str) -> None:
        if self._userAgent is None:
            version = await self._client.send("Browser.getVersion", {})
            self._userAgent = version["userAgent"]
        await self._client.send(
            "Network.setUserAgentOverride",
            {"userAgent": self._userAgent, "acceptLanguage": language},
        )

    async def setNavigatorPlatform(self, platform: str) -> None:
        if self._userAgent is None:
            version = await self._client.send("Browser.getVersion", {})
            self._userAgent = version["userAgent"]
        await self._client.send(
            "Network.setUserAgentOverride",
            {"userAgent": self._userAgent, "platform": platform},
        )

    async def setUserAgent(self, userAgent: str) -> None:
        if not Helper.is_string(userAgent):
            raise Exception(
                f"The userAgent is required to be string, got {type(userAgent)}"
            )
        self._userAgent = userAgent
        await self._client.send(
            "Network.setUserAgentOverride", {"userAgent": userAgent}
        )

    async def setRequestInterception(self, value: bool) -> None:
        """Enable request interception."""
        self._userRequestInterceptionEnabled = value
        await self._updateProtocolRequestInterception()

    async def _updateProtocolRequestInterception(self) -> None:
        enabled = self._userRequestInterceptionEnabled or bool(self._credentials)
        if enabled == self._protocolRequestInterceptionEnabled:
            return
        self._protocolRequestInterceptionEnabled = enabled
        if enabled:
            patterns = [{"urlPattern": "*"}] if enabled else []
            await asyncio.gather(
                self._updateProtocolCacheDisabled(),
                self._client.send("Fetch.enable", {"patterns": patterns}),
            )
        else:
            await asyncio.gather(
                self._updateProtocolCacheDisabled(), self._client.send("Fetch.disable")
            )

    async def _updateProtocolCacheDisabled(self) -> None:
        await self._client.send(
            "Network.setCacheDisabled",
            {
                "cacheDisabled": self._userCacheDisabled
                or self._protocolRequestInterceptionEnabled
            },
        )

    def _onRequestWillBeSent(self, event: CDPEvent) -> None:
        if self._protocolRequestInterceptionEnabled and not event["request"].get(
            "url", ""
        ).startswith("data:"):
            requestId = event.get("requestId")
            interceptionId = self._requestIdToInterceptionId.get(requestId)
            if interceptionId:
                self._onRequest(event, interceptionId)
                self._requestIdToInterceptionId.pop(requestId, None)
            else:
                self._requestIdToRequestWillBeSentEvent[requestId] = event
            return
        self._onRequest(event, None)

    def _onRequest(self, event: CDPEvent, interceptionId: Optional[str] = None) -> None:
        redirectChain: List[Request] = []
        requestId = event.get("requestId")
        if event.get("redirectResponse") is not None:
            request = self._requestIdToRequest.get(requestId)
            # If we connect late to the target, we could have missed the requestWillBeSent event.
            if request is not None:
                self._handleRequestRedirect(request, event)
                redirectChain = request._redirectChain
        frame = None
        if self._frameManager is not None and event.get("frameId") is not None:
            frame = self._frameManager.frame(event.get("frameId"))
        request = Request(
            self._client,
            event,
            frame,
            interceptionId,
            self._userRequestInterceptionEnabled,
            redirectChain,
        )
        self._requestIdToRequest[requestId] = request
        self.emit(Events.NetworkManager.Request, request)

    def _onRequestSeveredFromCache(self, event: CDPEvent) -> None:
        request = self._requestIdToRequest.get(event.get("requestId"))
        if request is not None:
            request._fromMemoryCache = True

    def _handleRequestRedirect(self, request: Request, event: CDPEvent) -> None:
        newEvent: Dict = dict(**event)
        newEvent["response"] = event.get("redirectResponse")
        newEvent.pop("redirectResponse", None)
        response = Response(self._client, request, newEvent, loop=self._loop)
        request._redirectChain.append(request)
        request._response = response
        response._bodyLoadedPromise.set()
        self._requestIdToRequest.pop(request.requestId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(Events.NetworkManager.Response, response)
        self.emit(Events.NetworkManager.RequestFinished, request)

    def _onResponseReceived(self, event: CDPEvent) -> None:
        request = self._requestIdToRequest.get(event["requestId"])
        # FileUpload sends a response without a matching request.
        if request is None:
            return
        response = Response(self._client, request, event, loop=self._loop)
        request._response = response
        self.emit(Events.NetworkManager.Response, response)

    def _onLoadingFinished(self, event: CDPEvent) -> None:
        request = self._requestIdToRequest.get(event.get("requestId", ""))
        # For certain requestIds we never receive requestWillBeSent event.
        # @see https://crbug.com/750469
        if request is None:
            return
        # Under certain conditions we never get the Network.responseReceived
        # event from protocol. @see https://crbug.com/883475
        response = request._response
        if response is not None:
            response._bodyLoadedPromise.set()
        self._requestIdToRequest.pop(request.requestId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(Events.NetworkManager.RequestFinished, request)

    def _onLoadingFailed(self, event: CDPEvent) -> None:
        request = self._requestIdToRequest.get(event["requestId"])
        # For certain requestIds we never receive requestWillBeSent event.
        # @see https://crbug.com/750469
        if request is None:
            return
        request._failureText = event.get("errorText")
        request._wasCanceled = event.get("canceled")
        request._blockedReason = event.get("blockedReason")
        request._type = event.get("type", request._type)
        response = request._response
        if response is not None:
            response._bodyLoadedPromise.set()
        self._requestIdToRequest.pop(request.requestId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(Events.NetworkManager.RequestFailed, request)

    def _onAuthRequired(self, event: CDPEvent) -> None:
        requestId = event.get("requestId")
        response = "Default"
        if requestId in self._attemptedAuthentications:
            response = "CancelAuth"
        elif self._credentials:
            response = "ProvideCredentials"
            self._attemptedAuthentications.add(requestId)
        authChallengeResponse = {"response": response}
        if self._credentials:
            authChallengeResponse["username"] = self._credentials["username"]
            authChallengeResponse["password"] = self._credentials["password"]
        self._loop.create_task(
            self._client.send(
                "Fetch.continueWithAuth",
                {
                    "requestId": requestId,
                    "authChallengeResponse": authChallengeResponse,
                },
            )
        )

    def _onRequestPaused(self, event: CDPEvent) -> None:
        if (
            not self._userRequestInterceptionEnabled
            and self._protocolRequestInterceptionEnabled
        ):
            self._loop.create_task(
                self._client.send(
                    "Fetch.continueRequest", {"requestId": event.get("requestId")}
                )
            )
            return
        requestId = event.get("networkId")
        interceptionId = event.get("requestId")
        if requestId and requestId in self._requestIdToRequestWillBeSentEvent:
            requestWillBeSentEvent = self._requestIdToRequestWillBeSentEvent.pop(
                requestId, None
            )
            self._onRequest(requestWillBeSentEvent, interceptionId)
            return
        self._requestIdToInterceptionId[requestId] = interceptionId
