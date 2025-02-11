import os
import time

from dns import reversename, resolver
from fastapi import Request

class SourceVerifier:
    def __init__(self):
        pass

    def verify(self, request: Request):
        pass

class NightbotVerifier(SourceVerifier):
    _CLEANUP_INTERVAL = 300
    _CHECK_CACHE = 3600
    def __init__(self):
        super().__init__()
        self.checked_ips = {}
        self.last_checked = 0

    def verify(self, request):
        ip = None
        real_ip_header_key = os.getenv("REAL_IP_HEADER", None)
        if real_ip_header_key:
            ip = request.headers.get(real_ip_header_key)
        if not ip:
            ip = request.client.host
        return self._is_ip_from_nightbot(ip)

    def _is_ip_from_nightbot(self, ip):
        self._cleanup()
        if ip not in self.checked_ips:
            self.checked_ips[ip] = {
                'checked_at': time.time(),
                'pass': self._check_ip(ip)
            }
        return self.checked_ips[ip]['pass']

    def _cleanup(self):
        if self.last_checked + self._CLEANUP_INTERVAL <= time.time():
            for ip in self.checked_ips:
                if self.checked_ips[ip]['checked_at'] + self._CHECK_CACHE <= time.time():
                    del self.checked_ips[ip]
            self.last_checked = time.time()

    @staticmethod
    def _check_ip(ip):
        addr = reversename.from_address(ip)
        resolved = resolver.resolve(addr, "PTR")
        if not resolved:
            return False
        resolved = str(resolved[0])
        if not resolved.endswith(".nightbot.net."):
            return False
        resolved_ip = resolver.resolve(resolved)
        if not resolved_ip:
            return False
        resolved_ips = [str(ip) for ip in resolved_ip]
        return ip in resolved_ips


