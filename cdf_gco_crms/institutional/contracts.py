"""Reference contracts separate access, evidence, currency and institutional approval."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol
from ..calibration.store import ReviewerContext
from pydantic import BaseModel, ConfigDict, Field


class OperatingMode(str, Enum):
    PUBLIC_SYNTHETIC_DEMO = 'PUBLIC_SYNTHETIC_DEMO'
    PRIVATE_INSTITUTIONAL = 'PRIVATE_INSTITUTIONAL'


class InstitutionalAccessDenied(PermissionError):
    pass


@dataclass(frozen=True)
class AccessContext:
    """Opaque session handle. Identity/roles are resolved by the trusted adapter."""
    session_handle: str
    case_id: str | None = None


class InstitutionalAuthorizer(Protocol):
    def authorize(self, context: AccessContext, permission: str, resource: str) -> ReviewerContext:
        """Validate real identity, tenancy, session expiry and resource grants or deny."""
        ...


class DenyAllAuthorizer:
    def authorize(self, context: AccessContext, permission: str, resource: str) -> ReviewerContext:
        raise InstitutionalAccessDenied('PENDING_INSTITUTIONAL_AUTHENTICATION')


class DoARecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    source_id: str
    source_version: str
    page: int = Field(ge=1)
    provision: str
    business_activity: str
    authority_category: str | None = None
    relevant_process: str | None = None
    requester: list[str] | None = None
    preparer: list[str] | None = None
    reviewer: list[str] | None = None
    recommender: list[str] | None = None
    approver: list[str] | None = None
    executor: list[str] | None = None
    other_roles: dict[str, str] = Field(default_factory=dict)
    financial_threshold: str | None = None
    delegation_conditions: dict[str, str] = Field(default_factory=dict)
    restrictions: list[str] | None = None
    exception_paths: list[str] | None = None
    escalation_requirements: list[str] | None = None
    approval_status: str = 'NOT_VERIFIED'
    interpretation: str = 'SOURCE_OCCURRENCE_ONLY_NOT_CURRENT_AUTHORITY'
    synthetic: bool


class ResponsibilityRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    source_id: str
    source_version: str
    page: int = Field(ge=1)
    sector: str
    name: str
    responsibilities: list[str]
    documented_internal_interfaces: list[str] = Field(default_factory=list)
    documented_external_interfaces: list[str] = Field(default_factory=list)
    reporting_relationship: str | None = None
    process_owner: str | None = None
    related_doa: list[str] = Field(default_factory=list)
    relationship_status: str = 'NOT_ESTABLISHED'
    approval_status: str = 'NOT_VERIFIED'
    synthetic: bool


class BrandAsset(BaseModel):
    model_config = ConfigDict(extra='allow')
    variant_id: str
    source_document: str
    original_asset_version: str
    integrity_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    languages: list[str]
    orientation: str
    intended_use: str
    color_restrictions: str
    background_restrictions: str
    minimum_size: str = 'NOT_VERIFIED'
    approval_status: str
    publication_status: str
    storage_location: str


def activation_status():
    return {'mode': OperatingMode.PUBLIC_SYNTHETIC_DEMO.value,
            'private_integration': 'IMPLEMENTED_IN_PROCESS_REQUIRES_TRUSTED_AUTH_ADAPTER',
            'private_production_activation': 'DISABLED',
            'institutional_authorization': 'NOT_AUTHORIZED',
            'required_prerequisites': ['INSTITUTIONAL_IDENTITY_AND_RESOURCE_GRANTS',
                'PRIVATE_STORAGE_ISOLATION', 'APPROVED_DATA_PROCESSING_POLICY',
                'SOURCE_AND_BRAND_APPROVAL_VERIFICATION', 'SECURITY_AND_OPERATIONAL_ACCEPTANCE']}
