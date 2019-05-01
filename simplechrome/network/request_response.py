import base64
from asyncio import AbstractEventLoop, Event, Future
from typing import AnyStr, Awaitable, Dict, List, Optional, Union

from ujson import loads

from simplechrome._typings import CDPEvent, HTTPHeaders, OptionalLoop, SlotsT
from simplechrome.connection import ClientType
from simplechrome.frame_manager import Frame
from simplechrome.helper import Helper
from .security_details import SecurityDetails

__all__ = ["Response", "Request"]


def headers_array(
    headers: Union[Dict[str, str], List[Dict[str, str]]]
) -> List[Dict[str, str]]:
    if not isinstance(headers, dict):
        return headers
    return [{"name": name, "value": value} for name, value in headers.items()]


errorReasons: Dict[str, str] = {
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


class Request:
    __slots__: SlotsT = [
        "__weakref__",
        "_allowInterception",
        "_blockedReason",
        "_client",
        "_failureText",
        "_frame",
        "_fromMemoryCache",
        "_interceptionHandled",
        "_interceptionId",
        "_preq",
        "_redirectChain",
        "_requestInfo",
        "_response",
        "_type",
        "_wasCanceled",
    ]

    def __init__(
        self,
        client: ClientType,
        cdpEvent: CDPEvent,
        frame: Optional[Frame] = None,
        interceptionId: Optional[str] = None,
        userRequestInterceptionEnabled: bool = False,
        redirectChain: Optional[List["Request"]] = None,
    ) -> None:
        self._client: ClientType = client
        self._frame: Optional[Frame] = frame
        self._interceptionId: Optional[str] = interceptionId
        self._allowInterception: bool = userRequestInterceptionEnabled
        self._requestInfo: CDPEvent = cdpEvent
        self._redirectChain: List[Request] = redirectChain or []
        self._response: Optional[Response] = None
        self._preq: Dict = self._requestInfo.get("request")
        self._type: str = self._requestInfo.get("type")
        self._failureText: str = ""
        self._fromMemoryCache: bool = False
        self._wasCanceled: bool = False
        self._interceptionHandled: bool = False
        self._blockedReason: Optional[str] = None

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
            return self.postData
        raw_pd = await self._client.send(
            "Network.getRequestPostData", {"requestId": self.requestId}
        )
        decoded = base64.b64decode(raw_pd.get("post_data", b"")).decode("utf-8")
        self._preq["postData"] = decoded
        return decoded

    async def continue_(
        self,
        url: Optional[str] = None,
        method: Optional[str] = None,
        postData: Optional[str] = None,
        headers: Optional[HTTPHeaders] = None,
    ) -> None:
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
        if self.url.startswith("data:"):
            return
        if not self._allowInterception:
            raise Exception("Request interception is not enabled.")
        if self._interceptionHandled:
            raise Exception("Request is already handled.")
        overrides = {"interceptionId": self._interceptionId}
        if isinstance(url, str):
            overrides["url"] = url
        if isinstance(method, str):
            overrides["method"] = method
        if postData is not None:
            overrides["postData"] = str(postData)
        if isinstance(headers, dict):
            overrides["headers"] = headers_array(headers)
        self._interceptionHandled = True
        try:
            await self._client.send("Fetch.continueRequest", overrides)
        except Exception:
            pass

    async def respond(
        self,
        status: int = 200,
        headers: Optional[HTTPHeaders] = None,
        contentType: Optional[str] = None,
        body: Optional[AnyStr] = None,
    ) -> None:
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
            raise Exception("Request interception is not enabled.")
        if self._interceptionHandled:
            raise Exception("Request is already handled.")
        self._interceptionHandled = True

        response = {"requestId": self._interceptionId, "responseCode": status}
        if body is not None:
            response["body"] = base64.b64encode(
                body.encode("utf-8") if Helper.is_string(body) else body
            )
        response_headers = headers_array(headers) if isinstance(headers, dict) else {}
        if contentType is not None:
            response_headers["responseHeaders"] = contentType
        if body is not None and not (
            "content-length" in response_headers
            and "Content-Length" in response_headers
        ):
            response_headers["Content-Length"] = str(len(response["body"]))

        response["responseHeaders"] = response_headers
        try:
            await self._client.send("Fetch.fulfillRequest", response)
        except Exception:
            pass

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
        if self.url.startswith("data:"):
            return
        errorReason = errorReasons[errorCode]
        if not errorReason:
            raise Exception(f"Unknown error code: {errorCode}")
        if not self._allowInterception:
            raise Exception("Request interception is not enabled.")
        if self._interceptionHandled:
            raise Exception("Request is already handled.")
        self._interceptionHandled = True
        try:
            await self._client.send(
                "Fetch.failRequest",
                {"requestId": self._interceptionId, "errorReason": errorReason},
            )
        except Exception:
            pass

    def to_dict(self) -> Dict:
        return self._requestInfo

    def __str__(self) -> str:
        return f"Request(url={self.url}, method={self.method}, headers={self.headers})"

    def __repr__(self) -> str:
        return self.__str__()


class Response:
    __slots__: SlotsT = [
        "__weakref__",
        "_bodyLoadedPromise",
        "_client",
        "_contentPromise",
        "_encodedDataLength",
        "_loop",
        "_pres",
        "_pres",
        "_protocol",
        "_request",
        "_responseInfo",
        "_responseInfo",
        "_securityDetails",
    ]

    def __init__(
        self,
        client: ClientType,
        request: Request,
        cdpEvent: CDPEvent,
        loop: OptionalLoop = None,
    ) -> None:
        self._client: ClientType = client
        self._request: Request = request
        self._responseInfo: Dict = cdpEvent
        self._loop: AbstractEventLoop = Helper.ensure_loop(loop)
        self._contentPromise: Optional[Future] = None
        self._bodyLoadedPromise: Event = Event(loop=self._loop)
        self._pres: Dict = self._responseInfo.get("response")
        self._protocol: str = self._pres.get("protocol")
        self._securityDetails: Optional[SecurityDetails] = None
        if self._pres.get("securityDetails") is not None:
            self._securityDetails = SecurityDetails(self._pres.get("securityDetails"))
        self._encodedDataLength: float = self._pres.get("encodedDataLength", 0.0)

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
    def headers(self) -> HTTPHeaders:
        """Return dictionary of HTTP headers of this response."""
        return self._pres.get("headers")

    @property
    def headersText(self) -> Optional[str]:
        return self._pres.get("headersText")

    @property
    def requestHeaders(self) -> HTTPHeaders:
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
    def securityDetails(self) -> Optional[SecurityDetails]:
        """Return security details associated with this response.

        Security details if the response was received over the secure
        connection, or `None` otherwise.
        """
        return self._securityDetails

    @property
    def securityState(self) -> str:
        return self._pres.get("securityState")

    async def _bufread(self) -> Union[bytes, str]:
        await self._bodyLoadedPromise.wait()
        response = await self._client.send(
            "Network.getResponseBody", {"requestId": self._request.requestId}
        )
        body = response.get("body", b"")
        if response.get("base64Encoded", False):
            return base64.b64decode(body)
        return body

    def buffer(self) -> Awaitable[bytes]:
        """Return awaitable which resolves to bytes with response body."""
        if self._contentPromise is None:
            self._contentPromise = self._loop.create_task(self._bufread())
        return self._contentPromise

    async def text(self) -> str:
        """Get text representation of response body."""
        content = await self.buffer()
        if isinstance(content, str):
            return content
        else:
            return content.decode("utf-8")

    async def json(self) -> Dict:
        """Get JSON representation of response body."""
        content = await self.text()
        return loads(content)

    def to_dict(self) -> Dict:
        return self._responseInfo

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
        return f"Response({', '.join(repr_args)})"

    def __repr__(self) -> str:
        return self.__str__()
