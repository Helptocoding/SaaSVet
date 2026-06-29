"""
Serializers for cross-tenant platform operations.

Validation rules
----------------
- All free-text fields pass through `sanitize_text()` (HTML stripped,
  unicode normalized, truncated).
- Passwords run Django's full validator stack (`validate_password`) plus
  a hard 12-char minimum — admin credentials hold SaaS-tenant clinical
  + financial data, justifying a stricter floor than the application
  default.
- Pre-DB duplicate checks (username/email/org name) catch the common
  case; the service layer also handles IntegrityError for races between
  validation and create.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.core.sanitize import sanitize_text
from apps.organizations.models import Organization


User = get_user_model()


ADMIN_PASSWORD_MIN_LENGTH = 12


class ProvisionOrgSerializer(serializers.Serializer):
    """
    Input contract for `POST /api/platform/organizations/`.

    Two logical blocks (flat for HTTP simplicity, regrouped in
    validated_data by the view):
      - Organization fields: name, timezone, tax_rate
      - Initial admin fields: admin_username, admin_email, admin_password,
        admin_first_name, admin_last_name
    """

    # Organization
    name = serializers.CharField(max_length=200)
    timezone = serializers.CharField(
        max_length=64,
        required=False,
        default='America/Mexico_City',
    )
    tax_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=4,
        required=False,
        default=Decimal('0.1600'),
    )

    # Initial admin
    admin_username = serializers.CharField(max_length=150)
    admin_email = serializers.EmailField()
    admin_password = serializers.CharField(
        write_only=True,
        min_length=ADMIN_PASSWORD_MIN_LENGTH,
        max_length=128,
        style={'input_type': 'password'},
    )
    admin_first_name = serializers.CharField(max_length=150)
    admin_last_name = serializers.CharField(max_length=150)

    # --- Organization validators -----------------------------------------

    def validate_name(self, value):
        clean = sanitize_text(value or '', max_length=200)
        if not clean.strip():
            raise serializers.ValidationError("Nombre requerido.")
        if Organization.objects.filter(name__iexact=clean).exists():
            raise serializers.ValidationError(
                "Ya existe una organización con ese nombre."
            )
        return clean

    def validate_tax_rate(self, value):
        if value < Decimal('0') or value > Decimal('1'):
            raise serializers.ValidationError(
                "tax_rate debe estar entre 0 y 1 (ej. 0.1600 para 16%)."
            )
        return value

    # --- Admin validators -------------------------------------------------

    def validate_admin_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username ya en uso.")
        return value

    def validate_admin_email(self, value):
        # ADR p48: correo = identidad global única, normalizado a minúsculas.
        value = (value or '').strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Email ya en uso.")
        return value

    def validate_admin_password(self, value):
        # min_length=12 ya enforced por CharField. Django validators agregan
        # common-password, numeric-only, similarity con user attributes.
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate_admin_first_name(self, value):
        clean = sanitize_text(value or '', max_length=150)
        if not clean.strip():
            raise serializers.ValidationError("first_name requerido.")
        return clean

    def validate_admin_last_name(self, value):
        clean = sanitize_text(value or '', max_length=150)
        if not clean.strip():
            raise serializers.ValidationError("last_name requerido.")
        return clean
