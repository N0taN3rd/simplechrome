from typing import Dict, List, Optional

from ._typings import Number, SlotsT

__all__ = ["SecurityDetails"]


class SecurityDetails:
    """Security details about a request"""

    __slots__: SlotsT = ["__weakref__", "_details"]

    def __init__(self, details: Dict) -> None:
        self._details: Dict = details

    @property
    def keyExchange(self) -> str:
        """Key Exchange used by the connection, or the empty string if not applicable"""
        return self._details.get("keyExchange")

    @property
    def keyExchangeGroup(self) -> Optional[str]:
        """(EC)DH group used by the connection, if applicable"""
        return self._details.get("keyExchangeGroup")

    @property
    def cipher(self) -> str:
        """Cipher name"""
        return self._details.get("cipher")

    @property
    def mac(self) -> Optional[str]:
        """TLS MAC. Note that AEAD ciphers do not have separate MACs"""
        return self._details.get("mac")

    @property
    def certificateId(self) -> str:
        """Certificate ID value"""
        return self._details.get("certificateId")

    @property
    def sanList(self) -> str:
        """Subject Alternative Name (SAN) DNS names and IP addresses"""
        return self._details.get("sanList")

    @property
    def certificateTransparencyCompliance(self) -> str:
        """Whether the request complied with Certificate Transparency policy"""
        return self._details.get("certificateTransparencyCompliance")

    @property
    def signedCertificateTimestampList(self) -> List[Dict]:
        """List of signed certificate timestamps (SCTs)"""
        return self._details.get("signedCertificateTimestampList")

    @property
    def subjectName(self) -> str:
        """Certificate subject name"""
        return self._details.get("subjectName")

    @property
    def issuer(self) -> str:
        """Name of the issuing CA"""
        return self._details.get("issuer")

    @property
    def validFrom(self) -> Number:
        """Certificate valid from issuing date (UnixTime)"""
        return self._details.get("validFrom")

    @property
    def validTo(self) -> Number:
        """Certificate valid to expiration date (UnixTime)"""
        return self._details.get("validTo")

    @property
    def protocol(self) -> str:
        """Protocol name (e.g. "TLS 1.2" or "QUIC")"""
        return self._details.get("protocol")

    def as_dict(self) -> Dict:
        return self._details

    def __str__(self) -> str:
        return f"SecurityDetails({self._details})"

    def __repr__(self) -> str:
        return self.__str__()
