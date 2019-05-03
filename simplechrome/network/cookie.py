from typing import Any, Dict, Optional, Set

from http.cookies import SimpleCookie

from simplechrome._typings import Number, OptionalNumber, OptionalStr, SlotsT
from simplechrome.connection import ClientType
from simplechrome.helper import Helper

__all__ = ["Cookie"]

ModifiableCookieParams: Set[str] = {
    "value",
    "url",
    "domain",
    "path",
    "expires",
    "httpOnly",
    "secure",
    "sameSite",
}

SkippedValue: Set[str] = {"max-age", "version", "comment"}


def parse_cookie_str(cookie_str: str) -> Dict:
    sc = SimpleCookie()
    sc.load(cookie_str)
    cd = {}
    for morsal in sc.values():
        cd["name"] = morsal.key
        cd["value"] = morsal.value
        for k, v in morsal.items():
            if k in SkippedValue:
                continue
            if v:
                cd[k if k != "httponly" else "httpOnly"] = v
    return cd


class Cookie:
    """This class acts an abstraction around the CDP types: Cookie and CookieParam
    in order to allow ease of use for working with cookies
    """

    __slots__: SlotsT = ["__weakref__", "_cookie", "_client"]

    @classmethod
    def from_string(
        cls, cookie_str: str, client: ClientType, **kwargs: Any
    ) -> "Cookie":
        """Create a new instance of Cookie from the supplied cookie string

        :param cookie_str: The string containing the cookie
        :param client: The client instance used to communicate with the remote browser
        :param kwargs: Cookie param overrides
        :return: The new Cookie instance
        """
        return cls(client, Helper.merge_dict(parse_cookie_str(cookie_str), kwargs))

    def __init__(
        self, client: ClientType, cookie: Optional[Dict] = None, **kwargs: Any
    ) -> None:
        """Initialize a the new Cookie instance

        :param client: The client instance to use to communicate with the browser
        :param cookie: Optional dictionary representing the cookie
        :param kwargs: Optional keyword args representing the values of the cookie
        """
        self._cookie: Dict = Helper.merge_dict(cookie, kwargs)
        self._client: ClientType = client

    @property
    def name(self) -> str:
        """Cookie name"""
        return self._cookie["name"]

    @property
    def value(self) -> str:
        """Cookie value"""
        return self._cookie["value"]

    @property
    def domain(self) -> OptionalStr:
        """Cookie domain"""
        return self._cookie.get("domain")

    @property
    def path(self) -> OptionalStr:
        """Cookie path"""
        return self._cookie.get("path")

    @property
    def url(self) -> OptionalStr:
        """The request-URI to associate with the setting of the cookie.
        This value can affect the default domain and path values of the created cookie
        """
        return self._cookie.get("url")

    @property
    def expires(self) -> Optional[Number]:
        """Cookie expiration date as the number of seconds since the UNIX epoch"""
        return self._cookie.get("expires")

    @property
    def size(self) -> Optional[Number]:
        """Cookie size"""
        return self._cookie.get("size")

    @property
    def httpOnly(self) -> Optional[bool]:
        """True if cookie is http-only"""
        return self._cookie.get("httpOnly")

    @property
    def secure(self) -> Optional[bool]:
        """True if cookie is secure"""
        return self._cookie.get("secure")

    @property
    def sameSite(self) -> OptionalStr:
        """Represents the cookie's 'SameSite' status: https://tools.ietf.org/html/draft-west-first-party-cookies

        Value is either:
          * Strict
          * Lax
          * Extended
          * None
        """
        return self._cookie.get("sameSite")

    @property
    def session(self) -> Optional[bool]:
        """True in case of session cookie"""
        return self._cookie.get("session")

    def cookie_params(self) -> Dict:
        """Returns a dictionary containing the values accepted as the CDP Type CookieParam"""
        return self._create_cookie_params()

    def modify_param(self, param: str, value: Any) -> None:
        """Sets the value of supplied cookie param

        To modify the name of the cookie you must use Cookie.setCookie

        Note must use Cookie.setCookie to actually set
        the modified cookie in the browser

        :param param: The name of the cookie param
        :param value: The value for the param
        """
        if param not in ModifiableCookieParams:
            raise Exception(f"Invalid cookie param name {param}")
        self._cookie[param] = value

    def remove_param(self, param: str) -> bool:
        """Removes the supplied param from the cookie

        Note must use Cookie.setCookie to actually set
        the modified cookie in the browser

        To modify the name of the cookie you must use Cookie.setCookie

        :param param: The param to be removed
        :return: T/F indicating if the param was actually removed
        """
        if param not in ModifiableCookieParams:
            raise Exception(f"Invalid cookie param name {param}")
        if param not in self._cookie:
            return False
        del self._cookie[param]
        return True

    async def setCookie(
        self,
        name: OptionalStr = None,
        value: OptionalStr = None,
        url: OptionalStr = None,
        domain: OptionalStr = None,
        path: OptionalStr = None,
        expires: OptionalNumber = None,
        httpOnly: Optional[bool] = None,
        secure: Optional[bool] = None,
        sameSite: OptionalStr = None,
    ) -> bool:
        """Modifies or sets this cookie with the given cookie data; may overwrite equivalent cookies if they exist.

        All values are optional but must this cookie's value must have values for the name and value fields

        :param name: Cookie name.
        :param value: Cookie value.
        :param url: The request-URI to associate with the setting of the cookie. This value can affect the
         default domain and path values of the created cookie.
        :param domain: Cookie domain.
        :param path: Cookie path.
        :param expires: Cookie expiration date, session cookie if not set
        :param httpOnly: True if cookie is http-only.
        :param secure: True if cookie is secure.
        :param sameSite: Cookie SameSite type.
        :raises Exception: if the cookie is nameless or valueless
        """
        new_cookie = self._create_cookie_params(
            name, value, url, domain, path, expires, httpOnly, secure, sameSite
        )
        if new_cookie["name"] is None:
            raise Exception(f"Can not set a nameless cookie")
        if new_cookie["value"] is None:
            raise Exception(f"Can not set a valueless cookie")
        # we attempt to delete this cookie because we may have preexisted
        # and we want ensure we do not have duplicate cookies
        try:
            await self.deleteCookie()
        except Exception:
            pass
        results = await self._client.send("Network.setCookie", new_cookie)
        success = results.get("success")
        if success:
            self._cookie.update(new_cookie)
        return success

    async def deleteCookie(self) -> None:
        """Deletes browser cookies with matching name and url or domain/path pair

        :raises Exception: If the cookie is nameless
        """
        name = self.name
        if name is None:
            raise Exception(f"Can not delete a nameless cookie")
        delete_me = {"name": name}
        url = self.url
        if url is not None:
            delete_me["url"] = url
        else:
            domain = self.domain
            if domain is not None:
                delete_me["domain"] = domain
            path = self.path
            if path is not None:
                delete_me["path"] = path
        await self._client.send("Network.deleteCookies", delete_me)

    def _create_cookie_params(
        self,
        name: OptionalStr = None,
        value: OptionalStr = None,
        url: OptionalStr = None,
        domain: OptionalStr = None,
        path: OptionalStr = None,
        expires: OptionalNumber = None,
        httpOnly: Optional[bool] = None,
        secure: Optional[bool] = None,
        sameSite: OptionalStr = None,
    ) -> Dict:
        new_cookie = {"name": name or self.name, "value": value or self.value}
        url = url or self.url
        if url is not None:
            new_cookie["url"] = url
        domain = domain or self.domain
        if domain is not None:
            new_cookie["domain"] = domain
        path = path or self.path
        if path is not None:
            new_cookie["path"] = path
        secure = secure if secure is not None else self.secure
        if secure is not None:
            new_cookie["secure"] = secure
        httpOnly = httpOnly if httpOnly is not None else self.httpOnly
        if httpOnly is not None:
            new_cookie["httpOnly"] = httpOnly
        sameSite = sameSite or self.sameSite
        if sameSite is not None:
            new_cookie["sameSite"] = sameSite
        expires = expires or self.expires
        if expires is not None:
            new_cookie["expires"] = expires
        return new_cookie

    def __str__(self) -> str:
        return f"Cookie({self._cookie})"

    def __repr__(self) -> str:
        return self.__str__()
