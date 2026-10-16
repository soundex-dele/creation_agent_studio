import ipaddress
from urllib.parse import urlsplit
from rest_framework import serializers


class FetchSerializer(serializers.Serializer):
    url = serializers.CharField(max_length=8192, trim_whitespace=True)

    def validate(self, attrs):
        if set(self.initial_data) - {"url"}:
            raise serializers.ValidationError("仅支持 url 参数。")
        return attrs

    def validate_url(self, value):
        try:
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.port not in {None, 80, 443} or "\\" in value
                    or any(ord(c) < 33 for c in value)):
                raise ValueError()
            host = parsed.hostname.rstrip(".").lower()
            if host == "localhost" or host.endswith((".localhost", ".local")):
                raise ValueError()
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address and (not address.is_global or host == "168.63.129.16"):
                raise ValueError()
        except ValueError:
            raise serializers.ValidationError("请输入不含账号密码的公网 HTTP/HTTPS 网址（端口 80 或 443）。") from None
        # DNS and every network connection are checked again by the pinned-IP proxy.
        return value
