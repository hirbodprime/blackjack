"""Atomic retention features: weekly missions, item market, and friend challenges."""

from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from game.models import (
    Achievement, ChipTransaction, FriendChallenge, ItemListing, Player,
    PlayerAchievement, PlayerItem, PlayerWeeklyMissionProgress, WeeklyMission,
)
from game.services.economy import InsufficientChips, adjust_balance
from game.services.progression import award_xp


class RetentionError(ValueError):
    pass


def _unlock(player, condition):
    achievement = Achievement.objects.filter(condition=condition).first()
    if achievement:
        _, created = PlayerAchievement.objects.get_or_create(
            player=player, achievement=achievement
        )
        if created:
            award_xp(player, 20)


def ensure_current_weekly_missions():
    """Create the small default weekly track once; admins can edit or disable it."""
    today = timezone.localdate()
    start = today - timedelta(days=today.weekday())
    templates = (
        ("blackjack", "join", "Join 15 blackjack games", 15, 120, 250),
        ("minigames", "dice", "Play dice 12 times", 12, 100, 200),
        ("race", "joinhorse", "Join 5 horse races", 5, 100, 200),
    )
    for quest_type, subtype, description, target, xp, chips in templates:
        WeeklyMission.objects.get_or_create(
            week_start=start, quest_type=quest_type, subtype=subtype,
            defaults={
                "description": description, "target": target,
                "reward_xp": xp, "reward_chips": chips, "available": True,
            },
        )
    return start


@transaction.atomic
def advance_weekly_missions(player_id, quest_type, subtype=None, amount=1):
    if amount <= 0:
        raise RetentionError("Progress must be positive")
    player = Player.objects.select_for_update().get(pk=player_id)
    start = ensure_current_weekly_missions()
    missions = WeeklyMission.objects.filter(
        available=True, week_start=start, quest_type=quest_type
    ).filter(Q(subtype=subtype) | Q(subtype__isnull=True) | Q(subtype=""))
    completed = []
    for mission in missions:
        progress, _ = PlayerWeeklyMissionProgress.objects.select_for_update().get_or_create(
            player=player, mission=mission
        )
        if progress.completed:
            continue
        progress.progress = min(mission.target, progress.progress + amount)
        if progress.progress >= mission.target:
            progress.completed = True
            progress.completed_at = timezone.now()
            award_xp(player, mission.reward_xp)
            if mission.reward_chips:
                adjust_balance(
                    player, mission.reward_chips,
                    category=ChipTransaction.Category.QUEST_REWARD,
                    description=f"Weekly mission: {mission.description}",
                    reference_type="weekly_mission", reference_id=mission.pk,
                    idempotency_key=f"weekly:{mission.pk}:player:{player.pk}",
                )
            completed.append(mission)
            _unlock(player, "weekly_warrior")
        progress.save(update_fields=("progress", "completed", "completed_at"))
    return completed


@transaction.atomic
def create_item_listing(seller_id, item_type, quantity, price):
    if quantity < 1 or price < 1:
        raise RetentionError("Quantity and price must be positive")
    item = PlayerItem.objects.select_for_update().get(player_id=seller_id, item_type=item_type)
    if item.quantity < quantity:
        raise RetentionError("Not enough items")
    item.quantity -= quantity
    item.save(update_fields=("quantity",))
    return ItemListing.objects.create(
        seller_id=seller_id, item_type=item_type, quantity=quantity, price=price
    )


@transaction.atomic
def cancel_item_listing(listing_id, seller_id):
    listing = ItemListing.objects.select_for_update().get(pk=listing_id, seller_id=seller_id)
    if not listing.active:
        raise RetentionError("Listing is no longer active")
    item, _ = PlayerItem.objects.select_for_update().get_or_create(
        player_id=seller_id, item_type=listing.item_type, defaults={"quantity": 0}
    )
    item.quantity += listing.quantity
    item.save(update_fields=("quantity",))
    listing.active = False
    listing.save(update_fields=("active",))
    return listing


@transaction.atomic
def buy_item_listing(listing_id, buyer_id):
    listing = ItemListing.objects.select_for_update().select_related("seller").get(pk=listing_id)
    if not listing.active:
        raise RetentionError("Listing is no longer active")
    if listing.seller_id == buyer_id:
        raise RetentionError("You cannot buy your own listing")
    buyer = Player.objects.select_for_update().get(pk=buyer_id)
    seller = Player.objects.select_for_update().get(pk=listing.seller_id)
    adjust_balance(
        buyer, -listing.price, category=ChipTransaction.Category.ITEM_PURCHASE,
        description=f"Marketplace purchase #{listing.pk}", reference_type="item_listing",
        reference_id=listing.pk, idempotency_key=f"market:{listing.pk}:buyer",
    )
    adjust_balance(
        seller, listing.price, category=ChipTransaction.Category.TRANSFER,
        description=f"Marketplace sale #{listing.pk}", reference_type="item_listing",
        reference_id=listing.pk, idempotency_key=f"market:{listing.pk}:seller",
    )
    item, _ = PlayerItem.objects.select_for_update().get_or_create(
        player=buyer, item_type=listing.item_type, defaults={"quantity": 0}
    )
    item.quantity += listing.quantity
    item.save(update_fields=("quantity",))
    listing.active = False
    listing.buyer = buyer
    listing.sold_at = timezone.now()
    listing.save(update_fields=("active", "buyer", "sold_at"))
    _unlock(seller, "first_market_sale")
    _unlock(buyer, "first_market_purchase")
    return listing


@transaction.atomic
def create_challenge(challenger_id, opponent_id, mode, stake):
    if challenger_id == opponent_id or stake < 1:
        raise RetentionError("Choose another player and a positive stake")
    if mode not in FriendChallenge.Mode.values:
        raise RetentionError("Unsupported challenge mode")
    if FriendChallenge.objects.filter(
        challenger_id__in=(challenger_id, opponent_id), opponent_id__in=(challenger_id, opponent_id),
        status__in=(FriendChallenge.Status.PENDING, FriendChallenge.Status.ACTIVE),
    ).exists():
        raise RetentionError("These players already have an open challenge")
    challenger = Player.objects.select_for_update().get(pk=challenger_id)
    if challenger.chips < stake:
        raise InsufficientChips
    return FriendChallenge.objects.create(
        challenger=challenger, opponent_id=opponent_id, mode=mode, stake=stake
    )


@transaction.atomic
def accept_challenge(challenge_id, opponent_id):
    challenge = FriendChallenge.objects.select_for_update().get(pk=challenge_id, opponent_id=opponent_id)
    if challenge.status != FriendChallenge.Status.PENDING:
        raise RetentionError("Challenge is no longer pending")
    players = {p.pk: p for p in Player.objects.select_for_update().filter(
        pk__in=(challenge.challenger_id, challenge.opponent_id)
    )}
    for role, player_id in (("challenger", challenge.challenger_id), ("opponent", challenge.opponent_id)):
        adjust_balance(
            players[player_id], -challenge.stake, category=ChipTransaction.Category.BET,
            description=f"Friend challenge #{challenge.pk} stake", reference_type="friend_challenge",
            reference_id=challenge.pk, idempotency_key=f"challenge:{challenge.pk}:{role}:stake",
        )
    challenge.status = FriendChallenge.Status.ACTIVE
    challenge.save(update_fields=("status", "updated_at"))
    return challenge


@transaction.atomic
def decline_challenge(challenge_id, opponent_id):
    challenge = FriendChallenge.objects.select_for_update().get(pk=challenge_id, opponent_id=opponent_id)
    if challenge.status != FriendChallenge.Status.PENDING:
        raise RetentionError("Challenge is no longer pending")
    challenge.status = FriendChallenge.Status.DECLINED
    challenge.save(update_fields=("status", "updated_at"))
    return challenge


@transaction.atomic
def record_challenge_round(challenge_id, actor_id, winner_id, state):
    challenge = FriendChallenge.objects.select_for_update().get(pk=challenge_id)
    if challenge.status != FriendChallenge.Status.ACTIVE or actor_id not in (
        challenge.challenger_id, challenge.opponent_id
    ):
        raise RetentionError("Challenge is not active")
    if winner_id == challenge.challenger_id:
        challenge.challenger_score += 1
    elif winner_id == challenge.opponent_id:
        challenge.opponent_score += 1
    challenge.round_state = state
    if max(challenge.challenger_score, challenge.opponent_score) >= 2:
        challenge.status = FriendChallenge.Status.COMPLETED
        challenge.winner_id = winner_id
        adjust_balance(
            winner_id, challenge.stake * 2, category=ChipTransaction.Category.MINIGAME_PAYOUT,
            description=f"Friend challenge #{challenge.pk} winnings", reference_type="friend_challenge",
            reference_id=challenge.pk, idempotency_key=f"challenge:{challenge.pk}:payout",
        )
        _unlock(Player.objects.select_for_update().get(pk=winner_id), "first_challenge_win")
    else:
        challenge.round_number += 1
    challenge.save()
    return challenge


advance_weekly_missions_async = sync_to_async(advance_weekly_missions, thread_sensitive=True)
create_item_listing_async = sync_to_async(create_item_listing, thread_sensitive=True)
cancel_item_listing_async = sync_to_async(cancel_item_listing, thread_sensitive=True)
buy_item_listing_async = sync_to_async(buy_item_listing, thread_sensitive=True)
create_challenge_async = sync_to_async(create_challenge, thread_sensitive=True)
accept_challenge_async = sync_to_async(accept_challenge, thread_sensitive=True)
decline_challenge_async = sync_to_async(decline_challenge, thread_sensitive=True)
record_challenge_round_async = sync_to_async(record_challenge_round, thread_sensitive=True)
