from django.db import migrations

LEGACY = ("season0_veteran", "season0_founder")


def defer(apps, schema_editor):
    """Legacy badges granted at launch become pending until the player plays again."""
    PlayerAchievement = apps.get_model("game", "PlayerAchievement")
    PendingAchievement = apps.get_model("game", "PendingAchievement")
    granted = PlayerAchievement.objects.filter(achievement__condition__in=LEGACY).select_related("achievement")
    PendingAchievement.objects.bulk_create(
        [PendingAchievement(player_id=row.player_id, condition=row.achievement.condition) for row in granted],
        ignore_conflicts=True,
    )
    granted.delete()


def restore(apps, schema_editor):
    Achievement = apps.get_model("game", "Achievement")
    PlayerAchievement = apps.get_model("game", "PlayerAchievement")
    PendingAchievement = apps.get_model("game", "PendingAchievement")
    for pending in PendingAchievement.objects.filter(condition__in=LEGACY):
        achievement = Achievement.objects.filter(condition=pending.condition).first()
        if achievement:
            PlayerAchievement.objects.get_or_create(player_id=pending.player_id, achievement=achievement)
    PendingAchievement.objects.filter(condition__in=LEGACY).delete()


class Migration(migrations.Migration):
    dependencies = [("game", "0050_pending_achievements")]
    operations = [migrations.RunPython(defer, restore)]
