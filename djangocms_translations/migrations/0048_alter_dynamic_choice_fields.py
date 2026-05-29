import djangocms_translations.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('djangocms_translations', '0047_merge_20260526_2134'),
    ]

    operations = [
        migrations.AlterField(
            model_name='translationrequest',
            name='source_language',
            field=djangocms_translations.fields.DynamicChoiceCharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='translationrequest',
            name='target_language',
            field=djangocms_translations.fields.DynamicChoiceCharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='translationrequest',
            name='provider_backend',
            field=djangocms_translations.fields.DynamicChoiceCharField(max_length=100),
        ),
        migrations.AlterField(
            model_name='apptranslationrequest',
            name='source_language',
            field=djangocms_translations.fields.DynamicChoiceCharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='apptranslationrequest',
            name='target_language',
            field=djangocms_translations.fields.DynamicChoiceCharField(max_length=10),
        ),
        migrations.AlterField(
            model_name='apptranslationrequest',
            name='provider_backend',
            field=djangocms_translations.fields.DynamicChoiceCharField(max_length=100),
        ),
    ]
