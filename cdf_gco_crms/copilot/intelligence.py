"""Record-grounded explanations. Accessibility never establishes authority."""

import json
from ..institutional.providers import (
    PublicSyntheticProvider,
    ReferenceLookupService,
    currency,
)


class KnowledgeService:
    def __init__(self, app):
        self.app = app

    def dispatch(self, action, r, p):
        a = self.app
        a.authorize_case(r.case_id, p)
        if action == "quality":
            case = a.calibration.case(r.case_id, p.reviewer)
            seen = {}
            items = []
            for o in case["observations"]:
                text = o.get("original_text", "")
                duplicate = seen.get(text)
                seen[text] = o["observation_id"]
                items.append(
                    {
                        "observation_id": o["observation_id"],
                        "source_accuracy": (
                            "EXACT_QUOTATION_AVAILABLE"
                            if o.get("quote")
                            else "REQUIRES_SOURCE_VERIFICATION"
                        ),
                        "materiality": (
                            "RECORDED_CATEGORY_REQUIRES_HUMAN_JUSTIFICATION"
                            if o.get("material_categories")
                            else "NOT_CLASSIFIED"
                        ),
                        "evidence_adequacy": (
                            "REFERENCE_LINKS_UNVERIFIED"
                            if o.get("authority_reference_ids")
                            else "EVIDENCE_GAP"
                        ),
                        "actionability": (
                            "EXPLICIT_RECOMMENDATION_PRESENT"
                            if "التوصية:" in text
                            else "REQUIRES_HUMAN_REVIEW"
                        ),
                        "duplicate_of": duplicate,
                        "institutional_applicability": "NOT_ESTABLISHED",
                        "proportionality": "HUMAN_ASSESSMENT_REQUIRED",
                        "numeric_quality_score": None,
                    }
                )
            return {
                "case_id": r.case_id,
                "assessments": items[r.cursor : r.cursor + r.limit],
                "total": len(items),
                "method": "AUDITABLE_RULE_STATUSES_NOT_VALIDATED_QUALITY_SCORE",
            }
        provider = PublicSyntheticProvider()
        catalog = provider.catalog()
        lookup = ReferenceLookupService(provider)
        sources = {s["id"]: s for s in catalog["sources"]}
        records = []
        if r.domain in ("all", "authority"):
            for item in lookup.authorities(r.query, limit=r.limit):
                source = sources[item["source_id"]]
                records.append(
                    {
                        "classification": "EXTRACTED_SYNTHETIC_SOURCE_STATEMENT",
                        "record": item,
                        "citation": {
                            "source_id": source["id"],
                            "title": source.get("title", source["id"]),
                            "page": item["page"],
                            "provision": item.get("provision"),
                            "version": source["version"],
                            "verification_status": source["approval_status"],
                            "currency": currency(source),
                        },
                        "limitation": "PUBLIC_FICTIONAL_REFERENCE_NOT_BINDING_AUTHORITY",
                    }
                )
        if r.domain in ("all", "responsibility"):
            for item in lookup.responsibilities(r.query, limit=r.limit):
                source = sources[item["source_id"]]
                records.append(
                    {
                        "classification": "EXTRACTED_SYNTHETIC_SOURCE_STATEMENT",
                        "record": item,
                        "citation": {
                            "source_id": source["id"],
                            "title": source.get("title", source["id"]),
                            "page": item["page"],
                            "provision": item["id"],
                            "version": source["version"],
                            "verification_status": source["approval_status"],
                            "currency": currency(source),
                        },
                        "limitation": "OWNERSHIP_NOT_INFERRED_FROM_TASK_OVERLAP",
                    }
                )
        issues = []
        # Explicit fixture scenarios, never asserted as actual institutional conflicts.
        if r.scenario_id == "DOA_CONFLICT":
            clauses = [
                {
                    "source_id": "SYN-CONFLICT-A",
                    "page": 1,
                    "provision": "1",
                    "version": "SYN-v1",
                    "quotation": "يتطلب التعاون الافتراضي مراجعة اللجنة الافتراضية قبل التوقيع.",
                    "approval_status": "SYNTHETIC_NOT_AUTHORITY",
                },
                {
                    "source_id": "SYN-CONFLICT-B",
                    "page": 2,
                    "provision": "2",
                    "version": "SYN-v2",
                    "quotation": self.app.calibration.case(r.case_id, p.reviewer)[
                        "observations"
                    ][0].get("quote", "SOURCE_QUOTATION_NOT_AVAILABLE"),
                    "approval_status": "SYNTHETIC_NOT_AUTHORITY",
                },
            ]
            issues = [
                {
                    "kind": "COMPETING_APPROVAL_ROUTES",
                    "competing_provisions": clauses,
                    "hierarchy": "NOT_ESTABLISHED",
                    "resolution": "ESCALATE_TO_AUTHORIZED_HUMAN",
                    "binding_conclusion": False,
                }
            ]
        if r.scenario_id == "DEPARTMENT_OVERLAP":
            issues = [
                {
                    "kind": "DOCUMENTED_TASK_OVERLAP",
                    "records": [
                        u["id"]
                        for u in catalog["units"]
                        if any("التعاون" in t for t in u["tasks"])
                    ],
                    "documented_tasks": [
                        {
                            "id": u["id"],
                            "tasks": u["tasks"],
                            "page": u["page"],
                            "source_id": u["source_id"],
                        }
                        for u in catalog["units"]
                    ],
                    "definitive_owner": None,
                    "resolution": "ESCALATE_OWNER_CLARIFICATION",
                }
            ]
        if r.scenario_id == "STALE_SOURCE":
            issues = [
                {
                    "kind": "SOURCE_CURRENCY_NOT_ESTABLISHED",
                    "sources": [currency(s) for s in catalog["sources"]],
                    "resolution": "VERIFY_APPROVAL_EFFECTIVE_DATE_AND_SUPERSESSION",
                }
            ]
        return {
            "case_id": r.case_id,
            "records": records[: r.limit],
            "issues": issues,
            "synthetic": True,
            "binding_authority_granted": False,
            "answer_classifications": [
                "EXTRACTED_SYNTHETIC_SOURCE_STATEMENT",
                "ANALYTICAL_INFERENCE_REQUIRES_HUMAN_REVIEW",
            ],
            "limitations": [
                "AUTHORITY_HIERARCHY_NOT_INVENTED",
                "PRIVATE_REFERENCE_ACCESS_DISABLED",
            ],
        }
