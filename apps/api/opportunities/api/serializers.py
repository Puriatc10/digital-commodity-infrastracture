from rest_framework import serializers

from opportunities.models import ExternalCounterparty


class ExternalCounterpartySerializer(serializers.ModelSerializer):
    """
    Explicit serializer for ExternalCounterparty.

    Guards against mass assignment:
    - Primary key (id), timestamps (created_at, updated_at), and
      internal actor (created_by) are strictly read-only.
    - Rejects empty or whitespace-only company_name.
    - Validates email format if provided.
    """

    company_name = serializers.CharField(
        max_length=255,
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        help_text="Display or legal entity name of the external counterparty.",
    )
    contact_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Name of the contact person or representative.",
    )
    phone = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Phone number for operational contact.",
    )
    email = serializers.EmailField(
        max_length=254,
        required=False,
        allow_blank=True,
        default="",
        help_text="Email address for operational contact.",
    )
    geography = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Country, port, or regional jurisdiction.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        default="",
        help_text="Operational notes recorded by the Operator.",
    )

    class Meta:
        model = ExternalCounterparty
        fields = [
            "id",
            "company_name",
            "contact_name",
            "phone",
            "email",
            "geography",
            "notes",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_company_name(self, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise serializers.ValidationError("Company name must not be blank.")
        return stripped
