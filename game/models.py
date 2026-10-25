from django.db import models
from django.utils import timezone

import random
import string

import string, secrets


def generate_referral_code():
    """
    Return a random 6-character string:
      - 4 uppercase letters [A–Z]
      - 2 digits [0–9]
    e.g. "XQRT05"
    """
    letters = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    digits  = "".join(secrets.choice(string.digits)          for _ in range(2))
    return letters + digits




class NextGameNotification(models.Model):
    user_id = models.BigIntegerField()
    chat_id = models.BigIntegerField()

    def __str__(self):
        return f"User {self.user_id} in chat {self.chat_id}"

class Achievement(models.Model):
    class Category(models.TextChoices):
        BLACKJACK = "blackjack", "Blackjack"
        HORSES = "horses", "Horses"
        MINIGAMES = "minigames", "Minigames"
        PROGRESS = "progress", "Progress"
        COMPETITION = "competition", "Competitions"
        SOCIAL = "social", "Social"
        LEGACY = "legacy", "Legacy"

    name = models.CharField(max_length=100)
    description = models.TextField()
    condition = models.CharField(max_length=100)  # e.g., "win_10_games", "reach_21_five_times"
    icon = models.CharField(max_length=100, null=True, blank=True)  # Optional, could be an emoji or icon
    category = models.CharField(max_length=16, choices=Category.choices, default=Category.BLACKJACK)
    reward_chips = models.PositiveIntegerField(default=0)
    reward_xp = models.PositiveIntegerField(default=20)
    hidden = models.BooleanField(default=False, help_text="Hidden until unlocked")


BET_PHASE_CHOICES = (
    ("total_pot","total_pot"),
    ("dealer","dealer")
    )


class Game(models.Model):
    chat_id = models.CharField(max_length=100)
    betting = models.BooleanField(default=False)
    started = models.BooleanField(default=False)
    join_time = models.BooleanField(default=False)
    forced = models.BooleanField(default=False)
    ended = models.BooleanField(default=False)
    hands_reset = models.BooleanField(default=False)
    bet_amount = models.IntegerField(default=5)
    dealer_hand = models.JSONField(default=list)  # To store the dealer's hand
    turn_order = models.JSONField(default=list)  # To store the turn order
    current_round = models.IntegerField(default=1)  # Current round number
    total_rounds = models.IntegerField(default=5)  # Total number of rounds in the game
    pot = models.IntegerField(default=0)  # Total pot amount
    join_start_time = models.DateTimeField(null=True, blank=True)  # Time when join period starts
    bet_phase = models.CharField(choices=BET_PHASE_CHOICES, max_length=50,default="total_pot")  # Time when join period starts
    dealer_bet_timer = models.IntegerField(default=30)
    poll_id = models.CharField(max_length=100, null=True, blank=True)
    is_round_starting = models.BooleanField(default=False)

# class GroupSettings(models.Model):
#     group = models.OneToOneField("Group", on_delete=models.CASCADE, related_name="settings")

#     LANGUAGE_CHOICES = [
#         ("en", "English"),
#         ("fa", "فارسی"),
#         # Add more languages here
#     ]
#     language = models.CharField(max_length=5, choices=LANGUAGE_CHOICES, default="en")

#     def __str__(self):
#         return f"Settings for group {self.group.group_chat_id}"


class Group(models.Model):
    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        PERSIAN = "fa", "فارسی"

    group_chat_id = models.CharField(max_length=100)
    group_name = models.CharField(max_length=255, null=True, blank=True)  # New field for the group's name
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.ENGLISH)
    games = models.IntegerField(default=0)
    vip = models.BooleanField(default=False)
    real_money = models.BooleanField(default=False)

class Dealer(models.Model):
    chips = models.IntegerField(default=0)  # The dealer's chips
    wins = models.IntegerField(default=0)   # Number of games the dealer has won
    loses = models.IntegerField(default=0)
    blackjack_count = models.IntegerField(default=0)
    games = models.IntegerField(default=0)
    real_tokens = models.IntegerField(default=0)


class HorseSale(models.Model):
    horse = models.OneToOneField(
        "OwnedHorse",
        on_delete=models.CASCADE,
        related_name="sale_listing"
    )
    price = models.IntegerField()
    listed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.horse} → {self.price:,} chips"



class UserSettings(models.Model):
    class Language(models.TextChoices):
        ENGLISH = "en", "English"
        PERSIAN = "fa", "فارسی"

    player = models.OneToOneField("Player", on_delete=models.CASCADE, related_name="settings")

    notify_classic_blackjack_start = models.BooleanField(default=True)
    notify_race_start = models.BooleanField(default=True)
    notify_new_sales = models.BooleanField(default=True)
    notify_new_events = models.BooleanField(default=True)
    daily_token_reminder_enabled = models.BooleanField(default=True)
    daily_dart_reminder = models.BooleanField(default=True)
    notify_high_roller_blackjack_start = models.BooleanField(default=True)
    notify_tournaments = models.BooleanField(default=True)
    notify_quests = models.BooleanField(default=True)
    notify_marketplace = models.BooleanField(default=True)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.ENGLISH)
    compact_mode = models.BooleanField(default=False)
    onboarding_complete = models.BooleanField(
        default=True,
        help_text="Existing accounts remain complete; new accounts explicitly enter onboarding.",
    )
    def __str__(self):
        return f"Settings for {self.player}"
# await update_daily_quest_progress(player_obj, "race", "win", 1, context)


class DailyQuest(models.Model):
    QUEST_TYPES = [
        ("blackjack", "Classic Blackjack"),
        ("minigames", "Minigames"),
        ("race", "Horse Race"),
    ]

    quest_type = models.CharField(max_length=50, choices=QUEST_TYPES)
    description = models.TextField(default="")
    target = models.PositiveIntegerField()
    reward_xp = models.PositiveIntegerField(default=0)
    reward_chips = models.PositiveIntegerField(default=0)
    date_assigned = models.DateField(default=timezone.now)
    subtype = models.CharField(max_length=50, blank=True, null=True,
        help_text="Optional specific subtype (e.g., 'draw', 'coin', 'rps') for minigames or others.")
    available = models.BooleanField(default=False)
    difficulty = models.CharField(max_length=8, blank=True, help_text="easy/medium/hard for generated challenges")
    auto_generated = models.BooleanField(default=False, db_index=True)
    def __str__(self):
        return f"{self.get_quest_type_display()} ({self.date_assigned})"

class PlayerDailyQuestProgress(models.Model):
    player = models.ForeignKey("Player", on_delete=models.CASCADE, related_name="quest_progress")
    quest = models.ForeignKey("DailyQuest", on_delete=models.CASCADE, related_name="progresses")
    subtype = models.CharField(max_length=50, blank=True, null=True,
        help_text="Optional specific subtype (e.g., 'draw', 'coin', 'rps') for minigames or others.")
    progress = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ("player", "quest")

    def __str__(self):
        return f"{self.player} - {self.quest.quest_type} ({self.progress}/{self.quest.target})"








class QuestHistory(models.Model):
    player = models.ForeignKey("Player", on_delete=models.CASCADE, related_name="quest_history")
    quest_type = models.CharField(max_length=50)
    subtype = models.CharField(max_length=50, blank=True, null=True)
    description = models.TextField()
    target = models.PositiveIntegerField()
    reward_xp = models.PositiveIntegerField()
    reward_chips = models.PositiveIntegerField()
    progress = models.PositiveIntegerField()
    date_assigned = models.DateField()
    date_completed = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.player.name} completed {self.quest_type} quest on {self.date_completed.date()}"


class WeeklyMission(models.Model):
    quest_type = models.CharField(max_length=50, choices=DailyQuest.QUEST_TYPES)
    description = models.TextField()
    target = models.PositiveIntegerField()
    reward_xp = models.PositiveIntegerField(default=0)
    reward_chips = models.PositiveIntegerField(default=0)
    week_start = models.DateField(default=timezone.now, db_index=True)
    subtype = models.CharField(max_length=50, blank=True, null=True)
    available = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.description} ({self.week_start})"


class PlayerWeeklyMissionProgress(models.Model):
    player = models.ForeignKey("Player", on_delete=models.CASCADE, related_name="weekly_mission_progress")
    mission = models.ForeignKey(WeeklyMission, on_delete=models.CASCADE, related_name="progresses")
    progress = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("player", "mission"), name="unique_player_weekly_mission")
        ]



class ActivePoll(models.Model):
    poll_id = models.CharField(max_length=255, unique=True)
    chat_id = models.BigIntegerField()
    message_id = models.BigIntegerField()
    has_response = models.BooleanField(default=False)
    options = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True,null=True,blank=True)


    def __str__(self):
        return f"Poll {self.poll_id} in chat {self.chat_id}"



class GameParameter(models.Model):
    """
    A singleton model for storing configurable game parameters.
    There should only ever be one row; we’ll get_or_create(pk=1).
    """
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    horse_move_min = models.PositiveIntegerField(default=2,
        help_text="Minimum per-tick movement for dealer’s horse")
    horse_move_max = models.PositiveIntegerField(default=5,
        help_text="Maximum per-tick movement for dealer’s horse")
    
    horse_move_event = models.BooleanField(default=False,
        help_text="If true, Win horse matches easier")
    

    crash_min = models.FloatField(default=1.0,
        help_text="Minimum crash multiplier")
    crash_max = models.FloatField(default=2.5,
        help_text="Maximum crash multiplier")
    crash_min_unrigged = models.FloatField(default=1.0,
        help_text="Minimum crash multiplier (for unrigged users)")
    crash_max_unrigged = models.FloatField(default=1.6,
        help_text="Maximum crash multiplier (for unrigged users)")
    crash_event = models.BooleanField(default=False,
        help_text="If true, Win crash matches easier")

    double_chance = models.FloatField(default=0.5,
        help_text="Probability threshold for some random rig check (e.g., 0.5 = 50%)")
    double_chance_event = models.BooleanField(default=False,
        help_text="If true, Double chance rises")
    
    join_bonus = models.BooleanField(default=False,
        help_text="If true, users receive a bonus when game starts")
    join_bonus_amount = models.PositiveIntegerField(default=0,
        help_text="Amount of chips to give if start bonus is enabled")
    
    new_quests = models.BooleanField(default=False,
        help_text="New quests are now available")
    
    buyhorse_event = models.BooleanField(default=False,
        help_text="If True, all horse numbers cost the same (see 'today_horse_price')")
    todays_horse_price = models.PositiveIntegerField(default=50_000,
        help_text="Flat price for horses during a buyhorse event")

    rename_horse_event = models.BooleanField(default=False,
        help_text="If True, rename horse is 1 chip")
    
    
    def __str__(self):
        return "Game Parameters (singleton)"

    class Meta:
        verbose_name = "Game Parameter"
        verbose_name_plural = "Game Parameters"


class Player(models.Model):
    name = models.CharField(max_length=50)
    chips = models.IntegerField(default=0)
    games = models.IntegerField(default=0)
    last_claimed_tokens = models.DateTimeField(null=True, blank=True)  # Track last claim time
    tokens_claimed_today = models.IntegerField(default=0)  # Track how many times they claimed today
    real_tokens = models.IntegerField(default=0)
    admin = models.BooleanField(default=False)
    xp = models.IntegerField(default=0)  # Add XP field
    level = models.IntegerField(default=1)  # Add Level field
    loan = models.IntegerField(default=0)  # New field to track player's loan
    last_spin = models.DateField(null=True, blank=True)
    is_frozen = models.BooleanField(default=False)
    freeze_reason = models.CharField(max_length=255, blank=True)
    referrer = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="referred_friends"
    )
    total_referral_bonus = models.IntegerField(default=0)
    title = models.CharField(max_length=40, blank=True)
    daily_streak = models.PositiveIntegerField(default=0)
    best_daily_streak = models.PositiveIntegerField(default=0)
    last_streak_date = models.DateField(null=True, blank=True)

    # ← New field: a 6-char code, unique
    referral_code = models.CharField(max_length=6, unique=True, blank=True)



    def save(self, *args, **kwargs):
        # If this Player has no referral_code yet, generate one now
        if not self.referral_code:
            code = generate_referral_code()
            while Player.objects.filter(referral_code=code).exists():
                code = generate_referral_code()
            self.referral_code = code
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.id}) – code={self.referral_code}"


class ChipTransaction(models.Model):
    class Category(models.TextChoices):
        BET = "bet", "Bet placed"
        REFUND = "refund", "Bet refunded"
        BLACKJACK_PAYOUT = "blackjack_payout", "Blackjack payout"
        POKER_BUY_IN = "poker_buy_in", "Poker buy-in"
        POKER_CASH_OUT = "poker_cash_out", "Poker cash-out"
        RACE_PAYOUT = "race_payout", "Race payout"
        MINIGAME_PAYOUT = "minigame_payout", "Minigame payout"
        DAILY_REWARD = "daily_reward", "Daily reward"
        QUEST_REWARD = "quest_reward", "Quest reward"
        REFERRAL_REWARD = "referral_reward", "Referral reward"
        ITEM_PURCHASE = "item_purchase", "Item purchase"
        HORSE_PURCHASE = "horse_purchase", "Horse purchase"
        LOAN = "loan", "Loan"
        LOAN_REPAYMENT = "loan_repayment", "Loan repayment"
        TRANSFER = "transfer", "Player transfer"
        ADMIN_ADJUSTMENT = "admin_adjustment", "Admin adjustment"
        LEVEL_REWARD = "level_reward", "Level reward"
        COMPETITION_PRIZE = "competition_prize", "Competition prize"
        ACHIEVEMENT_REWARD = "achievement_reward", "Achievement reward"
        SEASON_RESET = "season_reset", "Season reset"
        OTHER = "other", "Other"

    player = models.ForeignKey(
        Player,
        on_delete=models.PROTECT,
        related_name="chip_transactions",
    )
    amount = models.BigIntegerField(help_text="Signed balance change")
    balance_before = models.BigIntegerField()
    balance_after = models.BigIntegerField()
    category = models.CharField(max_length=32, choices=Category.choices)
    description = models.CharField(max_length=255, blank=True)
    reference_type = models.CharField(max_length=50, blank=True)
    reference_id = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(
        max_length=150,
        unique=True,
        null=True,
        blank=True,
        help_text="Prevents a retry from applying the same balance change twice.",
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("player", "created_at"), name="chip_tx_player_time"),
            models.Index(fields=("category", "created_at"), name="chip_tx_category_time"),
        ]

    def __str__(self):
        return f"{self.player_id}: {self.amount:+,} ({self.category})"


class BotControl(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    maintenance_mode = models.BooleanField(default=False)
    betting_paused = models.BooleanField(default=False)
    broadcasts_muted = models.BooleanField(default=False)
    maintenance_message = models.CharField(
        max_length=255,
        default="The bot is undergoing maintenance. Please try again shortly.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Bot operational controls"

    class Meta:
        verbose_name = "Bot Control"
        verbose_name_plural = "Bot Controls"


class OperationalEvent(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"
        CRITICAL = "critical", "Critical"

    severity = models.CharField(max_length=10, choices=Severity.choices, db_index=True)
    category = models.CharField(max_length=50, db_index=True)
    message = models.TextField()
    chat_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    player_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    game_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    context = models.JSONField(default=dict, blank=True)
    resolved = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"[{self.severity}] {self.category}: {self.message[:80]}"


class ReferralEarning(models.Model):
    referrer = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="referral_earnings"
    )
    referred = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="referral_generated"
    )
    amount = models.IntegerField(help_text="Bonus chips given to referrer")
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.referrer.name} ← {self.amount} (because {self.referred.name} won)"

class PlayerAchievement(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    unlocked_at = models.DateTimeField(auto_now_add=True)


class Stats(models.Model):
    wins = models.IntegerField(default=0)
    loses = models.IntegerField(default=0)
    how_many_21 = models.IntegerField(default=0)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    correct_dealer_guesses = models.IntegerField(default=0)  # New field for tracking correct guesses


class JoinGame(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=False)
    hand = models.JSONField(default=list)
    has_stood = models.BooleanField(default=False)
    last_action_time = models.DateTimeField(null=True, blank=True)
    consecutive_timeouts = models.PositiveSmallIntegerField(default=0)
    turn_token = models.CharField(max_length=36, blank=True)

# New model for tracking round winners
class RoundWinner(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    round_number = models.IntegerField()
    winner = models.ForeignKey(Player, null=True, blank=True, on_delete=models.CASCADE)  # Nullable for dealer wins
    is_dealer = models.BooleanField(default=False)  # To mark if the dealer won the round
    rounds_ended = models.BooleanField(default=False)  



class HorseRace(models.Model):
    chat_id = models.BigIntegerField()
    race_started = models.BooleanField(default=False)
    completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    race_distance = models.IntegerField(default=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Race {self.id} in Chat {self.chat_id}"

class HorseBet(models.Model):
    race = models.ForeignKey(HorseRace, related_name="bets", on_delete=models.CASCADE)
    user_id = models.BigIntegerField()
    horse_number = models.IntegerField()
    bet_amount = models.IntegerField()
    username = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Bet by {self.user_id} on horse {self.horse_number} ({self.bet_amount})"


class OwnedHorse(models.Model):
    user = models.ForeignKey(Player, on_delete=models.CASCADE)
    horse_number = models.IntegerField(unique=True)
    emoji = models.CharField(max_length=10, blank=True, null=True)
    name = models.CharField(max_length=50, blank=True, null=True)   # ← new field
    is_starter = models.BooleanField(default=False, help_text="Free Season horse; cannot be sold or gifted")

    bought_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user",), condition=models.Q(is_starter=True),
                name="one_starter_horse_per_player",
            )
        ]

    def __str__(self):
        return f"Horse {self.horse_number} owned by {self.user}"
    
class HorseRaceWin(models.Model):
    race = models.ForeignKey(
        "HorseRace",
        on_delete=models.PROTECT,
        related_name="wins"
    )
    # If user is NULL, that indicates the dealer took the pot
    user = models.ForeignKey(
        "Player",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        help_text="NULL means the dealer took the pot."
    )
    horse_number = models.IntegerField()
    horse_name = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="If the horse has a custom name, store it here."
    )
    amount = models.IntegerField(
        help_text="Amount this user (or dealer if user is NULL) won in chips."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        who = f"Player {self.user.id}" if self.user else "Dealer"
        return f"{who} won {self.amount} chips on horse {self.horse_number} (race #{self.race.id})"

class HorseUpgrade(models.Model):
    name = models.CharField(max_length=50)
    description = models.TextField()
    cost = models.IntegerField()

    def __str__(self):
        return self.name

class PlayerUpgrade(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    upgrade = models.ForeignKey(HorseUpgrade, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.player.name} owns {self.upgrade.name}"

class HorseAppliedUpgrade(models.Model):
    owner = models.ForeignKey(Player, on_delete=models.CASCADE)
    horse = models.ForeignKey(OwnedHorse, on_delete=models.CASCADE)
    upgrade = models.ForeignKey(HorseUpgrade, on_delete=models.CASCADE)
    uses_remaining = models.IntegerField(default=3)  
    def __str__(self):
        return f"{self.upgrade.name} on Horse {self.horse.horse_number} by {self.owner.name}"



class CrashGame(models.Model):
    user_id = models.BigIntegerField()
    bet = models.PositiveIntegerField()
    multiplier = models.FloatField(default=1.0)
    crashed = models.BooleanField(default=False)
    cashed_out = models.BooleanField(default=False)
    start_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"CrashGame(user={self.user_id}, bet={self.bet}, multiplier={self.multiplier:.2f})"

ITEM_TYPE_CHOICES = [
    # Potions
    ("double_chip_potion",   "Double Chip Potion"),
    ("triple_chip_potion",   "Triple Chip Potion"),
    ("10x_chip_potion",      "10× Chip Potion"),
    # Boosters
    ("xp_booster_500",       "+500 XP Booster"),
    ("xp_booster_2000",      "+2000 XP Booster"),
    ("xp_booster_15000",     "+15000 XP Booster"),
    ("xp_booster_50000",     "+50000 XP Booster"),
    # Passes
    ("insurance_pass",       "Insurance Pass"),
    ("first_hand_20_pass",   "First‐Hand‐20 Pass"),
    ("first_hand_11_potion",   "First‐Hand‐11 Pass"),
    # Season shop
    ("xp_charm",             "Lucky Charm (24h +25% XP)"),
    ("daily_doubler",        "Daily Doubler (24h)"),
    ("streak_freeze",        "Streak Freeze"),
    ("title_lucky",          "Title: Lucky"),
    ("title_shark",          "Title: Card Shark"),
    ("title_jockey",         "Title: Jockey"),
    ("title_ghost",          "Title: Ghost"),
    ("title_highroller",     "Title: High Roller"),
    ("title_tycoon",         "Title: Tycoon"),
    ("title_kingpin",        "Title: Kingpin"),
]

class PlayerItem(models.Model):
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="items"
    )
    item_type = models.CharField(
        max_length=32,
        choices=ITEM_TYPE_CHOICES
    )
    quantity = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("player", "item_type")

    def __str__(self):
        return f"{self.player.name} owns {self.quantity} × {self.get_item_type_display()}"


class ItemListing(models.Model):
    seller = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="item_listings")
    item_type = models.CharField(max_length=32, choices=ITEM_TYPE_CHOICES)
    quantity = models.PositiveIntegerField()
    price = models.PositiveIntegerField(help_text="Total listing price in chips")
    active = models.BooleanField(default=True, db_index=True)
    listed_at = models.DateTimeField(auto_now_add=True)
    buyer = models.ForeignKey(Player, null=True, blank=True, on_delete=models.SET_NULL, related_name="item_purchases")
    sold_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.quantity}× {self.item_type} for {self.price:,}"


class FriendChallenge(models.Model):
    class Mode(models.TextChoices):
        BLACKJACK = "blackjack", "Blackjack"
        DICE = "dice", "Dice"
        RPS = "rps", "Rock Paper Scissors"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        DECLINED = "declined", "Declined"
        CANCELLED = "cancelled", "Cancelled"

    challenger = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="challenges_sent")
    opponent = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="challenges_received")
    mode = models.CharField(max_length=12, choices=Mode.choices)
    stake = models.PositiveIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    challenger_score = models.PositiveSmallIntegerField(default=0)
    opponent_score = models.PositiveSmallIntegerField(default=0)
    round_number = models.PositiveSmallIntegerField(default=1)
    round_state = models.JSONField(default=dict, blank=True)
    winner = models.ForeignKey(Player, null=True, blank=True, on_delete=models.SET_NULL, related_name="challenges_won")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.challenger} vs {self.opponent} ({self.mode})"


# ─── Items currently active/equipped by a player (one‐time or “in‐effect”) ─────
class PlayerActiveItem(models.Model):
    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="active_items"
    )
    item_type = models.CharField(
        max_length=32,
        choices=ITEM_TYPE_CHOICES
    )
    activated_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        status = "active" if self.is_active else "used"
        return f"{self.player.name} → {self.get_item_type_display()} ({status})"


class PokerTable(models.Model):
    class Status(models.TextChoices):
        LOBBY = "lobby", "Lobby"
        PLAYING = "playing", "Hand in progress"
        BETWEEN_HANDS = "between", "Between hands"
        CLOSED = "closed", "Closed"

    chat_id = models.BigIntegerField(db_index=True)
    host = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="poker_tables_hosted")
    buy_in = models.PositiveIntegerField()
    small_blind = models.PositiveIntegerField()
    max_players = models.PositiveSmallIntegerField(default=8)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.LOBBY, db_index=True)
    dealer_seat = models.SmallIntegerField(default=-1)
    message_id = models.BigIntegerField(null=True, blank=True)
    hand_number = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("chat_id",),
                condition=~models.Q(status="closed"),
                name="unique_active_poker_table_per_chat",
            )
        ]

    def __str__(self):
        return f"Poker table #{self.pk} in {self.chat_id}"


class PokerSeat(models.Model):
    table = models.ForeignKey(PokerTable, on_delete=models.CASCADE, related_name="seats")
    player = models.ForeignKey(Player, null=True, blank=True, on_delete=models.PROTECT, related_name="poker_seats")
    is_bot = models.BooleanField(default=False)
    bot_name = models.CharField(max_length=40, blank=True)
    bot_style = models.CharField(
        max_length=12,
        choices=(("cautious", "Cautious"), ("balanced", "Balanced"), ("aggressive", "Aggressive"), ("wild", "Wild")),
        blank=True,
    )
    seat_number = models.PositiveSmallIntegerField()
    stack = models.PositiveIntegerField()
    hole_cards = models.JSONField(default=list, blank=True)
    committed_round = models.PositiveIntegerField(default=0)
    committed_hand = models.PositiveIntegerField(default=0)
    folded = models.BooleanField(default=False)
    all_in = models.BooleanField(default=False)
    acted = models.BooleanField(default=False)
    consecutive_timeouts = models.PositiveSmallIntegerField(default=0)
    leave_after_hand = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("table", "player"), name="unique_poker_table_player"),
            models.UniqueConstraint(fields=("table", "seat_number"), name="unique_poker_table_seat"),
        ]
        ordering = ("seat_number",)

    def __str__(self):
        name = self.bot_name if self.is_bot else self.player.name
        return f"{name} at table {self.table_id} seat {self.seat_number}"


class PokerHand(models.Model):
    class Phase(models.TextChoices):
        PREFLOP = "preflop", "Pre-flop"
        FLOP = "flop", "Flop"
        TURN = "turn", "Turn"
        RIVER = "river", "River"
        COMPLETE = "complete", "Complete"

    table = models.ForeignKey(PokerTable, on_delete=models.CASCADE, related_name="hands")
    number = models.PositiveIntegerField()
    phase = models.CharField(max_length=10, choices=Phase.choices, default=Phase.PREFLOP)
    deck = models.JSONField(default=list)
    community_cards = models.JSONField(default=list)
    pot = models.PositiveIntegerField(default=0)
    current_bet = models.PositiveIntegerField(default=0)
    min_raise = models.PositiveIntegerField(default=0)
    current_seat = models.SmallIntegerField(null=True, blank=True)
    action_token = models.CharField(max_length=36, blank=True)
    summary = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("table", "number"), name="unique_poker_table_hand")
        ]
        ordering = ("-number",)

    def __str__(self):
        return f"Poker hand {self.table_id}/{self.number} ({self.phase})"


class RPSBotProfile(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="rps_bot_profile")
    recent_choices = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"RPS memory for {self.player}"


class RouletteTable(models.Model):
    class Status(models.TextChoices):
        BETTING = "betting", "Betting open"
        SPINNING = "spinning", "Wheel spinning"
        COMPLETE = "complete", "Complete"
        CANCELLED = "cancelled", "Cancelled"

    chat_id = models.BigIntegerField(db_index=True)
    created_by = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="roulette_tables_created")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.BETTING, db_index=True)
    closes_at = models.DateTimeField(db_index=True)
    winning_number = models.PositiveSmallIntegerField(null=True, blank=True)
    seed_hash = models.CharField(max_length=64)
    seed_reveal = models.CharField(max_length=64, blank=True)
    access_token = models.CharField(max_length=32, unique=True)
    message_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("chat_id",), condition=models.Q(status="betting"),
                name="unique_open_roulette_table_per_chat",
            )
        ]

    def __str__(self):
        return f"Roulette table #{self.pk} in {self.chat_id} ({self.status})"


class RouletteTableBet(models.Model):
    class Kind(models.TextChoices):
        STRAIGHT = "straight", "Exact number"
        RED = "red", "Red"
        BLACK = "black", "Black"
        ODD = "odd", "Odd"
        EVEN = "even", "Even"
        LOW = "low", "1-18"
        HIGH = "high", "19-36"
        DOZEN = "dozen", "Dozen"
        COLUMN = "column", "Column"

    table = models.ForeignKey(RouletteTable, on_delete=models.PROTECT, related_name="bets")
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="roulette_table_bets")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    selection = models.CharField(max_length=12)
    amount = models.PositiveIntegerField()
    payout = models.PositiveIntegerField(default=0)
    won = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self):
        return f"{self.player} {self.amount} on {self.kind}:{self.selection}"


class Season(models.Model):
    number = models.PositiveSmallIntegerField(unique=True)
    name = models.CharField(max_length=60)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(db_index=True)
    starting_chips = models.PositiveIntegerField(default=10_000)
    is_active = models.BooleanField(default=False, db_index=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-number",)
        constraints = [
            models.UniqueConstraint(
                fields=("is_active",), condition=models.Q(is_active=True),
                name="single_active_season",
            )
        ]

    def __str__(self):
        return f"Season {self.number}: {self.name}"


class SeasonProgress(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="progress")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="season_progress")
    points = models.PositiveIntegerField(default=0, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("season", "player"), name="unique_season_player")
        ]

    def __str__(self):
        return f"{self.player} – S{self.season.number}: {self.points}"


class Tournament(models.Model):
    class Kind(models.TextChoices):
        BLACKJACK = "blackjack", "Blackjack"
        HORSES = "horses", "Horse racing"
        MINIGAMES = "minigames", "Minigames"
        POKER = "poker", "Poker"
        ALL = "all", "All games"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        LIVE = "live", "Live"
        SETTLED = "settled", "Settled"

    title = models.CharField(max_length=80)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    prize_pool = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED, db_index=True)
    announced = models.BooleanField(default=False)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("starts_at",)
        constraints = [
            models.UniqueConstraint(fields=("kind", "starts_at"), name="unique_tournament_slot")
        ]

    def __str__(self):
        return f"{self.title} ({self.starts_at:%Y-%m-%d %H:%M})"


class CompetitionPayout(models.Model):
    """One prize per (competition, rank); the unique key makes settlement idempotent."""

    competition = models.CharField(max_length=60, db_index=True)
    rank = models.PositiveSmallIntegerField()
    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="competition_payouts")
    score = models.BigIntegerField()
    prize_chips = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("competition", "rank")
        constraints = [
            models.UniqueConstraint(fields=("competition", "rank"), name="unique_competition_rank")
        ]

    def __str__(self):
        return f"{self.competition} #{self.rank}: {self.player_id} +{self.prize_chips:,}"


class ArcadeRound(models.Model):
    """One solo mini-app round; ``state`` holds the server-side secret (crash point, mines, deck)."""

    class Game(models.TextChoices):
        CRASH = "crash", "Crash"
        MINES = "mines", "Mines"
        HILO = "hilo", "Hi-Lo"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        WON = "won", "Cashed out"
        LOST = "lost", "Lost"

    player = models.ForeignKey(Player, on_delete=models.PROTECT, related_name="arcade_rounds")
    # The group the arcade was opened from, for that group's leaderboard; null when opened privately.
    chat_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    game = models.CharField(max_length=8, choices=Game.choices)
    bet = models.PositiveIntegerField()
    state = models.JSONField(default=dict)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    multiplier = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    payout = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("player",), condition=models.Q(status="active"),
                name="one_active_arcade_round",
            )
        ]

    def __str__(self):
        return f"{self.get_game_display()} #{self.pk} ({self.status})"


class BroadcastDelivery(models.Model):
    """One row per (campaign, chat) so a re-run never messages anyone twice."""

    campaign = models.CharField(max_length=40)
    chat_id = models.BigIntegerField()
    delivered = models.BooleanField(default=False)
    error = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("campaign", "chat_id"), name="unique_campaign_chat")
        ]


class PendingAchievement(models.Model):
    """Earned but not yet granted; handed over the next time the player actually plays."""

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="pending_achievements")
    condition = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("player", "condition"), name="unique_pending_achievement")
        ]
