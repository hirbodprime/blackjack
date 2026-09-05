"""Telegram UI for retention features."""

import random

from asgiref.sync import sync_to_async
from django.db.models import Count, Sum
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from game.models import (
    Achievement, ChipTransaction, FriendChallenge, HorseRaceWin, ITEM_TYPE_CHOICES, ItemListing,
    Player, PlayerAchievement, PlayerWeeklyMissionProgress, Stats, UserSettings,
    WeeklyMission,
)
from game.services.economy import InsufficientChips
from game.services.language import language_for_update
from game.services.retention import (
    RetentionError, accept_challenge_async, buy_item_listing_async,
    cancel_item_listing_async, create_challenge_async, create_item_listing_async,
    decline_challenge_async, ensure_current_weekly_missions,
    record_challenge_round_async,
)


def _notifications_keyboard(settings, language=None):
    language = language or settings.language
    fields = (
        ("notify_classic_blackjack_start", "Blackjack", "بلک‌جک"),
        ("notify_high_roller_blackjack_start", "High roller", "شرط بالا"),
        ("notify_race_start", "Races", "مسابقه اسب"),
        ("notify_tournaments", "Tournaments", "تورنمنت‌ها"),
        ("notify_quests", "Quests", "مأموریت‌ها"),
        ("notify_marketplace", "Marketplace", "بازار"),
        ("notify_new_events", "Events", "رویدادها"),
    )
    rows = [[InlineKeyboardButton(
        f"{'✅' if getattr(settings, field) else '❌'} {fa_label if language == 'fa' else label}",
        callback_data=f"retention:notify:{field}",
    )] for field, label, fa_label in fields]
    rows.append([InlineKeyboardButton(
        "🏠 منوی اصلی" if language == "fa" else "🏠 Main menu",
        callback_data="play:main",
    )])
    return InlineKeyboardMarkup(rows)


async def notifications_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        player = await Player.objects.aget(pk=update.effective_user.id)
    except Player.DoesNotExist:
        await update.effective_message.reply_text("Start the bot first with /start.")
        return
    settings, _ = await UserSettings.objects.aget_or_create(player=player)
    language = await language_for_update(update)
    await update.effective_message.reply_text(
        "🔔 مرکز اعلان‌ها\n\nبرای روشن یا خاموش کردن هر بخش روی آن بزنید."
        if language == "fa" else
        "🔔 Notification center\n\nTap a category to turn it on or off.",
        reply_markup=_notifications_keyboard(settings, language),
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = await build_profile_text(
            update.effective_user.id, await language_for_update(update)
        )
    except Player.DoesNotExist:
        text = "Start the bot first with /start."
    await update.effective_message.reply_text(text)


async def build_profile_text(user_id: int, language: str | None = None) -> str:

    def build():
        player = Player.objects.get(pk=user_id)
        stats, _ = Stats.objects.get_or_create(player=player)
        achievements = PlayerAchievement.objects.filter(player=player).count()
        total_achievements = Achievement.objects.count()
        horse_wins = HorseRaceWin.objects.filter(user=player).count()
        recent = list(player.chip_transactions.values("category", "amount", "created_at")[:5])
        favorite = (player.chip_transactions.exclude(category__in=(
            ChipTransaction.Category.ADMIN_ADJUSTMENT, ChipTransaction.Category.TRANSFER,
        )).values("category").annotate(total=Count("id")).order_by("-total").first())
        wagered = abs(player.chip_transactions.filter(
            category=ChipTransaction.Category.BET
        ).aggregate(total=Sum("amount"))["total"] or 0)
        return player, stats, achievements, total_achievements, horse_wins, recent, favorite, wagered

    player, stats, unlocked, total, horse_wins, recent, favorite, wagered = await sync_to_async(build, thread_sensitive=True)()
    settings, _ = await UserSettings.objects.aget_or_create(player=player)
    played = stats.wins + stats.loses
    rate = (stats.wins / played * 100) if played else 0
    activity = "\n".join(
        f"• {row['amount']:+,} — {row['category'].replace('_', ' ')}"
        for row in recent
    ) or ("• هنوز فعالیتی ثبت نشده" if settings.language == "fa" else "• No recorded activity yet")
    language = language or settings.language
    if language == "fa":
        return (
            f"👤 {player.name}\nسطح {player.level} • {player.xp} XP • {player.chips:,} چیپ\n\n"
            f"🏆 {stats.wins} برد / {stats.loses} باخت (نرخ برد {rate:.1f}٪)\n"
            f"🃏 {stats.how_many_21} بلک‌جک • 🐎 {horse_wins} برد مسابقه\n"
            f"🏅 {unlocked}/{total} دستاورد\n"
            f"🎮 فعالیت محبوب: {(favorite or {}).get('category', 'اطلاعات کافی نیست').replace('_', ' ')}\n\n"
            f"گزارش بازی مسئولانه\nمجموع شرط‌های ثبت‌شده: {wagered:,} چیپ\n"
            f"وام باقی‌مانده: {player.loan:,} چیپ\n\nفعالیت اخیر\n{activity}"
        )
    return (
        f"👤 {player.name}\n"
        f"Level {player.level} • {player.xp} XP • {player.chips:,} chips\n\n"
        f"🏆 {stats.wins} wins / {stats.loses} losses ({rate:.1f}% win rate)\n"
        f"🃏 {stats.how_many_21} blackjacks • 🐎 {horse_wins} race wins\n"
        f"🏅 {unlocked}/{total} achievements\n"
        f"🎮 Favorite activity: {(favorite or {}).get('category', 'Not enough data').replace('_', ' ')}\n\n"
        f"Responsible-play snapshot\nTotal recorded stakes: {wagered:,} chips\n"
        f"Outstanding loan: {player.loan:,} chips\n\nRecent activity\n{activity}"
    )


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = await build_weekly_text(
            update.effective_user.id, await language_for_update(update)
        )
    except Player.DoesNotExist:
        text = "Start the bot first with /start."
    await update.effective_message.reply_text(text)


async def build_weekly_text(user_id: int, language: str | None = None) -> str:

    def rows():
        start = ensure_current_weekly_missions()
        missions = list(WeeklyMission.objects.filter(
            available=True, week_start=start
        ).order_by("id")[:10])
        progress = {p.mission_id: p for p in PlayerWeeklyMissionProgress.objects.filter(
            player_id=user_id, mission__in=missions
        )}
        return missions, progress

    player = await Player.objects.aget(pk=user_id)
    settings, _ = await UserSettings.objects.aget_or_create(player=player)
    language = language or settings.language
    missions, progress = await sync_to_async(rows, thread_sensitive=True)()
    if not missions:
        return "فعلاً مأموریت هفتگی فعالی وجود ندارد." if language == "fa" else "No weekly missions are active right now."
    lines = ["📅 مأموریت‌های هفتگی" if language == "fa" else "📅 Weekly missions"]
    for mission in missions:
        current = progress.get(mission.pk)
        value = current.progress if current else 0
        mark = "✅" if current and current.completed else "▫️"
        reward_word = "چیپ" if language == "fa" else "chips"
        lines.append(f"{mark} {mission.description}: {value}/{mission.target} — {mission.reward_xp} XP, {mission.reward_chips} {reward_word}")
    return "\n".join(lines)


async def marketplace_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, keyboard = await build_marketplace_view(
        update.effective_user.id, await language_for_update(update)
    )
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def build_marketplace_view(user_id: int, language: str | None = None):
    listings = await sync_to_async(list)(
        ItemListing.objects.filter(active=True).select_related("seller").order_by("listed_at")[:10]
    )
    settings = await UserSettings.objects.filter(player_id=user_id).afirst()
    language = language or (settings.language if settings else "en")
    lines = ["🛒 بازار آیتم‌ها" if language == "fa" else "🛒 Item marketplace"]
    lines.extend(
        f"#{x.pk} • {x.quantity}× {x.get_item_type_display()} • {x.price:,} chips • {x.seller.name}"
        for x in listings
    )
    if not listings:
        lines.append("فهرست فعالی وجود ندارد." if language == "fa" else "No active listings.")
    lines.append("\nآیتم‌های قابل معامله:" if language == "fa" else "\nTradable items:")
    descriptions = {
        "double_chip_potion": ("Doubles an eligible blackjack payout, subject to its cap", "پرداخت مجاز بلک‌جک را تا سقف تعیین‌شده دو برابر می‌کند"),
        "triple_chip_potion": ("Triples an eligible blackjack payout, subject to its cap", "پرداخت مجاز بلک‌جک را تا سقف تعیین‌شده سه برابر می‌کند"),
        "10x_chip_potion": ("Boosts an eligible blackjack payout up to 10×, with a safety cap", "پرداخت مجاز بلک‌جک را تا 10 برابر و با سقف امنیتی افزایش می‌دهد"),
        "xp_booster_500": ("Grants 500 XP when consumed", "با مصرف 500 XP می‌دهد"),
        "xp_booster_2000": ("Grants 2,000 XP when consumed", "با مصرف 2,000 XP می‌دهد"),
        "xp_booster_15000": ("Grants 15,000 XP when consumed", "با مصرف 15,000 XP می‌دهد"),
        "xp_booster_50000": ("Grants 50,000 XP when consumed", "با مصرف 50,000 XP می‌دهد"),
        "insurance_pass": ("Provides blackjack insurance protection", "محافظت بیمه در بلک‌جک"),
        "first_hand_20_pass": ("Applies the special first-hand 20 effect", "افکت ویژه دست اول 20"),
        "first_hand_11_potion": ("Applies the special first-hand 11 effect", "افکت ویژه دست اول 11"),
    }
    for code, label in ITEM_TYPE_CHOICES:
        description = descriptions[code][1 if language == "fa" else 0]
        lines.append(f"• {label} [{code}] — {description}")
    lines.append(
        "\nبرای فروش: /sellitem نوع تعداد قیمت_کل\nمثال: /sellitem insurance_pass 1 5000"
        if language == "fa" else
        "\nTo sell: /sellitem type quantity total_price\nExample: /sellitem insurance_pass 1 5000"
    )
    buttons = []
    for listing in listings[:10]:
        if listing.seller_id == user_id:
            label = f"❌ #{listing.pk} " + ("لغو آگهی" if language == "fa" else "Cancel mine")
            data = f"retention:market:cancel:{listing.pk}"
        else:
            label = f"🛒 #{listing.pk} • {listing.price:,}"
            data = f"retention:market:buy:{listing.pk}"
        buttons.append([InlineKeyboardButton(label, callback_data=data)])
    buttons.append([InlineKeyboardButton("🏠 منوی اصلی" if language == "fa" else "🏠 Main menu", callback_data="play:main")])
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def sell_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3:
        await update.effective_message.reply_text("Usage: /sellitem item_type quantity total_price")
        return
    try:
        listing = await create_item_listing_async(
            update.effective_user.id, context.args[0], int(context.args[1]), int(context.args[2])
        )
        await update.effective_message.reply_text(f"Listing #{listing.pk} created. Items are safely held until sale or cancellation.")
    except (ValueError, Player.DoesNotExist, RetentionError) as exc:
        await update.effective_message.reply_text(f"Could not create listing: {exc}")


async def buy_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        listing = await buy_item_listing_async(int(context.args[0]), update.effective_user.id)
        await update.effective_message.reply_text(f"Purchased listing #{listing.pk}.")
    except (IndexError, ValueError, ItemListing.DoesNotExist, Player.DoesNotExist, RetentionError, InsufficientChips) as exc:
        await update.effective_message.reply_text(f"Could not buy listing: {exc or 'insufficient chips'}")


async def cancel_listing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        listing = await cancel_item_listing_async(int(context.args[0]), update.effective_user.id)
        await update.effective_message.reply_text(f"Listing #{listing.pk} cancelled and its items returned.")
    except (IndexError, ValueError, ItemListing.DoesNotExist, RetentionError) as exc:
        await update.effective_message.reply_text(f"Could not cancel listing: {exc}")


async def challenge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = update.effective_message.reply_to_message
    if not reply or len(context.args) != 2:
        await update.effective_message.reply_text("Reply to a player's message with /challenge blackjack|dice|rps stake")
        return
    try:
        challenge = await create_challenge_async(
            update.effective_user.id, reply.from_user.id, context.args[0].lower(), int(context.args[1])
        )
    except (ValueError, Player.DoesNotExist, RetentionError, InsufficientChips) as exc:
        await update.effective_message.reply_text(f"Could not create challenge: {exc or 'insufficient chips'}")
        return
    await update.effective_message.reply_text(
        f"⚔️ {update.effective_user.first_name} challenges {reply.from_user.first_name} to best-of-three {challenge.mode} for {challenge.stake:,} chips each.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Accept", callback_data=f"retention:challenge:accept:{challenge.pk}"),
            InlineKeyboardButton("Decline", callback_data=f"retention:challenge:decline:{challenge.pk}"),
        ]]),
    )


def _blackjack_score():
    cards = [random.randint(1, 10), random.randint(1, 10)]
    total = sum(11 if card == 1 else card for card in cards)
    while total > 21 and 1 in cards:
        total -= 10
        cards.remove(1)
    return total, cards


async def retention_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":")
    await query.answer()
    if parts[1] == "notify":
        allowed = {
            "notify_classic_blackjack_start", "notify_high_roller_blackjack_start",
            "notify_race_start", "notify_tournaments", "notify_quests",
            "notify_marketplace", "notify_new_events",
        }
        field = parts[2]
        if field not in allowed:
            return
        settings, _ = await UserSettings.objects.aget_or_create(player_id=query.from_user.id)
        setattr(settings, field, not getattr(settings, field))
        await settings.asave(update_fields=(field,))
        language = await language_for_update(update)
        await query.edit_message_reply_markup(reply_markup=_notifications_keyboard(settings, language))
        return
    if parts[1] == "market":
        action, listing_id = parts[2], int(parts[3])
        try:
            if action == "buy":
                await buy_item_listing_async(listing_id, query.from_user.id)
            elif action == "cancel":
                await cancel_item_listing_async(listing_id, query.from_user.id)
            text, keyboard = await build_marketplace_view(
                query.from_user.id, await language_for_update(update)
            )
            await query.edit_message_text(text, reply_markup=keyboard)
        except (ItemListing.DoesNotExist, Player.DoesNotExist, RetentionError, InsufficientChips) as exc:
            await query.answer(str(exc) or "Not enough chips", show_alert=True)
        return
    action, challenge_id = parts[2], int(parts[3])
    try:
        if action == "accept":
            challenge = await accept_challenge_async(challenge_id, query.from_user.id)
            await query.edit_message_text(
                f"Challenge accepted: {challenge.challenger_score}–{challenge.opponent_score}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Play round", callback_data=f"retention:challenge:play:{challenge.pk}")
                ]]),
            )
        elif action == "decline":
            await decline_challenge_async(challenge_id, query.from_user.id)
            await query.edit_message_text("Challenge declined.")
        elif action == "play":
            challenge = await FriendChallenge.objects.aget(pk=challenge_id)
            if query.from_user.id not in (challenge.challenger_id, challenge.opponent_id):
                raise RetentionError("Only the two players can play")
            if challenge.mode == FriendChallenge.Mode.DICE:
                a, b = random.randint(1, 6), random.randint(1, 6)
                label = f"Dice: {a}–{b}"
            elif challenge.mode == FriendChallenge.Mode.BLACKJACK:
                (a, ac), (b, bc) = _blackjack_score(), _blackjack_score()
                label = f"Blackjack: {ac}={a} vs {bc}={b}"
            else:
                choices = ("rock", "paper", "scissors")
                ai, bi = random.randrange(3), random.randrange(3)
                a, b = ai, bi
                label = f"RPS: {choices[ai]} vs {choices[bi]}"
            winner_id = None
            if a != b:
                if challenge.mode == FriendChallenge.Mode.RPS:
                    challenger_wins = (a - b) % 3 == 1
                else:
                    challenger_wins = a > b
                winner_id = challenge.challenger_id if challenger_wins else challenge.opponent_id
            challenge = await record_challenge_round_async(challenge.pk, query.from_user.id, winner_id, {"result": label})
            text = f"{label}\nScore: {challenge.challenger_score}–{challenge.opponent_score}"
            keyboard = None
            if challenge.status == FriendChallenge.Status.COMPLETED:
                winner_name = await Player.objects.filter(pk=challenge.winner_id).values_list("name", flat=True).aget()
                text += f"\n🏆 Winner: {winner_name} • prize {challenge.stake * 2:,} chips"
            else:
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Play next round", callback_data=f"retention:challenge:play:{challenge.pk}")
                ]])
            await query.edit_message_text(text, reply_markup=keyboard)
    except (FriendChallenge.DoesNotExist, Player.DoesNotExist, RetentionError, InsufficientChips) as exc:
        await query.answer(str(exc) or "Not enough chips", show_alert=True)
