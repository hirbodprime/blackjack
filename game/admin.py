from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse

from .models import (
    NextGameNotification,
    Achievement,
    Game,
    Group,
    Dealer,
    Player,
    PlayerAchievement,
    Stats,
    JoinGame,
    RoundWinner,
    HorseRace, 
    HorseBet,
)

# ─── HorseBet Inline ───
class HorseBetInline(admin.TabularInline):
    model = HorseBet
    extra = 0
    readonly_fields = ("user_id", "horse_number", "bet_amount", "username")
    can_delete = False

# ─── HorseRace Admin ───
@admin.register(HorseRace)
class HorseRaceAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "race_started", "race_distance", "created_at")
    list_filter = ("race_started", "created_at")
    search_fields = ("chat_id",)
    inlines = [HorseBetInline]
    readonly_fields = ("created_at",)

# ─── HorseBet Admin ───
@admin.register(HorseBet)
class HorseBetAdmin(admin.ModelAdmin):
    list_display = ("id", "race", "user_id", "username", "horse_number", "bet_amount")
    list_filter = ("horse_number", "race__chat_id")
    search_fields = ("user_id", "username")

# ──────────────────────────────────────────────────────────────────────────────
# Inline definitions
# ──────────────────────────────────────────────────────────────────────────────

class PlayerAchievementInline(admin.TabularInline):
    """
    Show unlocked achievements right in the Player edit page.
    """
    model = PlayerAchievement
    extra = 0
    readonly_fields = ("achievement", "unlocked_at")
    can_delete = False
    verbose_name = "Unlocked Achievement"
    verbose_name_plural = "Unlocked Achievements"


class JoinGameInline(admin.TabularInline):
    """
    Show which players have joined this Game.
    """
    model = JoinGame
    extra = 0
    readonly_fields = ("player", "is_active", "has_stood")
    can_delete = False
    verbose_name = "Joined Player"
    verbose_name_plural = "Joined Players"


class RoundWinnerInline(admin.TabularInline):
    """
    Show round winners beneath a Game.
    """
    model = RoundWinner
    extra = 0
    readonly_fields = ("round_number", "winner", "is_dealer", "rounds_ended")
    can_delete = False
    verbose_name = "Round Winner"
    verbose_name_plural = "Round Winners"


# ──────────────────────────────────────────────────────────────────────────────
# ModelAdmin definitions
# ──────────────────────────────────────────────────────────────────────────────

@admin.register(NextGameNotification)
class NextGameNotificationAdmin(admin.ModelAdmin):
    list_display = ("user_id", "chat_id")
    search_fields = ("user_id", "chat_id")
    list_per_page = 25


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("name", "condition", "icon_preview")
    search_fields = ("name", "condition")
    list_filter = ("condition",)
    readonly_fields = ("icon_preview",)

    def icon_preview(self, obj):
        """
        If the icon field holds an emoji or HTML, show a small preview.
        """
        if obj.icon:
            return format_html(f"<span style='font-size: 1.5em;'>{obj.icon}</span>")
        return "-"
    icon_preview.short_description = "Icon Preview"


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "chat_id",
        "join_time",
        "betting",
        "started",
        "forced",
        "ended",
        "bet_amount",
        "current_round",
        "total_rounds",
        "pot",
    )
    list_filter = (
        "join_time",
        "betting",
        "started",
        "forced",
        "ended",
    )
    search_fields = ("chat_id",)
    readonly_fields = ("dealer_hand", "turn_order")
    inlines = (JoinGameInline, RoundWinnerInline)
    list_per_page = 20

    fieldsets = (
        (None, {
            "fields": (
                "chat_id",
                "bet_amount",
                "current_round",
                "total_rounds",
                "pot",
            )
        }),
        ("Statuses", {
            "fields": (
                "join_time",
                "betting",
                "started",
                "forced",
                "ended",
                "hands_reset",
            )
        }),
        ("Extra Data", {
            "classes": ("collapse",),
            "fields": (
                "dealer_hand",
                "turn_order",
                "bet_phase",
                "dealer_bet_timer",
                "join_start_time",
                "poll_id",
            ),
        }),
    )


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("group_chat_id", "group_name", "games", "vip", "real_money")
    search_fields = ("group_chat_id", "group_name")
    list_filter = ("vip", "real_money")
    list_editable = ("group_name", "vip", "real_money")
    list_per_page = 25


@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ("id", "chips", "wins", "loses", "blackjack_count", "games", "real_tokens")
    search_fields = ("id",)
    list_per_page = 25


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "chips_with_icon",
        "real_tokens_with_icon",
        "xp_with_icon",
        "level",
        "games_played",
    )
    search_fields = ("name", "id")
    list_filter = ("level",)
    list_editable = ("level",)
    readonly_fields = ("games",)
    inlines = (PlayerAchievementInline,)
    list_per_page = 25

    def chips_with_icon(self, obj):
        return format_html(f"💰 {obj.chips}")
    chips_with_icon.short_description = "Chips"

    def real_tokens_with_icon(self, obj):
        return format_html(f"💵 {obj.real_tokens}")
    real_tokens_with_icon.short_description = "Real Tokens"

    def xp_with_icon(self, obj):
        return format_html(f"✨ {obj.xp}")
    xp_with_icon.short_description = "XP"

    def games_played(self, obj):
        return obj.games
    games_played.short_description = "Games"


@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    list_display = ("player", "achievement", "unlocked_at")
    search_fields = ("player__name", "achievement__name")
    list_filter = ("achievement",)
    readonly_fields = ("unlocked_at",)
    list_per_page = 25


@admin.register(Stats)
class StatsAdmin(admin.ModelAdmin):
    list_display = ("player", "wins", "loses", "how_many_21", "correct_dealer_guesses")
    search_fields = ("player__name",)
    list_editable = ("wins", "loses", "how_many_21", "correct_dealer_guesses")
    list_per_page = 25


@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = ("player", "game", "is_active", "has_stood")
    search_fields = ("player__name", "game__chat_id")
    list_filter = ("is_active", "has_stood")
    list_per_page = 25


@admin.register(RoundWinner)
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ("game", "round_number", "winner", "is_dealer", "rounds_ended")
    search_fields = ("game__chat_id", "winner__name")
    list_filter = ("is_dealer", "rounds_ended")
    list_per_page = 25
