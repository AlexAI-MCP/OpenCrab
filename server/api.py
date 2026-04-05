# Entrypoint adapter — Railway uses `uvicorn server.api:app`
from apps.api.main import app  # noqa: F401
