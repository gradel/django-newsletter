# Generated by Django 2.1.15 on 2020-04-18 16:19

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('newsletter', '0008_auto_20200418_1745'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='slug',
            field=models.SlugField(help_text='Leer lassen um den Slug automatisch zu erzeugen', verbose_name='slug'),
        ),
    ]
