"""AWS Lambda entrypoint for the ORIGIN dashboard and REST API.

The same ASGI application that ``origin.cli serve`` runs locally is served here
through a Lambda Function URL, so there is exactly one implementation of the API
and no second code path to keep honest.

Two deployment facts worth knowing:

* ``acryl-datahub`` is deliberately not in this package. ``api/app.py`` treats it
  as optional and reports its absence in the response rather than implying the
  catalogue write-back happened. See the comment there.
* Configuration arrives as Lambda environment variables, not a ``.env`` file, so
  nothing secret is baked into the zip. ``config.load()`` reads the environment
  either way and needs no deployment-specific branch.
"""

from __future__ import annotations

from mangum import Mangum

from .app import app

#: Function URLs deliver an API Gateway v2 payload. Mangum needs to be told the
#: stage is not part of the path, or every route would be prefixed with it.
handler = Mangum(app, api_gateway_base_path="/", lifespan="off")
