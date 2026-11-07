"""ASGI body admission independent of Content-Length, including chunked requests."""

from starlette.responses import JSONResponse


class CopilotBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith(
            "/api/copilot/"
        ):
            return await self.app(scope, receive, send)
        frames = []
        size = 0
        while True:
            frame = await receive()
            if frame["type"] == "http.disconnect":
                return
            size += len(frame.get("body", b""))
            if size > 131072:
                return await JSONResponse(
                    {"detail": "REQUEST_SIZE_LIMIT"}, status_code=413
                )(scope, receive, send)
            frames.append(frame)
            if not frame.get("more_body", False):
                break

        async def replay():
            if frames:
                return frames.pop(0)
            return await receive()

        await self.app(scope, replay, send)
