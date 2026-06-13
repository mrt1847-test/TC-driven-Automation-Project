from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Any
from urllib.parse import quote

import httpx

from worker.core.config import MASK, mask_secrets
from worker.models.schemas import ExcelColumnMapping, NormalizedTestCase, SourceLocation, TestStep
from worker.services.case_import import DEFAULT_MAPPING, _generate_automation_key, _parse_steps
from worker.services.automation_keys import reserve_automation_key


SHEETS_READONLY_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleSheetsConnectorError(Exception):
    __test__ = False

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def import_from_google_sheets(
    spreadsheet_id: str,
    sheet_name: str,
    mapping: ExcelColumnMapping | None,
    config: dict[str, Any] | None = None,
    existing_keys: set[str] | None = None,
) -> list[NormalizedTestCase]:
    config = config or {}
    existing = existing_keys if existing_keys is not None else set()
    if bool(config.get("mock")):
        return _mock_cases(existing)

    credential_json = str(config.get("credential_json") or "")
    if not spreadsheet_id.strip():
        raise GoogleSheetsConnectorError(400, "Google Sheets import requires spreadsheetId.")
    if not sheet_name.strip():
        raise GoogleSheetsConnectorError(400, "Google Sheets import requires sheetName.")
    if not credential_json.strip():
        raise GoogleSheetsConnectorError(
            400,
            "Google Sheets import requires credential JSON. Configure Google Sheets in Settings and store credentials.",
        )

    access_token = await _google_access_token(credential_json)
    values = await _fetch_sheet_values(spreadsheet_id, sheet_name, access_token, credential_json)
    return normalize_google_sheet_values(values, spreadsheet_id, sheet_name, mapping or DEFAULT_MAPPING, existing)


def normalize_google_sheet_values(
    values: list[list[Any]],
    spreadsheet_id: str,
    sheet_name: str,
    mapping: ExcelColumnMapping,
    existing_keys: set[str],
) -> list[NormalizedTestCase]:
    if not values:
        return []
    headers = [str(value or "").strip() for value in values[0]]
    rows = values[1:]
    cases: list[NormalizedTestCase] = []
    endpoint = _values_url(spreadsheet_id, sheet_name)
    for offset, raw_row in enumerate(rows, start=2):
        row = _row_dict(headers, raw_row)
        if not any(str(value or "").strip() for value in row.values()):
            continue
        case_id = _cell(row, mapping.case_id) or f"{spreadsheet_id}:{sheet_name}:{offset}"
        title = _cell(row, mapping.title) or case_id
        automation_key = reserve_automation_key(
            _cell(row, mapping.automation_key),
            title=title,
            source_id=case_id,
            reserved_keys=existing_keys,
        )
        existing_keys.add(automation_key)
        expected_result = _cell(row, mapping.expected) or None
        preconditions = [line.strip() for line in _cell(row, mapping.precondition).splitlines() if line.strip()]
        cases.append(
            NormalizedTestCase(
                source_type="google_sheets",
                source_id=case_id,
                source_location=SourceLocation(
                    sheet_name=sheet_name,
                    row_index=offset,
                    api_endpoint=endpoint,
                ),
                title=title,
                preconditions=preconditions,
                steps=_parse_steps(_cell(row, mapping.step), expected_result or ""),
                expected_result=expected_result,
                automation_key=automation_key,
                priority=_cell(row, mapping.priority) or None,
                start_url=_cell(row, mapping.start_url) or None,
            )
        )
    return cases


async def _google_access_token(credential_json: str, scope: str = SHEETS_READONLY_SCOPE) -> str:
    info = _credential_info(credential_json)
    access_token = str(info.get("access_token") or "").strip()
    if access_token:
        return access_token
    if info.get("type") == "service_account":
        return await _service_account_access_token(info, credential_json, scope)
    raise GoogleSheetsConnectorError(
        400,
        "Google Sheets credential JSON must include an OAuth access_token or service account private_key/client_email.",
    )


async def _service_account_access_token(info: dict[str, Any], credential_json: str, scope: str) -> str:
    client_email = str(info.get("client_email") or "").strip()
    private_key = str(info.get("private_key") or "").strip()
    if not client_email or not private_key:
        raise GoogleSheetsConnectorError(
            400,
            "Google service account JSON requires client_email and private_key.",
        )
    now = int(time.time())
    assertion = _signed_jwt(
        {"alg": "RS256", "typ": "JWT"},
        {
            "iss": client_email,
            "scope": scope,
            "aud": GOOGLE_TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
        private_key,
    )
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
        except httpx.HTTPError as error:
            raise GoogleSheetsConnectorError(
                502,
                _mask_with_credential(f"Google OAuth token request failed: {error}", credential_json),
            ) from error
    if response.status_code >= 400:
        raise GoogleSheetsConnectorError(
            401 if response.status_code in {400, 401, 403} else 502,
            f"Google Sheets credentials rejected. {_google_error_detail(response, credential_json)}",
        )
    payload = _json_payload(response, credential_json)
    token = str(payload.get("access_token") or "").strip() if isinstance(payload, dict) else ""
    if not token:
        raise GoogleSheetsConnectorError(502, "Google OAuth token response did not include an access token.")
    return token


async def _fetch_sheet_values(
    spreadsheet_id: str,
    sheet_name: str,
    access_token: str,
    credential_json: str,
) -> list[list[Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(
                _values_url(spreadsheet_id, sheet_name),
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
            )
        except httpx.HTTPError as error:
            raise GoogleSheetsConnectorError(
                502,
                _mask_with_credential(f"Google Sheets API request failed: {error}", credential_json),
            ) from error
    _raise_for_google_error(response, credential_json)
    payload = _json_payload(response, credential_json)
    values = payload.get("values", []) if isinstance(payload, dict) else []
    return values if isinstance(values, list) else []


def _raise_for_google_error(response: httpx.Response, credential_json: str) -> None:
    if response.status_code < 400:
        return
    detail = _google_error_detail(response, credential_json)
    if response.status_code in {401, 403}:
        raise GoogleSheetsConnectorError(response.status_code, f"Google Sheets credentials rejected or unauthorized. {detail}")
    if response.status_code == 404:
        raise GoogleSheetsConnectorError(404, f"Google spreadsheet or sheet range was not found. {detail}")
    raise GoogleSheetsConnectorError(502, f"Google Sheets API returned HTTP {response.status_code}. {detail}")


def _json_payload(response: httpx.Response, credential_json: str) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise GoogleSheetsConnectorError(
            502,
            _mask_with_credential("Google API returned invalid JSON.", credential_json),
        ) from error


def _google_error_detail(response: httpx.Response, credential_json: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            detail = error.get("message") or str(error)
        else:
            detail = payload.get("message") or str(payload)
    else:
        detail = str(payload)
    return _mask_with_credential(detail, credential_json)


def _credential_info(credential_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(credential_json)
    except ValueError:
        token = credential_json.strip()
        if token:
            return {"access_token": token}
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _values_url(spreadsheet_id: str, sheet_name: str) -> str:
    range_name = sheet_name.strip() or "Cases"
    encoded_range = quote(range_name, safe="!:")
    return f"https://sheets.googleapis.com/v4/spreadsheets/{quote(spreadsheet_id)}/values/{encoded_range}?majorDimension=ROWS"


def _row_dict(headers: list[str], row: list[Any]) -> dict[str, Any]:
    return {header: row[index] if index < len(row) else "" for index, header in enumerate(headers)}


def _cell(row: dict[str, Any], header: str) -> str:
    value = row.get(header)
    return "" if value is None else str(value).strip()


def _mock_cases(existing: set[str]) -> list[NormalizedTestCase]:
    title = "Sample Google Sheets Case"
    source_id = "GS-001"
    automation_key = _generate_automation_key(title, "sample_google_sheets_case", existing)
    existing.add(automation_key)
    return [
        NormalizedTestCase(
            source_type="google_sheets",
            source_id=source_id,
            title=title,
            steps=[TestStep(index=1, action="Navigate", expected="Page visible")],
            automation_key=automation_key,
        )
    ]


def _signed_jwt(header: dict[str, Any], payload: dict[str, Any], private_key_pem: str) -> str:
    signing_input = (
        f"{_base64url(json.dumps(header, separators=(',', ':')).encode('utf-8'))}."
        f"{_base64url(json.dumps(payload, separators=(',', ':')).encode('utf-8'))}"
    )
    signature = _rsa_sha256_sign(signing_input.encode("ascii"), private_key_pem)
    return f"{signing_input}.{_base64url(signature)}"


def _rsa_sha256_sign(message: bytes, private_key_pem: str) -> bytes:
    modulus, private_exponent = _rsa_private_numbers(private_key_pem)
    digest = hashlib.sha256(message).digest()
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + digest
    key_size = (modulus.bit_length() + 7) // 8
    if key_size < len(digest_info) + 11:
        raise GoogleSheetsConnectorError(400, "Google service account private key is too small for RS256 signing.")
    encoded = b"\x00\x01" + (b"\xff" * (key_size - len(digest_info) - 3)) + b"\x00" + digest_info
    signature_int = pow(int.from_bytes(encoded, "big"), private_exponent, modulus)
    return signature_int.to_bytes(key_size, "big")


def _rsa_private_numbers(private_key_pem: str) -> tuple[int, int]:
    der = _pem_to_der(private_key_pem)
    reader = _Asn1Reader(der).read_sequence()
    reader.read_integer()
    reader.skip()
    private_key_der = reader.read_octet_string()
    rsa = _Asn1Reader(private_key_der).read_sequence()
    rsa.read_integer()
    modulus = rsa.read_integer()
    rsa.read_integer()
    private_exponent = rsa.read_integer()
    return modulus, private_exponent


def _pem_to_der(private_key_pem: str) -> bytes:
    lines = [
        line.strip()
        for line in private_key_pem.strip().splitlines()
        if line and not line.startswith("-----")
    ]
    try:
        return base64.b64decode("".join(lines), validate=True)
    except ValueError as error:
        raise GoogleSheetsConnectorError(400, "Google service account private_key is not valid PEM.") from error


class _Asn1Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.offset = 0

    def read_sequence(self) -> "_Asn1Reader":
        return _Asn1Reader(self._read_value(0x30))

    def read_integer(self) -> int:
        value = self._read_value(0x02)
        return int.from_bytes(value, "big", signed=False)

    def read_octet_string(self) -> bytes:
        return self._read_value(0x04)

    def skip(self) -> None:
        _, length = self._read_header()
        self.offset += length

    def _read_value(self, expected_tag: int) -> bytes:
        tag, length = self._read_header()
        if tag != expected_tag:
            raise GoogleSheetsConnectorError(400, "Google service account private_key has an unsupported ASN.1 shape.")
        start = self.offset
        self.offset += length
        return self.data[start:self.offset]

    def _read_header(self) -> tuple[int, int]:
        if self.offset >= len(self.data):
            raise GoogleSheetsConnectorError(400, "Google service account private_key ended unexpectedly.")
        tag = self.data[self.offset]
        self.offset += 1
        if self.offset >= len(self.data):
            raise GoogleSheetsConnectorError(400, "Google service account private_key length is missing.")
        first = self.data[self.offset]
        self.offset += 1
        if first < 0x80:
            return tag, first
        length_bytes = first & 0x7F
        if length_bytes == 0 or self.offset + length_bytes > len(self.data):
            raise GoogleSheetsConnectorError(400, "Google service account private_key length is invalid.")
        length = int.from_bytes(self.data[self.offset:self.offset + length_bytes], "big")
        self.offset += length_bytes
        if self.offset + length > len(self.data):
            raise GoogleSheetsConnectorError(400, "Google service account private_key content is truncated.")
        return tag, length


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _mask_with_credential(message: str, credential_json: str) -> str:
    masked = message
    if credential_json:
        masked = masked.replace(credential_json, MASK)
    info = _credential_info(credential_json)
    secret_values = {
        "GOOGLE_ACCESS_TOKEN": str(info.get("access_token") or ""),
        "GOOGLE_PRIVATE_KEY": str(info.get("private_key") or ""),
        "GOOGLE_CLIENT_SECRET": str(info.get("client_secret") or ""),
        "GOOGLE_REFRESH_TOKEN": str(info.get("refresh_token") or ""),
    }
    masked = mask_secrets(masked, secret_values)
    for value in secret_values.values():
        if value:
            masked = masked.replace(value, MASK)
    return masked
