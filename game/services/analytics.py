"""Read-only economy analytics for operators."""

from dataclasses import asdict, dataclass
from statistics import median

from django.conf import settings
from django.db.models import Case, CharField, Count, F, Q, Sum, When

from game.models import ChipTransaction, Dealer, Player, PlayerActiveItem, PlayerItem


@dataclass(frozen=True)
class EconomyAnalytics:
    median_balance: float
    largest_wins: tuple[dict, ...]
    largest_losses: tuple[dict, ...]
    game_flows: tuple[dict, ...]
    item_inventory: tuple[dict, ...]
    active_items: int
    dealer_win_rate: float | None


def build_economy_analytics(*, limit: int = 5) -> EconomyAnalytics:
    balances = list(Player.objects.order_by("chips").values_list("chips", flat=True))
    largest_wins = tuple(
        ChipTransaction.objects.filter(amount__gt=0)
        .select_related("player")
        .order_by("-amount")
        .values("player_id", "player__name", "amount", "category", "created_at")[:limit]
    )
    largest_losses = tuple(
        ChipTransaction.objects.filter(amount__lt=0)
        .select_related("player")
        .order_by("amount")
        .values("player_id", "player__name", "amount", "category", "created_at")[:limit]
    )

    game_flows = []
    for row in (
        ChipTransaction.objects.exclude(reference_type="")
        .annotate(
            game_type=Case(
                When(reference_type="minigame", then=F("reference_id")),
                default=F("reference_type"),
                output_field=CharField(),
            )
        )
        .values("game_type")
        .annotate(
            net_player_change=Sum("amount"),
            transactions=Count("id"),
            stakes=Sum("amount", filter=Q(category=ChipTransaction.Category.BET)),
            payouts=Sum("amount", filter=Q(amount__gt=0)),
        )
        .order_by("game_type")
    ):
        row["casino_profit"] = -(row["net_player_change"] or 0)
        row["actual_payout_rate"] = (
            round((row["payouts"] or 0) * 100 / abs(row["stakes"]), 2)
            if row["stakes"]
            else None
        )
        row["expected_payout_rate"] = settings.EXPECTED_PAYOUT_RATES.get(
            row["game_type"]
        )
        row["payout_variance"] = (
            round(row["actual_payout_rate"] - row["expected_payout_rate"], 2)
            if row["actual_payout_rate"] is not None
            and row["expected_payout_rate"] is not None
            else None
        )
        game_flows.append(row)

    item_inventory = tuple(
        PlayerItem.objects.values("item_type")
        .annotate(quantity=Sum("quantity"), owners=Count("player", distinct=True))
        .order_by("item_type")
    )
    dealer = Dealer.objects.first()
    decided_games = (dealer.wins + dealer.loses) if dealer else 0
    dealer_win_rate = (
        round(dealer.wins * 100 / decided_games, 2) if decided_games else None
    )
    return EconomyAnalytics(
        median_balance=float(median(balances)) if balances else 0,
        largest_wins=largest_wins,
        largest_losses=largest_losses,
        game_flows=tuple(game_flows),
        item_inventory=item_inventory,
        active_items=PlayerActiveItem.objects.filter(is_active=True).count(),
        dealer_win_rate=dealer_win_rate,
    )


def economy_analytics_context(*, limit: int = 5) -> dict:
    return asdict(build_economy_analytics(limit=limit))
