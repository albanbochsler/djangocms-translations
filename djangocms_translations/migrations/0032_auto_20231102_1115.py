# Generated by Django 3.2.21 on 2023-11-02 11:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangocms_translations', '0031_auto_20231031_0953'),
    ]

    operations = [
        migrations.AlterField(
            model_name='apptranslationrequest',
            name='source_language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English'), ('fr', 'French')], max_length=10),
        ),
        migrations.AlterField(
            model_name='apptranslationrequest',
            name='target_language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English'), ('fr', 'French')], max_length=10),
        ),
        migrations.AlterField(
            model_name='translationdirective',
            name='master_language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English'), ('fr', 'French')], default='de', max_length=10, verbose_name='master language'),
        ),
        migrations.AlterField(
            model_name='translationdirectiveinline',
            name='language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English'), ('fr', 'French')], default='de', editable=False, max_length=10, verbose_name='language'),
        ),
    ]
