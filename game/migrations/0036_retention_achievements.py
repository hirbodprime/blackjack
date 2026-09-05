from django.db import migrations


ACHIEVEMENTS = (
    ("Weekly Warrior", "Complete your first weekly mission.", "weekly_warrior", "📅"),
    ("Market Debut", "Sell your first item on the marketplace.", "first_market_sale", "🏪"),
    ("Treasure Hunter", "Buy your first marketplace item.", "first_market_purchase", "🛍️"),
    ("Friendly Rival", "Win your first friend challenge.", "first_challenge_win", "⚔️"),
)


def seed(apps, schema_editor):
    Achievement = apps.get_model("game", "Achievement")
    for name, description, condition, icon in ACHIEVEMENTS:
        Achievement.objects.get_or_create(
            condition=condition,
            defaults={"name": name, "description": description, "icon": icon},
        )


def unseed(apps, schema_editor):
    Achievement = apps.get_model("game", "Achievement")
    Achievement.objects.filter(condition__in=[x[2] for x in ACHIEVEMENTS]).delete()


class Migration(migrations.Migration):
    dependencies = [("game", "0035_weeklymission_usersettings_notify_marketplace_and_more")]
    operations = [migrations.RunPython(seed, unseed)]
