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
    name = models.CharField(max_length=100)
    description = models.TextField()
    condition = models.CharField(max_length=100)  # e.g., "win_10_games", "reach_21_five_times"
    icon = models.CharField(max_length=100, null=True, blank=True)  # Optional, could be an emoji or icon


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



class Group(models.Model):
    group_chat_id = models.CharField(max_length=100)
    group_name = models.CharField(max_length=255, null=True, blank=True)  # New field for the group's name
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
    player = models.OneToOneField("Player", on_delete=models.CASCADE, related_name="settings")

    notify_classic_blackjack_start = models.BooleanField(default=True)
    notify_race_start = models.BooleanField(default=True)
    notify_new_sales = models.BooleanField(default=True)
    notify_new_events = models.BooleanField(default=True)
    daily_token_reminder_enabled = models.BooleanField(default=True)
    daily_dart_reminder = models.BooleanField(default=True)
    notify_high_roller_blackjack_start = models.BooleanField(default=True)
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
    
    new_quests = models.PositiveIntegerField(default=0,
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
    referrer = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="referred_friends"
    )
    total_referral_bonus = models.IntegerField(default=0)

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

    bought_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Horse {self.horse_number} owned by {self.user}"
    
class HorseRaceWin(models.Model):
    race = models.ForeignKey(
        "HorseRace",
        on_delete=models.CASCADE,
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
    