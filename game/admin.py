from django.contrib import admin
from django.utils.html import format_html
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
    OwnedHorse,
    HorseSale,
    HorseUpgrade,
    PlayerUpgrade,
    HorseAppliedUpgrade,
    CrashGame,
)


# ──────────────────────────────────────────────────────────────────────────────
# Admin for CrashGame
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(CrashGame)
class CrashGameAdmin(admin.ModelAdmin):
    list_display = (
        'user_id',
        'bet',
        'multiplier',
        'crashed',
        'cashed_out',
        'start_time'
    )
    list_filter = (
        'crashed',
        'cashed_out',
        'start_time',
    )
    search_fields = ('user_id',)
    ordering = ('-start_time',)
    readonly_fields = (
        'user_id',
        'bet',
        'multiplier',
        'crashed',
        'cashed_out',
        'start_time'
    )


# ──────────────────────────────────────────────────────────────────────────────
# Inline for HorseAppliedUpgrade under OwnedHorse
# ──────────────────────────────────────────────────────────────────────────────
class HorseAppliedUpgradeInline(admin.TabularInline):
    model = HorseAppliedUpgrade
    extra = 0
    verbose_name = "Applied Upgrade"
    verbose_name_plural = "Applied Upgrades"
    fields = ("upgrade",)
    readonly_fields = ()


# ──────────────────────────────────────────────────────────────────────────────
# Admin for OwnedHorse
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(OwnedHorse)
class OwnedHorseAdmin(admin.ModelAdmin):
    list_display = (
        "horse_number",
        "name",
        "user",
        "emoji",
        "bought_at",
    )
    list_filter = ("user",)
    search_fields = ("horse_number", "user__name", "name")
    ordering = ("horse_number",)
    inlines = [HorseAppliedUpgradeInline]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "user",
                    "horse_number",
                    "name",
                    "emoji",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": ("bought_at",),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = ("bought_at",)


# ──────────────────────────────────────────────────────────────────────────────
# Admin for HorseSale
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(HorseSale)
class HorseSaleAdmin(admin.ModelAdmin):
    list_display = ("horse", "price", "listed_at")
    list_filter = ("price", "listed_at")
    search_fields = ("horse__horse_number", "horse__name", "horse__user__name")
    ordering = ("-listed_at",)
    readonly_fields = ("listed_at",)


# ──────────────────────────────────────────────────────────────────────────────
# Admin for HorseUpgrade
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(HorseUpgrade)
class HorseUpgradeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "cost",
    )
    list_filter = ("cost",)
    search_fields = ("name",)
    ordering = ("cost",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "description",
                    "cost",
                ),
            },
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Admin for PlayerUpgrade
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(PlayerUpgrade)
class PlayerUpgradeAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "upgrade",
    )
    list_filter = ("upgrade",)
    search_fields = ("player__name", "upgrade__name")
    ordering = ("player__name",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "player",
                    "upgrade",
                ),
            },
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Admin for HorseAppliedUpgrade
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(HorseAppliedUpgrade)
class HorseAppliedUpgradeAdmin(admin.ModelAdmin):
    list_display = (
        "owner",
        "horse",
        "upgrade",
    )
    list_filter = ("upgrade",)
    search_fields = ("owner__name", "horse__horse_number", "upgrade__name")
    ordering = ("owner__name",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "owner",
                    "horse",
                    "upgrade",
                ),
            },
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Inline for HorseBet under HorseRace
# ──────────────────────────────────────────────────────────────────────────────
class HorseBetInline(admin.TabularInline):
    model = HorseBet
    extra = 0
    readonly_fields = ("user_id", "horse_number", "bet_amount", "username")
    can_delete = False


# ──────────────────────────────────────────────────────────────────────────────
# Admin for HorseRace
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(HorseRace)
class HorseRaceAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "race_started", "race_distance", "created_at")
    list_filter = ("race_started", "created_at")
    search_fields = ("chat_id",)
    inlines = [HorseBetInline]
    readonly_fields = ("created_at",)


# ──────────────────────────────────────────────────────────────────────────────
# Admin for HorseBet
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(HorseBet)
class HorseBetAdmin(admin.ModelAdmin):
    list_display = ("id", "race", "user_id", "username", "horse_number", "bet_amount")
    list_filter = ("horse_number", "race__chat_id")
    search_fields = ("user_id", "username")


# ──────────────────────────────────────────────────────────────────────────────
# Inline definitions for Game and its related models
# ──────────────────────────────────────────────────────────────────────────────
class JoinGameInline(admin.TabularInline):
    model = JoinGame
    extra = 0
    readonly_fields = ("player", "is_active", "has_stood")
    can_delete = False
    verbose_name = "Joined Player"
    verbose_name_plural = "Joined Players"


class RoundWinnerInline(admin.TabularInline):
    model = RoundWinner
    extra = 0
    readonly_fields = ("round_number", "winner", "is_dealer", "rounds_ended")
    can_delete = False
    verbose_name = "Round Winner"
    verbose_name_plural = "Round Winners"


# ──────────────────────────────────────────────────────────────────────────────
# Admin for Game
# ──────────────────────────────────────────────────────────────────────────────
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
        (
            None,
            {
                "fields": (
                    "chat_id",
                    "bet_amount",
                    "current_round",
                    "total_rounds",
                    "pot",
                )
            },
        ),
        (
            "Statuses",
            {
                "fields": (
                    "join_time",
                    "betting",
                    "started",
                    "forced",
                    "ended",
                    "hands_reset",
                )
            },
        ),
        (
            "Extra Data",
            {
                "classes": ("collapse",),
                "fields": (
                    "dealer_hand",
                    "turn_order",
                    "bet_phase",
                    "dealer_bet_timer",
                    "join_start_time",
                    "poll_id",
                ),
            },
        ),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Admin for JoinGame
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = ("player", "game", "is_active", "has_stood")
    search_fields = ("player__name", "game__chat_id")
    list_filter = ("is_active", "has_stood")
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for RoundWinner
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(RoundWinner)
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ("game", "round_number", "winner", "is_dealer", "rounds_ended")
    search_fields = ("game__chat_id", "winner__name")
    list_filter = ("is_dealer", "rounds_ended")
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for NextGameNotification
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(NextGameNotification)
class NextGameNotificationAdmin(admin.ModelAdmin):
    list_display = ("user_id", "chat_id")
    search_fields = ("user_id", "chat_id")
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for Achievement
# ──────────────────────────────────────────────────────────────────────────────
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


# ──────────────────────────────────────────────────────────────────────────────
# Admin for Group
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("group_chat_id", "group_name", "games", "vip", "real_money")
    search_fields = ("group_chat_id", "group_name")
    list_filter = ("vip", "real_money")
    list_editable = ("group_name", "vip", "real_money")
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for Dealer
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ("id", "chips", "wins", "loses", "blackjack_count", "games", "real_tokens")
    search_fields = ("id",)
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for Player
# ──────────────────────────────────────────────────────────────────────────────
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
        "loan",
        "last_spin",
    )
    search_fields = ("name", "id")
    list_filter = ("level",)
    list_editable = ("level",)
    readonly_fields = ("games", "last_claimed_tokens", "tokens_claimed_today")
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


# ──────────────────────────────────────────────────────────────────────────────
# Inline for PlayerAchievement under Player
# ──────────────────────────────────────────────────────────────────────────────
class PlayerAchievementInline(admin.TabularInline):
    model = PlayerAchievement
    extra = 0
    readonly_fields = ("achievement", "unlocked_at")
    can_delete = False
    verbose_name = "Unlocked Achievement"
    verbose_name_plural = "Unlocked Achievements"


# ──────────────────────────────────────────────────────────────────────────────
# Admin for PlayerAchievement
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    list_display = ("player", "achievement", "unlocked_at")
    search_fields = ("player__name", "achievement__name")
    list_filter = ("achievement",)
    readonly_fields = ("unlocked_at",)
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for Stats
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(Stats)
class StatsAdmin(admin.ModelAdmin):
    list_display = ("player", "wins", "loses", "how_many_21", "correct_dealer_guesses")
    search_fields = ("player__name",)
    list_editable = ("wins", "loses", "how_many_21", "correct_dealer_guesses")
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for JoinGame
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = ("player", "game", "is_active", "has_stood")
    search_fields = ("player__name", "game__chat_id")
    list_filter = ("is_active", "has_stood")
    list_per_page = 25


# ──────────────────────────────────────────────────────────────────────────────
# Admin for RoundWinner
# ──────────────────────────────────────────────────────────────────────────────
@admin.register(RoundWinner)
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ("game", "round_number", "winner", "is_dealer", "rounds_ended")
    search_fields = ("game__chat_id", "winner__name")
    list_filter = ("is_dealer", "rounds_ended")
    list_per_page = 25
