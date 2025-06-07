from django.contrib import admin
from .models import *

# ─── Inlines ─────────────────────────────────────────────
class PlayerItemInline(admin.TabularInline):
    model = PlayerItem
    extra = 0

class PlayerUpgradeInline(admin.TabularInline):
    model = PlayerUpgrade
    extra = 0

class PlayerActiveItemInline(admin.TabularInline):
    model = PlayerActiveItem
    extra = 0

class PlayerAchievementInline(admin.TabularInline):
    model = PlayerAchievement
    extra = 0

class PlayerQuestProgressInline(admin.TabularInline):
    model = PlayerDailyQuestProgress
    extra = 0

# ─── Admin Models ────────────────────────────────────────
@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "level", "xp", "chips", "games", "admin", "referral_code", "get_referrer", "tokens_claimed_today")
    search_fields = ("name", "referral_code")
    list_filter = ("admin", "level")
    readonly_fields = ("referral_code",)
    inlines = [PlayerItemInline, PlayerUpgradeInline, PlayerActiveItemInline, PlayerAchievementInline, PlayerQuestProgressInline]

    def get_referrer(self, obj):
        return obj.referrer.name if obj.referrer else "-"
    get_referrer.short_description = "Referrer"

@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "started", "betting", "pot", "current_round", "total_rounds", "bet_phase")

@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("group_chat_id", "group_name", "games", "vip", "real_money")
    search_fields = ("group_chat_id", "group_name")

@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ("chips", "wins", "loses", "blackjack_count", "games", "real_tokens")

@admin.register(OwnedHorse)
class OwnedHorseAdmin(admin.ModelAdmin):
    list_display = ("horse_number", "user", "name", "emoji", "bought_at")
    search_fields = ("name", "horse_number")

@admin.register(HorseRace)
class HorseRaceAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "race_started", "race_distance", "created_at")

@admin.register(HorseRaceWin)
class HorseRaceWinAdmin(admin.ModelAdmin):
    list_display = ("race", "horse_number", "user", "amount", "created_at")

@admin.register(PlayerItem)
class PlayerItemAdmin(admin.ModelAdmin):
    list_display = ("player", "item_type", "quantity")

@admin.register(PlayerActiveItem)
class PlayerActiveItemAdmin(admin.ModelAdmin):
    list_display = ("player", "item_type", "is_active", "activated_at")

@admin.register(HorseSale)
class HorseSaleAdmin(admin.ModelAdmin):
    list_display = ("horse", "price", "listed_at")

@admin.register(GameParameter)
class GameParameterAdmin(admin.ModelAdmin):
    list_display = ("join_bonus", "join_bonus_amount", "buyhorse_event", "todays_horse_price", "rename_horse_event")
    fieldsets = (
        ("Horse Event Settings", {"fields": ("buyhorse_event", "todays_horse_price", "rename_horse_event")}),
        ("Crash Game Settings", {"fields": ("crash_min", "crash_max", "crash_min_unrigged", "crash_max_unrigged")}),
        ("Bonus Settings", {"fields": ("join_bonus", "join_bonus_amount", "double_chance")}),
        ("Movement Settings", {"fields": ("horse_move_min", "horse_move_max")}),
    )

@admin.register(ReferralEarning)
class ReferralEarningAdmin(admin.ModelAdmin):
    list_display = ("referrer", "referred", "amount", "created_at")

@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ("name", "condition", "icon")

@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    list_display = ("player", "achievement", "unlocked_at")

@admin.register(DailyQuest)
class DailyQuestAdmin(admin.ModelAdmin):
    list_display = (
        "quest_type", "subtype", "description", "target",
        "reward_xp", "reward_chips", "date_assigned", "available"
    )
    list_filter = ("quest_type", "available")
    list_editable = ("available",)  # ✅ makes it editable in the list view

@admin.register(PlayerDailyQuestProgress)
class PlayerDailyQuestProgressAdmin(admin.ModelAdmin):
    list_display = ("player", "quest", "subtype", "progress", "completed")

@admin.register(QuestHistory)
class QuestHistoryAdmin(admin.ModelAdmin):
    list_display = ("player", "quest_type", "subtype", "progress", "reward_chips", "date_completed")

@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = ("player", "game", "is_active", "has_stood")

@admin.register(RoundWinner)
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ("game", "round_number", "winner", "is_dealer", "rounds_ended")

@admin.register(HorseUpgrade)
class HorseUpgradeAdmin(admin.ModelAdmin):
    list_display = ("name", "cost")

@admin.register(PlayerUpgrade)
class PlayerUpgradeAdmin(admin.ModelAdmin):
    list_display = ("player", "upgrade")

@admin.register(HorseAppliedUpgrade)
class HorseAppliedUpgradeAdmin(admin.ModelAdmin):
    list_display = ("owner", "horse", "upgrade", "uses_remaining")

@admin.register(Stats)
class StatsAdmin(admin.ModelAdmin):
    list_display = ("player", "wins", "loses", "how_many_21", "correct_dealer_guesses")

@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ("player", "notify_classic_blackjack_start", "notify_race_start", "notify_new_sales", "daily_token_reminder_enabled")

@admin.register(CrashGame)
class CrashGameAdmin(admin.ModelAdmin):
    list_display = ("user_id", "bet", "multiplier", "crashed", "cashed_out", "start_time")

@admin.register(NextGameNotification)
class NextGameNotificationAdmin(admin.ModelAdmin):
    list_display = ("user_id", "chat_id")
