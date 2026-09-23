"""CFBD access through the official `cfbd` client.

Responses are decoded as JSON objects instead of the generated pydantic
models. Those models mark some nullable fields as required, which would
drop games when attendance or division is null. One HTTP call per endpoint.
"""

from __future__ import annotations

from collections.abc import Callable


class CfbdError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class MissingApiKey(CfbdError):
    pass


class CfbdClient:
    def __init__(self, api_key: str, on_call: Callable[[str, int, int | None], None] | None = None):
        cleaned = (api_key or "").strip()
        if not cleaned:
            raise MissingApiKey("CFBD_API_KEY is empty.")
        self.api_key = cleaned
        self.on_call = on_call or (lambda _endpoint, _status, _year: None)

    def fetch_teams(self, year: int) -> list:
        return self._get("/teams/fbs", {"year": year}, year)

    def fetch_games(self, year: int) -> list:
        try:
            return self._get(
                "/games",
                {"year": year, "classification": "fbs", "seasonType": "both"},
                year,
            )
        except CfbdError as exc:
            if exc.status != 400:
                raise
            regular = self._get(
                "/games",
                {"year": year, "classification": "fbs", "seasonType": "regular"},
                year,
            )
            postseason = self._get(
                "/games",
                {"year": year, "classification": "fbs", "seasonType": "postseason"},
                year,
            )
            return _merge_by_id(regular, postseason)

    def fetch_records(self, year: int) -> list:
        return self._get("/records", {"year": year}, year)

    def fetch_rankings(self, year: int) -> list:
        # Do not send poll=AP. CFBD documents poll=cfp only; other values return 400.
        try:
            return self._get("/rankings", {"year": year, "seasonType": "both"}, year)
        except CfbdError as exc:
            if exc.status != 400:
                raise
            regular = self._get("/rankings", {"year": year, "seasonType": "regular"}, year)
            postseason = self._get("/rankings", {"year": year, "seasonType": "postseason"}, year)
            return list(regular) + list(postseason)

    def fetch_venues(self) -> list:
        return self._get("/venues", {}, None)

    def _get(self, path: str, params: dict, year: int | None) -> list:
        cfbd = _import_cfbd()
        from cfbd.exceptions import ApiException

        configuration = cfbd.Configuration(access_token=self.api_key)
        query = [(key, value) for key, value in params.items() if value is not None]
        endpoint = path if not query else path + "?" + "&".join(f"{key}={value}" for key, value in query)
        with cfbd.ApiClient(configuration) as api_client:
            try:
                data = api_client.call_api(
                    path,
                    "GET",
                    query_params=query,
                    header_params={"Accept": "application/json"},
                    response_types_map={"200": "object"},
                    auth_settings=["apiKey"],
                    _return_http_data_only=True,
                    _request_timeout=90,
                )
            except ApiException as exc:
                status = getattr(exc, "status", None)
                self.on_call(endpoint, int(status or 0), year)
                raise CfbdError(_public_error(exc), status=status) from exc
        self.on_call(endpoint, 200, year)
        if not isinstance(data, list):
            raise CfbdError(f"CFBD {path} did not return a list.")
        return data


def _import_cfbd():
    try:
        import cfbd
    except ImportError as exc:
        raise CfbdError(
            "The cfbd package is not installed. From the repo root run: pip install -r requirements.txt"
        ) from exc
    return cfbd


def _public_error(exc: Exception) -> str:
    status = getattr(exc, "status", None)
    body = getattr(exc, "body", None)
    snippet = ""
    if isinstance(body, bytes):
        snippet = body.decode("utf-8", errors="replace")[:300]
    elif body:
        snippet = str(body)[:300]
    if status == 401:
        return "CFBD rejected CFBD_API_KEY (HTTP 401). Check the key at https://collegefootballdata.com/key"
    if status in {403, 429}:
        return (
            "CFBD refused the request (HTTP "
            f"{status}). The free tier is 1,000 calls per month, and the existing cache was left unchanged."
        )
    if status:
        return f"CFBD request failed with HTTP {status}. {snippet}".strip()
    return f"CFBD request failed: {exc}"


def _merge_by_id(first: list, second: list) -> list:
    merged = {}
    for game in list(first) + list(second):
        if isinstance(game, dict) and game.get("id") is not None:
            merged[game["id"]] = game
    return list(merged.values())
