from rest_framework import serializers

from matching.enums import CandidateKind, MatchingAudience
from matching.models.candidate import MatchingCandidate
from matching.models.run import MatchingRun
from matching.models.signal import MatchingSignal


class MatchingRunCreateSerializer(serializers.Serializer):
    """Input payload for executing a new matching run."""

    audience = serializers.ChoiceField(
        choices=MatchingAudience.choices,
        default=MatchingAudience.BUYER,
        help_text="Target audience scope: BUYER (default) or OPERATOR.",
    )
    policy_version_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Optional UUID of specific Published matching policy version.",
    )


class MatchingRunResponseSerializer(serializers.ModelSerializer):
    """Standardized representation of a persisted MatchingRun."""

    rfq_id = serializers.UUIDField(source="rfq.id", read_only=True)
    policy_version_number = serializers.IntegerField(source="policy_version.version", read_only=True)
    is_stale = serializers.SerializerMethodField(help_text="True if RFQ aggregate version has progressed since run.")
    candidate_count = serializers.SerializerMethodField(help_text="Total number of evaluated candidates in this run.")

    class Meta:
        model = MatchingRun
        fields = [
            "id",
            "rfq_id",
            "rfq_version",
            "audience",
            "policy_version_id",
            "policy_version_number",
            "engine_version",
            "generated_at",
            "is_stale",
            "input_fingerprint",
            "result_fingerprint",
            "candidate_count",
        ]

    def get_is_stale(self, obj: MatchingRun) -> bool:
        return obj.rfq_version != obj.rfq.version

    def get_candidate_count(self, obj: MatchingRun) -> int:
        return obj.candidates.count()


class MatchingSignalResponseSerializer(serializers.ModelSerializer):
    """Structured analytical signal explanation."""

    weight = serializers.DecimalField(max_digits=6, decimal_places=2, coerce_to_string=True)
    raw_score = serializers.DecimalField(max_digits=5, decimal_places=4, allow_null=True, coerce_to_string=True)
    contribution = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True, coerce_to_string=True)

    class Meta:
        model = MatchingSignal
        fields = [
            "id",
            "dimension",
            "code",
            "outcome",
            "is_hard",
            "weight",
            "raw_score",
            "contribution",
            "reason_code",
            "expected_value",
            "actual_value",
            "semantic_identity",
        ]


class MatchingCandidateResponseSerializer(serializers.ModelSerializer):
    """
    Audience-safe matching candidate projection.

    Never exposes internal CRM notes, contact attempts, personal phone/email,
    or raw snapshot dumps to Buyer.
    """

    fit_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True, coerce_to_string=True)
    evidence_coverage = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True, coerce_to_string=True)
    ranking_score = serializers.DecimalField(max_digits=6, decimal_places=2, allow_null=True, coerce_to_string=True)
    source = serializers.SerializerMethodField(help_text="Audience-safe safe source projection.")
    signals = MatchingSignalResponseSerializer(many=True, read_only=True)

    class Meta:
        model = MatchingCandidate
        fields = [
            "id",
            "run_id",
            "lane",
            "candidate_kind",
            "eligible",
            "exclusion_code",
            "fit_score",
            "evidence_coverage",
            "ranking_score",
            "rank",
            "source",
            "signals",
        ]

    def get_source(self, obj: MatchingCandidate) -> dict:
        ev = obj.candidate_snapshot or {}

        if obj.candidate_kind == CandidateKind.SUPPLY_LISTING:
            return {
                "listing_id": str(obj.supply_listing_id) if obj.supply_listing_id else None,
                "organization_id": ev.get("organization_id"),
                "organization_name": ev.get("organization_name", ""),
                "verification_status": ev.get("verification_status", "unverified"),
                "commodity_id": ev.get("commodity_id"),
                "quantity": ev.get("quantity"),
                "unit": ev.get("unit"),
                "origin_area_code": ev.get("geography", {}).get("area_code", ""),
                "availability_window_start": ev.get("availability_window_start"),
                "availability_window_end": ev.get("availability_window_end"),
            }

        if obj.candidate_kind == CandidateKind.SUPPLIER_ORGANIZATION:
            return {
                "organization_id": str(obj.supplier_organization_id) if obj.supplier_organization_id else None,
                "organization_name": ev.get("organization_name", ""),
                "verification_status": ev.get("verification_status", "unverified"),
                "operating_areas": ev.get("geography", {}).get("operating_areas", []),
            }

        if obj.candidate_kind == CandidateKind.BROKER_ORGANIZATION:
            return {
                "organization_id": str(obj.broker_organization_id) if obj.broker_organization_id else None,
                "organization_name": ev.get("organization_name", ""),
                "verification_status": ev.get("verification_status", "unverified"),
                "operating_areas": ev.get("geography", {}).get("operating_areas", []),
            }

        if obj.candidate_kind == CandidateKind.SUPPLY_OPPORTUNITY:
            # OPERATOR only: safe opportunity projection
            cp = ev.get("counterparty") or {}
            return {
                "opportunity_id": str(obj.supply_opportunity_id) if obj.supply_opportunity_id else None,
                "is_external": bool(cp.get("is_external")),
                "counterparty_name": cp.get("counterparty_name", ""),
                "origin_area_code": ev.get("geography", {}).get("area_code", ""),
            }

        return {}


class MatchingErrorResponseSerializer(serializers.Serializer):
    """Standardized error structure for controlled business failures."""

    code = serializers.CharField(help_text="Machine-readable error code.")
    detail = serializers.CharField(help_text="Descriptive explanation of the failure.")
