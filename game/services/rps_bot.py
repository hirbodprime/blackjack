"""A fair, deliberately imperfect RPS opponent with historical memory."""

import random

from django.db import transaction

from game.models import RPSBotProfile


CHOICES = ("rock", "paper", "scissors")
COUNTER = {"rock": "paper", "paper": "scissors", "scissors": "rock"}


@transaction.atomic
def choose_and_record_rps(player_id: int, current_choice: str) -> str:
    """Choose from prior behavior, then record the current move.

    The current move is intentionally not considered until after the bot has
    selected, preventing the Telegram command's visible argument from becoming
    hidden cheating.
    """
    profile, _ = RPSBotProfile.objects.select_for_update().get_or_create(player_id=player_id)
    history = list(profile.recent_choices)
    rng = random.SystemRandom()
    if len(history) >= 3 and rng.random() < 0.55:
        weights = {choice: 0.0 for choice in CHOICES}
        for index, choice in enumerate(history[-12:], start=1):
            weights[choice] += index
        predicted = max(CHOICES, key=weights.get)
        bot_choice = COUNTER[predicted]
    else:
        bot_choice = rng.choice(CHOICES)
    profile.recent_choices = (history + [current_choice])[-12:]
    profile.save(update_fields=("recent_choices", "updated_at"))
    return bot_choice
