from django.contrib import admin
from .models import Player, Stats, Game, JoinGame, Dealer, RoundWinner, Group, NextGameNotification, Achievement, PlayerAchievement









# Customizing the admin display for the Achievement model
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'condition', 'icon')
    search_fields = ('name', 'condition')
    list_filter = ('condition',)
    ordering = ['name']


# Inline admin for PlayerAchievements (to show achievements within the Player admin)
class PlayerAchievementInline(admin.TabularInline):
    model = PlayerAchievement
    extra = 1


# Customizing the admin display for the Player model
@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'chips', 'games', 'admin')
    search_fields = ('name',)
    list_filter = ('admin',)
    inlines = [PlayerAchievementInline]


# Customizing the admin display for the Game model
class JoinGameInline(admin.TabularInline):
    model = JoinGame
    extra = 0


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('chat_id', 'betting', 'started', 'ended', 'current_round', 'total_rounds')
    list_filter = ('betting', 'started', 'ended')
    search_fields = ('chat_id',)
    ordering = ['-current_round']
    fieldsets = (
        (None, {
            'fields': ('chat_id', 'betting', 'started', 'ended', 'total_rounds', 'pot', 'bet_amount','bet_phase')
        }),
        ('Round Details', {
            'fields': ('current_round', 'dealer_hand', 'turn_order')
        }),
        ('Time Management', {
            'fields': ('join_start_time', 'join_time')
        }),
    )
    inlines = [JoinGameInline]


# Customizing the admin display for the Group model
@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('group_name', 'group_chat_id', 'games', 'vip', 'real_money')
    search_fields = ('group_chat_id', 'group_name')
    list_filter = ('vip', 'real_money')


# Customizing the admin display for the RoundWinner model
@admin.register(RoundWinner)
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ('game', 'round_number', 'get_winner', 'is_dealer', 'rounds_ended')
    list_filter = ('game', 'is_dealer', 'round_number', 'rounds_ended')
    search_fields = ('game__chat_id', 'winner__name')

    def get_winner(self, obj):
        if obj.is_dealer:
            return "Dealer"
        elif obj.winner:
            return obj.winner.name
        return "No Winner"
    
    get_winner.short_description = 'Winner'


# Customizing the admin display for the Dealer model
@admin.register(Dealer)
class DealerAdmin(admin.ModelAdmin):
    list_display = ('chips', 'wins', 'loses', 'blackjack_count')
    search_fields = ('wins', 'loses', 'blackjack_count')
    list_filter = ('wins', 'loses', 'blackjack_count')
    ordering = ['-wins']


# Customizing the admin display for the Stats model
@admin.register(Stats)
class StatsAdmin(admin.ModelAdmin):
    list_display = ('get_player_name', 'wins', 'loses', 'how_many_21')
    search_fields = ('player__name', 'wins', 'loses')
    list_filter = ('wins', 'loses')

    # Custom method to display player's name
    def get_player_name(self, obj):
        return obj.player.name

    get_player_name.short_description = 'Player'


# Customizing the admin display for the PlayerAchievement model
@admin.register(PlayerAchievement)
class PlayerAchievementAdmin(admin.ModelAdmin):
    list_display = ('get_player_name', 'achievement', 'unlocked_at')
    search_fields = ('player__name', 'achievement__name')
    list_filter = ('unlocked_at',)
    ordering = ['-unlocked_at']

    # Custom method to display player's name
    def get_player_name(self, obj):
        return obj.player.name

    get_player_name.short_description = 'Player'


# Customizing the admin display for the NextGameNotification model
@admin.register(NextGameNotification)
class NextGameNotificationAdmin(admin.ModelAdmin):
    list_display = ('user_id', 'chat_id')
    search_fields = ('user_id', 'chat_id')
    list_filter = ('chat_id',)
    ordering = ['-user_id']


# Registering JoinGame separately
@admin.register(JoinGame)
class JoinGameAdmin(admin.ModelAdmin):
    list_display = ('get_player_name', 'game', 'is_active')
    search_fields = ('player__name', 'game__chat_id')
    list_filter = ('is_active',)
    ordering = ['-is_active']

    # Custom method to display player's name
    def get_player_name(self, obj):
        return obj.player.name

    get_player_name.short_description = 'Player'
