from rest_framework.renderers import BaseRenderer, JSONRenderer


class EventStreamRenderer(BaseRenderer):
    """Allow DRF content negotiation to admit SSE streaming requests."""

    media_type = "text/event-stream"
    format = "event-stream"
    charset = None
    render_style = "binary"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # Successful stream responses bypass renderer serialization. This path
        # preserves a useful JSON body for authentication and validation errors.
        if data is None:
            return b""
        return JSONRenderer().render(
            data,
            accepted_media_type="application/json",
            renderer_context=renderer_context,
        )
