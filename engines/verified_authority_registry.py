"""Verified New York insurance-rescission authorities with offline matching."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date as calendar_date
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit


SUPPORTED_JURISDICTIONS = frozenset({"NY"})
SUPPORTED_AUTHORITY_TYPES = frozenset({"case", "statute"})
TRUSTED_SOURCE_HOSTS = frozenset({"www.nycourts.gov", "www.nysenate.gov"})
MAX_PROPOSITION_LENGTH = 500
MAX_PROPOSITIONS = 12

_CANONICAL_FIELDS = (
    "authority_id",
    "jurisdiction",
    "authority_type",
    "citation",
    "title",
    "source_url",
    "issuing_body",
    "date",
    "propositions",
)
_AUTHORITY_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _canonical_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the fields covered by the authority's content hash."""
    missing = [field for field in _CANONICAL_FIELDS if field not in record]
    if missing:
        raise ValueError(f"authority record missing fields: {', '.join(missing)}")
    return {
        field: list(record[field]) if field == "propositions" else record[field]
        for field in _CANONICAL_FIELDS
    }


def compute_authority_sha256(record: Mapping[str, Any] | "AuthorityRecord") -> str:
    """Compute SHA-256 over stable UTF-8 JSON for the canonical record fields."""
    values = record.as_canonical_dict() if isinstance(record, AuthorityRecord) else record
    encoded = json.dumps(
        _canonical_payload(values),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_source_url(source_url: str) -> None:
    parsed = urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in TRUSTED_SOURCE_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or not parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"untrusted or malformed authority source URL: {source_url!r}")


@dataclass(frozen=True)
class AuthorityRecord:
    """An immutable, hash-verified legal authority record."""

    authority_id: str
    jurisdiction: str
    authority_type: str
    citation: str
    title: str
    source_url: str
    issuing_body: str
    date: str
    propositions: tuple[str, ...]
    sha256: str

    def __post_init__(self) -> None:
        scalar_fields = (
            "authority_id",
            "jurisdiction",
            "authority_type",
            "citation",
            "title",
            "source_url",
            "issuing_body",
            "date",
            "sha256",
        )
        for field in scalar_fields:
            value = getattr(self, field)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{field} must be a non-empty, trimmed string")

        if not _AUTHORITY_ID_PATTERN.fullmatch(self.authority_id):
            raise ValueError(f"malformed authority_id: {self.authority_id!r}")
        if self.jurisdiction not in SUPPORTED_JURISDICTIONS:
            raise ValueError(f"unsupported jurisdiction: {self.jurisdiction!r}")
        if self.authority_type not in SUPPORTED_AUTHORITY_TYPES:
            raise ValueError(f"unsupported authority_type: {self.authority_type!r}")
        _validate_source_url(self.source_url)

        try:
            parsed_date = calendar_date.fromisoformat(self.date)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"date must be a valid ISO date: {self.date!r}") from exc
        if parsed_date.isoformat() != self.date:
            raise ValueError(f"date must use YYYY-MM-DD format: {self.date!r}")

        if not isinstance(self.propositions, tuple) or not (
            1 <= len(self.propositions) <= MAX_PROPOSITIONS
        ):
            raise ValueError("propositions must be a non-empty bounded tuple")
        for proposition in self.propositions:
            if (
                not isinstance(proposition, str)
                or proposition != proposition.strip()
                or not 20 <= len(proposition) <= MAX_PROPOSITION_LENGTH
            ):
                raise ValueError("each proposition must be trimmed and 20-500 characters")

        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        if compute_authority_sha256(self) != self.sha256:
            raise ValueError(f"hash mismatch for authority {self.authority_id!r}")

    def as_canonical_dict(self) -> dict[str, Any]:
        return {
            field: list(getattr(self, field))
            if field == "propositions"
            else getattr(self, field)
            for field in _CANONICAL_FIELDS
        }


def _record_from_mapping(raw: Mapping[str, Any]) -> AuthorityRecord:
    expected = set(_CANONICAL_FIELDS) | {"sha256"}
    if set(raw) != expected:
        extra = sorted(set(raw) - expected)
        missing = sorted(expected - set(raw))
        raise ValueError(f"malformed authority fields; missing={missing}, extra={extra}")
    values = dict(raw)
    propositions = values.get("propositions")
    if isinstance(propositions, list):
        values["propositions"] = tuple(propositions)
    return AuthorityRecord(**values)


def validate_registry(
    records: Iterable[Mapping[str, Any] | AuthorityRecord],
) -> tuple[AuthorityRecord, ...]:
    """Validate and freeze a registry, rejecting duplicates and malformed records."""
    validated: list[AuthorityRecord] = []
    seen_ids: set[str] = set()
    for raw in records:
        record = raw if isinstance(raw, AuthorityRecord) else _record_from_mapping(raw)
        if record.authority_id in seen_ids:
            raise ValueError(f"duplicate authority_id: {record.authority_id!r}")
        seen_ids.add(record.authority_id)
        validated.append(record)
    if not validated:
        raise ValueError("authority registry must not be empty")
    return tuple(validated)


_SEEDED_RECORDS = (
    {
        "authority_id": "ny-ins-law-3105",
        "jurisdiction": "NY",
        "authority_type": "statute",
        "citation": "N.Y. Ins. Law § 3105",
        "title": "Representations by the insured",
        "source_url": "https://www.nysenate.gov/legislation/laws/ISC/3105",
        "issuing_body": "New York State Legislature",
        "date": "1984-09-01",
        "propositions": (
            "A false representation is a statement that does not conform to the facts.",
            "A misrepresentation permits avoidance of an insurance contract only if it was material.",
            "Materiality exists when truthful knowledge would have led the insurer to refuse to make the contract.",
            "Evidence of the insurer’s practice concerning acceptance or rejection of similar risks is admissible on materiality.",
        ),
        "sha256": "08143aca44aabb2bb864bc61c967e76da4d3c142b3c25c2ad7f310788aee4ad7",
    },
    {
        "authority_id": "ny-estiverne-mic-2024-06327",
        "jurisdiction": "NY",
        "authority_type": "case",
        "citation": "2024 NY Slip Op 06327; 233 AD3d 844",
        "title": "Estiverne v MIC Gen. Ins. Corp.",
        "source_url": "https://www.nycourts.gov/reporter//3dseries/2024/2024_06327.htm",
        "issuing_body": "New York Supreme Court, Appellate Division, Second Department",
        "date": "2024-12-18",
        "propositions": (
            "An insurer may rescind an insurance policy based on a material misrepresentation in the insurance application.",
            "Underwriting documentation may establish materiality as a matter of law by showing the insurer would not have issued the policy had it known the truth.",
            "An innocent material misrepresentation may be sufficient for rescission.",
            "Acceptance of a policy may ratify the answers supplied in the insurance application.",
        ),
        "sha256": "4004a6bb7b2c920011d32cf194fc456965243bfc84657a94b4dcbc1464c3d75a",
    },
    {
        "authority_id": "ny-associated-industrial-farahnik-2025-03760",
        "jurisdiction": "NY",
        "authority_type": "case",
        "citation": "2025 NY Slip Op 03760; 239 AD3d 533",
        "title": "Associated Indus. Ins. Co., Inc. v Farahnik",
        "source_url": "https://www.nycourts.gov/reporter/3dseries/2025/2025_03760.htm",
        "issuing_body": "New York Supreme Court, Appellate Division, First Department",
        "date": "2025-06-17",
        "propositions": (
            "Rescission for material misrepresentation renders an insurance policy void ab initio.",
            "A policy void ab initio affords no coverage to an additional insured.",
            "An insurer’s post-discovery conduct may support equitable waiver of the right to rescind.",
        ),
        "sha256": "0f235fbec0e96e24d5c91d5b073ffcba051492774b9f10cca3d6cae7263bde6b",
    },
)

VERIFIED_NY_RESCISSION_AUTHORITIES = validate_registry(_SEEDED_RECORDS)

_NY_SIGNALS = (
    "new york",
    "n.y. ins",
    "ny insurance law",
    "insurance law § 3105",
    "insurance law 3105",
    "section 3105",
    "2024 ny slip op 06327",
    "2025 ny slip op 03760",
    "233 ad3d 844",
    "239 ad3d 533",
    "estiverne",
    "farahnik",
)
_INSURANCE_SIGNALS = (
    "insurance",
    "insurer",
    "insured",
    "underwriting",
    "coverage",
    "additional insured",
    "section 3105",
)
_DOCTRINE_SIGNALS = (
    "material misrepresentation",
    "material false representation",
    "innocent misrepresentation",
    "false statement in the application",
    "false answer in the application",
    "rescind",
    "rescission",
    "void ab initio",
    "section 3105",
    "§ 3105",
)


def match_verified_authorities(question: str) -> tuple[AuthorityRecord, ...]:
    """Return this pack only for NY insurance rescission/misrepresentation issues."""
    if not isinstance(question, str):
        raise TypeError("question must be a string")
    normalized = " ".join(question.casefold().replace("’", "'").split())
    if not normalized:
        return ()
    has_ny = any(signal in normalized for signal in _NY_SIGNALS)
    has_insurance = any(signal in normalized for signal in _INSURANCE_SIGNALS)
    has_doctrine = any(signal in normalized for signal in _DOCTRINE_SIGNALS)
    if has_ny and has_insurance and has_doctrine:
        return VERIFIED_NY_RESCISSION_AUTHORITIES
    return ()


__all__ = [
    "AuthorityRecord",
    "SUPPORTED_AUTHORITY_TYPES",
    "SUPPORTED_JURISDICTIONS",
    "TRUSTED_SOURCE_HOSTS",
    "VERIFIED_NY_RESCISSION_AUTHORITIES",
    "compute_authority_sha256",
    "match_verified_authorities",
    "validate_registry",
]
