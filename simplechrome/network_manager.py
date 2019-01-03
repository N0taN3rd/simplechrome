"""Network Manager module."""

import asyncio
import base64
import ujson as json
from asyncio import Future, AbstractEventLoop
from collections import OrderedDict
from typing import Awaitable, Dict, Optional, Union, Set, List, ClassVar
from urllib.parse import unquote

import attr
from pyee import EventEmitter

from .connection import ClientType
from .errors import NetworkError
from .frame_manager import FrameManager, Frame
from .multimap import Multimap
from .util import ensure_loop

__all__ = ["NetworkManager", "Request", "Response", "SecurityDetails"]


@attr.dataclass(slots=True, frozen=True)
class NetworkEvents(object):
    Request: str = attr.ib(default="request")
    Response: str = attr.ib(default="response")
    RequestFailed: str = attr.ib(default="requestfailed")
    RequestFinished: str = attr.ib(default="requestfinished")


class NetworkManager(EventEmitter):
    """NetworkManager class."""

    Events: ClassVar[NetworkEvents] = NetworkEvents()

    def __init__(
        self, client: ClientType, loop: Optional[AbstractEventLoop] = None
    ) -> None:
        """Make new NetworkManager."""
        super().__init__(loop=ensure_loop(loop))
        self._client: ClientType = client
        self._frameManager: Optional["FrameManager"] = None
        self._requestIdToRequest: Dict[str, Request] = dict()
        self._interceptionIdToRequest: Dict[str, Request] = dict()
        self._requestIdToRequestWillBeSentEvent: Dict[str, Dict] = dict()
        self._extraHTTPHeaders: OrderedDict[str, str] = OrderedDict()
        self._offline: bool = False
        self._credentials: Optional[Dict[str, str]] = None
        self._attemptedAuthentications: Set[str] = set()
        self._userRequestInterceptionEnabled: bool = False
        self._protocolRequestInterceptionEnabled: bool = False
        self._requestHashToRequestIds: Multimap = Multimap()
        self._requestHashToInterceptionIds: Multimap = Multimap()

        self._client.on("Network.requestWillBeSent", self._onRequestWillBeSent)
        self._client.on(
            "Network.requestServedFromCache", self._onRequestSeveredFromCache
        )  # noqa: #501
        self._client.on("Network.responseReceived", self._onResponseReceived)
        self._client.on("Network.loadingFinished", self._onLoadingFinished)
        self._client.on("Network.loadingFailed", self._onLoadingFailed)
        self._client.on("Network.requestIntercepted", self._onRequestIntercepted)

    def setFrameManager(self, frameManager: "FrameManager") -> None:
        self._frameManager = frameManager

    async def authenticate(self, credentials: Dict[str, str]) -> None:
        """Provide credentials for http auth."""
        self._credentials = credentials
        await self._updateProtocolRequestInterception()

    async def setExtraHTTPHeaders(self, extraHTTPHeaders: Dict[str, str]) -> None:
        """Set extra http headers."""
        self._extraHTTPHeaders = OrderedDict()
        for k, v in extraHTTPHeaders.items():
            if not isinstance(v, str):
                em = (
                    f'Expected value of header "{k}" to be string, '
                    + "but {} is found.".format(type(v))
                )
                raise TypeError(em)
            self._extraHTTPHeaders[k.lower()] = v
        await self._client.send(
            "Network.setExtraHTTPHeaders", {"headers": self._extraHTTPHeaders}
        )

    def extraHTTPHeaders(self) -> Dict[str, str]:
        """Get extra http headers."""
        return dict(**self._extraHTTPHeaders)

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

    async def setUserAgent(self, userAgent: str) -> None:
        """Set user agent."""
        await self._client.send(
            "Network.setUserAgentOverride", {"userAgent": userAgent}
        )

    async def setRequestInterception(self, value: bool) -> None:
        """Enable request intercetion."""
        self._userRequestInterceptionEnabled = value
        await self._updateProtocolRequestInterception()

    async def _updateProtocolRequestInterception(self) -> None:
        enabled = self._userRequestInterceptionEnabled or bool(self._credentials)
        if enabled == self._protocolRequestInterceptionEnabled:
            return
        self._protocolRequestInterceptionEnabled = enabled
        patterns = [{"urlPattern": "*"}] if enabled else []
        await asyncio.gather(
            self._client.send("Network.setCacheDisabled", {"cacheDisabled": enabled}),
            self._client.send("Network.setRequestInterception", {"patterns": patterns}),
        )

    def _onRequestWillBeSent(self, event: Dict) -> None:
        if self._protocolRequestInterceptionEnabled:
            requestHash = generateRequestHash(event["request"])
            interceptionId = self._requestHashToInterceptionIds.firstValue(requestHash)
            if interceptionId:
                self._onRequest(event, interceptionId)
                self._requestHashToInterceptionIds.delete(requestHash, interceptionId)
            else:
                self._requestHashToRequestIds.set(requestHash, event["requestId"])
                self._requestIdToRequestWillBeSentEvent[event["requestId"]] = event
            return
        self._onRequest(event, None)

    def _onRequestIntercepted(self, event: Dict) -> None:  # noqa: C901
        if event.get("authChallenge"):
            response = "Default"
            if event["interceptionId"] in self._attemptedAuthentications:
                response = "CancelAuth"
            elif self._credentials:
                response = "ProvideCredentials"
                self._attemptedAuthentications.add(event["interceptionId"])
            username = None
            password = None
            if self._credentials is not None:
                username = self._credentials.get("username")
                password = self._credentials.get("password")
            self._loop.create_task(
                self._client.send(
                    "Network.continueInterceptedRequest",
                    {
                        "interceptionId": event["interceptionId"],
                        "authChallengeResponse": {
                            "response": response,
                            "username": username,
                            "password": password,
                        },
                    },
                )
            )
            return

        if (
            not self._userRequestInterceptionEnabled
            and self._protocolRequestInterceptionEnabled
        ):
            self._loop.create_task(
                self._client.send(
                    "Network.continueInterceptedRequest",
                    {"interceptionId": event["interceptionId"]},
                )
            )

        requestHash = generateRequestHash(event["request"])
        requestId = self._requestHashToRequestIds.firstValue(requestHash)
        if requestId is not None:
            requestWillBeSentEvent = self._requestIdToRequestWillBeSentEvent.get(
                requestId
            )
            self._onRequest(requestWillBeSentEvent, event.get("interceptionId"))
            self._requestHashToRequestIds.delete(requestHash, requestId)
            del self._requestIdToRequestWillBeSentEvent[requestId]
        else:
            self._requestHashToInterceptionIds.set(requestHash, event["interceptionId"])

    def _onRequest(self, event: Dict, interceptionId: Optional[str] = None) -> None:
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
            frame,
            interceptionId,
            self._userRequestInterceptionEnabled,
            event,
            redirectChain,
        )
        self._requestIdToRequest[requestId] = request
        self.emit(NetworkManager.Events.Request, request)

    def _onRequestSeveredFromCache(self, event: Dict) -> None:
        request = self._requestIdToRequest.get(event.get("requestId"))
        if request is not None:
            request._fromMemoryCache = True

    def _handleRequestRedirect(self, request: "Request", event: Dict) -> None:
        newEvent: Dict = dict(**event)
        newEvent["response"] = event.get("redirectResponse")
        del newEvent["redirectResponse"]
        response = Response(self._client, request, newEvent)
        request._redirectChain.append(request)
        request._response = response
        self._requestIdToRequest.pop(request.requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.Response, response)
        self.emit(NetworkManager.Events.RequestFinished, request)

    def _onResponseReceived(self, event: Dict) -> None:
        request = self._requestIdToRequest.get(event["requestId"])
        # FileUpload sends a response without a matching request.
        if not request:
            return
        response = Response(self._client, request, event)
        request._response = response
        self.emit(NetworkManager.Events.Response, response)

    def _onLoadingFinished(self, event: Dict) -> None:
        request = self._requestIdToRequest.get(event.get("requestId", ""))
        # For certain requestIds we never receive requestWillBeSent event.
        # @see https://crbug.com/750469
        if request is None:
            return
        # Under certain conditions we never get the Network.responseReceived
        # event from protocol. @see https://crbug.com/883475
        response = request._response
        if response is not None and not response._bodyLoadedPromiseFulfill.done():
            response._bodyLoadedPromiseFulfill.set_result(None)
        self._requestIdToRequest.pop(request.requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.RequestFinished, request)

    def _onLoadingFailed(self, event: Dict) -> None:
        request = self._requestIdToRequest.get(event["requestId"])
        # For certain requestIds we never receive requestWillBeSent event.
        # @see https://crbug.com/750469
        if not request:
            return
        request._failureText = event.get("errorText")
        request._wasCanceled = event.get("canceled")
        request._blockedReason = event.get("blockedReason")
        request._type = event.get("type", request._type)
        response = request._response
        if response is not None and not response._bodyLoadedPromiseFulfill.done():
            response._bodyLoadedPromiseFulfill.set_result(None)
        self._requestIdToRequest.pop(request.requestId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.RequestFailed, request)


@attr.dataclass
class Request(object):
    _client: ClientType = attr.ib()
    _frame: Optional[Frame] = attr.ib()
    _interceptionId: Optional[str] = attr.ib()
    _allowInterception: bool = attr.ib()
    _requestInfo: Dict = attr.ib()
    _redirectChain: List["Request"] = attr.ib()
    _response: Optional["Response"] = attr.ib(init=False, default=None)
    _preq: Dict = attr.ib(init=False, default=None)
    _type: str = attr.ib(init=False, default="")
    _failureText: str = attr.ib(init=False, default="")
    _fromMemoryCache: bool = attr.ib(init=False, default=False)
    _wasCanceled: bool = attr.ib(init=False, default=False)
    _interceptionHandled: bool = attr.ib(init=False, default=False)
    _blockedReason: Optional[str] = attr.ib(init=False, default=None)

    def __attrs_post_init__(self) -> None:
        self._preq = self._requestInfo.get("request")
        self._type = self._requestInfo.get("type")

    @property
    def wasCanceled(self) -> bool:
        return self._wasCanceled

    @property
    def blockedReason(self) -> Optional[str]:
        return self._blockedReason

    @property
    def url(self) -> str:
        return self._preq.get("url")

    @property
    def method(self) -> str:
        return self._preq.get("method")

    @property
    def postData(self) -> Optional[str]:
        return self._preq.get("postData")

    @property
    def headers(self) -> Dict[str, str]:
        return self._preq.get("headers")

    @property
    def urlFragment(self) -> Optional[str]:
        return self._preq.get("urlFragment")

    @property
    def hasPostData(self) -> Optional[bool]:
        return self._preq.get("hasPostData")

    @property
    def requestId(self) -> str:
        return self._requestInfo.get("requestId")

    @property
    def loaderId(self) -> str:
        return self._requestInfo.get("loaderId")

    @property
    def timeStamp(self) -> int:
        return self._requestInfo.get("timeStamp")

    @property
    def wallTime(self) -> float:
        return self._requestInfo.get("wallTime")

    @property
    def initiator(self) -> str:
        return self._requestInfo.get("initiator")

    @property
    def resourceType(self) -> Optional[str]:
        return self._type

    @property
    def frameId(self) -> Optional[str]:
        return self._requestInfo.get("frameId")

    @property
    def frame(self) -> Optional[Frame]:
        return self._frame

    @property
    def hasUserGesture(self) -> Optional[bool]:
        return self._requestInfo.get("hasUserGesture")

    @property
    def documentURL(self) -> str:
        return self._requestInfo.get("documentURL")

    @property
    def isNavigationRequest(self) -> bool:
        return self.requestId == self.loaderId and self.resourceType == "Document"

    @property
    def initialPriority(self) -> str:
        return self._preq.get("initialPriority")

    @property
    def referrerPolicy(self) -> str:
        return self._preq.get("referrerPolicy")

    @property
    def isLinkPreload(self) -> Optional[bool]:
        return self._preq.get("isLinkPreload")

    @property
    def mixedContentType(self) -> Optional[str]:
        return self._preq.get("mixedContentType")

    @property
    def response(self) -> Optional["Response"]:
        """Return matching :class:`Response` object, or ``None``.

        If the response has not been recieved, return ``None``.
        """
        return self._response

    @property
    def redirectChain(self) -> List["Request"]:
        return self._redirectChain

    @property
    def failureText(self) -> Optional[str]:
        return self._failureText

    @property
    def failure(self) -> Optional[Dict]:
        """Return error text.

        Return ``None`` unless this request was failed, as reported by
        ``requestfailed`` event.

        When request failed, this method return dictionary which has a
        ``errorText`` field, which contains human-readable error message, e.g.
        ``'net::ERR_RAILED'``.
        """
        if not self.failureText:
            return None
        return {"errorText": self.failureText}

    async def get_post_data(self) -> Optional[str]:
        if not self.hasPostData:
            return None
        raw_pd = await self._client.send(
            "Network.getRequestPostData", dict(requestId=self.requestId)
        )
        decoded = base64.b64decode(raw_pd.get("post_data", b"")).decode("utf8")
        self._preq["postData"] = decoded
        return decoded

    async def continue_(self, overrides: Dict = None) -> None:
        """Continue request with optional request overrides.

        To use this method, request interception should be enabled by
        :meth:`simplechrome.page.Page.setRequestInterception`. If request
        interception is not enabled, raise ``NetworkError``.

        ``overrides`` can have the following fields:

        * ``url`` (str): If set, the request url will be changed.
        * ``method`` (str): If set, change the request method (e.g. ``GET``).
        * ``postData`` (str): If set, change the post data or request.
        * ``headers`` (dict): If set, change the request HTTP header.
        """
        if overrides is None:
            overrides = {}

        if not self._allowInterception:
            raise NetworkError("Request interception is not enabled.")
        if self._interceptionHandled:
            raise NetworkError("Request is already handled.")

        self._interceptionHandled = True
        opt = {"interceptionId": self._interceptionId}
        opt.update(overrides)
        await self._client.send("Network.continueInterceptedRequest", opt)

    async def respond(self, response: Dict) -> None:  # noqa: C901
        """Fulfills request with given response.

        To use this, request interception shuold by enabled by
        :meth:`simplechrome.page.Page.setRequestInterception`. Requst interception
        is not enabled, raise ``NetworkError``.

        ``response`` is a dictinary which can have the following fields:

        * ``status`` (int): Response status code, defaults to 200.
        * ``headers`` (dict): Optional response headers.
        * ``contentType`` (str): If set, euqals to setting ``Content-Type``
          response header.
        * ``body`` (str|bytes): Optional response body.
        """
        if self.url.startswith("data:"):
            return
        if not self._allowInterception:
            raise NetworkError("Request interception is not enabled.")
        if self._interceptionHandled:
            raise NetworkError("Request is already handled.")
        self._interceptionHandled = True

        if response.get("body") and isinstance(response["body"], str):
            responseBody: Optional[bytes] = response["body"].encode("utf-8")
        else:
            responseBody = response.get("body")

        responseHeaders = {}
        if response.get("headers"):
            for header in response["headers"]:
                responseHeaders[header.lower()] = response["headers"][header]
        if response.get("contentType"):
            responseHeaders["content-type"] = response["contentType"]
        if responseBody and "content-length" not in responseHeaders:
            responseHeaders["content-length"] = len(responseBody)

        statusCode = response.get("status", 200)
        statusText = statusTexts.get(statusCode, "")
        statusLine = f"HTTP/1.1 {statusCode} {statusText}"

        CRLF = "\r\n"
        text = statusLine + CRLF
        for header in responseHeaders:
            text = f"{text}{header}: {responseHeaders[header]}{CRLF}"
        text = text + CRLF
        responseBuffer = text.encode("utf-8")
        if responseBody:
            responseBuffer = responseBuffer + responseBody

        rawResponse = base64.b64encode(responseBuffer).decode("ascii")
        await self._client.send(
            "Network.continueInterceptedRequest",
            {"interceptionId": self._interceptionId, "rawResponse": rawResponse},
        )

    async def abort(self, errorCode: str = "failed") -> None:
        """Abort request.

        To use this, request interception should be enabled by
        :meth:`simplechrome.page.Page.setRequestInterception`.
        If request interception is not enabled, raise ``NetworkError``.

        ``errorCode`` is an optional error code string. Defaults to ``failed``,
        could be one of the following: ``aborted``, ``accesdenied``,
        ``addressunreachable``, ``connectionaborted``, ``connectionclosed``,
        ``connectionfailed``, ``connnectionrefused``, ``connectionreset``,
        ``internetdisconnected``, ``namenotresolved``, ``timedout``, ``failed``
        """
        errorReason = errorReasons[errorCode]
        if not errorReason:
            raise NetworkError("Unknown error code: {}".format(errorCode))
        if not self._allowInterception:
            raise NetworkError("Request interception is not enabled.")
        if self._interceptionHandled:
            raise NetworkError("Request is already handled.")
        self._interceptionHandled = True
        await self._client.send(
            "Network.continueInterceptedRequest",
            dict(interceptionId=self._interceptionId, errorReason=errorReason),
        )

    def to_dict(self) -> dict:
        return dict(requestId=self.requestId, **self._preq)


errorReasons = {
    "aborted": "Aborted",
    "accessdenied": "AccessDenied",
    "addressunreachable": "AddressUnreachable",
    "blockedbyclient": "BlockedByClient",
    "blockedbyresponse": "BlockedByResponse",
    "connectionaborted": "ConnectionAborted",
    "connectionclosed": "ConnectionClosed",
    "connectionfailed": "ConnectionFailed",
    "connectionrefused": "ConnectionRefused",
    "connectionreset": "ConnectionReset",
    "internetdisconnected": "InternetDisconnected",
    "namenotresolved": "NameNotResolved",
    "timedout": "TimedOut",
    "failed": "Failed",
}


@attr.dataclass(repr=False)
class Response(object):
    _client: ClientType = attr.ib()
    _request: Request = attr.ib()
    _responseInfo: Dict = attr.ib()
    _contentPromise: Optional[Future] = attr.ib(init=False, default=None)
    _bodyLoadedPromiseFulfill: Future = attr.ib(init=False, default=None)
    _pres: Dict = attr.ib(init=False, default=None)
    _protocol: str = attr.ib(init=False, default="")
    _encodedDataLength: float = attr.ib(init=False, default=0.0)

    def __attrs_post_init__(self) -> None:
        self._bodyLoadedPromiseFulfill = asyncio.get_event_loop().create_future()
        self._pres = self._responseInfo.get("response")
        sdetails = None
        if self._pres.get("securityDetails") is not None:
            sdetails = SecurityDetails(self._pres.get("securityDetails"))
        self._securityDetails: Optional[SecurityDetails] = sdetails
        self._protocol = self._pres.get("protocol")
        self._encodedDataLength = self._pres.get("encodedDataLength")

    @property
    def frame(self) -> Optional[Frame]:
        return self._request.frame

    @property
    def url(self) -> str:
        """URL of the response."""
        return self._pres.get("url")

    @property
    def protocol(self) -> str:
        return self._protocol

    @property
    def mimeType(self) -> Optional[str]:
        return self._pres.get("mimeType")

    @property
    def ok(self) -> bool:
        """Return bool whether this request is successfull (200-299) or not."""
        return 200 <= self.status <= 299

    @property
    def status(self) -> int:
        """Status code of the response."""
        return self._pres.get("status")

    @property
    def headers(self) -> Dict[str, str]:
        """Return dictionary of HTTP headers of this response."""
        return self._pres.get("headers")

    @property
    def headersText(self) -> Optional[str]:
        return self._pres.get("headersText")

    @property
    def requestHeaders(self) -> Dict[str, str]:
        """Return dictionary of HTTP headers of this response."""
        return self._pres.get("requestHeaders")

    @property
    def requestHeadersText(self) -> Optional[str]:
        return self._pres.get("requestHeadersText")

    @property
    def remoteIPAddress(self) -> Optional[str]:
        return self._pres.get("remoteIPAddress")

    @property
    def remotePort(self) -> Optional[int]:
        return self._pres.get("remotePort")

    @property
    def requestId(self) -> str:
        return self._responseInfo.get("requestId")

    @property
    def loaderId(self) -> str:
        return self._responseInfo.get("loaderId")

    @property
    def resourceType(self) -> str:
        return self._responseInfo.get("resourceType")

    @property
    def frameId(self) -> Optional[str]:
        return self._responseInfo.get("frameId")

    @property
    def timestamp(self) -> int:
        return self._responseInfo.get("timestamp")

    @property
    def request(self) -> Request:
        """Get matching :class:`Request` object."""
        return self._request

    @property
    def fromCache(self) -> bool:
        """Return ``True`` if the response was served from cache.

        Here `cache` is either the browser's disk cache or memory cache.
        """
        return self._pres.get("fromDiskCache") or self._request._fromMemoryCache

    @property
    def fromServiceWorker(self) -> bool:
        """Return ``True`` if the response was served by a service worker."""
        return self._pres.get("fromServiceWorker")

    @property
    def encodedDataLength(self) -> float:
        return self._encodedDataLength

    @property
    def securityDetails(self) -> Optional["SecurityDetails"]:
        """Return security details associated with this response.

        Security details if the response was received over the secure
        connection, or `None` otherwise.
        """
        return self._securityDetails

    @property
    def securityState(self) -> str:
        return self._pres.get("securityState")

    async def _bufread(self) -> Union[bytes, str]:
        if not self._bodyLoadedPromiseFulfill.done():
            await self._bodyLoadedPromiseFulfill
        response = await self._client.send(
            "Network.getResponseBody", {"requestId": self._request.requestId}
        )
        body = response.get("body", b"")
        if response.get("base64Encoded", False):
            return base64.b64decode(body)
        return body

    def buffer(self) -> Awaitable[bytes]:
        """Retrun awaitable which resolves to bytes with response body."""
        if self._contentPromise is None:
            self._contentPromise = asyncio.ensure_future(self._bufread())
        return self._contentPromise

    async def text(self) -> str:
        """Get text representation of response body."""
        content = await self.buffer()
        if isinstance(content, str):
            return content
        else:
            return content.decode("utf-8")

    async def json(self) -> dict:
        """Get JSON representation of response body."""
        content = await self.text()
        return json.loads(content)

    def to_dict(self) -> Dict:
        return dict(requestId=self.requestId, **self._pres)

    def __str__(self) -> str:
        repr_args = []
        if self.url is not None:
            repr_args.append("url={!r}".format(self.url))
        if self.protocol is not None:
            repr_args.append("protocol={!r}".format(self.protocol))
        if self.mimeType is not None:
            repr_args.append("mimeType={!r}".format(self.mimeType))
        if self.status is not None:
            repr_args.append("status={!r}".format(self.status))
        return "Response(" + ", ".join(repr_args) + ")"


def generateRequestHash(request: Dict) -> str:
    """Generate request hash."""
    normalizedURL: str = request.get("url", "")
    try:
        normalizedURL = unquote(normalizedURL)
    except Exception:
        pass

    _hash: Dict[str, Union[str, Dict[str, str]]] = {
        "url": normalizedURL,
        "method": request.get("method"),
        "postData": request.get("postData"),
    }

    _new_headers: Dict[str, str] = dict()

    if not normalizedURL.startswith("data:"):
        headers: List[str] = list(request["headers"].keys())
        headers.sort()
        for header in headers:
            headerValue: str = request["headers"][header]
            header = header.lower()
            if (
                header == "accept"
                or header == "referer"
                or header == "x-devtools-emulate-network-conditions-client-id"
            ):  # noqa: E501
                continue
            _new_headers[header] = headerValue
        _hash["headers"] = _new_headers
    return json.dumps(_hash)


@attr.dataclass(slots=True)
class SecurityDetails(object):
    """Class represents responses which are received by page."""

    _details: Dict[str, Union[str, int, List[int], List[str]]] = attr.ib()

    @property
    def subjectName(self) -> str:
        """Return the subject to which the certificate was issued to."""
        return self._details.get("subjectName")

    @property
    def issuer(self) -> str:
        """Return a string with the name of issuer of the certificate."""
        return self._details.get("issuer")

    @property
    def validFrom(self) -> int:
        """Return UnixTime of the start of validity of the certificate."""
        return self._details.get("validFrom")

    @property
    def validTo(self) -> int:
        """Return UnixTime of the end of validity of the certificate."""
        return self._details.get("validTo")

    @property
    def protocol(self) -> str:
        """Return string of with the security protocol, e.g. "TLS1.2"."""
        return self._details.get("protocol")


statusTexts: Dict[str, str] = {
    "100": "Continue",
    "101": "Switching Protocols",
    "102": "Processing",
    "200": "OK",
    "201": "Created",
    "202": "Accepted",
    "203": "Non-Authoritative Information",
    "204": "No Content",
    "206": "Partial Content",
    "207": "Multi-Status",
    "208": "Already Reported",
    "209": "IM Used",
    "300": "Multiple Choices",
    "301": "Moved Permanently",
    "302": "Found",
    "303": "See Other",
    "304": "Not Modified",
    "305": "Use Proxy",
    "306": "Switch Proxy",
    "307": "Temporary Redirect",
    "308": "Permanent Redirect",
    "400": "Bad Request",
    "401": "Unauthorized",
    "402": "Payment Required",
    "403": "Forbidden",
    "404": "Not Found",
    "405": "Method Not Allowed",
    "406": "Not Acceptable",
    "407": "Proxy Authentication Required",
    "408": "Request Timeout",
    "409": "Conflict",
    "410": "Gone",
    "411": "Length Required",
    "412": "Precondition Failed",
    "413": "Payload Too Large",
    "414": "URI Too Long",
    "415": "Unsupported Media Type",
    "416": "Range Not Satisfiable",
    "417": "Expectation Failed",
    "418": "I'm a teapot",
    "421": "Misdirected Request",
    "422": "Unprocessable Entity",
    "423": "Locked",
    "424": "Failed Dependency",
    "426": "Upgrade Required",
    "428": "Precondition Required",
    "429": "Too Many Requests",
    "431": "Request Header Fields Too Large",
    "451": "Unavailable For Legal Reasons",
    "500": "Internal Server Error",
    "501": "Not Implemented",
    "502": "Bad Gateway",
    "503": "Service Unavailable",
    "504": "Gateway Timeout",
    "505": "HTTP Version Not Supported",
    "506": "Variant Also Negotiates",
    "507": "Insufficient Storage",
    "508": "Loop Detected",
    "510": "Not Extended",
    "511": "Network Authentication Required",
}
