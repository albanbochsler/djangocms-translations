from django.core.management.base import BaseCommand, CommandError

from djangocms_translations.models import (
    AppTranslationRequest,
    TranslationRequest,
)


class Command(BaseCommand):
    help = (
        'Re-import the stored response_content of a translation request. '
        'Useful when the import logic was fixed and you want to re-run the '
        'import without asking the provider to resend the callback.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'pk',
            type=int,
            help='Primary key of the (App)TranslationRequest',
        )
        parser.add_argument(
            '--app',
            action='store_true',
            help='Target an AppTranslationRequest instead of a TranslationRequest',
        )

    def handle(self, *args, **options):
        pk = options['pk']
        model = AppTranslationRequest if options['app'] else TranslationRequest

        try:
            trans_request = model.objects.get(pk=pk)
        except model.DoesNotExist:
            raise CommandError(f'{model.__name__} with pk={pk} not found.')

        if not getattr(trans_request, 'order', None) or not trans_request.order.response_content:
            raise CommandError(f'{model.__name__} {pk} has no stored response_content.')

        # Reset to IN_TRANSLATION so import_response runs cleanly
        trans_request.set_status(trans_request.STATES.IN_TRANSLATION)

        self.stdout.write(f'Re-importing response for {model.__name__} {pk}...')
        success = trans_request.import_response(trans_request.order.response_content)

        if success:
            self.stdout.write(self.style.SUCCESS(f'Re-import successful (state: {trans_request.state}).'))
        else:
            self.stdout.write(self.style.ERROR(f'Re-import failed (state: {trans_request.state}).'))
