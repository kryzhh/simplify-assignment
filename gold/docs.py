"""Pinned, integrity-checked browser assets for the interactive OpenAPI documentation."""
import base64
import hashlib

from fastapi.responses import HTMLResponse

SWAGGER = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.36.0"
REDOC = "https://cdn.jsdelivr.net/npm/redoc@2.5.4/bundles/redoc.standalone.js"
SWAGGER_JS = "sha384-fUpRgC19yPykTqzdrUbdAg8NTiu16NEKf9U12J+IJWCg8/1mEI8f2+PEIz60Wyd+"
SWAGGER_CSS = "sha384-z/AtSaOHGn5MJ5auAHXUypohywlIWLBZo1jeGmhdpVIbCnFhxAH92cwdV41oyINc"
REDOC_JS = "sha384-w447zOpYfw/1Tv/5AK9NfHTlQIqE3RVR6KY62jCyy9zNDgO64cMwGGP1Fj0zJVf5"


def documentation(redoc=False):
    if redoc:
        url, digest = REDOC, REDOC_JS
        init = "Redoc.init('./openapi.json', {disableGoogleFont:true}, document.getElementById('ui'));"
        css = ""
    else:
        url, digest = SWAGGER + "/swagger-ui-bundle.js", SWAGGER_JS
        init = ("SwaggerUIBundle({url:'./openapi.json',dom_id:'#ui',validatorUrl:null,"
                "persistAuthorization:false,queryConfigEnabled:false});")
        css = (f'<link rel="stylesheet" href="{SWAGGER}/swagger-ui.css" '
               f'integrity="{SWAGGER_CSS}" crossorigin="anonymous">')
    inline_hash = base64.b64encode(hashlib.sha256(init.encode()).digest()).decode()
    policy = (f"default-src 'none'; script-src '{digest}' 'sha256-{inline_hash}'; "
              f"style-src 'unsafe-inline' {SWAGGER}/swagger-ui.css; img-src 'self' data:; "
              "connect-src 'self'; worker-src blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    html = (f'<!doctype html><html lang="en"><meta charset="utf-8"><title>Digital Gold API</title>'
            f'{css}<div id="ui"></div><script src="{url}" integrity="{digest}" '
            f'crossorigin="anonymous"></script><script>{init}</script></html>')
    return HTMLResponse(html, headers={"Content-Security-Policy": policy, "Referrer-Policy": "no-referrer",
                                       "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
