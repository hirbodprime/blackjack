from django.urls import path

from game import casino_views


urlpatterns = [
    path("", casino_views.casino_home, name="casino-home"),
    path("roulette/", casino_views.roulette_app, name="casino-roulette"),
    path("api/auth/", casino_views.telegram_auth, name="casino-auth"),
    path("api/table/", casino_views.table_state, name="casino-table-state"),
    path("api/bet/", casino_views.place_bet, name="casino-place-bet"),
    path("arcade/", casino_views.arcade_app, name="casino-arcade"),
    path("api/arcade/auth/", casino_views.arcade_auth, name="casino-arcade-auth"),
    path("api/arcade/state/", casino_views.arcade_state, name="casino-arcade-state"),
    path("api/arcade/ranks/", casino_views.arcade_ranks, name="casino-arcade-ranks"),
    path("api/arcade/<slug:action>/", casino_views.arcade_action, name="casino-arcade-action"),
]
