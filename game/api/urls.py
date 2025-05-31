from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PlayerViewSet, GameViewSet, GroupViewSet, DealerViewSet, StatsViewSet

router = DefaultRouter()
router.register(r'players', PlayerViewSet)
router.register(r'games', GameViewSet)
router.register(r'groups', GroupViewSet)
router.register(r'dealers', DealerViewSet)
router.register(r'stats', StatsViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
