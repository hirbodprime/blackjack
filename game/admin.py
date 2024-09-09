from django.contrib import admin
from .models import Player, Stats, Game, JoinGame,Dealer,RoundWinner
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ('game', 'round_number', 'get_winner', 'is_dealer')
    list_filter = ('game', 'is_dealer', 'round_number')
    search_fields = ('game__chat_id', 'winner__name')

    # Custom method to display winner's name (handle null cases)
    def get_winner(self, obj):
        if obj.is_dealer:
            return "Dealer"
        elif obj.winner:
            return obj.winner.name
        return "No Winner"
    
    get_winner.short_description = 'Winner'

# Register the model in the admin
admin.site.register(RoundWinner, RoundWinnerAdmin)

@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ('chips', 'wins', 'loses', 'blackjack_count')  # Fields to display in the admin list view
    search_fields = ('wins', 'loses', 'blackjack_count')  # Fields to search in the admin interface
    # list_editable = ('chips',)  # Allow chips to be editable directly in the list view

    # Optional: Adding filters for the number of wins, loses, and Blackjack count
    list_filter = ('wins', 'loses', 'blackjack_count')

# Register the Stats model
@admin.register(Stats)
class StatsAdmin(admin.ModelAdmin):
    list_display = ('wins', 'loses', 'how_many_21')  # Display these fields in the list view
    search_fields = ('wins', 'loses')  # Add search by wins and loses


# Register the Player model
@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name',)  # Display player's name and stats in the list view
    search_fields = ('name',)  # Add search by player name


# Register the Game model
@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('chat_id', 'betting', 'started', 'ended')  # Display these fields in the list view
    list_filter = ('betting', 'started', 'ended')  # Add filter options for the boolean fields
    search_fields = ('chat_id',)  # Add search by chat_id


# Register the JoinGame model
@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = ('player', 'game')  # Display player and game fields in the list view
    search_fields = ('player__name', 'game__chat_id')  # Add search by player name and game chat_id
