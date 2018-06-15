"""Network Manager module."""

import asyncio
import base64
import ujson as json
from collections import OrderedDict
from types import SimpleNamespace
from typing import Awaitable, Dict, Optional, Union, TYPE_CHECKING
from urllib.parse import unquote

from pyee import EventEmitter

from .connection import CDPSession
from .errors import NetworkError
from .frame_manager import FrameManager, Frame
from .multimap import Multimap

if TYPE_CHECKING:
    from typing import Set  # noqa: F401

__all__ = ["NetworkManager", "Request", "Response", "SecurityDetails"]


class NetworkManager(EventEmitter):
    """NetworkManager class."""

    Events = SimpleNamespace(
        Request="request",
        Response="response",
        RequestFailed="requestfailed",
        RequestFinished="requestfinished",
    )

    def __init__(self, client: CDPSession, frameManager: FrameManager) -> None:
        """Make new NetworkManager."""
        super().__init__()
        self._client = client
        self._frameManager = frameManager
        self._requestIdToRequest: Dict[Optional[str], Request] = dict()
        self._interceptionIdToRequest: Dict[Optional[str], Request] = dict()
        self._extraHTTPHeaders: OrderedDict[str, str] = OrderedDict()
        self._offline: bool = False
        self._credentials: Optional[Dict[str, str]] = None
        self._attemptedAuthentications: Set[str] = set()
        self._userRequestInterceptionEnabled = False
        self._protocolRequestInterceptionEnabled = False
        self._requestHashToRequestIds = Multimap()
        self._requestHashToInterceptionIds = Multimap()

        self._client.on("Network.requestWillBeSent", self._onRequestWillBeSent)
        self._client.on(
            "Network.requestServedFromCache", self._onRequestServedFromCache
        )  # noqa: #501
        self._client.on("Network.responseReceived", self._onResponseReceived)
        self._client.on("Network.loadingFinished", self._onLoadingFinished)
        self._client.on("Network.loadingFailed", self._onLoadingFailed)

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

    def _onRequestIntercepted(self, event: dict) -> None:  # noqa: C901
        if event.get("authChallenge"):
            response = "Default"
            if event["interceptionId"] in self._attemptedAuthentications:
                response = "CancelAuth"
            elif self._credentials:
                response = "ProvideCredentials"
                self._attemptedAuthentications.add(event["interceptionId"])
            username = getattr(self, "_credentials", {}).get("username")
            password = getattr(self, "_credentials", {}).get("password")
            asyncio.ensure_future(
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
            asyncio.ensure_future(
                self._client.send(
                    "Network.continueInterceptedRequest",
                    {"interceptionId": event["interceptionId"]},
                )
            )

        if "redirectURL" in event:
            request = self._interceptionIdToRequest.get(event.get("interceptionId", ""))
            if request:
                self._handleRequestRedirect(
                    request,
                    event.get("redirectStatusCode", 0),
                    event.get("redirectHeaders", {}),
                    False,
                    None,
                )
                self._handleRequestStart(
                    request.requestId,
                    event.get("interceptionId", ""),
                    event.get("redirectUrl", ""),
                    event.get("resourceType", ""),
                    event.get("request", {}),
                    event.get("frameId"),
                    event.get("frameId"),
                )
            return

        requestHash = generateRequestHash(event["request"])
        requestId = self._requestHashToRequestIds.firstValue(requestHash)
        if requestId:
            self._requestHashToRequestIds.delete(requestHash, requestId)
            self._handleRequestStart(
                requestId,
                event["interceptionId"],
                event["request"]["url"],
                event["resourceType"],
                event["request"],
                event["frameId"],
                event["frameId"],
            )
        else:
            self._requestHashToInterceptionIds.set(requestHash, event["interceptionId"])
            self._handleRequestStart(
                None,
                event["interceptionId"],
                event["request"]["url"],
                event["resourceType"],
                event["request"],
                event["frameId"],
                event["frameId"],
            )

    def _onRequestServedFromCache(self, event: Dict) -> None:
        request = self._requestIdToRequest.get(event.get("requestId"))
        if request:
            request._fromMemoryCache = True

    def _handleRequestRedirect(
        self, request: "Request", redirectResponse: dict
    ) -> None:
        response = Response(
            self._client,
            request,
            redirectResponse.get("status"),
            redirectResponse.get("headers"),
            redirectResponse.get("fromDiskCache"),
            redirectResponse.get("fromServiceWorker"),
            redirectResponse.get("securityDetails"),
            redirectResponse.get("mimeType"),
            redirectResponse.get("headersText"),
            redirectResponse.get("requestHeaders"),
            redirectResponse.get("requestHeadersText"),
            redirectResponse.get("protocol"),
            redirectResponse.get("url"),
        )
        request._response = response
        self._requestIdToRequest.pop(request.requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.Response, response)

    def _handleRequestStart(
        self,
        requestId: Optional[str],
        interceptionId: str,
        url: str,
        resourceType: str,
        requestPayload: Dict,
        frameId: Optional[str],
        initiator: Optional[str],
    ) -> None:
        frame = None
        if frameId and self._frameManager is not None:
            frame = self._frameManager.frame(frameId)

        request = Request(
            self._client,
            requestId,
            interceptionId,
            self._userRequestInterceptionEnabled,
            url,
            resourceType,
            requestPayload,
            frame,
            initiator,
        )
        if requestId:
            self._requestIdToRequest[requestId] = request
        if interceptionId:
            self._interceptionIdToRequest[interceptionId] = request
        self.emit(NetworkManager.Events.Request, request)

    def _onRequestWillBeSent(self, event: dict) -> None:
        if self._protocolRequestInterceptionEnabled:
            if event.get("redirectResponse"):
                return
            requestHash = generateRequestHash(event["request"])
            interceptionId = self._requestHashToInterceptionIds.firstValue(requestHash)
            request = self._interceptionIdToRequest.get(interceptionId)
            if request:
                request.requestId = event["requestId"]
                self._requestIdToRequest[event["requestId"]] = request
                self._requestHashToInterceptionIds.delete(requestHash, interceptionId)
            else:
                self._requestHashToRequestIds.set(requestHash, event["requestId"])
            return
        if event.get("redirectResponse"):
            request = self._requestIdToRequest[event["requestId"]]
            if request:
                redirectResponse = event.get("redirectResponse", {})
                self._handleRequestRedirect(request, redirectResponse)
        r = event.get("request", {})
        self._handleRequestStart(
            event.get("requestId", ""),
            "",
            r.get("url", ""),
            event.get("type", ""),
            r,
            event.get("frameId"),
            event.get("initiator"),
        )

    def _onResponseReceived(self, event: dict) -> None:
        request = self._requestIdToRequest.get(event["requestId"])
        # FileUpload sends a response without a matching request.
        if not request:
            return
        _resp = event.get("response", {})
        response = Response(
            self._client,
            request,
            _resp.get("status", 0),
            _resp.get("headers", {}),
            _resp.get("fromDiskCache"),
            _resp.get("fromServiceWorker"),
            _resp.get("securityDetails"),
            _resp.get("mimeType"),
            _resp.get("headersText"),
            _resp.get("requestHeaders"),
            _resp.get("requestHeadersText"),
            _resp.get("protocol"),
            _resp.get("url"),
        )
        request._response = response
        self.emit(NetworkManager.Events.Response, response)

    def _onLoadingFinished(self, event: dict) -> None:
        request = self._requestIdToRequest.get(event.get("requestId", ""))
        # For certain requestIds we never receive requestWillBeSent event.
        # @see https://crbug.com/750469
        if not request:
            return
        request._completePromiseFulfill()
        request.shouldReportCorbBlocking = event.get("shouldReportCorbBlocking")
        self._requestIdToRequest.pop(request.requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.RequestFinished, request)

    def _onLoadingFailed(self, event: dict) -> None:
        request = self._requestIdToRequest.get(event["requestId"])
        # For certain requestIds we never receive requestWillBeSent event.
        # @see https://crbug.com/750469
        if not request:
            return
        request.failureText = event.get("errorText")
        request.wasCanceled = event.get("canceled")
        request.blockedReason = event.get("blockedReason")
        request.resourceType = event.get("type", "").lower()
        request._completePromiseFulfill()
        self._requestIdToRequest.pop(request.requestId, None)
        self._interceptionIdToRequest.pop(request._interceptionId, None)
        self._attemptedAuthentications.discard(request._interceptionId)
        self.emit(NetworkManager.Events.RequestFailed, request)


class Request(object):
    """Request class."""

    def __init__(
        self,
        client: CDPSession,
        requestId: Optional[str],
        interceptionId: str,
        allowInterception: bool,
        url: str,
        resourceType: str,
        payload: dict,
        frame: Optional[Frame],
        initiator: Optional[str] = None,
    ) -> None:
        self._client = client
        self.requestId = requestId
        self._interceptionId = interceptionId
        self._allowInterception = allowInterception
        self._interceptionHandled = False
        self._response: Optional[Response] = None
        self.failureText: Optional[str] = None
        self._completePromise = asyncio.get_event_loop().create_future()
        self.wasCanceled: bool = False
        self.blockedReason: Optional[str] = None
        self.url: str = url
        self.initiator: Optional[str] = initiator
        self.resourceType = resourceType.lower()
        self.method = payload.get("method")
        self.postData = payload.get("postData")
        headers = payload.get("headers", {})
        self.headers = headers
        self.frame = frame
        self.shouldReportCorbBlocking: Optional[bool] = None

        self._fromMemoryCache = False

    def to_dict(self) -> dict:
        return dict(
            url=self.url,
            method=self.method,
            requestId=self.requestId,
            blockedReason=self.blockedReason,
            initiator=self.initiator,
            headers=self.headers,
            resourceType=self.resourceType,
            wasCanceled=self.wasCanceled,
            failureText=self.failureText,
            shouldReportCorbBlocking=self.shouldReportCorbBlocking,
        )

    def _completePromiseFulfill(self) -> None:
        self._completePromise.set_result(None)

    @property
    def response(self) -> Optional["Response"]:
        """Return matching :class:`Response` object, or ``None``.

        If the response has not been recieved, return ``None``.
        """
        return self._response

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

    async def continue_(self, overrides: Dict = None) -> None:
        """Continue request with optional request overrides.

        To use this method, request interception should be enabled by
        :meth:`pyppeteer.page.Page.setRequestInterception`. If request
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
        :meth:`pyppeteer.page.Page.setRequestInterception`. Requst interception
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
        :meth:`pyppeteer.page.Page.setRequestInterception`.
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


errorReasons = {
    "aborted": "Aborted",
    "accessdenied": "AccessDenied",
    "addressunreachable": "AddressUnreachable",
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


class Response(object):
    """Response class represents responses which are recieved by ``Page``."""

    def __init__(
        self,
        client: CDPSession,
        request: Request,
        status: int,
        headers: Dict[str, str],
        fromDiskCache: bool,
        fromServiceWorker: bool,
        securityDetails: Optional[dict] = None,
        mimeType: Optional[str] = None,
        headersText: Optional[str] = None,
        requestHeaders: Optional[dict] = None,
        requestHeadersText: Optional[str] = None,
        protocol: Optional[str] = None,
        url: Optional[str] = None,
    ) -> None:
        self.mimeType: Optional[str] = mimeType
        self._url: Optional[str] = url
        self.headersText: Optional[str] = headersText
        self.requestHeaders: Optional[dict] = requestHeaders
        self.requestHeadersText: Optional[str] = requestHeadersText
        self.protocol: Optional[str] = protocol
        self._client = client
        self._request = request
        self._status = status
        self._contentPromise = asyncio.get_event_loop().create_future()
        self._fromDiskCache = fromDiskCache
        self._fromServiceWorker = fromServiceWorker
        self._headers = headers
        self._securityDetails: Optional[dict] = securityDetails

    def to_dict(self) -> dict:
        return dict(
            url=self._url,
            mimeType=self.mimeType,
            status=self._status,
            protocol=self.protocol,
            requestHeaders=self.requestHeaders,
            requestHeadersText=self.requestHeadersText,
            headersText=self.headersText,
            headers=self.headers,
            requestId=self.requestId,
        )

    @property
    def requestId(self) -> str:
        return self._request.requestId

    @property
    def url(self) -> str:
        """URL of the response."""
        return self._url

    @property
    def ok(self) -> bool:
        """Return bool whether this request is successfull (200-299) or not."""
        return 200 <= self._status <= 299

    @property
    def status(self) -> int:
        """Status code of the response."""
        return self._status

    @property
    def headers(self) -> Dict:
        """Return dictionary of HTTP headers of this response.

        All header names are lower-case.
        """
        return self._headers

    @property
    def securityDetails(self) -> Union[Dict, "SecurityDetails"]:
        """Return security details associated with this response.

        Security details if the response was received over the secure
        connection, or `None` otherwise.
        """
        return self._securityDetails

    async def _bufread(self) -> bytes:
        response = await self._client.send(
            "Network.getResponseBody", {"requestId": self._request.requestId}
        )
        body = response.get("body", b"")
        if response.get("base64Encoded"):
            return base64.b64decode(body)
        return body

    def buffer(self) -> Awaitable[bytes]:
        """Retrun awaitable which resolves to bytes with response body."""
        if not self._contentPromise.done():
            return asyncio.ensure_future(self._bufread())
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

    @property
    def request(self) -> Request:
        """Get matching :class:`Request` object."""
        return self._request

    @property
    def fromCache(self) -> bool:
        """Return ``True`` if the response was served from cache.

        Here `cache` is either the browser's disk cache or memory cache.
        """
        return self._fromDiskCache or self._request._fromMemoryCache

    @property
    def fromServiceWorker(self) -> bool:
        """Return ``True`` if the response was served by a service worker."""
        return self._fromServiceWorker

    def __repr__(self) -> str:
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


def generateRequestHash(request: dict) -> str:
    """Generate request hash."""
    normalizedURL = request.get("url", "")
    try:
        normalizedURL = unquote(normalizedURL)
    except Exception:
        pass

    _hash = {
        "url": normalizedURL,
        "method": request.get("method"),
        "postData": request.get("postData"),
        "headers": {},
    }

    if not normalizedURL.startswith("data:"):
        headers = list(request["headers"].keys())
        headers.sort()
        for header in headers:
            headerValue = request["headers"][header]
            header = header.lower()
            if (
                header == "accept"
                or header == "referer"
                or header == "x-devtools-emulate-network-conditions-client-id"
            ):  # noqa: E501
                continue
            _hash["headers"][header] = headerValue
    return json.dumps(_hash)


class SecurityDetails(object):
    """Class represents responses which are received by page."""

    def __init__(
        self, subjectName: str, issuer: str, validFrom: int, validTo: int, protocol: str
    ) -> None:
        self._subjectName = subjectName
        self._issuer = issuer
        self._validFrom = validFrom
        self._validTo = validTo
        self._protocol = protocol

    @property
    def subjectName(self) -> str:
        """Return the subject to which the certificate was issued to."""
        return self._subjectName

    @property
    def issuer(self) -> str:
        """Return a string with the name of issuer of the certificate."""
        return self._issuer

    @property
    def validFrom(self) -> int:
        """Return UnixTime of the start of validity of the certificate."""
        return self._validFrom

    @property
    def validTo(self) -> int:
        """Return UnixTime of the end of validity of the certificate."""
        return self._validTo

    @property
    def protocol(self) -> str:
        """Return string of with the security protocol, e.g. "TLS1.2"."""
        return self._protocol


statusTexts = {
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