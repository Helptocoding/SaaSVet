import re
import unicodedata

from rest_framework import serializers
from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenObtainSerializer
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from django.contrib.auth import get_user_model
from apps.organizations.models import Organization
from apps.users.models import StaffAbsence
from apps.users.professional import (
    attends_for, is_clinician, license_required_message, normalize_license_number,
)

User = get_user_model()


class SpecialtiesField(serializers.ListField):
    """Lista de códigos del catálogo de especialidades (ADR p68). Devuelve los
    códigos sin repetir y en el orden del catálogo; uno desconocido es 400."""

    def __init__(self, **kwargs):
        kwargs.setdefault('child', serializers.CharField())
        kwargs.setdefault('allow_empty', True)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        from apps.users.specialties import normalize_specialties
        codes = super().to_internal_value(data)
        try:
            return normalize_specialties(codes)
        except ValueError as exc:
            raise serializers.ValidationError(
                f'Especialidad no reconocida: {", ".join(exc.args[0])}.')


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
        # Autentica (y fija self.user) SIN emitir tokens todavía: con la
        # verificación en dos pasos activa (ADR p68) la contraseña sola no basta.
        TokenObtainSerializer.validate(self, attrs)
        from apps.users.mfa import is_mfa_enabled, issue_login_challenge
        if is_mfa_enabled(self.user):
            return {'mfa_required': True, 'mfa_token': issue_login_challenge(self.user)}
        refresh = self.get_token(self.user)
        data = {'refresh': str(refresh), 'access': str(refresh.access_token)}
        if jwt_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)
        return data

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
# ADR p66: la función clínica solo es una elección en ADMIN.
ASSISTANT_DOES_NOT_ATTEND = "Un asistente no atiende pacientes; elige Veterinario o Administrador."
ATTENDS_ONLY_FOR_ADMIN = (
    "Solo se ajusta en administradores: en veterinarios y asistentes lo define el rol."
)


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
    """Integrante tal como lo ve quien gestiona personal (Equipo).

    Solo lo usan respuestas que exigen un permiso de gestión (listado para
    gestores, alta, edición y reactivación). Quien solo tiene ``staff.list``
    recibe ``StaffDirectorySerializer``.
    """
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    # D5 (plan Equipo): solo para que la interfaz oculte acciones sobre las
    # cuentas semilla de la demo. NO autoriza nada: lo aplican los servicios.
    demo_protected = serializers.SerializerMethodField()
    # Fase 1 Equipo: estado de acceso derivado (apps/users/access.py).
    access = serializers.SerializerMethodField()
    # ADR p66: función clínica efectiva (VET siempre; ADMIN si se marcó).
    attends_patients = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    permission_overrides = serializers.SerializerMethodField()

    class Meta:
        model = User
        # Día 6 Fase 5: expone public_id para que frontend construya
        # URLs /staff/<uuid>/. id se conserva pre-beta.
        fields = ['id', 'public_id', 'username', 'email', 'first_name', 'last_name',
                  'role', 'attends_patients', 'specialties', 'specialty_label',
                  'license_number', 'is_active',
                  'organization', 'organization_name', 'demo_protected', 'access',
                  'permissions', 'permission_overrides']
        read_only_fields = ['id', 'public_id', 'specialty_label']

    def get_attends_patients(self, obj):
        return is_clinician(obj)

    def _permissions_entry(self, obj):
        # ADR p69: la lista los calcula en bloque (``bulk_permissions``) y los pasa
        # en el contexto; una sola persona los calcula aquí.
        bulk = self.context.get('permissions_by_user')
        if bulk is not None and obj.pk in bulk:
            return bulk[obj.pk]
        from apps.users.member_permissions import bulk_permissions
        return bulk_permissions([obj])[obj.pk]

    def get_permissions(self, obj):
        return self._permissions_entry(obj)['permissions']

    def get_permission_overrides(self, obj):
        entry = self._permissions_entry(obj)
        return {'granted': entry['granted'], 'revoked': entry['revoked']}

    def get_demo_protected(self, obj):
        from apps.users.services import is_demo_seed_account
        return is_demo_seed_account(obj)

    def get_access(self, obj):
        from apps.users.access import access_summary
        return access_summary(obj)


class StaffDirectorySerializer(serializers.ModelSerializer):
    """Directorio mínimo del equipo para quien no gestiona personal (Fase 1).

    VET y ASSISTANT tienen ``staff.list`` porque Citas necesita elegir
    veterinario: nombre, rol y el PK que viaja en el cuerpo de la cita (ADR p18).
    Correo, usuario, cédula, estado de acceso y datos de la organización no son
    necesarios para eso y no se exponen. ``attends_patients`` sí: es lo que decide
    quién aparece como veterinario en la agenda (ADR p66).
    """
    attends_patients = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'public_id', 'first_name', 'last_name', 'role', 'attends_patients']
        read_only_fields = fields

    def get_attends_patients(self, obj):
        return is_clinician(obj)


class CreateEmployeeSerializer(serializers.Serializer):
    """Entrada de ``POST /api/staff/create/`` (alta de integrante).

    Solo valida; el alta la hace ``services.create_staff_member``. La contraseña
    inicial la genera el sistema (Fase 1 Equipo): enviar ``password`` es 400,
    para que un cliente antiguo no crea que fijó una contraseña.

    La organización nunca viene del cuerpo (Día 6 Fase 4, Issue #40; ADR p18): un
    ``organization``/``organization_id`` enviado se ignora y el servicio usa la del
    ADMIN autenticado.
    """
    PASSWORD_NOT_ACCEPTED = (
        'La contraseña inicial la genera el sistema; no se envía en el alta.'
    )

    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
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
    # ADR p68: códigos del catálogo cerrado; se guardan sin repetir y en su orden.
    specialties = SpecialtiesField(required=False, default=list)
    # M01 (orden 7) y ADR p66: obligatoria para quien atiende (validate).
    license_number = serializers.CharField(required=False, allow_blank=True, default='')
    # ADR p66: solo decide en ADMIN; VET siempre atiende y ASSISTANT nunca.
    attends_patients = serializers.BooleanField(required=False, default=False)

    def to_internal_value(self, data):
        if hasattr(data, 'keys') and 'password' in data:
            raise serializers.ValidationError({'password': [self.PASSWORD_NOT_ACCEPTED]})
        return super().to_internal_value(data)

    def validate_username(self, value):
        if not USERNAME_REGEX.match(value):
            raise serializers.ValidationError(
                "El nombre de usuario solo puede contener letras, números, puntos, guiones y guiones bajos."
            )
        # Único global sin distinguir mayúsculas (como el correo, ADR p48): «Ana»
        # y «ana» serían dos cuentas que se confunden al entrar. El mensaje no
        # dice en qué clínica existe. La restricción de base de datos decide las
        # carreras (services.create_staff_member).
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Este nombre de usuario no está disponible.")
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

    def validate_license_number(self, value):
        return normalize_license_number(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        role = attrs.get('role')
        if role == 'ASSISTANT' and attrs.get('attends_patients'):
            raise serializers.ValidationError({'attends_patients': [ASSISTANT_DOES_NOT_ATTEND]})
        attrs['attends_patients'] = attends_for(role, attrs.get('attends_patients'))
        if attrs['attends_patients'] and not attrs.get('license_number'):
            raise serializers.ValidationError({'license_number': license_required_message(role)})
        return attrs


class UpdateEmployeeSerializer(serializers.Serializer):
    """PATCH /api/staff/<uuid>/: identidad (A1, plan Equipo), especialidad y
    cédula (M01, orden 7) y, solo en ADMIN, si atiende pacientes (ADR p66).

    Cualquier otra clave es 400: rol, username, contraseña o estado tienen sus
    propios caminos, y descartarla en silencio haría creer que se guardó.

    ``validated_data`` contiene solo lo que de verdad cambia: un valor igual al
    actual (el mismo correo con otras mayúsculas, por ejemplo) no se guarda ni se
    registra.
    """
    EDITABLE_FIELDS = frozenset({
        'first_name', 'last_name', 'email', 'specialties', 'license_number',
        'attends_patients',
    })

    first_name = serializers.CharField(
        required=False, allow_blank=True, max_length=PERSON_NAME_MAX_LENGTH,
    )
    last_name = serializers.CharField(
        required=False, allow_blank=True, max_length=PERSON_NAME_MAX_LENGTH,
    )
    email = serializers.EmailField(required=False)
    specialties = SpecialtiesField(required=False)
    license_number = serializers.CharField(required=False, allow_blank=True)
    # ADR p66: solo en ADMIN; en VET y ASSISTANT lo define el rol.
    attends_patients = serializers.BooleanField(required=False)

    def _target(self):
        target = self.context.get('target')
        assert target is not None, 'UpdateEmployeeSerializer requiere context["target"]'
        return target

    def to_internal_value(self, data):
        unknown = sorted(set(data) - self.EDITABLE_FIELDS) if hasattr(data, 'keys') else []
        if unknown:
            raise serializers.ValidationError({'non_field_errors': [
                'Solo se pueden editar nombre, apellido, correo, especialidades, '
                'cédula profesional y si atiende pacientes.']})
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
        if 'attends_patients' in attrs and target.role != 'ADMIN':
            raise serializers.ValidationError({'attends_patients': [ATTENDS_ONLY_FOR_ADMIN]})
        license_number = attrs.get('license_number', target.license_number)
        attends = attends_for(target.role, attrs.get('attends_patients', target.attends_patients))
        if attends and not license_number:
            raise serializers.ValidationError({'license_number': license_required_message(target.role)})
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


class ChangeRoleSerializer(serializers.Serializer):
    """Entrada de ``POST /api/staff/<uuid>/role/`` (ADR p66).

    ``attends_patients`` solo decide en ADMIN; si se omite, un ADMIN conserva la
    función clínica que tenía. Las reglas (último ADMIN, cédula, a sí mismo) las
    aplica ``services.change_staff_role``.
    """
    role = serializers.ChoiceField(choices=['ADMIN', 'VET', 'ASSISTANT'])
    attends_patients = serializers.BooleanField(required=False, allow_null=True, default=None)
    # ADR p69: con permisos personalizados hay que decidir si se conservan.
    keep_custom_permissions = serializers.BooleanField(required=False, allow_null=True, default=None)


class MemberChangeSerializer(serializers.Serializer):
    """La parte de ``PATCH /api/staff/<uuid>/`` que no son datos personales
    (ADR p69 §9): rol, función clínica al cambiar de rol, permisos efectivos
    deseados y la decisión sobre los personalizados. Las reglas las aplica
    ``services.update_staff_member``."""
    role = serializers.ChoiceField(choices=['ADMIN', 'VET', 'ASSISTANT'], required=False)
    attends_patients = serializers.BooleanField(required=False, allow_null=True, default=None)
    permissions = serializers.ListField(child=serializers.CharField(), required=False,
                                        allow_empty=True)
    # ADR p69 §12: los permisos efectivos que el llamador veía al abrir la ficha.
    expected_permissions = serializers.ListField(child=serializers.CharField(), required=False,
                                                 allow_empty=True)
    keep_custom_permissions = serializers.BooleanField(required=False, allow_null=True, default=None)


class StaffAccessEventSerializer(serializers.Serializer):
    """Evento del historial de accesos (ADR p66). Sin PK internos ni datos
    personales: tipo, cuándo, quién y qué cambió (nombres de campo y roles)."""
    kind = serializers.CharField()
    kind_label = serializers.CharField(source='get_kind_display')
    created_at = serializers.DateTimeField()
    actor_name = serializers.SerializerMethodField()
    changes = serializers.JSONField()

    def get_actor_name(self, obj):
        actor = obj.actor
        return f'{actor.first_name} {actor.last_name}'.strip() or actor.username


def _person_name(user):
    if user is None:
        return None
    return f'{user.first_name} {user.last_name}'.strip() or user.username


class StaffAbsenceDirectorySerializer(serializers.Serializer):
    """Ausencia vista desde la agenda (ADR p67): solo quién y qué días. ``member``
    es el PK con el que la agenda identifica al veterinario de cada cita."""
    public_id = serializers.UUIDField()
    member = serializers.IntegerField(source='member_id')
    member_public_id = serializers.UUIDField(source='member.public_id')
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class StaffAbsenceSerializer(StaffAbsenceDirectorySerializer):
    """Ausencia completa, para quien gestiona personal: además el tipo y quién la
    registró."""
    member_name = serializers.SerializerMethodField()
    kind = serializers.CharField()
    kind_label = serializers.CharField(source='get_kind_display')
    created_at = serializers.DateTimeField()
    created_by_name = serializers.SerializerMethodField()

    def get_member_name(self, obj):
        return _person_name(obj.member)

    def get_created_by_name(self, obj):
        return _person_name(obj.created_by)


class CreateAbsenceSerializer(serializers.Serializer):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    kind = serializers.ChoiceField(choices=StaffAbsence.KIND_CHOICES,
                                   default=StaffAbsence.KIND_OTHER)

    def validate(self, attrs):
        from apps.users.absences import validate_absence_dates
        validate_absence_dates(self.context['organization'], attrs['start_date'], attrs['end_date'])
        return attrs


class StaffAppointmentSerializer(serializers.Serializer):
    """Cita por atender de un integrante, para avisar y reasignar (ADR p67).
    Lleva su ``expected_state``: la reasignación la devuelve tal cual (INV-A)."""
    public_id = serializers.UUIDField()
    date = serializers.DateField()
    start_time = serializers.TimeField(format='%H:%M')
    end_time = serializers.TimeField(format='%H:%M')
    status = serializers.CharField()
    reason = serializers.CharField()
    pet_name = serializers.CharField(source='pet.name')
    owner_name = serializers.CharField(source='pet.owner.name')
    expected_state = serializers.SerializerMethodField()

    def get_expected_state(self, obj):
        from apps.appointments.services import current_state
        return current_state(obj)
