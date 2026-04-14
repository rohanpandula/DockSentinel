from __future__ import annotations

import logging
import socket
from typing import Optional

from zeroconf import IPVersion, ServiceInfo, Zeroconf

logger = logging.getLogger(__name__)


class MDNSPublisher:
    """Publishes `<hostname>.local` on the LAN via multicast DNS.

    Runs in-process (no avahi/dbus) so the container stays non-root.
    """

    def __init__(self, hostname: str, port: int) -> None:
        self._hostname = hostname
        self._port = port
        self._zc: Optional[Zeroconf] = None
        self._info: Optional[ServiceInfo] = None

    def start(self) -> None:
        if self._zc is not None:
            return

        ip = _primary_ipv4()
        if not ip:
            logger.warning("mdns: no routable IPv4 found; skipping publish")
            return

        self._info = ServiceInfo(
            type_="_http._tcp.local.",
            name=f"{self._hostname}._http._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=self._port,
            server=f"{self._hostname}.local.",
            properties={"path": "/"},
        )
        try:
            self._zc = Zeroconf(ip_version=IPVersion.V4Only)
            self._zc.register_service(self._info)
            logger.info("mdns: advertising %s.local -> %s:%d", self._hostname, ip, self._port)
        except Exception as exc:
            logger.warning("mdns: failed to register service: %s", exc)
            self._zc = None
            self._info = None

    def stop(self) -> None:
        if self._zc is None:
            return
        try:
            if self._info is not None:
                self._zc.unregister_service(self._info)
            self._zc.close()
        except Exception as exc:
            logger.debug("mdns: error during shutdown: %s", exc)
        finally:
            self._zc = None
            self._info = None


def _primary_ipv4() -> Optional[str]:
    """Return the IP of the interface used for outbound traffic."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
