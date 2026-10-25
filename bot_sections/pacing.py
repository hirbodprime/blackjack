"""Pauses between blackjack table messages, in seconds.

They give players time to read each announcement. Telegram allows roughly
20 messages per minute in a group, so keep them above zero.
"""

SHORT_BEAT = 0.5
BEAT = 1.0
DRAMATIC_BEAT = 1.5

# Minimum time between one player's /hit or /stand actions; it ends as the
# next "hit or stand" prompt arrives.
ACTION_COOLDOWN_SECONDS = DRAMATIC_BEAT
