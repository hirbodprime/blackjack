from django.contrib import admin
from .models import *

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "chips", "xp", "level",
        "games", "loan", "admin", "referral_code",
        "referrer", "total_referral_bonus"
    )
    list_filter = ("admin", "level")
    search_fields = ("name", "referral_code", "id")
    readonly_fields = ("referral_code",)
    list_editable = ("chips", "xp", "level", "loan", "admin")
    autocomplete_fields = ("referrer",)

    fieldsets = (
        (None, {
            "fields": ("name", "referrer", "referral_code")
        }),
        ("Stats", {
            "fields": ("chips", "xp", "level", "games", "loan")
        }),
        ("Admin Flags", {
            "fields": ("admin",)
        }),
        ("Referral Info", {
            "fields": ("total_referral_bonus",)
        }),
        ("Activity", {
            "fields": ("last_claimed_tokens", "tokens_claimed_today", "last_spin", "real_tokens")
        }),
    )

@admin.register(DailyQuest)
class DailyQuestAdmin(admin.ModelAdmin):
    list_display = ("quest_type", "subtype", "description", "target", "reward_xp", "reward_chips", "date_assigned", "available")
    list_editable = ("subtype", "description", "target", "reward_xp", "reward_chips", "date_assigned", "available")
    readonly_fields = ("date_assigned",)
    list_filter = ("quest_type", "available")
    list_per_page = 25
    ordering = ("-date_assigned",)


@admin.register(PlayerItem)
class PlayerItemAdmin(admin.ModelAdmin):
    list_display = ("player", "item_type", "quantity")
    list_editable = ("item_type", "quantity")
    list_per_page = 25


@admin.register(PlayerActiveItem)
class PlayerActiveItemAdmin(admin.ModelAdmin):
    list_display = ("player", "item_type", "is_active", "activated_at")
    list_editable = ("item_type", "is_active")
    readonly_fields = ("activated_at",)
    list_per_page = 25


@admin.register(HorseSale)
class HorseSaleAdmin(admin.ModelAdmin):
    list_display = ("horse", "price", "listed_at")
    list_editable = ("price",)
    readonly_fields = ("listed_at",)
    list_per_page = 25


@admin.register(GameParameter)
class GameParameterAdmin(admin.ModelAdmin):
    list_display = ("id", "horse_move_min", "horse_move_max", "crash_min", "crash_max", "crash_min_unrigged", "crash_max_unrigged",
                    "double_chance", "join_bonus", "join_bonus_amount", "buyhorse_event", "todays_horse_price", "rename_horse_event")
    list_editable = ("horse_move_min", "horse_move_max", "crash_min", "crash_max", "crash_min_unrigged", "crash_max_unrigged",
                     "double_chance", "join_bonus", "join_bonus_amount", "buyhorse_event", "todays_horse_price", "rename_horse_event")
    list_per_page = 10


@admin.register(ReferralEarning)
class ReferralEarningAdmin(admin.ModelAdmin):
    list_display = ("referrer", "referred", "amount", "created_at")
    list_editable = ("amount",)
    readonly_fields = ("created_at",)
    list_per_page = 25
    ordering = ("-created_at",)


@admin.register(HorseRaceWin)
class HorseRaceWinAdmin(admin.ModelAdmin):
    list_display = ("race", "horse_number", "user", "horse_name", "amount", "created_at")
    list_editable = ("horse_number", "horse_name", "amount")
    readonly_fields = ("created_at",)
    list_per_page = 25
    ordering = ("-created_at",)


@admin.register(HorseUpgrade)
class HorseUpgradeAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "cost")
    list_editable = ("description", "cost")
    list_per_page = 25


@admin.register(PlayerUpgrade)
class PlayerUpgradeAdmin(admin.ModelAdmin):
    list_display = ("player", "upgrade")
    list_per_page = 25


@admin.register(HorseAppliedUpgrade)
class HorseAppliedUpgradeAdmin(admin.ModelAdmin):
    list_display = ("owner", "horse", "upgrade", "uses_remaining")
    list_editable = ("upgrade", "uses_remaining")
    list_per_page = 25


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ("player", "notify_classic_blackjack_start", "notify_race_start", "notify_new_sales", "notify_new_events",
                    "daily_token_reminder_enabled", "daily_dart_reminder", "notify_high_roller_blackjack_start")
    list_editable = ("notify_classic_blackjack_start", "notify_race_start", "notify_new_sales", "notify_new_events",
                     "daily_token_reminder_enabled", "daily_dart_reminder", "notify_high_roller_blackjack_start")
    list_per_page = 25


@admin.register(Stats)
class StatsAdmin(admin.ModelAdmin):
    list_display = ("player", "wins", "loses", "how_many_21", "correct_dealer_guesses")
    list_editable = ("wins", "loses", "how_many_21", "correct_dealer_guesses")
    list_per_page = 25


@admin.register(CrashGame)
class CrashGameAdmin(admin.ModelAdmin):
    list_display = ("user_id", "bet", "multiplier", "crashed", "cashed_out", "start_time")
    list_editable = ("bet", "multiplier", "crashed", "cashed_out")
    readonly_fields = ("start_time",)
    ordering = ("-start_time",)
    list_per_page = 25


@admin.register(NextGameNotification)
class NextGameNotificationAdmin(admin.ModelAdmin):
    list_display = ("user_id", "chat_id")
    list_editable = ("chat_id",)
    list_per_page = 25


@admin.register(HorseRace)
class HorseRaceAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "race_started", "race_distance", "created_at")
    list_editable = ("chat_id", "race_started", "race_distance")
    readonly_fields = ("created_at",)
    ordering = ("-created_at",)
    list_per_page = 25


@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = ("player", "game", "is_active", "has_stood")
    list_editable = ("is_active", "has_stood")
    list_per_page = 25


@admin.register(RoundWinner)
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ("game", "round_number", "winner", "is_dealer", "rounds_ended")
    list_editable = ("round_number", "winner", "is_dealer", "rounds_ended")
    list_per_page = 25


@admin.register(QuestHistory)
class QuestHistoryAdmin(admin.ModelAdmin):
    list_display = ("player", "quest_type", "subtype", "description", "progress", "target", "reward_xp", "reward_chips", "date_assigned", "date_completed")
    list_editable = ("quest_type", "subtype", "description", "progress", "target", "reward_xp", "reward_chips")
    readonly_fields = ("date_completed",)
    ordering = ("-date_completed",)
    list_per_page = 25


@admin.register(PlayerDailyQuestProgress)
class PlayerDailyQuestProgressAdmin(admin.ModelAdmin):
    list_display = ("player", "quest", "subtype", "progress", "completed")
    list_editable = ("subtype", "progress", "completed")
    list_per_page = 25


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "condition", "icon")
    list_editable = ("description", "condition", "icon")
    list_per_page = 25


@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    list_display = ("player", "achievement", "unlocked_at")
    readonly_fields = ("unlocked_at",)
    list_per_page = 25


@admin.register(OwnedHorse)
class OwnedHorseAdmin(admin.ModelAdmin):
    list_display = ("horse_number", "user", "name", "emoji", "bought_at")
    list_editable = ("name", "emoji")
    readonly_fields = ("bought_at",)
    list_per_page = 25


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("group_chat_id", "group_name", "games", "vip", "real_money")
    list_editable = ("group_name", "vip", "real_money")
    list_per_page = 25


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("chat_id", "betting", "started", "join_time", "forced", "ended", "hands_reset", "bet_amount",
                    "current_round", "total_rounds", "pot", "bet_phase", "dealer_bet_timer")
    list_editable = ("betting", "started", "join_time", "forced", "ended", "hands_reset", "bet_amount",
                     "current_round", "total_rounds", "pot", "bet_phase", "dealer_bet_timer")
    list_per_page = 25


@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ("chips", "wins", "loses", "blackjack_count", "games", "real_tokens")
    list_display_links = ("chips",)
    list_editable = ("wins", "loses", "blackjack_count", "games", "real_tokens")
    list_per_page = 25
