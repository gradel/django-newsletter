# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-05-12 18:12
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('newsletter', '0008_auto_20180930_1853'),
    ]

    operations = [
        migrations.AlterField(
            model_name='message',
            name='slug',
            field=models.SlugField(help_text='Leer lassen um den Slug automatisch zu erzeugen', verbose_name='slug'),
        ),
    ]
