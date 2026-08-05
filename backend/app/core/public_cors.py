"""Make the order-status endpoint readable from any origin.

`/track/{id}/{token}` is deliberately public: it is how a **supplier's** page is
read by their **customer's** browser, and those are two different Taktline
instances on two different hosts. The app's ordinary `CORSMiddleware` carries a
strict origin allowlist — correct for every other endpoint, and fatal for this
one, because it answers the preflight itself and returns 400 before any route
runs. Setting the headers on the route cannot fix that; the response never gets
there.

So this sits **outside** `CORSMiddleware` (added last, therefore outermost) and
handles `/track/` entirely: it answers the preflight and stamps the headers on
the way out, error responses included — a 404 for an expired link is something
the reader is entitled to see rather than have blocked.

**`*` and no credentials, always.** That pairing is the security property, not a
shortcut: a browser sends no cookies to a wildcard origin, so a cross-origin
reader can only ever get the customer view. The signed-in extras
(`_viewer_is_a_member`, the *Start work* handle) ride on the session cookie, which
only a same-origin request carries — and same-origin requests do not consult CORS
at all, so this changes nothing for our own page. `access-control-allow-credentials`
is stripped rather than left to `CORSMiddleware`, because `*` together with
credentials is a combination browsers reject outright.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

#: Only the JSON. `/o/{id}/{token}` is a page a person opens, not something
#: another site fetches, and widening this to it would buy nothing.
PUBLIC_PREFIX = "/track/"

_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Accept, Content-Type",
    "Access-Control-Max-Age": "600",
}


class PublicReadCORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith(PUBLIC_PREFIX):
            return await call_next(request)

        if request.method == "OPTIONS":
            return Response(status_code=204, headers=_HEADERS)

        response = await call_next(request)
        response.headers.update(_HEADERS)
        # Starlette's MutableHeaders has no `pop`; `del` on an absent key raises.
        if "access-control-allow-credentials" in response.headers:
            del response.headers["access-control-allow-credentials"]
        return response
