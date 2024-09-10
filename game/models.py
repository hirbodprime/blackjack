from django.db import models
from django.utils import timezone




class Game(models.Model):
    chat_id = models.CharField(max_length=100)
    betting = models.BooleanField(default=False)
    started = models.BooleanField(default=False)
    join_time = models.BooleanField(default=False)
    ended = models.BooleanField(default=False)
    hands_reset = models.BooleanField(default=False)
    bet_amount = models.IntegerField(default=5)
    dealer_hand = models.JSONField(default=list)  # To store the dealer's hand
    turn_order = models.JSONField(default=list)  # To store the turn order
    current_round = models.IntegerField(default=1)  # Current round number
    total_rounds = models.IntegerField(default=5)  # Total number of rounds in the game
    pot = models.IntegerField(default=0)  # Total pot amount
    join_start_time = models.DateTimeField(default=timezone.now)  # Time when join period starts

class Group(models.Model):
    group_chat_id = models.CharField(max_length=100)
    games = models.IntegerField(default=0)
    

class Dealer(models.Model):
    chips = models.IntegerField(default=0)  # The dealer's chips
    wins = models.IntegerField(default=0)   # Number of games the dealer has won
    loses = models.IntegerField(default=0)
    blackjack_count = models.IntegerField(default=0)
    games = models.IntegerField(default=0)


class Player(models.Model):
    name = models.CharField(max_length=50)
    chips = models.IntegerField(default=0)
    games = models.IntegerField(default=0)


class Stats(models.Model):
    wins = models.IntegerField(default=0)
    loses = models.IntegerField(default=0)
    how_many_21 = models.IntegerField(default=0)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)


class JoinGame(models.Model):
    player = models.ForeignKey(Player, on_delete=models.CASCADE)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=False)
    hand = models.JSONField(default=list)


# New model for tracking round winners
class RoundWinner(models.Model):
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    round_number = models.IntegerField()
    winner = models.ForeignKey(Player, null=True, blank=True, on_delete=models.CASCADE)  # Nullable for dealer wins
    is_dealer = models.BooleanField(default=False)  # To mark if the dealer won the round
    rounds_ended = models.BooleanField(default=False)  
