from django.urls import path

from game import casino_views


urlpatterns = [
    path("", casino_views.roulette_app, name="casino-roulette"),
    path("api/auth/", casino_views.telegram_auth, name="casino-auth"),
    path("api/table/", casino_views.table_state, name="casino-table-state"),
    path("api/bet/", casino_views.place_bet, name="casino-place-bet"),
]
