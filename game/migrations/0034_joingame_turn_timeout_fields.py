from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("game", "0033_usersettings_compact_mode_usersettings_language")]

    operations = [
        migrations.AddField(
            model_name="joingame",
            name="consecutive_timeouts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="joingame",
            name="turn_token",
            field=models.CharField(blank=True, max_length=36),
        ),
    ]
