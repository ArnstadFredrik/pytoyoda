"""Toyota Connected Services Controller."""

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any, ClassVar, Dict, Optional
from urllib import parse

import hishel
import httpx
import jwt

from pytoyoda.const import (
    ACCESS_TOKEN_URL,
    API_BASE_URL,
    AUTHENTICATE_URL,
    AUTHORIZE_URL,
)
from pytoyoda.exceptions import (
    ToyotaApiError,
    ToyotaInternalError,
    ToyotaInvalidUsernameError,
    ToyotaLoginError,
)
from pytoyoda.utils.log_utils import format_httpx_response

_LOGGER: logging.Logger = logging.getLogger(__name__)


@dataclass
class TokenInfo:
    """Class to store token information."""

    access_token: str
    refresh_token: str
    uuid: str
    expiration: datetime


class Controller:
    """Controller class for Toyota Connected Services."""

    # Class variable for token cache
    _TOKEN_CACHE: ClassVar[Dict[str, TokenInfo]] = {}

    def __init__(self, username: str, password: str, timeout: int = 60) -> None:
        """Initialize Controller class.

        Args:
            username: Toyota account username
            password: Toyota account password
            timeout: HTTP request timeout in seconds

        """
        self._username: str = username
        self._password: str = password
        self._timeout = timeout

        # URLs
        self._api_base_url = httpx.URL(API_BASE_URL)
        self._access_token_url = httpx.URL(ACCESS_TOKEN_URL)
        self._authenticate_url = httpx.URL(AUTHENTICATE_URL)
        self._authorize_url = httpx.URL(AUTHORIZE_URL)

        # Authentication state
        self._token_info: Optional[TokenInfo] = None

        # Load from cache if available
        if self._username in self._TOKEN_CACHE:
            self._token_info = self._TOKEN_CACHE[self._username]

    @property
    def _token(self) -> Optional[str]:
        """Get the current access token."""
        return self._token_info.access_token if self._token_info else None

    @property
    def _refresh_token(self) -> Optional[str]:
        """Get the current refresh token."""
        return self._token_info.refresh_token if self._token_info else None

    @property
    def _uuid(self) -> Optional[str]:
        """Get the current UUID."""
        return self._token_info.uuid if self._token_info else None

    @property
    def _token_expiration(self) -> Optional[datetime]:
        """Get the token expiration datetime."""
        return self._token_info.expiration if self._token_info else None

    def _is_token_valid(self) -> bool:
        """Check if the current token is valid and not expired."""
        if not self._token_info:
            return False
        return self._token_info.expiration > datetime.now()

    async def login(self) -> None:
        """Perform initial login if necessary."""
        if not self._is_token_valid():
            await self._update_token()

    async def _update_token(self) -> None:
        """Update the authentication token.

        First tries to refresh the token if available, falls back to
        full authentication.

        """
        if not self._is_token_valid():
            if self._refresh_token:
                try:
                    await self._refresh_tokens()
                    return
                except ToyotaLoginError:
                    _LOGGER.debug(
                        "Token refresh failed, falling back to full authentication"
                    )

            await self._authenticate()

    @asynccontextmanager
    async def _get_http_client(self):
        """Context manager for HTTP client with consistent timeout."""
        async with hishel.AsyncCacheClient(timeout=self._timeout) as client:
            yield client

    async def _authenticate(self) -> None:
        """Authenticate with username and password."""
        _LOGGER.debug("Authenticating with username and password")

        async with self._get_http_client() as client:
            # Authentication flow
            auth_data = await self._perform_authentication(client)

            # Authorization flow
            auth_code = await self._perform_authorization(client, auth_data["tokenId"])

            # Token retrieval
            token_data = await self._retrieve_tokens(client, auth_code)

            # Update tokens
            self._update_tokens(token_data)

    async def _perform_authentication(self, client) -> Dict[str, Any]:
        """Perform the authentication part of the login flow."""
        data: Dict[str, Any] = {}

        for _ in range(10):  # Try up to 10 times
            if "callbacks" in data:
                for cb in data["callbacks"]:
                    if (
                        cb["type"] == "NameCallback"
                        and cb["output"][0]["value"] == "User Name"
                    ):
                        cb["input"][0]["value"] = self._username
                    elif cb["type"] == "PasswordCallback":
                        cb["input"][0]["value"] = self._password
                    elif (
                        cb["type"] == "TextOutputCallback"
                        and cb["output"][0]["value"] == "User Not Found"
                    ):
                        raise ToyotaInvalidUsernameError(
                            "Authentication Failed. User Not Found."
                        )

            resp = await client.post(self._authenticate_url, json=data)
            _LOGGER.debug(format_httpx_response(resp))

            if resp.status_code != HTTPStatus.OK:
                raise ToyotaLoginError(
                    f"Authentication Failed. {resp.status_code}, {resp.text}."
                )

            data = resp.json()

            # Wait for tokenId to be returned in response
            if "tokenId" in data:
                return data

        raise ToyotaLoginError(
            "Authentication Failed. Token ID not received after multiple attempts."
        )

    async def _perform_authorization(self, client, token_id: str) -> str:
        """Perform the authorization part of the login flow.

        Args:
            client: HTTP client
            token_id: Token ID from authentication

        Returns:
            Authentication code

        """
        resp = await client.get(
            self._authorize_url,
            headers={"cookie": f"iPlanetDirectoryPro={token_id}"},
        )
        _LOGGER.debug(format_httpx_response(resp))

        if resp.status_code != HTTPStatus.FOUND:
            raise ToyotaLoginError(
                f"Authorization failed. {resp.status_code}, {resp.text}."
            )

        return parse.parse_qs(httpx.URL(resp.headers.get("location")).query.decode())[
            "code"
        ]

    async def _retrieve_tokens(self, client, auth_code: str) -> Dict[str, Any]:
        """Retrieve access and refresh tokens.

        Args:
            client: HTTP client
            auth_code: Authorization code

        Returns:
            Token response data

        """
        resp = await client.post(
            self._access_token_url,
            headers={"authorization": "basic b25lYXBwOm9uZWFwcA=="},
            data={
                "client_id": "oneapp",
                "code": auth_code,
                "redirect_uri": "com.toyota.oneapp:/oauth2Callback",
                "grant_type": "authorization_code",
                "code_verifier": "plain",
            },
        )
        _LOGGER.debug(format_httpx_response(resp))

        if resp.status_code != HTTPStatus.OK:
            raise ToyotaLoginError(
                f"Token retrieval failed. {resp.status_code}, {resp.text}."
            )

        return resp.json()

    async def _refresh_tokens(self) -> None:
        """Refresh the access token using the refresh token."""
        _LOGGER.debug("Refreshing tokens")

        async with self._get_http_client() as client:
            resp = await client.post(
                self._access_token_url,
                headers={"authorization": "basic b25lYXBwOm9uZWFwcA=="},
                data={
                    "client_id": "oneapp",
                    "redirect_uri": "com.toyota.oneapp:/oauth2Callback",
                    "grant_type": "refresh_token",
                    "code_verifier": "plain",
                    "refresh_token": self._refresh_token,
                },
            )
            _LOGGER.debug(format_httpx_response(resp))

            if resp.status_code != HTTPStatus.OK:
                raise ToyotaLoginError(
                    f"Token refresh failed. {resp.status_code}, {resp.text}."
                )

            self._update_tokens(resp.json())

    def _update_tokens(self, response_data: Dict[str, Any]) -> None:
        """Update token information from response data.

        Args:
            response_data: Token response data from API

        Raises:
            ToyotaLoginError: If required tokens are missing

        """
        # Verify all required tokens are present
        required_fields = ["access_token", "id_token", "refresh_token", "expires_in"]
        missing_fields = [
            field for field in required_fields if field not in response_data
        ]

        if missing_fields:
            raise ToyotaLoginError(
                f"Token retrieval failed. Missing fields: {', '.join(missing_fields)}"
            )

        # Decode the JWT to get the UUID
        uuid = jwt.decode(
            response_data["id_token"],
            algorithms=["RS256"],
            options={"verify_signature": False},
            audience="oneappsdkclient",
        )["uuid"]

        # Calculate expiration time
        expiration = datetime.now() + timedelta(seconds=response_data["expires_in"])

        # Update token info
        self._token_info = TokenInfo(
            access_token=response_data["access_token"],
            refresh_token=response_data["refresh_token"],
            uuid=uuid,
            expiration=expiration,
        )

        # Update cache
        self._TOKEN_CACHE[self._username] = self._token_info

    async def request_raw(  # noqa: PLR0913
        self,
        method: str,
        endpoint: str,
        vin: Optional[str] = None,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """Send a raw HTTP request to the Toyota API.

        Args:
            method: The HTTP method to use ("GET", "POST", "PUT", "DELETE")
            endpoint: The API endpoint to request
            vin: Vehicle Identification Number (optional)
            body: Request body as dictionary (optional)
            params: URL query parameters (optional)
            headers: Additional HTTP headers (optional)

        Returns:
            The raw HTTP response

        Raises:
            ToyotaInternalError: If an invalid HTTP method is provided
            ToyotaApiError: If the API returns an error response

        """
        valid_methods = ("GET", "POST", "PUT", "DELETE")
        if method not in valid_methods:
            raise ToyotaInternalError(
                f"Invalid request method: {method}. Must be one of {valid_methods}"
            )

        # Ensure we have a valid token
        if not self._is_token_valid():
            await self._update_token()

        # Prepare headers
        request_headers = self._prepare_headers(vin, headers)

        # Make the request
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(
                method,
                f"{self._api_base_url}{endpoint}",
                headers=request_headers,
                json=body,
                params=params,
                follow_redirects=True,
            )
            _LOGGER.debug(format_httpx_response(response))

            if response.status_code in [HTTPStatus.OK, HTTPStatus.ACCEPTED]:
                return response

        raise ToyotaApiError(
            f"Request Failed. {response.status_code}, {response.text}."
        )

    def _prepare_headers(
        self,
        vin: Optional[str] = None,
        additional_headers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Prepare headers for API requests.

        Args:
            vin: Vehicle Identification Number (optional)
            additional_headers: Additional headers to include (optional)

        Returns:
            Complete headers dictionary

        """
        headers = {
            "x-api-key": "tTZipv6liF74PwMfk9Ed68AQ0bISswwf3iHQdqcF",
            "x-guid": self._uuid,
            "guid": self._uuid,
            "authorization": f"Bearer {self._token}",
            "x-channel": "ONEAPP",
            "x-brand": "T",
            "user-agent": "okhttp/4.10.0",
        }

        # Add VIN if provided
        if vin is not None:
            headers["vin"] = vin

        # Add additional headers
        if additional_headers:
            headers.update(additional_headers)

        return headers

    async def request_json(  # noqa: PLR0913
        self,
        method: str,
        endpoint: str,
        vin: Optional[str] = None,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a request to the Toyota API and return JSON response.

        Args:
            method: The HTTP method to use ("GET", "POST", "PUT", "DELETE")
            endpoint: The API endpoint to request
            vin: Vehicle Identification Number (optional)
            body: Request body as dictionary (optional)
            params: URL query parameters (optional)
            headers: Additional HTTP headers (optional)

        Returns:
            The JSON response as a dictionary

        Examples:
            response = await controller.request_json("GET", "/cars", vin="1234567890")

        """
        response = await self.request_raw(method, endpoint, vin, body, params, headers)
        return response.json()
