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
    HorseUpgrade,
    PlayerUpgrade,
    HorseAppliedUpgrade,
    HorseSale,
    CrashGame,
    HorseRaceWin,
    PlayerItem, PlayerActiveItem
)
@admin.register(PlayerItem)
class PlayerItemAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "item_type",
        "quantity",
    )
    list_editable = ("quantity",)
    list_filter = ("item_type",)
    search_fields = (
        "player__name",
        "item_type",
    )
    autocomplete_fields = ("player",)
    ordering = ("player__name", "item_type")


@admin.register(PlayerActiveItem)
class PlayerActiveItemAdmin(admin.ModelAdmin):
    list_display = (
        "player",
        "item_type",
        "activated_at",
        "is_active",
    )
    list_filter = (
        "item_type",
        "is_active",
    )
    search_fields = (
        "player__name",
        "item_type",
    )
    readonly_fields = ("activated_at",)
    autocomplete_fields = ("player",)
    ordering = ("-activated_at",)








@admin.register(HorseRaceWin)
class HorseRaceWinAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "race",
        "user",
        "horse_number",
        "horse_name",
        "amount",
        "created_at",
    )
    list_filter = (
        "horse_number",
        "created_at",
        "user",
    )
    search_fields = (
        "race__id",
        "user__name",
        "horse_number",
    )
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)

# ─── CrashGameAdmin ─────────────────────────────────────────────────────────────
@admin.register(CrashGame)
class CrashGameAdmin(admin.ModelAdmin):
    list_display = (
        "user_id",
        "bet",
        "multiplier",
        "crashed",
        "cashed_out",
        "start_time",
    )
    list_filter = (
        "crashed",
        "cashed_out",
        "start_time",
    )
    search_fields = ("user_id",)
    ordering = ("-start_time",)
    readonly_fields = (
        "user_id",
        "bet",
        "multiplier",
        "crashed",
        "cashed_out",
        "start_time",
    )


# ─── HorseAppliedUpgrade Inline ─────────────────────────────────────────────────
class HorseAppliedUpgradeInline(admin.TabularInline):
    model = HorseAppliedUpgrade
    extra = 0
    verbose_name = "Applied Upgrade"
    verbose_name_plural = "Applied Upgrades"
    fields = ("upgrade",)
    readonly_fields = ()


# ─── HorseSale Inline ───────────────────────────────────────────────────────────
class HorseSaleInline(admin.TabularInline):
    model = HorseSale
    extra = 0
    verbose_name = "Sale Listing"
    verbose_name_plural = "Sale Listings"
    fields = ("price", "listed_at")
    readonly_fields = ("listed_at",)
    can_delete = False


# ─── OwnedHorseAdmin ────────────────────────────────────────────────────────────
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
    inlines = [HorseAppliedUpgradeInline, HorseSaleInline]
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


# ─── HorseSaleAdmin ─────────────────────────────────────────────────────────────
@admin.register(HorseSale)
class HorseSaleAdmin(admin.ModelAdmin):
    list_display = (
        "horse_display",
        "price",
        "listed_at",
    )
    list_filter = ("price", "listed_at")
    search_fields = ("horse__horse_number", "horse__user__name", "horse__name")
    ordering = ("-listed_at",)
    readonly_fields = ("listed_at",)

    def horse_display(self, obj):
        """
        Display the horse with its name/number and owner.
        """
        label = f"Horse {obj.horse.horse_number}"
        if obj.horse.name:
            label = f"{obj.horse.name} ({obj.horse.horse_number})"
        return format_html(
            "{} – owned by {}",
            label,
            obj.horse.user.name or obj.horse.user.id,
        )

    horse_display.short_description = "Horse Listing"


# ─── HorseUpgradeAdmin ───────────────────────────────────────────────────────────
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


# ─── PlayerUpgradeAdmin ─────────────────────────────────────────────────────────
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


# ─── HorseAppliedUpgradeAdmin ───────────────────────────────────────────────────
@admin.register(HorseAppliedUpgrade)
class HorseAppliedUpgradeAdmin(admin.ModelAdmin):
    list_display = (
        "owner",
        "horse",
        "upgrade",
        "uses_remaining",
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
                    "uses_remaining",

                ),
            },
        ),
    )


# ─── HorseBetInline ──────────────────────────────────────────────────────────────
class HorseBetInline(admin.TabularInline):
    model = HorseBet
    extra = 0
    readonly_fields = ("user_id", "horse_number", "bet_amount", "username")
    can_delete = False


# ─── HorseRaceAdmin ─────────────────────────────────────────────────────────────
@admin.register(HorseRace)
class HorseRaceAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "race_started", "race_distance", "created_at")
    list_filter = ("race_started", "created_at")
    search_fields = ("chat_id",)
    inlines = [HorseBetInline]
    readonly_fields = ("created_at",)


# ─── HorseBetAdmin ──────────────────────────────────────────────────────────────
@admin.register(HorseBet)
class HorseBetAdmin(admin.ModelAdmin):
    list_display = ("id", "race", "user_id", "username", "horse_number", "bet_amount")
    list_filter = ("horse_number", "race__chat_id")
    search_fields = ("user_id", "username")


# ────────────────────────────────────────────────────────────────────────────────
# Inline definitions
# ────────────────────────────────────────────────────────────────────────────────


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


# ────────────────────────────────────────────────────────────────────────────────
# ModelAdmin definitions
# ────────────────────────────────────────────────────────────────────────────────


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
