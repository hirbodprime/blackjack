import asyncio
from datetime import (
    datetime,
)

from asgiref.sync import (
    sync_to_async,
)
from django.core.exceptions import (
    ObjectDoesNotExist,
)
from django.utils import (
    timezone,
)
from telegram import (
    Update,
)
from telegram.error import (
    RetryAfter,
    TimedOut,
)
from telegram.ext import (
    ContextTypes,
)

from bot_sections.core_and_menus import (
    update_daily_quest_progress,
)
from game.models import (
    Achievement,
    ChipTransaction,
    JoinGame,
    Player,
    PlayerAchievement,
    Stats,
)
from game.services.blackjack import (
    InsufficientChips,
)
from game.services.economy import (
    adjust_balance_async,
)
from game.services.operations import (
    get_bot_control_async,
)
from game.services.progression import (
    award_xp_async,
    deduct_xp_amount_async,
)


def xp_for_next_level(level: int) -> int:
    """
    Returns the XP required *to complete* the current `level` and bump to `level+1`.
    E.g. level=1 → need 50 XP, level=2 → need 100 XP, level=3 → need 150 XP, etc.
    """
    return level * 50

# Function to add XP, check for level-up, and give rewards
async def add_xp(player, amount, context):
    result = await award_xp_async(player, amount)
    for level, chips_reward in result.level_rewards:
        await asyncio.sleep(2)  # Non-blocking wait
        await context.bot.send_message(
            chat_id=player.id, 
            text=f"🎉 Congratulations! You've reached level {level}! You've been rewarded with {chips_reward} 💰 chips!"
        )

async def normalize_player_level_xp(player: Player):
    """
    If player.xp is already ≥ xp_for_next_level(player.level),
    then remove that threshold from xp, increment level, and repeat until
    xp < xp_for_next_level(level). This ensures the stored xp is always "in‐level."
    No chips or messages are awarded here; it's purely a data‐correction step.
    """
    changed = False

    # Keep leveling up as long as xp reaches the threshold for the current level
    while player.xp >= xp_for_next_level(player.level):
        threshold = xp_for_next_level(player.level)
        player.xp -= threshold
        player.level += 1
        changed = True

    # Just in case someone’s XP was negative, clamp it at 0 at level 1:
    if player.xp < 0 and player.level == 1:
        player.xp = 0
        changed = True

    # If anything changed, save
    if changed:
        await sync_to_async(player.save)()

async def safe_send_reaction(bot, chat_id, reaction, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=reaction)
            return  # Exit the loop if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking wait
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Rate limit exceeded. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Wait for the retry after time
            retries += 1
        except Exception as e:
            print(f"Failed to send message: {e}")
            break  # Exit on other exceptions

    print("Failed to send reaction after multiple retries.")

# Function to deduct XP and check for level-down
async def deduct_xp(player, amount, context):
    result = await deduct_xp_amount_async(player, amount)
    if result.level_changed:
        await context.bot.send_message(
            chat_id=player.id,
            text=f"⚠️ You lost {amount} XP and have been demoted to level {result.level}."
        )




# achievementssssssssssssssss ------------------------------------------------ 


async def unlock_achievement(player, condition_name, context):
    try:
        # Fetch the achievement by its condition name
        achievement = await sync_to_async(Achievement.objects.get)(condition=condition_name)
        
        # Check if the player already has this achievement
        already_unlocked = await sync_to_async(lambda: PlayerAchievement.objects.filter(player=player, achievement=achievement).exists())()

        if not already_unlocked:
            # Unlock the achievement for the player
            await sync_to_async(PlayerAchievement.objects.create)(
                player=player, achievement=achievement, unlocked_at=datetime.now()
            )

            # Notify the player
            await add_xp(player, 20, context)

            await context.bot.send_message(
                chat_id=player.id,
                text=f"🎉 Congratulations! You've unlocked the '{achievement.name}' achievement: {achievement.description}"
            )
        else:
            print(f"{player.name} already has the {achievement.name} achievement.")

    except ObjectDoesNotExist:
        print(f"Achievement with condition '{condition_name}' does not exist.")





async def my_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    chat_id = update.message.chat_id  # This is the chat where the command was used
    
    try:
        # Fetch the player from the database
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, you don't seem to have a player profile. Start a game first!")
        return

    # Fetch all achievements for the player
    player_achievements = await sync_to_async(list)(
        PlayerAchievement.objects.filter(player=player).select_related('achievement')
    )

    # Fetch total achievements available in the system
    total_achievements = await sync_to_async(Achievement.objects.count)()

    # If no achievements found
    if not player_achievements:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{user_name}, you haven't unlocked any achievements yet.\n\n0/{total_achievements} achievements unlocked.",
            parse_mode="Markdown"
        )
        return

    # Calculate the player's achievement progress
    unlocked_achievements_count = len(player_achievements)

    # Prepare the achievement list
    achievements_list = "\n".join([f"🏅 *{pa.achievement.name}*: {pa.achievement.description}" for pa in player_achievements])

    # Send the message with the achievements list and progress to the player's private chat
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎉 *{user_name}'s Achievements* 🎉\n\n"
             f"Progress: {unlocked_achievements_count}/{total_achievements} achievements unlocked.\n\n"
             f"{achievements_list}",
        parse_mode="Markdown"
    )




async def achievement_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Fetch all achievements from the database
    achievements = await sync_to_async(list)(Achievement.objects.all())

    # Check if there are any achievements available
    if not achievements:
        await update.message.reply_text("There are no achievements available yet.")
        return

    # Prepare the list of achievements with descriptions
    achievement_list = "\n".join([f"🏅 *{achievement.name}*: {achievement.description}" for achievement in achievements])

    # Send the achievements list to the player
    await context.bot.send_message(
        chat_id=user_id,  # Send to player's private chat
        text=f"🎉 *Achievements Info* 🎉\n\n"
             f"Here’s how you can unlock the achievements:\n\n{achievement_list}",
        parse_mode="Markdown"
    )

    # Inform the user in the group chat if the message is sent in a group
    if chat_id != user_id:
        await update.message.reply_text("📩 A message with the achievements info has been sent to your private chat.")




async def is_player_in_another_game(player_id: int, current_chat_id: int) -> bool:
    """
    Check if the player is already joined in another game in a different group.
    
    Args:
        player_id (int): The ID of the player.
        current_chat_id (int): The ID of the current group chat.

    Returns:
        bool: True if the player is in another game, False otherwise.
    """
    # Query to check if the player is active in another game in a different group
    is_in_another_game = await sync_to_async(
        JoinGame.objects.filter(
            player_id=player_id, 
            is_active=True
        ).exclude(game__chat_id=current_chat_id).exists
    )()
    
    return is_in_another_game
from telegram.error import TelegramError


async def check_player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Try to get the Player instance from the database
        player = await sync_to_async(Player.objects.get)(id=user_id)

        if player.is_frozen:
            reason = f"\nReason: {player.freeze_reason}" if player.freeze_reason else ""
            await update.message.reply_text(
                f"Your player account is temporarily frozen.{reason}"
            )
            return False

        control = await get_bot_control_async()
        if control.maintenance_mode and not player.admin:
            await update.message.reply_text(control.maintenance_message)
            return False

        try:
            # Test if the bot can send a chat action (e.g., typing) to check if the user has blocked the bot
            await context.bot.send_chat_action(chat_id=user_id, action="typing")

            # If no exception is raised, the bot can message the user
            return True

        except TelegramError as e:
            # Handle case where the bot is blocked or cannot message the user
            await update.message.reply_text(
                "It seems like I can't message you in private. Please make sure to start the bot in private chat first: "
                "t.me/blackjack_21_game_bot"
            )
            return False

    except ObjectDoesNotExist:
        # If no player exists, prompt the user to start the bot in private chat
        await update.message.reply_text(
            "It looks like you don't have a player profile. Please start the bot in private chat to create one. "
            "Use the following link: t.me/blackjack_21_game_bot"
        )
        return False  # Player does not exist

from datetime import timedelta


async def claim_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    # 1) Check if player exists
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)
    now = timezone.now()

    # 2) If never claimed or more than 24h passed, reset claim window
    if player.last_claimed_tokens is None or (now - player.last_claimed_tokens) >= timedelta(hours=24):
        player.tokens_claimed_today = 0
        player.last_claimed_tokens = now
        await sync_to_async(player.save)()

    # 3) If already claimed 3 times, calculate time remaining
    if player.tokens_claimed_today >= 3:
        next_window = player.last_claimed_tokens + timedelta(hours=24)
        remaining = next_window - now

        if remaining.total_seconds() <= 0:
            # Force reset in case of weird clock issue
            player.tokens_claimed_today = 0
            player.last_claimed_tokens = now
            await sync_to_async(player.save)()
        else:
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60

            time_str = f"{hours} hour{'s' if hours != 1 else ''}"
            if minutes > 0:
                time_str += f" and {minutes} minute{'s' if minutes != 1 else ''}"

            await update.message.reply_text(
                f"You’ve already claimed 3 times in the past 24 hours.\n"
                f"Try again in {time_str}."
            )
            return

    # 4) Allow claim
    player.tokens_claimed_today += 1
    await sync_to_async(player.save)()

    # 5) Send 🎯 and wait for result
    message = await context.bot.send_dice(chat_id=update.message.chat_id, emoji="🎯")
    await asyncio.sleep(3)

    # 6) Check if bullseye
    if message.dice.value == 6:
        await adjust_balance_async(
            player,
            200,
            category=ChipTransaction.Category.MINIGAME_PAYOUT,
            description="Free dart bullseye reward",
            reference_type="telegram_update",
            reference_id=update.update_id,
            idempotency_key=f"free-dart:{update.update_id}",
        )
        await update_daily_quest_progress(player, "minigames", "dart", 1, context)
        await update.message.reply_text(
            f"🎯 Bullseye! You've received 💰200 chips! You now have 💰{player.chips} chips."
        )
    else:
        await update.message.reply_text("🎯 You missed the bullseye! Better luck next time!")

    await sync_to_async(player.save)()


async def dart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.message.from_user
    user_id = user.id
    chat_id = update.message.chat_id

    # 1) Check player exists
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    # 2) Get bet amount or default to 50
    try:
        bet = int(context.args[0]) if context.args else 50
        if bet <= 0:
            raise ValueError()
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Invalid amount. Usage: `/dart 100`", parse_mode="Markdown")
        return

    if player.chips < bet:
        await update.message.reply_text(f"❌ Not enough chips! You only have {player.chips:,}.")
        return

    # 3) Deduct bet atomically and audit it
    try:
        await adjust_balance_async(
            player,
            -bet,
            category=ChipTransaction.Category.BET,
            description="Dart minigame bet",
            reference_type="telegram_update",
            reference_id=update.update_id,
            idempotency_key=f"dart-bet:{update.update_id}",
        )
    except InsufficientChips:
        await update.message.reply_text("❌ Your balance changed and there are no longer enough chips.")
        return

    # 4) Send dice
    message = await context.bot.send_dice(chat_id=chat_id, emoji="🎯")
    await asyncio.sleep(3)

    # 5) Check outcome
    if message.dice.value == 6:
        win_amount = bet * 2
        await adjust_balance_async(
            player,
            win_amount,
            category=ChipTransaction.Category.MINIGAME_PAYOUT,
            description="Dart bullseye payout",
            reference_type="telegram_update",
            reference_id=update.update_id,
            idempotency_key=f"dart-payout:{update.update_id}",
        )
        await update_daily_quest_progress(player, "minigames", "dart", 1, context)
        await update.message.reply_text(f"🎯 Bullseye! You win 💰{win_amount:,} chips! 🎉")
    else:
        await update.message.reply_text(f"😢 You missed the bullseye and lost 💸{bet:,} chips.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id   = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Fetch the Player & Stats objects for this user
        player = await sync_to_async(Player.objects.get)(id=user_id)
        stats  = await sync_to_async(Stats.objects.get)(player=player)

        # Normalize their xp/level before computing "xp to next"
        await normalize_player_level_xp(player)

        # Now player.level and player.xp are guaranteed to satisfy:
        #    player.xp < xp_for_next_level(player.level)

        xp    = player.xp
        level = player.level
        threshold = xp_for_next_level(level)  # how much XP needed *this* level

        xp_to_next_level = threshold - xp  # always > 0, unless xp==threshold (in which
                                           # case normalize would have bumped them already)

        message = (
            f"🎮 *Your Stats* 🎮\n\n"
            f"🏆 *Wins*: {stats.wins}\n"
            f"❌ *Losses*: {stats.loses}\n"
            f"💥 *Blackjacks*: {stats.how_many_21}\n"
            f"💪 *XP (this level)*: {xp}\n"
            f"📈 *Level*: {level}\n"
            f"🔜 *XP to next level*: {xp_to_next_level} XP\n"
        )
        await update.message.reply_text(message, parse_mode="Markdown")

    except ObjectDoesNotExist:
        # First‐time user: create Player & Stats, give 20 chips
        player = await sync_to_async(Player.objects.create)(
            id=user_id,
            name=user_name,
            chips=0,
            xp=0,
            level=1
        )
        await adjust_balance_async(
            player, 20,
            category=ChipTransaction.Category.DAILY_REWARD,
            description="Legacy stats signup balance",
            reference_type="player_signup",
            reference_id=player.id,
            idempotency_key=f"stats-signup:{player.id}",
        )
        stats  = await sync_to_async(Stats.objects.create)(
            wins=0, loses=0, how_many_21=0, player=player
        )

        message = (
            f"Welcome to Blackjack, {user_name}! You have been given 20 💰 chips to start.\n\n"
            f"🎮 *Your Stats* 🎮\n\n"
            f"🏆 *Wins*: {stats.wins}\n"
            f"❌ *Losses*: {stats.loses}\n"
            f"💥 *Blackjacks*: {stats.how_many_21}\n"
            f"💪 *XP (this level)*: 0\n"
            f"📈 *Level*: 1\n"
            f"🔜 *XP to next level*: 50 XP\n"
            f"\nKeep playing to earn XP and level up!"
        )
        await update.message.reply_text(message, parse_mode="Markdown")



# # Deck of cards
