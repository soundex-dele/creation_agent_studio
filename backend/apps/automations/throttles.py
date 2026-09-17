from rest_framework.throttling import SimpleRateThrottle


class AutomationWebhookThrottle(SimpleRateThrottle):
    scope = "automation_webhook"
    rate = "120/min"

    def get_cache_key(self, request, view):
        public_id = view.kwargs.get("public_id", "unknown")
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": f"{public_id}:{ident}"}
