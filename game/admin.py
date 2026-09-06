from django.contrib import admin
from django.db.models import Avg, Count, Q, Sum
from django.utils import timezone
from datetime import timedelta
from .models import *
from .services.recovery import cancel_blackjack_game, cancel_crash_game, cancel_poker_table, cancel_race, cancel_roulette_table
from .services.economy import (
    InsufficientChips,
    TransactionAlreadyReversed,
    adjust_balance,
    reverse_chip_transaction,
)
from .services.analytics import economy_analytics_context


admin.site.register(HorseBet)
admin.site.register(ActivePoll)


@admin.register(ChipTransaction)
class ChipTransactionAdmin(admin.ModelAdmin):
    change_list_template = "admin/game/chiptransaction/change_list.html"
    list_display = (
        "created_at", "player", "amount", "balance_before", "balance_after",
        "category", "reference_type", "reference_id",
    )
    list_filter = ("category", "created_at")
    search_fields = (
        "player__name", "player__id", "description", "reference_type",
        "reference_id", "idempotency_key",
    )
    readonly_fields = (
        "player", "amount", "balance_before", "balance_after", "category",
        "description", "reference_type", "reference_id", "idempotency_key",
        "metadata", "created_at",
    )
    ordering = ("-created_at",)
    list_select_related = ("player",)
    actions = ("reverse_selected_transactions",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    @admin.action(description="Reverse selected ledger entries")
    def reverse_selected_transactions(self, request, queryset):
        reversed_count = 0
        failed = []
        for transaction_id in queryset.values_list("pk", flat=True):
            try:
                reverse_chip_transaction(
                    transaction_id, operator=request.user.get_username()
                )
                reversed_count += 1
            except TransactionAlreadyReversed:
                failed.append(f"#{transaction_id} was already reversed")
            except InsufficientChips:
                failed.append(f"#{transaction_id} would make the balance negative")
        self.message_user(request, f"Reversed {reversed_count} transaction(s).")
        if failed:
            self.message_user(request, "; ".join(failed), level="warning")

    def changelist_view(self, request, extra_context=None):
        since = timezone.now() - timedelta(hours=24)
        ledger = ChipTransaction.objects.filter(created_at__gte=since).aggregate(
            created=Sum("amount", filter=Q(amount__gt=0)),
            destroyed=Sum("amount", filter=Q(amount__lt=0)),
            entries=Count("id"),
        )
        players = Player.objects.aggregate(
            total_supply=Sum("chips"),
            average_balance=Avg("chips"),
            outstanding_loans=Sum("loan"),
            frozen_players=Count("id", filter=Q(is_frozen=True)),
        )
        context = {
            **(extra_context or {}),
            "economy": {
                "created_24h": ledger["created"] or 0,
                "destroyed_24h": abs(ledger["destroyed"] or 0),
                "net_24h": (ledger["created"] or 0) + (ledger["destroyed"] or 0),
                "entries_24h": ledger["entries"],
                "total_supply": players["total_supply"] or 0,
                "average_balance": players["average_balance"] or 0,
                "outstanding_loans": players["outstanding_loans"] or 0,
                "frozen_players": players["frozen_players"],
            },
            "analytics": economy_analytics_context(),
        }
        return super().changelist_view(request, extra_context=context)


@admin.register(BotControl)
class BotControlAdmin(admin.ModelAdmin):
    change_list_template = "admin/game/botcontrol/change_list.html"
    list_display = (
        "maintenance_mode", "betting_paused", "broadcasts_muted", "updated_at",
    )

    def has_add_permission(self, request):
        return not BotControl.objects.exists()

    def changelist_view(self, request, extra_context=None):
        context = {
            **(extra_context or {}),
            "operations": {
                "active_games": Game.objects.filter(ended=False).count(),
                "active_races": HorseRace.objects.filter(race_started=True, completed=False).count(),
                "active_crash_games": CrashGame.objects.filter(
                    crashed=False, cashed_out=False
                ).count(),
                "active_players": JoinGame.objects.filter(is_active=True).count(),
            },
        }
        return super().changelist_view(request, extra_context=context)


@admin.register(OperationalEvent)
class OperationalEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at", "severity", "category", "chat_id", "player_id",
        "game_id", "resolved",
    )
    list_filter = ("severity", "category", "resolved", "created_at")
    search_fields = ("message", "chat_id", "player_id", "game_id")
    readonly_fields = (
        "severity", "category", "message", "chat_id", "player_id", "game_id",
        "context", "created_at",
    )
    list_editable = ("resolved",)
    ordering = ("-created_at",)
@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = (
        "id", "name", "chips", "xp", "level",
        "games", "loan", "admin", "referral_code",
        "referrer", "total_referral_bonus", "is_frozen"
    )
    list_filter = ("admin", "is_frozen", "level")
    search_fields = ("name", "referral_code", "id")
    readonly_fields = ("referral_code",)
    list_editable = ("chips", "xp", "level", "loan", "admin")
    autocomplete_fields = ("referrer",)

    def save_model(self, request, obj, form, change):
        if change and obj.pk:
            stored = Player.objects.get(pk=obj.pk)
            chip_delta = obj.chips - stored.chips
            if chip_delta:
                balance_change = adjust_balance(
                    stored,
                    chip_delta,
                    category=ChipTransaction.Category.ADMIN_ADJUSTMENT,
                    description=f"Django admin adjustment by {request.user.get_username()}",
                    reference_type="django_admin",
                    reference_id=request.user.pk or request.user.get_username(),
                    metadata={"admin_user_id": request.user.pk},
                    allow_negative=True,
                )
                obj.chips = balance_change.balance
        super().save_model(request, obj, form, change)

    fieldsets = (
        (None, {
            "fields": ("name", "referrer", "referral_code")
        }),
        ("Stats", {
            "fields": ("chips", "xp", "level", "games", "loan")
        }),
        ("Admin Flags", {
            "fields": ("admin", "is_frozen", "freeze_reason")
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
    readonly_fields = ("referrer", "referred", "amount", "created_at")
    list_per_page = 25
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


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
    list_display = ("player", "language", "compact_mode", "notify_classic_blackjack_start", "notify_race_start", "notify_new_sales", "notify_new_events",
                    "daily_token_reminder_enabled", "daily_dart_reminder", "notify_high_roller_blackjack_start")
    list_editable = ("language", "compact_mode", "notify_classic_blackjack_start", "notify_race_start", "notify_new_sales", "notify_new_events",
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
    actions = ("cancel_and_refund",)

    @admin.action(description="Emergency cancel selected crash games and refund players")
    def cancel_and_refund(self, request, queryset):
        refunds = sum(cancel_crash_game(pk) for pk in queryset.values_list("pk", flat=True))
        self.message_user(request, f"Cancelled selected crash games; issued {refunds} refund(s).")


@admin.register(NextGameNotification)
class NextGameNotificationAdmin(admin.ModelAdmin):
    list_display = ("user_id", "chat_id")
    list_editable = ("chat_id",)
    list_per_page = 25


@admin.register(HorseRace)
class HorseRaceAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "race_started", "completed", "race_distance", "created_at", "completed_at")
    list_filter = ("completed", "race_started")
    list_editable = ("chat_id", "race_started", "race_distance")
    readonly_fields = ("created_at", "completed_at")
    ordering = ("-created_at",)
    list_per_page = 25
    actions = ("cancel_and_refund",)

    @admin.action(description="Emergency cancel selected races and refund all bets")
    def cancel_and_refund(self, request, queryset):
        refunds = sum(cancel_race(pk) for pk in queryset.values_list("pk", flat=True))
        self.message_user(request, f"Cancelled selected races; issued {refunds} refund(s).")


@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = (
        "player", "game", "is_active", "has_stood", "consecutive_timeouts"
    )
    list_editable = ("is_active", "has_stood")
    readonly_fields = ("consecutive_timeouts", "turn_token")
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
    list_display = ("id","name", "description", "condition", "icon")
    list_editable = ("description", "condition", "icon")
    list_per_page = 25


@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    list_display = ("player", "achievement", "unlocked_at")
    readonly_fields = ("unlocked_at",)
    list_per_page = 25


@admin.register(WeeklyMission)
class WeeklyMissionAdmin(admin.ModelAdmin):
    list_display = ("week_start", "quest_type", "subtype", "description", "target", "reward_xp", "reward_chips", "available")
    list_filter = ("week_start", "quest_type", "available")
    list_editable = ("target", "reward_xp", "reward_chips", "available")


@admin.register(PlayerWeeklyMissionProgress)
class PlayerWeeklyMissionProgressAdmin(admin.ModelAdmin):
    list_display = ("player", "mission", "progress", "completed", "completed_at")
    list_filter = ("completed", "mission__week_start")
    readonly_fields = ("completed_at",)


@admin.register(ItemListing)
class ItemListingAdmin(admin.ModelAdmin):
    list_display = ("id", "seller", "item_type", "quantity", "price", "active", "buyer", "listed_at", "sold_at")
    list_filter = ("active", "item_type", "listed_at")
    search_fields = ("seller__name", "buyer__name")
    readonly_fields = ("listed_at", "sold_at")


@admin.register(FriendChallenge)
class FriendChallengeAdmin(admin.ModelAdmin):
    list_display = ("id", "challenger", "opponent", "mode", "stake", "status", "challenger_score", "opponent_score", "winner", "created_at")
    list_filter = ("mode", "status", "created_at")
    search_fields = ("challenger__name", "opponent__name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OwnedHorse)
class OwnedHorseAdmin(admin.ModelAdmin):
    list_display = ("horse_number", "user", "name", "emoji", "bought_at")
    list_editable = ("name", "emoji")
    readonly_fields = ("bought_at",)
    list_per_page = 25


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ("group_chat_id", "group_name", "language", "games", "vip", "real_money")
    list_editable = ("group_name", "language", "vip", "real_money")
    list_per_page = 25


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("chat_id", "betting", "started", "join_time", "forced", "ended", "hands_reset", "bet_amount",
                    "current_round", "total_rounds", "pot", "bet_phase", "dealer_bet_timer")
    list_editable = ("betting", "started", "join_time", "forced", "ended", "hands_reset", "bet_amount",
                     "current_round", "total_rounds", "pot", "bet_phase", "dealer_bet_timer")
    list_per_page = 25
    actions = ("cancel_and_refund",)

    @admin.action(description="Emergency cancel selected games and refund active players")
    def cancel_and_refund(self, request, queryset):
        refunds = sum(
            cancel_blackjack_game(pk) for pk in queryset.values_list("pk", flat=True)
        )
        self.message_user(request, f"Cancelled selected games; issued {refunds} refund(s).")


@admin.register(PokerTable)
class PokerTableAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "host", "status", "buy_in", "small_blind", "hand_number", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("chat_id", "host__name", "host__id")
    readonly_fields = ("created_at", "updated_at")
    actions = ("cancel_and_refund",)

    @admin.action(description="Emergency close selected poker tables and refund all stacks")
    def cancel_and_refund(self, request, queryset):
        refunds = sum(cancel_poker_table(pk) for pk in queryset.values_list("pk", flat=True))
        self.message_user(request, f"Closed selected poker tables; issued {refunds} refund(s).")


@admin.register(PokerSeat)
class PokerSeatAdmin(admin.ModelAdmin):
    list_display = ("table", "seat_number", "player", "bot_name", "bot_style", "stack", "committed_hand", "folded", "all_in")
    list_filter = ("is_bot", "bot_style", "folded", "all_in")
    search_fields = ("player__name", "player__id", "bot_name", "table__id")


@admin.register(PokerHand)
class PokerHandAdmin(admin.ModelAdmin):
    list_display = ("id", "table", "number", "phase", "pot", "current_seat", "created_at", "completed_at")
    list_filter = ("phase", "created_at")
    readonly_fields = ("deck", "community_cards", "summary", "created_at", "completed_at")


@admin.register(RouletteTable)
class RouletteTableAdmin(admin.ModelAdmin):
    list_display = ("id", "chat_id", "created_by", "status", "closes_at", "winning_number", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("chat_id", "created_by__name", "created_by__id")
    readonly_fields = ("seed_hash", "seed_reveal", "access_token", "message_id", "created_at", "completed_at")
    actions = ("cancel_and_refund",)

    @admin.action(description="Emergency cancel selected roulette tables and refund bets")
    def cancel_and_refund(self, request, queryset):
        refunds = sum(cancel_roulette_table(pk) for pk in queryset.values_list("pk", flat=True))
        self.message_user(request, f"Cancelled selected roulette tables; issued {refunds} refund(s).")


@admin.register(RouletteTableBet)
class RouletteTableBetAdmin(admin.ModelAdmin):
    list_display = ("id", "table", "player", "kind", "selection", "amount", "won", "payout", "created_at")
    list_filter = ("kind", "won", "created_at")
    search_fields = ("table__id", "player__name", "player__id", "idempotency_key")
    readonly_fields = ("table", "player", "kind", "selection", "amount", "payout", "won", "idempotency_key", "created_at", "settled_at")


@admin.register(RPSBotProfile)
class RPSBotProfileAdmin(admin.ModelAdmin):
    list_display = ("player", "updated_at")
    search_fields = ("player__name", "player__id")
    readonly_fields = ("player", "recent_choices", "updated_at")


@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ("chips", "wins", "loses", "blackjack_count", "games", "real_tokens")
    list_display_links = ("chips",)
    list_editable = ("wins", "loses", "blackjack_count", "games", "real_tokens")
    list_per_page = 25
