from django.shortcuts import get_object_or_404
from .models import Player, Stats, PlayerAchievement
from django.http import HttpResponse

def calculate_xp_for_next_level(level):
    return level * 50  # XP required for each level increases by 50


def check_level_up(player):
    leveled_up = False
    while True:
        next_level_xp = calculate_xp_for_next_level(player.level)
        
        if player.xp >= next_level_xp:
            player.xp -= next_level_xp
            player.level += 1
            # Reward the player with 50 chips per level
            chips_reward = player.level * 50
            player.chips += chips_reward

            # Save player data and mark as leveled up
            player.save()
            leveled_up = True
        else:
            break

    return leveled_up

def update_player_xp(player, amount):
    player.xp += amount
    leveled_up = check_level_up(player)
    return leveled_up

def deduct_player_xp(player, amount):
    """
    Function to deduct XP and handle leveling down if necessary.
    """
    player.xp -= amount
    while player.xp < 0 and player.level > 1:
        # Level down the player
        player.level -= 1
        player.xp += calculate_xp_for_next_level(player.level)
    
    player.save()

# Function to reset XP for all players at the start
def reset_all_player_xp():
    players = Player.objects.all()
    for player in players:
        player.xp = 0
        player.level = 1
        player.save()

# Function to process all player stats and update XP accordingly
def process_game_results(request):
    # Reset XP for all players at the start of the game processing
    reset_all_player_xp()

    players = Player.objects.all()  # Get all players in the system

    # Process each player's stats
    for player in players:
        stats, created = Stats.objects.get_or_create(player=player)

        # Calculate XP for wins (25 XP per win)
        win_xp = stats.wins * 25

        achievements_count = PlayerAchievement.objects.filter(player=player).count()
        achievement_xp = achievements_count * 20
        
        # Calculate XP for blackjack (30 XP for each blackjack)
        blackjack_xp = stats.how_many_21 * 30
        
        total_xp = win_xp + blackjack_xp + achievement_xp
        
        # Update player's XP and check for level-up
        leveled_up = update_player_xp(player, total_xp)

        if leveled_up:
            # Send the reward message (can be done using context in a bot scenario)
            print(f"Player {player.name} leveled up to {player.level} and received {player.level * 50} chips.")

        # Deduct XP for losses (25 XP per loss)
        loss_xp_deduction = stats.loses * 25
        deduct_player_xp(player, loss_xp_deduction)

        # Save updated stats
        stats.save()

    return HttpResponse("XP processing complete.")  # No rendering of templates