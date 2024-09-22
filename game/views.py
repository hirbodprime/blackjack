from django.shortcuts import get_object_or_404
from .models import Player, Stats, PlayerAchievement
from django.http import HttpResponse

def calculate_xp_for_next_level(level):
    print(f"level user {level}")
    return level * 50  # XP required for each level increases by 50

def check_level_up(player):
    leveled_up = False
    while True:
        next_level_xp = calculate_xp_for_next_level(player.level)
        print(f"next level check {next_level_xp} for level {player.level}")
        
        if player.xp >= next_level_xp:
            print(f"player xp before level-up: {player.xp}, next level xp required: {next_level_xp}")
            player.xp -= next_level_xp
            player.level += 1
            player.save()
            leveled_up = True
            print(f"player leveled up! New level: {player.level}, remaining xp: {player.xp}")
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
        
        print(f"Player: {player.name}, XP: {player.xp}, Wins XP: {win_xp}, Blackjack XP: {blackjack_xp}, Achievement XP: {achievement_xp}")
        total_xp = win_xp + blackjack_xp + achievement_xp
        print(f"Total XP: {total_xp}")
        
        update_player_xp(player, total_xp)

        # Deduct XP for losses (25 XP per loss)
        loss_xp_deduction = stats.loses * 25
        print(f"Losses: {stats.loses}, XP to deduct: {loss_xp_deduction}")
        deduct_player_xp(player, loss_xp_deduction)

        # Save updated stats
        print("-----------------------------\n")
        stats.save()

    return HttpResponse("XP processing complete.")  # No rendering of templates

