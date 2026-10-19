"""Anonimiza una copia de la base de producción para usarla en STAGING.

Lo corre `deploy/refresh-staging-db.sh` después de restaurar el dump de prod en la
base de staging. Reemplaza todo dato personal o de pagos por valores ficticios,
pero conserva la forma de los datos (cantidades, estados, relaciones, fechas), que
es lo que hace útil al espejo para probar.

- **Bootcampers y leads:** nombre, correo, teléfono y cédula pasan a valores
  inventados (`bootcamper<n>@staging.test`, `lead<n>@staging.test`). La cédula se
  genera **válida** según `validate_cedula_ecuatoriana`, para que los formularios
  que la revalidan no fallen.
- **Staff (vendedores, admins, finanzas, coordinadores):** son las cuentas del
  equipo, así que conservan nombre y correo para poder entrar. Se borran teléfono
  y cédula.
- **Todas** las contraseñas pasan a `STAGING_DEFAULT_PASSWORD`.
- **Pagos:** datos del pagador, texto y campos del OCR, números de transacción y
  comprobante. Los archivos (comprobantes y planes de pago) pasan a apuntar a un
  placeholder: los originales son fotos de transferencias reales.
- Los destinatarios de correo de coordinación pasan a `@staging.test`, el
  `google_event_id` de las reuniones se borra para no tocar eventos reales, y se
  vacían las sesiones y los tokens JWT emitidos en producción.

**Guarda:** se niega a correr salvo que `APP_ENV=staging` y que la base no sea la
de producción (`boottracker`). Es la única barrera entre este comando y los datos
reales, por eso no tiene flag para saltarla.

    docker compose -p boottracker-staging ... exec backend \
        python manage.py anonymize_for_staging
"""
import os
import random

from django.contrib.auth.hashers import make_password
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.authentication.models import CustomUser
from apps.authentication.validators import validate_cedula_ecuatoriana
from apps.leads.models import Interaction, Lead
from apps.meetings.models import Meeting
from apps.payments.models import Payment, PaymentPlan
from apps.programs.models import CoordinatorEmailConfig

PRODUCTION_DB_NAME = 'boottracker'
PLACEHOLDER_PATH = 'staging/placeholder.pdf'
# PDF mínimo válido de una página en blanco: los visores lo abren sin error.
PLACEHOLDER_PDF = (
    b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n'
    b'2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n'
    b'3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n'
    b'trailer<</Root 1 0 R>>\n%%EOF\n'
)

FIRST_NAMES = ['Ana', 'Luis', 'María', 'Carlos', 'Sofía', 'Diego', 'Valeria', 'Jorge', 'Camila', 'Andrés']
LAST_NAMES = ['Prueba', 'Ficticio', 'Ejemplo', 'Demo', 'Staging', 'Muestra', 'Simulado', 'Ensayo']


def fake_cedula(rng: random.Random, usadas: set[str]) -> str:
    """Cédula ecuatoriana inventada, válida según el mod-10 y no repetida.

    `cedula` es única en CustomUser: `usadas` evita que dos bootcampers reciban la
    misma y el UPDATE falle a la mitad.
    """
    while True:
        base = f'{rng.randint(1, 24):02d}{rng.randint(0, 5)}{rng.randint(0, 999999):06d}'
        for dv in range(10):
            candidata = f'{base}{dv}'
            if validate_cedula_ecuatoriana(candidata) and candidata not in usadas:
                usadas.add(candidata)
                return candidata


def fake_phone(n: int) -> str:
    return f'09{n:08d}'


def fake_name(rng: random.Random) -> tuple[str, str]:
    return rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)


class Command(BaseCommand):
    help = 'Anonimiza una copia de producción para staging. Se niega a correr fuera de staging.'

    def handle(self, *args, **options):
        self._check_guard()
        password = os.environ.get('STAGING_DEFAULT_PASSWORD', '')
        if len(password) < 8:
            raise CommandError('STAGING_DEFAULT_PASSWORD falta o tiene menos de 8 caracteres.')

        # Semilla fija: dos refrescos seguidos producen los mismos nombres, así los
        # devs pueden referirse a "el lead de Ana Prueba" entre refrescos.
        rng = random.Random(20261019)
        self._cedulas: set[str] = set()
        placeholder = self._ensure_placeholder()

        with transaction.atomic():
            counts = {
                'usuarios': self._users(rng, make_password(password)),
                'leads': self._leads(rng),
                'interacciones': Interaction.objects.update(notes='', next_action=''),
                'pagos': self._payments(rng, placeholder),
                'planes de pago': PaymentPlan.objects.update(
                    file=placeholder, original_name='plan-de-pagos-staging.pdf', file_type='pdf',
                ),
                'destinatarios de coordinación': self._coordinator_emails(),
                'reuniones': self._meetings(),
            }
            with connection.cursor() as cursor:
                for table in ('django_session', 'token_blacklist_blacklistedtoken',
                              'token_blacklist_outstandingtoken'):
                    cursor.execute(f'DELETE FROM {table}')  # nosec B608 - nombres fijos

        for name, count in counts.items():
            self.stdout.write(f'  {name}: {count}')
        self.stdout.write(self.style.SUCCESS('Base anonimizada para staging.'))

    def _check_guard(self):
        app_env = os.environ.get('APP_ENV', '')
        db_name = connection.settings_dict['NAME']
        if app_env != 'staging':
            raise CommandError(f'APP_ENV={app_env!r}: este comando solo corre con APP_ENV=staging.')
        if db_name == PRODUCTION_DB_NAME:
            raise CommandError(f'La base es {db_name!r}, la de producción. Abortado.')

    def _ensure_placeholder(self) -> str:
        if not default_storage.exists(PLACEHOLDER_PATH):
            default_storage.save(PLACEHOLDER_PATH, ContentFile(PLACEHOLDER_PDF))
        return PLACEHOLDER_PATH

    def _users(self, rng, password_hash) -> int:
        users = list(CustomUser.objects.order_by('created_at', 'id'))
        for n, user in enumerate(users, start=1):
            user.password = password_hash
            user.phone = None
            user.cedula = None
            if user.role == CustomUser.Role.BOOTCAMPER:
                user.first_name, user.last_name = fake_name(rng)
                user.email = f'bootcamper{n}@staging.test'
                user.phone = fake_phone(n)
                user.cedula = fake_cedula(rng, self._cedulas)
                user.verification_rejection_reason = ''
        CustomUser.objects.bulk_update(
            users,
            ['password', 'first_name', 'last_name', 'email', 'phone', 'cedula',
             'verification_rejection_reason'],
        )
        return len(users)

    def _leads(self, rng) -> int:
        # all_objects y no objects: el manager por defecto oculta los leads con
        # soft-delete (deleted_at), y esos también tienen datos personales.
        leads = list(Lead.all_objects.order_by('created_at', 'id'))
        for n, lead in enumerate(leads, start=1):
            first, last = fake_name(rng)
            lead.name = f'{first} {last}'
            lead.email = f'lead{n}@staging.test'
            lead.phone = fake_phone(5_000_000 + n)
            lead.discard_detail = ''
        Lead.all_objects.bulk_update(leads, ['name', 'email', 'phone', 'discard_detail'])
        return len(leads)

    def _payments(self, rng, placeholder) -> int:
        payments = list(Payment.objects.select_related('bootcamper'))
        for n, p in enumerate(payments, start=1):
            p.receipt_file = placeholder
            p.receipt_file_type = 'pdf'
            p.ocr_raw_text = ''
            p.ocr_account_last_digits = '0000' if p.ocr_account_last_digits else ''
            p.ocr_transaction_id = f'STG-OCR-{n:05d}' if p.ocr_transaction_id else ''
            p.confirmed_transaction_id = f'STG-{n:05d}' if p.confirmed_transaction_id else ''
            p.document_number = f'STG-DOC-{n:05d}' if p.document_number else ''
            p.payer_name = p.bootcamper.get_full_name() if p.payer_name else ''
            p.payer_identification = fake_cedula(rng, self._cedulas) if p.payer_identification else ''
            p.payer_email = p.bootcamper.email if p.payer_email else ''
            p.payer_address = 'Dirección de prueba' if p.payer_address else ''
            p.payer_phone = fake_phone(9_000_000 + n) if p.payer_phone else ''
            p.rejection_reason = 'Motivo de prueba' if p.rejection_reason else ''
        Payment.objects.bulk_update(
            payments,
            ['receipt_file', 'receipt_file_type', 'ocr_raw_text', 'ocr_account_last_digits',
             'ocr_transaction_id', 'confirmed_transaction_id', 'document_number', 'payer_name',
             'payer_identification', 'payer_email', 'payer_address', 'payer_phone',
             'rejection_reason'],
        )
        return len(payments)

    def _coordinator_emails(self) -> int:
        configs = list(CoordinatorEmailConfig.objects.order_by('id'))
        for n, cfg in enumerate(configs, start=1):
            cfg.email = f'coordinacion{n}@staging.test'
            cfg.name = f'Coordinación de prueba {n}'
        CoordinatorEmailConfig.objects.bulk_update(configs, ['email', 'name'])
        return len(configs)

    def _meetings(self) -> int:
        meetings = list(Meeting.objects.order_by('id'))
        for n, m in enumerate(meetings, start=1):
            m.title = f'Reunión de prueba {n}'
            m.description = ''
            m.google_event_id = None
        Meeting.objects.bulk_update(meetings, ['title', 'description', 'google_event_id'])
        return len(meetings)
