# Generated by Django 3.2.21 on 2023-10-31 09:53

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangocms_translations', '0030_auto_20231011_1810'),
    ]

    operations = [
        migrations.AlterField(
            model_name='apptranslationrequest',
            name='source_language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English')], max_length=10),
        ),
        migrations.AlterField(
            model_name='apptranslationrequest',
            name='target_language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English')], max_length=10),
        ),
        migrations.AlterField(
            model_name='translationdirective',
            name='master_language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English')], default='de', max_length=10, verbose_name='master language'),
        ),
        migrations.AlterField(
            model_name='translationdirectiveinline',
            name='language',
            field=models.CharField(choices=[('de', 'German'), ('en', 'English')], default='de', editable=False, max_length=10, verbose_name='language'),
        ),
    ]