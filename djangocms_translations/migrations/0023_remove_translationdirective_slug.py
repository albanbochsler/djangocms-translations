# Generated by Django 3.2.21 on 2023-10-02 16:59

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('djangocms_translations', '0022_auto_20231002_1656'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='translationdirective',
            name='slug',
        ),
    ]