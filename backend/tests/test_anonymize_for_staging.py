"""anonymize_for_staging: la guarda contra producción y que no quede ningún dato real."""
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.authentication.models import CustomUser
from apps.authentication.validators import validate_cedula_ecuatoriana
from apps.leads.models import Interaction, Lead
from apps.payments.models import Payment
from apps.programs.models import CoordinatorEmailConfig

STAGING_PASSWORD = 'clave-de-staging-123'


@pytest.fixture
def staging_env(monkeypatch, settings, tmp_path):
    monkeypatch.setenv('APP_ENV', 'staging')
    monkeypatch.setenv('STAGING_DEFAULT_PASSWORD', STAGING_PASSWORD)
    # El placeholder se escribe en MEDIA_ROOT: no ensuciar el media/ del repo.
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def real_bootcamper(db):
    return CustomUser.objects.create_user(
        email='persona.real@gmail.com', password='la-de-verdad',
        first_name='Persona', last_name='Real', phone='0991234567',
        cedula='0926687856', role=CustomUser.Role.BOOTCAMPER,
    )


@pytest.fixture
def populated(db, real_bootcamper, salesperson_user, program, coordinator_config):
    lead = Lead.objects.create(
        name='Lead Real', phone='0987654321', email='lead.real@gmail.com',
        owner=salesperson_user,
    )
    Interaction.objects.create(
        lead=lead, salesperson=salesperson_user,
        interaction_type=Interaction.InteractionType.CALL,
        outcome=Interaction.Outcome.CALL_AGAIN,
        notes='Dijo que paga el viernes con la tarjeta de su papá',
        next_action='Llamar al 0987654321',
    )
    Payment.objects.create(
        bootcamper=real_bootcamper, program=program,
        receipt_file='receipts/2026/08/foto-transferencia.jpg', receipt_file_type='image',
        payer_name='Persona Real', payer_identification='0926687856',
        payer_email='persona.real@gmail.com', payer_phone='0991234567',
        payer_address='Av. Real 123', ocr_raw_text='BANCO PICHINCHA CTA 2203456789',
        ocr_transaction_id='998877', document_number='001-002-000123',
    )
    return lead


class TestGuard:
    def test_refuses_without_app_env(self, db, monkeypatch):
        monkeypatch.delenv('APP_ENV', raising=False)
        with pytest.raises(CommandError, match='APP_ENV'):
            call_command('anonymize_for_staging')

    def test_refuses_with_production_app_env(self, db, monkeypatch):
        monkeypatch.setenv('APP_ENV', 'production')
        with pytest.raises(CommandError, match='APP_ENV'):
            call_command('anonymize_for_staging')

    def test_refuses_on_production_database(self, staging_env, monkeypatch):
        from django.db import connection
        monkeypatch.setitem(connection.settings_dict, 'NAME', 'boottracker')
        with pytest.raises(CommandError, match='producción'):
            call_command('anonymize_for_staging')

    def test_refuses_short_password(self, staging_env, monkeypatch):
        monkeypatch.setenv('STAGING_DEFAULT_PASSWORD', 'corta')
        with pytest.raises(CommandError, match='STAGING_DEFAULT_PASSWORD'):
            call_command('anonymize_for_staging')

    def test_guard_leaves_data_untouched(self, populated, real_bootcamper, monkeypatch):
        monkeypatch.setenv('APP_ENV', 'production')
        with pytest.raises(CommandError):
            call_command('anonymize_for_staging')
        real_bootcamper.refresh_from_db()
        assert real_bootcamper.email == 'persona.real@gmail.com'


class TestAnonymization:
    def test_bootcamper_has_no_real_data(self, staging_env, populated, real_bootcamper):
        call_command('anonymize_for_staging')
        real_bootcamper.refresh_from_db()
        assert real_bootcamper.email.endswith('@staging.test')
        assert real_bootcamper.first_name != 'Persona'
        assert real_bootcamper.phone != '0991234567'
        assert real_bootcamper.cedula != '0926687856'
        assert validate_cedula_ecuatoriana(real_bootcamper.cedula)
        assert real_bootcamper.check_password(STAGING_PASSWORD)

    def test_staff_keeps_login_but_not_personal_ids(self, staging_env, populated, salesperson_user):
        call_command('anonymize_for_staging')
        salesperson_user.refresh_from_db()
        assert salesperson_user.email == 'salesperson@test.com'
        assert salesperson_user.phone is None and salesperson_user.cedula is None
        assert salesperson_user.check_password(STAGING_PASSWORD)

    def test_leads_and_interactions(self, staging_env, populated):
        call_command('anonymize_for_staging')
        assert not Lead.objects.exclude(email__endswith='@staging.test').exists()
        assert not Lead.objects.filter(name='Lead Real').exists()
        interaction = Interaction.objects.get()
        assert interaction.notes == '' and interaction.next_action == ''

    def test_soft_deleted_leads_are_anonymized_too(self, staging_env, populated):
        borrado = Lead.objects.create(name='Borrado Real', phone='0981112233', email='borrado@gmail.com')
        borrado.soft_delete()
        call_command('anonymize_for_staging')
        borrado = Lead.all_objects.get(pk=borrado.pk)
        assert borrado.email.endswith('@staging.test')
        assert borrado.name != 'Borrado Real'

    def test_payments(self, staging_env, populated):
        call_command('anonymize_for_staging')
        p = Payment.objects.get()
        assert p.receipt_file.name == 'staging/placeholder.pdf'
        assert p.receipt_file.storage.exists(p.receipt_file.name)
        assert p.ocr_raw_text == ''
        assert p.payer_identification != '0926687856'
        assert p.payer_email.endswith('@staging.test')
        assert 'Real' not in p.payer_address
        assert p.ocr_transaction_id != '998877'
        assert p.document_number != '001-002-000123'

    def test_coordinator_emails(self, staging_env, populated):
        call_command('anonymize_for_staging')
        assert not CoordinatorEmailConfig.objects.exclude(email__endswith='@staging.test').exists()

    def test_is_idempotent(self, staging_env, populated):
        call_command('anonymize_for_staging')
        first = list(CustomUser.objects.order_by('email').values_list('email', 'cedula'))
        call_command('anonymize_for_staging')
        second = list(CustomUser.objects.order_by('email').values_list('email', 'cedula'))
        assert first == second
