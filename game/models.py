from django.db import models


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

# New model for tracking round winners
class RoundWinner(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    round_number = models.IntegerField()
    winner = models.ForeignKey(Player, null=True, blank=True, on_delete=models.CASCADE)  # Nullable for dealer wins
    is_dealer = models.BooleanField(default=False)  # To mark if the dealer won the round
    rounds_ended = models.BooleanField(default=False)  
