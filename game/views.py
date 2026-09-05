from django.shortcuts import get_object_or_404
from .models import Player, Stats, PlayerAchievement
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from .services.progression import award_xp, deduct_xp_amount, xp_for_level

def calculate_xp_for_next_level(level):
    return xp_for_level(level)


def check_level_up(player):
    return award_xp(player, 0).level_changed

def update_player_xp(player, amount):
    return award_xp(player, amount).level_changed

def deduct_player_xp(player, amount):
    """
    Function to deduct XP and handle leveling down if necessary.
    """
    deduct_xp_amount(player, amount)

# Function to reset XP for all players at the start
def reset_all_player_xp():
    players = Player.objects.all()
    for player in players:
        player.xp = 0
        player.level = 1
        player.save()

# Function to process all player stats and update XP accordingly
@staff_member_required
@require_POST
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


        # Deduct XP for losses (25 XP per loss)
        loss_xp_deduction = stats.loses * 25
        deduct_player_xp(player, loss_xp_deduction)

        # Save updated stats
        stats.save()

    return HttpResponse("XP processing complete.")  # No rendering of templates
