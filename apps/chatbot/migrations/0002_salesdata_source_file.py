from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chatbot', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='salesdata',
            name='source_file',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]