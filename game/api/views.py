from rest_framework import viewsets
from game.models import Player, Game, Group, Dealer, Stats
from .serializers import PlayerSerializer, GameSerializer, GroupSerializer, DealerSerializer, StatsSerializer

class PlayerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Player.objects.all()
    serializer_class = PlayerSerializer

class GameViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Game.objects.all()
    serializer_class = GameSerializer

class GroupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Group.objects.all()
    serializer_class = GroupSerializer

class DealerViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dealer.objects.all()
    serializer_class = DealerSerializer

class StatsViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Stats.objects.all()
    serializer_class = StatsSerializer
