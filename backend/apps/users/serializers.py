import re
import unicodedata
import logging

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization
from apps.users.professional import (
    LICENSE_REQUIRED_MESSAGE, LICENSE_REQUIRED_ROLES, normalize_license_number,
)

logger = logging.getLogger(__name__)

User = get_user_model()


class EmailOrUsernameTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    ADR p48: login por correo O username.

    Si el identificador enviado en el campo de username contiene '@', se resuelve
    a su usuario por correo (case-insensitive, solo activos) y se sustituye por el
    username canónico antes de autenticar. El constraint único parcial
    `Lower(email)` (migración 0010) garantiza ≤1 match → no hay ambigüedad
    cross-tenant. Si no hay match, se deja el identificador tal cual:
    `TokenObtainPairSerializer.validate` autentica contra un username inexistente
    → 401 genérico, y `ModelBackend` corre su hash dummy (constant-time), sin
    oráculo de enumeración.
    """

    def validate(self, attrs):
        identifier = attrs.get(self.username_field, "")
        if identifier and "@" in identifier:
            normalized = identifier.strip().lower()
            user = (
                User.objects.filter(email__iexact=normalized, is_active=True)
                .only("pk", self.username_field)
                .first()
            )
            if user is not None:
                attrs[self.username_field] = user.get_username()
        return super().validate(attrs)

    @classmethod
    def get_token(cls, user):
        """ADR p65: el refresh lleva la versión de sesión; el access la hereda."""
        from apps.core.authentication import stamp_session_version
        return stamp_session_version(super().get_token(user), user)


# Min length para self-change (ADR p20). Distinto del floor=12 de
# ``apps/platform/serializers.py:ProvisionOrgSerializer.admin_password``,
# que aplica solo a admins iniciales SaaS por su privilegio amplificado.
SELF_CHANGE_MIN_PASSWORD_LENGTH = 8

USERNAME_REGEX = re.compile(r"^[A-Za-z0-9_.\-]+$")

# D4 (plan Equipo, A1): nombres de personas tal como se escriben. Letras latinas
# por rangos explícitos (A-Z, À-Ö, Ø-ö, ø-ÿ, Ā-ž), espacio, guion y los
# apóstrofos ' (U+0027) y ’ (U+2019, el que inserta iOS). Rangos explícitos y no
# `\w`: deja fuera números, emojis y letras de otros alfabetos que imitan a las
# latinas (una «А» cirílica) sin agregar dependencias. El frontend replica la
# misma regla solo para avisar; la autoridad es esta.
PERSON_NAME_REGEX = re.compile(
    r"^[A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u00FF\u0100-\u017E '\u2019-]+$"
)
PERSON_NAME_MAX_LENGTH = 150  # AbstractUser.first_name / last_name
EMAIL_UNAVAILABLE_MESSAGE = "Este correo no está disponible."


def normalize_person_name(value, *, label, required):
    """NFC + recorte de extremos; nada más (sin `.title()`, sin colapsar espacios).

    `label` es «El nombre» o «El apellido». Vacío: error si `required`, si no ''.
    """
    value = unicodedata.normalize('NFC', value or '').strip()
    if not value:
        if required:
            raise serializers.ValidationError(f"{label} es obligatorio.")
        return ''
    if not PERSON_NAME_REGEX.fullmatch(value):
        raise serializers.ValidationError(
            f"{label} solo puede contener letras, espacios, guiones y apóstrofos."
        )
    return value


# D5 (plan Equipo): en la demo solo se aceptan dominios reservados que no son de
# nadie (RFC 2606 y 6761). Así un visitante no inutiliza un correo real: el
# correo es único global y la demo no borra las cuentas que crean los visitantes.
DEMO_RESERVED_EMAIL_DOMAINS = frozenset({'example.com', 'example.net', 'example.org'})
DEMO_RESERVED_EMAIL_SUFFIXES = ('.test', '.example')
DEMO_EMAIL_MESSAGE = "En la demo usa un correo de ejemplo, como nombre@example.com."


def _is_reserved_email_domain(email):
    domain = email.rsplit('@', 1)[-1]
    return (
        domain in DEMO_RESERVED_EMAIL_DOMAINS
        or any(domain.endswith(suffix) for suffix in DEMO_RESERVED_EMAIL_SUFFIXES)
    )


def normalize_staff_email(value, *, exclude_pk=None, organization=None):
    """ADR p48: obligatorio, en minúsculas y único global (sin distinguir
    mayúsculas, incluidos inactivos). El mensaje es genérico (T-2): no confirma
    en qué organización existe el correo. En la organización demo exige un
    dominio reservado (D5)."""
    value = (value or '').strip().lower()
    if not value:
        raise serializers.ValidationError("El correo electrónico es obligatorio.")
    if organization is not None and organization.is_demo and not _is_reserved_email_domain(value):
        raise serializers.ValidationError(DEMO_EMAIL_MESSAGE)
    taken = User.objects.filter(email__iexact=value)
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)
    if taken.exists():
        raise serializers.ValidationError(EMAIL_UNAVAILABLE_MESSAGE)
    return value


class UserSerializer(serializers.ModelSerializer):
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    # D5 (plan Equipo): solo para que la interfaz oculte acciones sobre las
    # cuentas semilla de la demo. NO autoriza nada: lo aplican los servicios.
    demo_protected = serializers.SerializerMethodField()

    class Meta:
        model = User
        # Día 6 Fase 5: expone public_id para que frontend construya
        # URLs /staff/<uuid>/. id se conserva pre-beta.
        fields = ['id', 'public_id', 'username', 'email', 'first_name', 'last_name',
                  'role', 'specialty', 'license_number', 'is_active', 'organization',
                  'organization_name', 'demo_protected']
        read_only_fields = ['id', 'public_id']

    def get_demo_protected(self, obj):
        from apps.users.services import is_demo_seed_account
        return is_demo_seed_account(obj)


class CreateEmployeeSerializer(serializers.ModelSerializer):
    username = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    # D4: el nombre es obligatorio también aquí (antes solo lo exigía el frontend).
    first_name = serializers.CharField(
        allow_blank=True, max_length=PERSON_NAME_MAX_LENGTH,
        error_messages={'required': 'El nombre es obligatorio.'},
    )
    last_name = serializers.CharField(
        required=False, allow_blank=True, default='', max_length=PERSON_NAME_MAX_LENGTH,
    )
    role = serializers.ChoiceField(
        choices=['ADMIN', 'VET', 'ASSISTANT'],
        default='ASSISTANT'
    )
    specialty = serializers.CharField(required=False, allow_blank=True, default='')
    # M01 (orden 7): obligatoria para VET (validate).
    license_number = serializers.CharField(required=False, allow_blank=True, default='')
    # Día 6 Fase 4 (Issue #40): organization_id NO writable.
    # ADR p18: organization siempre se deriva de request.user.organization (JWT).
    # Aceptarlo en body permite que un ADMIN cree usuarios en otra org →
    # privilege escalation cross-tenant. read_only es el guard correcto.
    organization_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'first_name', 'last_name',
                  'role', 'specialty', 'license_number', 'organization_id']

    def validate_username(self, value):
        if not USERNAME_REGEX.match(value):
            raise serializers.ValidationError(
                "El nombre de usuario solo puede contener letras, números, puntos, guiones y guiones bajos."
            )
        return value

    def validate_email(self, value):
        # ADR p48: correo obligatorio, normalizado a minúsculas y único global.
        # Ningún flujo normal de negocio crea usuarios sin correo.
        request = self.context.get('request')
        organization = getattr(getattr(request, 'user', None), 'organization', None)
        return normalize_staff_email(value, organization=organization)

    def validate_first_name(self, value):
        return normalize_person_name(value, label="El nombre", required=True)

    def validate_last_name(self, value):
        return normalize_person_name(value, label="El apellido", required=False)

    def validate_password(self, value):
        if len(value) < 8:
            raise serializers.ValidationError("La contraseña debe tener al menos 8 caracteres.")
        if not any(c.isupper() for c in value):
            raise serializers.ValidationError("La contraseña debe contener al menos una letra mayúscula.")
        if not any(c.isdigit() for c in value):
            raise serializers.ValidationError("La contraseña debe contener al menos un número.")
        return value

    def validate_license_number(self, value):
        return normalize_license_number(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs.get('role') in LICENSE_REQUIRED_ROLES and not attrs.get('license_number'):
            raise serializers.ValidationError({'license_number': LICENSE_REQUIRED_MESSAGE})
        return attrs

    def create(self, validated_data):
        # Día 6 Fase 4: organization_id es read_only — extra-safety pop por si
        # algún caller histórico envía el campo (DRF ignora read_only en input,
        # pero el .pop() documenta que jamás se debe consumir de body).
        validated_data.pop('organization_id', None)

        request = self.context.get('request')
        organization = request.user.organization if request else None

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            specialty=validated_data.get('specialty', ''),
            license_number=validated_data.get('license_number', ''),
            role=validated_data.get('role', 'ASSISTANT'),
            organization=organization,
        )

        # El staff creado por el ADMIN entra con contraseña de un solo uso: debe
        # cambiarla en el primer login (MustChangePasswordGate). Sin
        # password_temp_issued_at → no caduca a 24h (igual que el admin
        # provisionado). Se setea SOLO aquí (ruta de alta por endpoint), NUNCA en
        # User.create_user / signal / default del modelo, para no gatear los
        # usuarios de setUp de la suite, los seeds, ni createsuperuser.
        user.password_must_change = True
        user.save(update_fields=['password_must_change'])

        self._assign_rbac_role(user, organization)
        return user

    def _assign_rbac_role(self, user, organization):
        if not organization:
            return
        from apps.core.models import Role, UserRole
        try:
            db_role = Role.objects.get(
                name=user.role,
                organization=organization,
                is_system_role=True,
            )
            UserRole.objects.get_or_create(user=user, role=db_role)
        except Role.DoesNotExist:
            logger.warning(
                "Rol '%s' no encontrado en org %s al crear usuario %s — "
                "ejecuta seed_permissions",
                user.role, organization.id, user.id,
            )


class UpdateEmployeeSerializer(serializers.Serializer):
    """PATCH /api/staff/<uuid>/: identidad (A1, plan Equipo), especialidad y
    cédula (M01, orden 7).

    Cualquier otra clave es 400: rol, username, contraseña o estado tienen sus
    propios caminos, y descartarla en silencio haría creer que se guardó.

    ``validated_data`` contiene solo lo que de verdad cambia: un valor igual al
    actual (el mismo correo con otras mayúsculas, por ejemplo) no se guarda ni se
    registra.
    """
    EDITABLE_FIELDS = frozenset({
        'first_name', 'last_name', 'email', 'specialty', 'license_number',
    })

    first_name = serializers.CharField(
        required=False, allow_blank=True, max_length=PERSON_NAME_MAX_LENGTH,
    )
    last_name = serializers.CharField(
        required=False, allow_blank=True, max_length=PERSON_NAME_MAX_LENGTH,
    )
    email = serializers.EmailField(required=False)
    specialty = serializers.CharField(required=False, allow_blank=True, max_length=100)
    license_number = serializers.CharField(required=False, allow_blank=True)

    def _target(self):
        target = self.context.get('target')
        assert target is not None, 'UpdateEmployeeSerializer requiere context["target"]'
        return target

    def to_internal_value(self, data):
        unknown = sorted(set(data) - self.EDITABLE_FIELDS) if hasattr(data, 'keys') else []
        if unknown:
            raise serializers.ValidationError({'non_field_errors': [
                'Solo se pueden editar nombre, apellido, correo, especialidad '
                'y cédula profesional.']})
        return super().to_internal_value(data)

    def validate_first_name(self, value):
        return normalize_person_name(value, label="El nombre", required=True)

    def validate_last_name(self, value):
        return normalize_person_name(value, label="El apellido", required=False)

    def validate_email(self, value):
        target = self._target()
        if (value or '').strip().lower() == (target.email or '').lower():
            return target.email
        return normalize_staff_email(
            value, exclude_pk=target.pk, organization=target.organization,
        )

    def validate_license_number(self, value):
        return normalize_license_number(value)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError({'non_field_errors': [
                'Indica al menos un dato para editar.']})
        target = self._target()
        license_number = attrs.get('license_number', target.license_number)
        if target.role in LICENSE_REQUIRED_ROLES and not license_number:
            raise serializers.ValidationError({'license_number': LICENSE_REQUIRED_MESSAGE})
        return {
            field: value for field, value in attrs.items()
            if getattr(target, field) != value
        }


class ChangePasswordSerializer(serializers.Serializer):
    """
    Input contract for ``POST /api/users/change-password/``.

    Field-level checks here are intentionally minimal: empty strings,
    length floor, confirm match. The full Django validator stack
    (``validate_password``) runs inside the service so it has access to
    the user for similarity checks. The service is also responsible for
    rejecting ``new == current``.
    """

    current_password = serializers.CharField(write_only=True, max_length=128)
    new_password = serializers.CharField(
        write_only=True,
        max_length=128,
        min_length=SELF_CHANGE_MIN_PASSWORD_LENGTH,
    )
    confirm_password = serializers.CharField(write_only=True, max_length=128)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({
                "confirm_password": "Las contraseñas no coinciden.",
            })
        return attrs
