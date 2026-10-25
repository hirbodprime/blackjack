import asyncio
import random
from datetime import (
    timedelta,
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
    MessageHandler,
    filters,
)
from telegram.helpers import (
    escape_markdown,
)

from bot_sections.pacing import ACTION_COOLDOWN_SECONDS, BEAT, DRAMATIC_BEAT, SHORT_BEAT
from bot_sections.core_and_menus import (
    apply_referral_bonus,
    escape_md,
    update_daily_quest_progress,
)
from bot_sections.horse_racing_and_social import (
    escape_markdown_v2,
)
from bot_sections.players_and_progression import (
    add_xp,
    check_player,
    deduct_xp,
    safe_send_reaction,
    unlock_achievement,
)
from game.economy_config import (
    apply_potion_multiplier,
)
from game.models import (
    ITEM_TYPE_CHOICES,
    ActivePoll,
    ChipTransaction,
    Dealer,
    Game,
    GameParameter,
    Group,
    JoinGame,
    NextGameNotification,
    Player,
    PlayerActiveItem,
    RoundWinner,
    Stats,
    UserSettings,
)
from game.services.blackjack import (
    ActiveInAnotherGame,
    AlreadyJoined,
    BettingPaused,
    InsufficientChips,
    join_game_with_chips_async,
    refund_joined_player_async,
)
from game.telegram.group_buttons import blackjack_join_keyboard, blackjack_turn_keyboard
from game.services.cards import (
    all_players_busted,
    calculate_hand_value,
    deal_card,
    format_hand,
    dealer_should_hit,
    resolve_round,
)
from game.services.economy import (
    adjust_balance_async,
)
from game.services.language import (
    group_language,
)
from game.services.table_games import (
    GroupTableBusy,
    ensure_blackjack_can_open,
)
from game.services.turns import (
    apply_player_timeout_async,
    begin_player_turn_async,
    record_player_action_async,
)
from game.telegram.runtime import (
    record_telegram_failure,
)
from lang import (
    t,
)

game_start_reactions = [
    "A new round begins! Are you ready? 🃏",
    "let the cards decide your fate! 💰",
    "Good luck to all! Let’s have a great round. 🍀",
    "New round, new chances to win! Let’s get started. 🎯",
    "It’s time to deal the cards Losers. Ready? 🃏",
    "A fresh round begins! May the best hand win. 👑",
    "Let’s shuffle up and deal! Good luck! 🔄",
    "The cards are ready. Who’s going to win this one? 👀",
    "Let the round begin! Who’s feeling lucky? 🔥"
]

# Dealer reactions for betting phase
betting_phase_reactions = [
    "Place your bets! It’s time to see who’s daring today. 💰",
    "Bet wisely! The game is about to heat up. 🔥",
    "Time to put your chips on the table! Who’s going big? 💸",
    "Betting is open! Will you play it safe or take a risk? 🎲",
    "Place your bets now! Will you go all in? 🤑",
    "How much are you willing to risk? Place your bets! 💪",
    "The pot is waiting! Let’s see who’s feeling bold. 💼",
    "Bet smart! The cards don’t lie. 🃏",
    "Who’s betting big this round? Let’s see! 💰",
    "Betting is open! Choose your risk carefully. 🎯"
]
async def create_highroller_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id

    try:
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        group = await sync_to_async(Group.objects.create)(group_chat_id=chat_id)

    # Define the high-roller choices
    options = [
        "1000000 (1M) chips💰",
        "5000000 (5M) chips💰",
        "10000000 (10M) chips💰",
        "50000000 (50M) chips💰",
        "100000000 (100M) chips💰",
        "200000000 (200M) chips💰",
        "500000000 (500M) chips💰",
        "1000000000 (1B) chips💰",
        "10000000000 (10B) chips💰",
        "100000000000 (100B) chips💰",
    ]

    question = "High-roller Bet (in chips 💰):"

    # Send the poll
    message = await safe_send_poll(context.bot, chat_id, question, options)


    await sync_to_async(ActivePoll.objects.create)(
        poll_id=message.poll.id,
        chat_id=chat_id,
        options=options,
        message_id=message.message_id,
        has_response=False  # 👈 This is required!
    )
    asyncio.create_task(remove_game_if_no_poll_answer(context, message.poll.id, timeout=60))


# --- New command handler: highroller ---
async def highroller(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Exactly mirrors start_blackjack, but uses create_highroller_poll() instead of create_poll().
    """
    if not await check_player(update, context):
        return

    chat_id = update.message.chat_id
    group_name = update.message.chat.title  # Get the group name
    language = await sync_to_async(group_language)(chat_id)
    try:
        await sync_to_async(ensure_blackjack_can_open, thread_sensitive=True)(chat_id)
    except GroupTableBusy as exc:
        await update.message.reply_text(
            "یک میز پوکر در این گروه باز است. ابتدا آن را ببندید."
            if language == "fa" else str(exc)
        )
        return

    # Check if a game exists and if it has ended
    game = await sync_to_async(lambda: Game.objects.filter(chat_id=chat_id).order_by('-id').first())()

    if not game or game.ended:
        # (Create or get a fresh Game, set betting=True, started=False)
        game, created = await sync_to_async(Game.objects.get_or_create)(chat_id=chat_id, ended=False)
        game.betting = True
        game.started = False
        await sync_to_async(game.save)()

        # Notify anyone who subscribed to /nextgame
        next_game_users = await sync_to_async(list)(
            NextGameNotification.objects.filter(chat_id=chat_id)
        )

        # Send a message to each user in their private chat, using the group's actual name
        for next_user in next_game_users:
            try:
                await context.bot.send_message(
                    chat_id=next_user.user_id,
                    text=t("group.blackjack_started", language, group_name=group_name)
                )
            except Exception as e:
                await record_telegram_failure(
                    e, player_id=next_user.user_id, chat_id=chat_id,
                    message_type="highroller_subscription"
                )

        notified_users = await sync_to_async(list)(
            UserSettings.objects.filter(notify_high_roller_blackjack_start=True)
                                .select_related("player")
        )
        print("ehrawe")
        for setting in notified_users:
            try:
                await context.bot.send_message(
                    chat_id=setting.player.id,
                    text=t("group.blackjack_started", language, group_name=group_name)
                )
            except Exception as e:
                await record_telegram_failure(
                    e, player_id=setting.player.id, chat_id=chat_id,
                    message_type="highroller_notification"
                )
        # Clear notifications
        await sync_to_async(lambda: NextGameNotification.objects.filter(chat_id=chat_id).delete())()

        await asyncio.sleep(BEAT)
        await context.bot.send_message(chat_id=chat_id, text=t("group.highroller_set_bet", language))

        # Use create_highroller_poll() instead of create_poll()
        await create_highroller_poll(update, context)

        await asyncio.sleep(BEAT)
        await context.bot.send_message(chat_id=chat_id, text=t("group.highroller_betting_started", language))
        await asyncio.sleep(SHORT_BEAT)
        reaction = random.choice(betting_phase_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        return

    # If a Game exists and hasn't ended yet, behave exactly as start_blackjack does:
    if game.betting:
        await update.message.reply_text("A Blackjack game is in betting progress. Wait for the betting process to end and use /join to join the game.")
    elif game.started:
        await update.message.reply_text("A game has already started. Use the /nextgame command to be notified when the next game starts.")
    elif game.join_time:
        await update.message.reply_text("A game is in join time. Use the /join command to join the game.")
    else:
        await update.message.reply_text("An error occurred, please try again.")

async def start_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return
    chat_id = update.message.chat_id
    group_name = update.message.chat.title  # Get the group name
    language = await sync_to_async(group_language)(chat_id)
    try:
        await sync_to_async(ensure_blackjack_can_open, thread_sensitive=True)(chat_id)
    except GroupTableBusy as exc:
        await update.message.reply_text(
            "یک میز پوکر در این گروه باز است. ابتدا آن را ببندید."
            if language == "fa" else str(exc)
        )
        return

    # Check if a game exists and if it has ended
    game = await sync_to_async(lambda: Game.objects.filter(chat_id=chat_id).order_by('-id').first())()

    if not game or game.ended:
        game, created = await sync_to_async(Game.objects.get_or_create)(chat_id=chat_id, ended=False)
        game.betting = True
        game.started = False
        await sync_to_async(game.save)()
        if update.effective_chat.type in ["group", "supergroup"]:

            # Notify users who subscribed to the next game
            next_game_users = await sync_to_async(list)(
                NextGameNotification.objects.filter(chat_id=chat_id)
            )

            # Send a message to each user in their private chat, using the group's actual name
            for next_user in next_game_users:
                try:
                    await context.bot.send_message(
                        chat_id=next_user.user_id,
                        text=t("group.blackjack_started", language, group_name=group_name)
                    )
                except Exception as e:
                    await record_telegram_failure(
                        e, player_id=next_user.user_id, chat_id=chat_id,
                        message_type="blackjack_subscription"
                    )


            # 1. Notify users with notify_classic_blackjack_start=True
            notified_users = await sync_to_async(list)(
                UserSettings.objects.filter(notify_classic_blackjack_start=True)
                                    .select_related("player")
            )

            for setting in notified_users:
                    user_id = setting.player.id
                    try:
                        # Check if the user is still in the group
                        member = await context.bot.get_chat_member(chat_id, user_id)
                        if member.status not in ["left", "kicked"]:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=t("group.blackjack_started", language, group_name=group_name)
                            )
                    except Exception as e:
                        await record_telegram_failure(
                            e, player_id=user_id, chat_id=chat_id,
                            message_type="blackjack_notification"
                        )


        # Optionally, clear the list after notifying
        await sync_to_async(lambda: NextGameNotification.objects.filter(chat_id=chat_id).delete())()

        await asyncio.sleep(BEAT)
        await context.bot.send_message(chat_id=chat_id, text=t("group.blackjack_set_bet", language))

        await create_poll(update, context)
        

        await asyncio.sleep(BEAT)
        await context.bot.send_message(chat_id=chat_id, text=t("group.blackjack_betting_started", language))
        await asyncio.sleep(SHORT_BEAT)
        reaction = random.choice(betting_phase_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        return


    # Check the game state and respond accordingly
    if game.betting:
        await update.message.reply_text("A Blackjack game is in betting progress. Wait for the betting process to end and use /join to join the game.")
    elif game.started:
        await update.message.reply_text("A game has already started. Use the /nextgame command to be notified when the next game starts.")
    elif game.join_time:
        await update.message.reply_text("A game is in join time. Use the /join command to join the game.")
    else:
        await update.message.reply_text("An error occurred, please try again.")

async def safe_send_poll(bot, chat_id, question, options, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            message = await bot.send_poll(
                chat_id=chat_id,
                question=question,
                options=options,
                is_anonymous=False,
                allows_multiple_answers=False,
                open_period=60  # ⏳ Keeps poll open for 10 minutes
            )
            return message  # Exit if successful
        except TimedOut:
            retries += 1
            await asyncio.sleep(4)
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            await asyncio.sleep(retry_after)
            retries += 1

# async def safe_send_poll(bot, chat_id, question, options, max_retries=10):
#     retries = 0
#     while retries < max_retries:
#         try:
#             message = await bot.send_poll(chat_id=chat_id, question=question, options=options, is_anonymous=False)
#             return message  # Exit if successful
#         except TimedOut:
#             retries += 1
#             await asyncio.sleep(4)  # Use async sleep
#         except RetryAfter as e:
#             retry_after = int(e.retry_after)
#             await asyncio.sleep(retry_after)  # Use async sleep
#             retries += 1
# Create poll function for setting bet amounts
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id

    # Retrieve or create Group instance using sync_to_async
    try:
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        group = await sync_to_async(Group.objects.create)(group_chat_id=chat_id)

    # Determine if the game should be based on real tokens or chips
    if group.vip and group.real_money:
        options = ["100 $", "200 $", "500 $", "1000 $"]
        if group.games >= 100:
            options.extend(["10000 $", "20000 $", "50000 $"])
        question = "How much do you want to bet (real tokens 💵)?"
    else:
        options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰"]
        if group.games >= 100:
            options.extend(["10000 chips💰", "20000 chips💰", "50000 chips💰"])
        question = "How much do you want to bet (virtual chips 💰)?"

    # Send the poll asynchronously
    message = await safe_send_poll(context.bot, chat_id, question, options)


    await sync_to_async(ActivePoll.objects.create)(
        poll_id=message.poll.id,
        chat_id=chat_id,
        message_id=message.message_id,
        has_response=False  # 👈 This is required!

    )
    asyncio.create_task(remove_game_if_no_poll_answer(context, message.poll.id, timeout=60))


async def remove_game_if_no_poll_answer(context, poll_id, timeout=10):
    await asyncio.sleep(timeout)

    try:
        active_poll = await sync_to_async(ActivePoll.objects.get)(poll_id=poll_id)
    except ActivePoll.DoesNotExist:
        print(f"⚠️ No ActivePoll found for poll_id={poll_id}")
        return

    if not active_poll.has_response:
        chat_id = active_poll.chat_id

        # Delete the Game instance if it exists
        deleted_count, _ = await sync_to_async(Game.objects.filter(chat_id=chat_id, started=False, ended=False).delete)()
        print(f"🗑 Deleted Game for chat {chat_id} due to poll timeout. Deleted: {deleted_count}")

        try:
            await context.bot.send_message(chat_id, "⏰ No one responded to the bet poll. Game cancelled.")
        except:
            pass

        # Delete the poll row from DB
        await sync_to_async(active_poll.delete)()



async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # chat_id = update.message.chat_id

    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    user_name = poll_answer.user.first_name
    selected_option = poll_answer.option_ids[0]  # Get the index of the selected option

    # Retrieve the poll data from context using poll_id
    try:
        active_poll = await sync_to_async(ActivePoll.objects.get)(poll_id=poll_answer.poll_id)
        poll_data = {
            'chat_id': active_poll.chat_id,
            'poll_message_id': active_poll.message_id,
            'has_response': active_poll.has_response,
        }
        active_poll.has_response = True
        await sync_to_async(active_poll.save)()
    except ActivePoll.DoesNotExist:
        print("No ActivePoll found in DB.")
        return

    if not poll_data:
        print("No poll data found.")
        return
    else:
        poll_data['has_response'] = True
        print("Poll data exists.")
        try:
            chat_id = poll_data['chat_id']
            print(f"Chat ID: {chat_id}")

            game = await sync_to_async(Game.objects.get)(
                chat_id=chat_id, betting=False, started=True, ended=False
            )
            print("Game found with betting=False, started=True, ended=False.")
        except Game.DoesNotExist:
            print("No game found with betting=False, started=True, ended=False.")
            try:
                game = await sync_to_async(Game.objects.get)(
                    chat_id=chat_id, betting=True, started=False, ended=False
                )
                print("Game found with betting=True, started=False, ended=False.")
            except Game.DoesNotExist:
                print("Game not found?")
                return

        if game.bet_phase != "total_pot":
            print(f"Current bet phase: {game.bet_phase}")
            if game.bet_phase == "dealer":
                print("Handling dealer poll response.")
                await handle_poll_response(update, context)
            else:
                print("Poll data not found.")
                return


    chat_id = poll_data['chat_id']
    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, betting=True, started=False, ended=False)
    except Game.DoesNotExist:
        print("Game not found?")
        return
    # Retrieve the group using sync_to_async
    group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)

    # Set bet amounts based on real tokens or chips
    stored_options = active_poll.options
    if stored_options:
        # This was a HIGH-ROLLER poll, so use that array:
        options = stored_options
    else:
        # It wasn’t a highroller poll—fall back to your “normal betting” array:
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
        if group.vip and group.real_money:
            options = ["100 $", "200 $", "500 $", "1000 $", "10000 $", "20000 $", "50000 $"]
        else:
            options = [
                "10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", 
                "500 chips💰", "1000 chips💰", "10000 chips💰", 
                "20000 chips💰", "50000 chips💰"
            ]

    # Now pick the chosen option by index:
    chosen_option = options[selected_option]

    # If “chosen_option” is something like "1 000 000 chips💰", split out the number:
    bet_amount_str = chosen_option.split()[0].replace(" ", "").replace(",", "")  
    # (the .replace() is in case you have non-standard thousands separators)
    bet_amount = int(bet_amount_str)

    # Update the game and save:
    game.bet_amount = bet_amount
    game.betting = False
    game.join_time = True
    game.bet_phase = "dealer"
    await sync_to_async(game.save)()

    # Then send your confirmation to the group (escaping markdown, etc.) as usual
    escaped_user_name = escape_markdown(user_name, version=2)
    currency_type = "$" if (group.vip and group.real_money) else "chips💰"
    chosen_option_escaped = escape_markdown(chosen_option, version=2)
    await sync_to_async(ActivePoll.objects.filter(poll_id=poll_answer.poll_id).delete)()

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"[{escaped_user_name}](tg://user?id={user_id}) has set "
            f"the bet amount to {chosen_option_escaped}\n"
            "Tap 🙋 Join to play"
        ),
        parse_mode="MarkdownV2",
        reply_markup=blackjack_join_keyboard(),
    )
async def handle_poll_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll = update.poll

    try:
        active_poll = await sync_to_async(ActivePoll.objects.get)(poll_id=poll.id)
    except ActivePoll.DoesNotExist:
        return

    if poll.is_closed and not active_poll.has_response:
        deleted_count, _ = await sync_to_async(
            Game.objects.filter(chat_id=active_poll.chat_id, started=False, ended=False).delete
        )()

        await sync_to_async(active_poll.delete)()

        try:
            await context.bot.send_message(
                chat_id=active_poll.chat_id,
                text="🗳 Poll ended with no responses. The Blackjack game was cancelled."
            )
        except:
            pass

async def safe_send_message_join(bot, chat_id, text, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking sleep
    print("Failed to send the message after retries.")

async def join_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=True, started=False, ended=False, betting=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game found or the game is not in join time.")
        return

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)

    # Check if the player already joined
    if await sync_to_async(JoinGame.objects.filter(game=game, player=player, is_active=True).exists)():
        await update.message.reply_text(f"{user_name}, you are already in the game!")
        return
    if await sync_to_async(JoinGame.objects.filter(player=player, is_active=True).exclude(game=game).exists)():
        await update.message.reply_text(f"{user_name}, you are already active in another game!")
        return

    if group.vip and group.real_money:
        # Real token game
        if player.real_tokens < game.bet_amount:
            await update.message.reply_text(
                f"{user_name}, you do not have enough 💵real tokens to join the game.\nMinimum bet is {game.bet_amount} 💵real tokens."
            )
            return
        # Deduct real tokens **when joining**
        player.real_tokens -= game.bet_amount
        await sync_to_async(player.save)(update_fields=("real_tokens",))
        await sync_to_async(JoinGame.objects.create)(player=player, game=game, is_active=True)
    else:
        try:
            await join_game_with_chips_async(player.id, game.id)
        except InsufficientChips:
            await update.message.reply_text(
                f"{user_name}, you do not have enough 💰chips to join the game.\nMinimum bet is {game.bet_amount} 💰chips."
            )
            return
        except AlreadyJoined:
            await update.message.reply_text(f"{user_name}, you are already in the game!")
            return
        except ActiveInAnotherGame:
            await update.message.reply_text(f"{user_name}, you are already active in another game!")
            return
        except BettingPaused:
            await update.message.reply_text("New bets are temporarily paused by an operator.")
            return

    escaped_user_name = escape_markdown(user_name, version=2)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"[{escaped_user_name}](tg://user?id={user_id}) has joined the game\\!",
        parse_mode="MarkdownV2"
    )
    await context.bot.send_message(
        chat_id=player.id,
        text=f"You have successfully joined a game in group {update.message.chat.title}, Good Luck😃"
    )



scare_players_reactions = [
    "I wouldn’t get too comfortable if I were you. 😈",
    "Do you really think you can win this? Think again. 😏",
    "I can already see the outcome, and it’s not in your favor. 👀",
    "You might want to start preparing for a loss. 🎲",
    "The cards don’t look good for you. Better luck next time. 😎",
    "Feeling lucky? You might need more than that. 😏",
    "Oh, I wouldn’t bet too much on this round if I were you. 🃏",
    "Your fate is sealed. This won’t end well. 😈",
    "I’ve seen better hands, and trust me, this isn’t one of them. 😅",
    "Get ready to lose everything, because that’s where this is heading. 💥",
    "I hope you didn’t go all in, because this might hurt. 💸",
    "The house always wins, and today is no exception. 🤑",
    "I wouldn’t count on winning this one. Better get used to losing. 🎯",
    "This is where it all goes downhill for you. 😎",
    "Enjoy your last moments of hope, because they’re fading fast. 🃏"
]


# Force start the Blackjack game
# Force start the Blackjack game
async def force_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    chat_id = update.message.chat_id


    # Find an existing game in join_time state; otherwise walk through other states
    try:
        game = await sync_to_async(Game.objects.get)(
            chat_id=chat_id,
            join_time=True,
            started=False,
            ended=False,
            betting=False
        )
    except Game.DoesNotExist:
        try:
            game = await sync_to_async(Game.objects.get)(
                chat_id=chat_id,
                join_time=False,
                started=False,
                ended=False,
                betting=True
            )
            await safe_send_message_join(
                context.bot,
                chat_id,
                "The game is in the betting process. Please wait for it to end, then /forcestart the game."
            )
            return
        except Game.DoesNotExist:
            try:
                game = await sync_to_async(Game.objects.get)(
                    chat_id=chat_id,
                    join_time=False,
                    started=True,
                    ended=False,
                    betting=False
                )
                await safe_send_message_join(
                    context.bot,
                    chat_id,
                    "A game has already started. You cannot /forcestart. Use /nextgame to be prompted when another game is started."
                )
                return
            except Game.DoesNotExist:
                await safe_send_message_join(
                    context.bot,
                    chat_id,
                    "No active Blackjack game. Start one by typing /startblackjack."
                )
                return

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(lambda: list(
        JoinGame.objects.filter(game=game, is_active=True)
    ))()

    # If fewer than 1 player, cancel the game immediately
    if len(joined_players) < 1:
        await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()
        await update.message.reply_text(
            'At least 1 player is required to start the game. Ending the game!'
        )
        return

    # If the game was already forced, no need to do it again
    if game.forced:
        await context.bot.send_message(
            chat_id=chat_id,
            text="This game has already been force\\-started\\."
        )
        return

    game.forced = True
    await sync_to_async(game.save)()
    
    # Fetch dealer and group
    dealer = await sync_to_async(Dealer.objects.first)()
    group_game, created = await sync_to_async(Group.objects.get_or_create)(
        group_chat_id=chat_id
    )
    group_game.games += 1
    await sync_to_async(group_game.save)()

    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)

    # Join bonus logic
    if params.join_bonus:
        rewarded_names = []

        for joined in joined_players:
            try:
                # Use player_id directly
                player = await sync_to_async(Player.objects.get)(id=joined.player_id)
                await adjust_balance_async(
                    player,
                    params.join_bonus_amount,
                    category=ChipTransaction.Category.DAILY_REWARD,
                    description="Blackjack join bonus",
                    reference_type="blackjack_game",
                    reference_id=game.id,
                    idempotency_key=f"blackjack:{game.id}:player:{player.id}:join-bonus",
                )

                name = player.name or f"User {player.id}"
                rewarded_names.append(name)

                await context.bot.send_message(
                    chat_id=player.id,
                    text=f"🎁 You received a start bonus of {params.join_bonus_amount} chips for joining this Blackjack game!"
                )

            except Exception as e:
                print(f"[JOIN_BONUS_ERROR] Failed to message or update player {joined.player_id}: {e}")
                continue


        # Announce in the group
        if rewarded_names:
            names_text = ", ".join(rewarded_names)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"🎉 All joined players received a start bonus of {params.join_bonus_amount}"
            )


    # Determine currency type (real tokens vs. chips)
    is_real_token_game = group_game.vip and group_game.real_money
    currency_type = "$" if is_real_token_game else "chips💰"

    # -------------------------------------------
    # CHECK: Does the dealer have enough chips?
    # -------------------------------------------
    if dealer:
        # (If you ever support real tokens, you’d do that check here;
        #  for now, we're only checking chips, as in your original code.)
        if dealer.chips < game.bet_amount:
            # *** REFUND EVERY JOINED PLAYER BEFORE ENDING THE GAME ***
            for join_entry in joined_players:
                player = await sync_to_async(lambda: join_entry.player)()

                # Refund the bet amount:
                if is_real_token_game:
                    player.real_tokens += game.bet_amount
                    await sync_to_async(player.save)(update_fields=("real_tokens",))
                    await sync_to_async(join_entry.delete)()
                else:
                    await refund_joined_player_async(
                        join_entry.id,
                        description="Dealer could not cover blackjack game",
                    )

                # Optionally, notify each player privately that they were refunded:
                # (You can comment this out if you prefer not to spam DMs.)
                try:
                    await context.bot.send_message(
                        chat_id=player.id,
                        text=(
                            f"You have been refunded {game.bet_amount} {currency_type} "
                            f"because the dealer could not participate. The game is ending."
                        )
                    )
                except Exception:
                    # In case sending a private message fails, ignore it.
                    pass

            # Delete the Game record entirely
            await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()

            # Inform the group that the dealer lacked funds and everyone was refunded
            await context.bot.send_message(
                chat_id=chat_id,
                text="🤖 Dealer doesn't have enough chips to participate. "
                     "All players have been refunded and the game is ending."
            )
            return
        else:
            # Dealer **does** have enough chips; deduct from dealer and proceed
            dealer.chips -= game.bet_amount
            dealer.games += 1
            await sync_to_async(dealer.save)()

            reaction = random.choice(scare_players_reactions)
            await safe_send_reaction(context.bot, chat_id, reaction)

            await asyncio.sleep(BEAT)
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🤖 Dealer is in the game with {game.bet_amount} {currency_type} on the table\\."
                ),
                parse_mode="MarkdownV2"
            )

    # -------------------------------------------
    # CONTINUE: Deduct each player's bet & start
    # -------------------------------------------

    # If there were ≥5 joined players, unlock the "5_or_more_player" achievement
    if len(joined_players) >= 5:
        for join_entry in joined_players:
            player = await sync_to_async(lambda: join_entry.player)()
            await unlock_achievement(player, "5_or_more_player", context)

    for join_entry in joined_players:
        player = await sync_to_async(lambda: join_entry.player)()
        if game.bet_amount >= 1000000:
            await update_daily_quest_progress(player, "blackjack", "join1m", 1, context)
        if game.bet_amount >= 50000:
            await update_daily_quest_progress(player, "blackjack", "join50", 1, context)
        if game.bet_amount >= 10000000:
            await update_daily_quest_progress(player, "blackjack", "join10m", 1, context)
        if game.bet_amount <= 1000:
            await update_daily_quest_progress(player, "blackjack", "join1", 1, context)
        await update_daily_quest_progress(player, "blackjack", "join", 1, context)
        # Add XP for joining
        await add_xp(player, 10, context)

        # If the bet amount is ≥5000, unlock that achievement
        if game.bet_amount >= 5000:
            await unlock_achievement(player, "5000_game_join", context)

        # Deduct each player’s chips (already checked above that they all had enough)
        # if is_real_token_game:
        #     player.real_tokens -= game.bet_amount
        # else:
        #     player.chips -= game.bet_amount

        # If they went all‐in (chips now 0), unlock that achievement
        if player.chips == 0:
            await unlock_achievement(player, "all_in", context)

        player.games += 1
        await sync_to_async(player.save)(update_fields=("games",))

        # Build the Markdown‐escaped mention & send a group message
        # user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', player.name)
        escaped_user_name = escape_markdown(player.name, version=2)
        mention = f"[{escaped_user_name}](tg://user?id={player.id})"

        remaining_tokens = player.chips if not is_real_token_game else player.real_tokens

        # Debug prints for player basics
        print("🧪 PLAYER NAME:", player.name)
        print("🧪 ESCAPED USER NAME:", escaped_user_name)
        print("🧪 MENTION:", mention)
        print("🧪 Remaining tokens:", remaining_tokens)

        # Fetch active items (excluding boosters)
        BOOSTER_TYPES = ["xp_booster_500", "xp_booster_2000", "xp_booster_15000", "xp_booster_50000"]
        active_items = await sync_to_async(lambda: list(
            PlayerActiveItem.objects.filter(player=player, is_active=True)
                                .exclude(item_type__in=BOOSTER_TYPES)
        ))()

        # Process and debug active item names
        if active_items:
            item_names = []
            for item in active_items:
                label = dict(ITEM_TYPE_CHOICES).get(item.item_type, item.item_type)
                safe_label = escape_md(label)
                item_names.append(safe_label)
                print(f"🧪 Raw item: {item.item_type} → Label: {label} → Escaped: {safe_label}")

            combined_text = "🧪 Active: " + ", ".join(item_names)
            items_text = escape_markdown(combined_text, version=2)

        else:
            items_text = "🧪 Active: None"
            print("🧪 No active items.")

        # Final debug
        print("🧪 Final items_text:", items_text)


        await asyncio.sleep(BEAT)
        print("⚠️ DEBUG: mention =", mention)
        print("⚠️ DEBUG: bet amount =", game.bet_amount)
        print("⚠️ DEBUG: remaining =", remaining_tokens)
        print("⚠️ DEBUG: items_text =", items_text)

        text_to_send = (
            f"{mention} has bet {game.bet_amount} {currency_type}\\.\n"
            f"Remaining {currency_type}: {remaining_tokens}\\.\n"
            f"{items_text}"
        )

        print("⚠️ DEBUG: full message =", text_to_send)

        await context.bot.send_message(
            chat_id=chat_id,
            text=text_to_send,
            parse_mode="MarkdownV2"
        )

        # await context.bot.send_message(
        #     chat_id=chat_id,
        #     text=(
        #         f"{mention} has bet {game.bet_amount} {currency_type}\\.\n"
        #         f"Remaining {currency_type}: {remaining_tokens}\\.\n"
        #         f"{items_text}"
        #     ),
        #     parse_mode="MarkdownV2"
        # )

    # Set up turn order, pot, etc., and mark the game as started
    game.turn_order = [join_entry.player.id for join_entry in joined_players]
    game.current_round = 1
    players_count = len(joined_players) + 1  # +1 for the dealer
    game.pot = game.bet_amount * players_count
    game.started = True
    game.join_time = False
    await sync_to_async(game.save)()

    # Proceed to the first round
    await start_round(update, context, game, joined_players)



# # Function to start each round
async def safe_pin_chat_message(bot, chat_id, message_id, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=message_id)  # Assuming timeout is 20
            return  # Exit the loop if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while pinning message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Rate limit exceeded. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Wait for the retry after time
            retries += 1

    print("Failed to pin message after multiple retries.")

async def start_round(update: Update, context: ContextTypes.DEFAULT_TYPE, game, joined_players):
    chat_id = update.message.chat_id
    joined_players = await sync_to_async(list)(
        JoinGame.objects.filter(game=game, is_active=True).select_related("player")
    )
    if not joined_players:
        await context.bot.send_message(
            chat_id=chat_id,
            text="All players were removed for inactivity. The game is ending.",
        )
        await end_game(update, context)
        return

    print(game.current_round)
    # game.is_round_starting = True
    # await sync_to_async(game.save)()

    if game.current_round >= 2:

        bot_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)

        round_winners = await sync_to_async(list)(RoundWinner.objects.filter(game=game, is_dealer=False))
        dealer_wins = await sync_to_async(RoundWinner.objects.filter(game=game, is_dealer=True).count)()
        winner_count = {}

        for winner in round_winners:
            # Accessing related 'winner' field asynchronously
            winner_player = await sync_to_async(lambda: winner.winner)()
            if winner_player in winner_count:
                winner_count[winner_player] += 1
            else:
                winner_count[winner_player] = 1

        winners = []
        no_wins = []

        # Fetch related fields with sync_to_async
        for join_entry in joined_players:
            player_name = await sync_to_async(lambda: join_entry.player.name)()
            player_id = await sync_to_async(lambda: join_entry.player.id)()
            wins = winner_count.get(join_entry.player, 0)

            if wins > 0:
                winners.append((player_name, wins, player_id))
            else:
                no_wins.append((player_name, player_id))

        winners = sorted(winners, key=lambda x: x[1], reverse=True)

        await asyncio.sleep(SHORT_BEAT)
        standings_message = "📊 Current standings:\n"

        if dealer_wins > 0:
            standings_message += f"🤖 Dealer: {dealer_wins} round\\(s\\) won\n"
        else:
            standings_message += "🤖 Dealer: No wins yet\n"

        for winner_name, wins, user_id in winners:
            user_name_escaped = escape_markdown(winner_name, version=2)
            mention = f"[{user_name_escaped}](tg://user?id={user_id})"
            standings_message += f"🏆 {mention}: {wins} round\\(s\\) won\n"

        for player_name, player_id in no_wins:
            user_name_escaped = escape_markdown(player_name, version=2)
            mention = f"[{user_name_escaped}](tg://user?id={player_id})"
            standings_message += f"🎲 {mention}: No wins yet\n"

        message = await context.bot.send_message(chat_id=chat_id, text=standings_message, parse_mode="MarkdownV2")

        # if bot_member.status in ['administrator', 'creator']:
        #     await safe_pin_chat_message(context.bot, chat_id, message.message_id)

    await asyncio.sleep(BEAT)

    await context.bot.send_message(chat_id=chat_id, text=f"🃏 ━━ ROUND {game.current_round} of {game.total_rounds} ━━ 🃏")
    await asyncio.sleep(DRAMATIC_BEAT)
    reaction = random.choice(game_start_reactions)
    await safe_send_reaction(context.bot, chat_id, reaction)

    await asyncio.sleep(BEAT)

    player_blackjacks = []

    for join_entry in joined_players:
        # ── Apply potion/pass only if current round is 1 ──
        used_first_hand_potion = False
        hand_override = None

        if game.current_round == 1:
            active_items = await sync_to_async(list)(
                PlayerActiveItem.objects.filter(player=join_entry.player, is_active=True)
            )

            for item in active_items:
                if item.item_type == "first_hand_20_pass":
                    hand_override = [10, "K"]  # or any 20-point combo you prefer
                    await sync_to_async(item.delete)()  # Consume the pass
                    used_first_hand_potion = True
                    break
                elif item.item_type == "first_hand_11_potion":
                    hand_override = [5, 6]  # 11 points
                    await sync_to_async(item.delete)()  # Consume the potion
                    used_first_hand_potion = True
                    break

        # ── Deal hand ──
        player_hand = hand_override if used_first_hand_potion else [deal_card(), deal_card()]
        join_entry.hand = player_hand
        await sync_to_async(join_entry.save)()

        # ── Show to player if not blackjack ──
        player_hand_value = calculate_hand_value(player_hand)
        if player_hand_value == 21:
            player_blackjacks.append(join_entry)  # ✅ Add to blackjack list
        else:
            await context.bot.send_message(
                chat_id=join_entry.player.id,
                text=f"🃏 Your hand\n{format_hand(player_hand)}"
            )
        # if player_hand_value != 21:
        #     await context.bot.send_message(
        #         chat_id=join_entry.player.id,
        #         text=f"🃏Your hand: {player_hand}.\n♠️Total value: {player_hand_value}"
        #     )

    dealer_hand = [deal_card(), deal_card()]
    game.dealer_hand = dealer_hand
    await sync_to_async(game.save)()
    

    dealer_value = calculate_hand_value(dealer_hand)
    dealer_has_blackjack = dealer_value == 21

    if dealer_has_blackjack:
        if game.current_round == 1:
            await send_vote_results(update, context,chat_id,game.poll_id)

        await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer has a natural Blackjack! 💥")
        dealer = await sync_to_async(Dealer.objects.get)(id=1)
        dealer.blackjack_count += 1
        await sync_to_async(dealer.save)()

        for join_entry in player_blackjacks:
            await context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} had Blackjack💥 too.")

        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
        game.current_round += 1
        await check_for_next_round(update, context, game, joined_players)
        # game.is_round_starting = False
        # await sync_to_async(game.save)()

        return

    if player_blackjacks:
        for join_entry in player_blackjacks:
            await unlock_achievement(join_entry.player, "first_natrual_blackjack", context)
            if game.current_round == 1:
                await send_vote_results(update, context,chat_id,game.poll_id)

            await context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} has a natural Blackjack!💥 They win the round.")
            await add_xp(join_entry.player, 35, context)
            player = await sync_to_async(lambda: join_entry.player)()

            await update_daily_quest_progress(player, "blackjack", "natural", 1, context)

            stats = await sync_to_async(Stats.objects.get)(player=join_entry.player)

            stats.how_many_21 += 1
            await sync_to_async(stats.save)()
            if stats.how_many_21 >= 21:
                await unlock_achievement(join_entry.player, "21_black_jacks", context)
            if stats.how_many_21 >= 100:
                await unlock_achievement(join_entry.player, "100_black_jacks", context)

            await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, winner=join_entry.player)

        game.current_round += 1
        # game.is_round_starting = False
        # await sync_to_async(game.save)()

        await check_for_next_round(update, context, game, joined_players)
        return

    for join_entry in joined_players:
        if join_entry not in player_blackjacks:
            stats = await sync_to_async(Stats.objects.get)(player=join_entry.player)
            await sync_to_async(stats.save)()
    # game.is_round_starting = False
    # await sync_to_async(game.save)()
    await player_turn(update, context)

async def send_vote_results(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id=None, poll_id=None, game=None):
    poll_data = context.bot_data.get('poll_data', {}).get(poll_id)

    if not poll_data:
        print("Poll data not found.")
        return

    correct_guess_player_ids = poll_data.get('correct_guess_player_ids', [])
    wrong_guess_player_ids = poll_data.get('wrong_guess_player_ids', [])
    
    # Set chips and xp based on correct guesses
    if correct_guess_player_ids:
        xp = poll_data.get('xp', [])
        chips = poll_data.get('chips', [])
    else:
        xp = 0
        chips = 0

    # Construct the results message based on correct guesses
    results_message_correct = "✅ Correct Guesses:\n"
    results_message_wrong = "❌ Wrong Guesses:\n"

    if correct_guess_player_ids:
        for player_id in correct_guess_player_ids:
            results_message_correct += f"- Player ID: {player_id}\n"
    else:
        results_message_correct += "No players guessed correctly.\n"

    if wrong_guess_player_ids: 
        for player_id in wrong_guess_player_ids:
            results_message_wrong += f"- Player ID: {player_id}\n"
    else:
        results_message_wrong += "No players guessed incorrectly.\n"

    # Add rewards information
    rewards_message = f"🎉 Players who guessed correctly received:\n💰 {chips} Chips\n📈 {xp} XP"

    # Send the message
    await context.bot.send_message(chat_id=chat_id, text=f"{results_message_correct}\n\n{results_message_wrong}\n\n{rewards_message}")
async def handle_poll_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.poll_answer.user.id
    print(f"User ID: {user_id}")

    poll_answer = update.poll_answer
    try:
        active_poll = await sync_to_async(ActivePoll.objects.get)(poll_id=poll_answer.poll_id)
        poll_data = {
            'chat_id': active_poll.chat_id,
            'poll_message_id': active_poll.message_id,
            'has_response': active_poll.has_response,
        }
        active_poll.has_response = True
        await sync_to_async(active_poll.save)()
    except ActivePoll.DoesNotExist:
        print("No ActivePoll found in DB.")
        return
        
    if not poll_data:
        print("Poll data not found.")
        return

    chat_id = poll_data['chat_id']
    print(f"Chat ID: {chat_id}")

    try:
        join_entry = await sync_to_async(JoinGame.objects.get)(player__id=user_id, game__chat_id=chat_id)
        print(f"Join entry found for user {user_id} in chat {chat_id}.")
    except JoinGame.DoesNotExist:
        print(f"Join entry not found for user {user_id} in chat {chat_id}.")
        return

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id)
        print(f"Game found for user {game.chat_id}")
    except Game.DoesNotExist:
        print(f"Game not found for user {game.chat_id}")
        return

    if game.dealer_bet_timer == 1:
        return

    poll_id = poll_data['poll_id']
    print(f"Current Poll ID: {poll_id}")

    # Check if the player has already voted
    if user_id in poll_data.get('voted_player_ids', []):
        print(f"Player {user_id} has already voted. Ignoring duplicate vote.")
        return  # Ignore if they've already voted

    # Add user ID to the list of voters
    if 'voted_player_ids' not in poll_data:
        poll_data['voted_player_ids'] = []
    
    poll_data['voted_player_ids'].append(user_id)

    if update.poll_answer.poll_id == poll_id:
        selected_option = update.poll_answer.option_ids[0]
        print(f"Selected option: {selected_option}")

        dealer_value = calculate_hand_value(game.dealer_hand)
        print(f"Dealer's hand value: {dealer_value}")

        correct_guess = (
            (dealer_value < 10 and selected_option == 0) or
            (10 <= dealer_value <= 15 and selected_option == 1) or
            (15 <= dealer_value <= 18 and selected_option == 2) or
            (19 <= dealer_value <= 20 and selected_option == 3) or
            (dealer_value == 21 and selected_option == 4) 
        )
        

        if correct_guess:
            player_playerentry = await sync_to_async(lambda: join_entry.player)()
            player_stats = await sync_to_async(Stats.objects.get)(player=player_playerentry)
            player_stats.correct_dealer_guesses += 1
            await sync_to_async(player_stats.save)()
            player_name = await sync_to_async(lambda: join_entry.player.name)()
            

            pot_amount = game.pot  # Ensure you have access to the pot
            

            bonus = pot_amount // 3  # Calculate 1/3 of the pot
            
            await add_xp(player_playerentry, 50, context)
            

            # Store player ID in the poll data for later use
            context.bot_data['poll_data'][poll_id]['chips'] = bonus
            context.bot_data['poll_data'][poll_id]['xp'] = 50
            
            context.bot_data['poll_data'][poll_id]['correct_guess_player_ids'].append(player_name)

        else:
            player_name = await sync_to_async(lambda: join_entry.player.name)()
            context.bot_data['poll_data'][poll_id]['wrong_guess_player_ids'].append(player_name)
            
    else:
            print("[DEBUG] si")
async def update_statistics(overall_winners, dealer_won_overall, joined_players, context):
    # ─── 1) Handle winners ─────────────────────────────────────────────────────────
    for winner in overall_winners:
        if winner == "dealer":
            await sync_to_async(_increment_dealer_wins)()
        else:
            player = await sync_to_async(Player.objects.get)(id=winner.id)
            stats, _ = await sync_to_async(Stats.objects.get_or_create)(player=player)
            await add_xp(player, 25, context)

            stats.wins += 1
            await sync_to_async(stats.save)()

            total_games = stats.wins + stats.loses
            if stats.wins >= 100:
                await unlock_achievement(player, "100_wins", context)
            if total_games >= 100:
                await unlock_achievement(player, "100_games", context)
            if total_games >= 500:
                await unlock_achievement(player, "500_games", context)

    # ─── 2) Build set of winner IDs (excluding the string 'dealer') ─────────────────
    winner_ids = {w.id for w in overall_winners if w != "dealer"}

    # ─── 3) Determine non‐winners ───────────────────────────────────────────────────
    non_winners = []
    dealer_obj = await sync_to_async(Dealer.objects.first)()
    dealer_id = dealer_obj.id if dealer_obj else None

    for join_entry in joined_players:
        player = await sync_to_async(lambda: join_entry.player)()
        pid = player.id

        if pid not in winner_ids and pid != dealer_id:
            non_winners.append(player)

    # Deduplicate
    non_winners = list({p.id: p for p in non_winners}.values())

    # ─── 4) Apply losses to each non-winner ─────────────────────────────────────────
    for player in non_winners:
        stats, _ = await sync_to_async(Stats.objects.get_or_create)(player=player)
        stats.loses += 1
        await deduct_xp(player, 25, context)
        await sync_to_async(stats.save)()

        total_games = stats.wins + stats.loses
        if stats.loses >= 100:
            await unlock_achievement(player, "100_loses", context)
        if total_games >= 100:
            await unlock_achievement(player, "100_games", context)
        if total_games >= 500:
            await unlock_achievement(player, "500_games", context)

    # ─── 5) Increment dealer losses if dealer did NOT win overall ──────────────────
    if not dealer_won_overall:
        await sync_to_async(_increment_dealer_losses)()

# ─── Synchronous helper: increment dealer.wins ────────────────────────────────────
def _increment_dealer_wins():
    dealer = Dealer.objects.first()
    if dealer:
        dealer.wins += 1
        dealer.save()


# ─── Synchronous helper: increment dealer.loses ──────────────────────────────────
def _increment_dealer_losses():
    dealer = Dealer.objects.first()
    if dealer:
        dealer.loses += 1
        dealer.save()


async def check_for_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE, game, joined_players):
    chat_id = update.message.chat_id
    await asyncio.sleep(DRAMATIC_BEAT)

    if game.current_round > game.total_rounds:
        # ─── 1) Fetch all RoundWinner rows for this game ──────────────────────────────
        round_winners = await sync_to_async(list)(RoundWinner.objects.filter(game=game))

        # ─── 2) Count how many rounds each player won ─────────────────────────────────
        winner_count = {}
        for row in round_winners:
            winner_player = await sync_to_async(lambda: row.winner)()
            if winner_player:
                winner_count[winner_player] = winner_count.get(winner_player, 0) + 1

        # ─── 3) Count how many rounds the dealer won ─────────────────────────────────
        dealer_rounds_won = await sync_to_async(RoundWinner.objects.filter)(
            game=game, is_dealer=True
        )
        dealer_rounds_won = await sync_to_async(dealer_rounds_won.count)()
        print(f"[DEBUG] Dealer won {dealer_rounds_won} rounds")

        # If dealer won any rounds, put “dealer” into the map for ease of overall-winner logic:
        if dealer_rounds_won > 0:
            winner_count['dealer'] = dealer_rounds_won

        # ─── 4) Determine overall winner(s) ──────────────────────────────────────────
        if winner_count:
            max_wins = max(winner_count.values())
            overall_winners = [w for w, cnt in winner_count.items() if cnt == max_wins]

            # Boolean: did the dealer win the overall game?
            dealer_won_overall = ('dealer' in overall_winners)
            print(f"[DEBUG] overall_winners = {overall_winners}; dealer_won_overall = {dealer_won_overall}")

            if len(overall_winners) == 1:
                single = overall_winners[0]
                if single == 'dealer':
                    await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer is the overall winner of the game! 🏆")
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"{single.name} is the overall winner of the game! 🏆"
                    )

            else:
                # A tie for top number of rounds
                if len(overall_winners) == (len(joined_players) + 1) and dealer_won_overall:
                    # Everyone (all players + dealer) tied
                    for join_entry in joined_players:
                        player = await sync_to_async(lambda: join_entry.player)()
                        await unlock_achievement(player, "paid_back_tie", context)

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="All players and the dealer tied and shared the pot! 🏆 Everyone gets the `paid_back_tie` achievement."
                    )
                else:
                    # Multiple winners but not literally everyone
                    pieces = []
                    for w in overall_winners:
                        if w == 'dealer':
                            pieces.append("🤖 Dealer")
                        else:
                            pieces.append(f"[{w.name}](tg://user?id={w.id})")
                    text = ", ".join(pieces) + r" tied and shared the pot\! 🏆"
                    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")

            # ─── 5) Update stats for winners/losers ────────────────────────────────────
            # Pass dealer_won_overall (True/False) instead of raw dealer_rounds_won
            await update_statistics(overall_winners, dealer_won_overall, joined_players, context)
        else:
            await context.bot.send_message(chat_id=chat_id, text="No overall winner was determined.")

        # ─── 6) Finalize / clean up ─────────────────────────────────────────────────
        await end_game(update, context)

        # Prepare standings message (players vs. dealer by round-wins):
        await asyncio.sleep(SHORT_BEAT)
        standings = "📊 Current standings:\n"
        if dealer_rounds_won > 0:
            standings += f"🤖 Dealer: {dealer_rounds_won} round\\(s\\) won\n"
        else:
            standings += "🤖 Dealer: No wins yet\n"

        # Count only player‐round-winners (exclude dealer)
        player_round_winner_count = {}
        for row in await sync_to_async(list)(RoundWinner.objects.filter(game=game, is_dealer=False)):
            pl = await sync_to_async(lambda: row.winner)()
            player_round_winner_count[pl] = player_round_winner_count.get(pl, 0) + 1

        winners_list = []
        losers_list = []
        for join_entry in joined_players:
            pl = join_entry.player
            wins = player_round_winner_count.get(pl, 0)
            if wins > 0:
                winners_list.append((pl.name, wins, pl.id))
            else:
                losers_list.append((pl.name, pl.id))

        winners_list.sort(key=lambda x: x[1], reverse=True)

        for name, wins, uid in winners_list:
            esc = escape_markdown_v2(name)

            mention = f"[{esc}](tg://user?id={uid})"
            standings += f"🏆 {mention}: {wins} round\\(s\\) won\n"

        for name, uid in losers_list:
            esc = escape_markdown_v2(name)

            mention = f"[{esc}](tg://user?id={uid})"
            standings += f"🎲 {mention}: No wins yet\n"

        await context.bot.send_message(chat_id=chat_id, text=standings, parse_mode="MarkdownV2")

        # Finally delete the Game record and announce that the game has ended
        await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()
        await context.bot.send_message(
            chat_id=chat_id,
            text="The game has ended. You can start a new game by typing /startblackjack."
        )

    else:
        # ─── Not finished all rounds: reset for next round ─────────────────────────
        for jp in joined_players:
            await sync_to_async(
                JoinGame.objects.filter(pk=jp.pk, is_active=True).update
            )(has_stood=False)

        game.hands_reset = False
        await sync_to_async(game.save)()
        await asyncio.sleep(BEAT)
        await start_round(update, context, game, joined_players)

TURN_TIMEOUT_SECONDS = 30


async def _player_turn_timeout(update, context, game_id, player_id, token):
    await asyncio.sleep(TURN_TIMEOUT_SECONDS)
    result = await apply_player_timeout_async(game_id, player_id, token)
    if not result.applied:
        return
    try:
        player = await sync_to_async(Player.objects.get)(pk=player_id)
        escaped_name = escape_markdown(player.name, version=2)
        mention = f"[{escaped_name}](tg://user?id={player_id})"
        if result.removed:
            message = (
                f"⏱ {mention} did not act for 30 seconds twice in a row and "
                "was removed from this game\\."
            )
        else:
            message = (
                f"⏱ {mention} did not act within 30 seconds and was "
                "automatically skipped\\. One more consecutive timeout removes them\\."
            )
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text=message,
            parse_mode="MarkdownV2",
        )
    finally:
        await next_player_turn(update, context)


async def schedule_player_turn_timeout(update, context, game, player_id):
    try:
        token = await begin_player_turn_async(game.id, player_id)
    except (Game.DoesNotExist, JoinGame.DoesNotExist, ValueError):
        return
    asyncio.create_task(
        _player_turn_timeout(update, context, game.id, player_id, token)
    )


async def player_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        # Fetch the active game in the chat
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return
    # game.is_round_starting = False
    # await sync_to_async(game.save)()
    # Get the players in turn order for the current game
    players_in_game = await sync_to_async(list)(
        JoinGame.objects.filter(game=game, is_active=True).order_by('id')
    )

    # Check if turn order exists, initialize if not
    if not game.turn_order or game.current_round > 1:
        game.turn_order = await sync_to_async(list)(
            JoinGame.objects.filter(game=game, is_active=True).values_list('player__id', flat=True)
        )
        await sync_to_async(game.save)()

    # Get the current player from the turn order
    current_player_id = game.turn_order[0]
    current_player = await sync_to_async(Player.objects.get)(id=current_player_id)

    # user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', current_player.name)
    escaped_user_name = escape_markdown(current_player.name, version=2)

    mention = f"[{escaped_user_name}](tg://user?id={current_player.id})"

    if update.message.from_user.id == current_player_id:
        # Notify the current player it is their turn

        await asyncio.sleep(BEAT)  # Non-blocking sleep
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"{mention}, it's your turn\\! You have 30 seconds\\.",
            parse_mode="MarkdownV2",
            reply_markup=blackjack_turn_keyboard(),
        )
    else:
        # Notify others that the current player is making a decision
        await asyncio.sleep(BEAT)  # Non-blocking sleep
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🎯 {mention}, your turn\\! 30 seconds\\.",
            parse_mode="MarkdownV2",
            reply_markup=blackjack_turn_keyboard(),
        )
    await schedule_player_turn_timeout(update, context, game, current_player_id)


# # Escape special characters in the player's name

# Asynchronous version of safe_send_message
async def safe_send_message_async(bot, chat_id, text, parse_mode="MarkdownV2", max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            
            await asyncio.sleep(4)  # Non-blocking exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            
            await asyncio.sleep(retry_after)  # Non-blocking wait for the RetryAfter period before retrying
            retries += 1
    

async def is_on_cooldown(join_game, cooldown_seconds=ACTION_COOLDOWN_SECONDS):
    from django.utils import timezone
    if not join_game.last_action_time:
        return False
    return timezone.now() - join_game.last_action_time < timedelta(seconds=cooldown_seconds)

async def hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return
    # if game.is_round_starting:
    #     await update.message.reply_text("⏳ Please wait, the round is still starting.")
    #     return

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    try:
        join_game = await sync_to_async(JoinGame.objects.select_related('player').get)(player=player, game=game, is_active=True)
    except JoinGame.DoesNotExist:
        await update.message.reply_text("You are not part of the game.")
        return

    # Check if it's the player's turn
    try:
        print(f"[DEBUG] user_id: {user_id}")
        print(f"[DEBUG] turn_order: {game.turn_order}")

        if user_id != game.turn_order[0]:
            await update.message.reply_text("It's not your turn!")
            return
    except Exception as e:
        print(f"[ERROR] Checking turn: {e}")
        await update.message.reply_text("It's not your turn!")
        return
    if await is_on_cooldown(join_game):
        await update.message.reply_text("⏳ Please wait a few seconds before taking your next action.")
        return

    await record_player_action_async(game.id, user_id)
    join_game.consecutive_timeouts = 0
    join_game.turn_token = ""

    join_game.last_action_time = timezone.now()
    await sync_to_async(join_game.save)()

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    if hand_value > 21:
        await update.message.reply_text("You have already busted and cannot take any more actions.")
        return
    elif hand_value == 21:
        await update.message.reply_text("You are automatically standing and cannot take any more actions.")
        return
    # Add a card to the player's hand
    new_card = deal_card()
    join_game.hand.append(new_card)
    await sync_to_async(join_game.save)()

    # user_name_escaped = re.sub(r'([_*[\]()~>#+\-=|{}.!])', r'\\\1', user_name)
    escaped_user_name = escape_markdown(user_name, version=2)

    mention = f"[{escaped_user_name}](tg://user?id={user_id})"

    await safe_send_message_async(context.bot, chat_id, f"🃏 {mention} draws 『{new_card}』")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    
    await safe_send_message_async(context.bot, user_id, f"🃏 Your hand\n{format_hand(player_hand)}")
    # Check for bust or 21
    if hand_value == 21:
        join_game.has_stood = True
        await sync_to_async(join_game.save)()
        await asyncio.sleep(DRAMATIC_BEAT)
        stats = await sync_to_async(Stats.objects.get)(player=join_game.player)
        stats.how_many_21 += 1
        await sync_to_async(stats.save)()
        if stats.how_many_21 >= 21:
            await unlock_achievement(join_game.player, "21_black_jacks", context)
        if stats.how_many_21 >= 100:
            await unlock_achievement(join_game.player, "100_black_jacks", context)
        

        await safe_send_message_async(context.bot, chat_id, f"{mention} Reached BlackJack💥\\! \n They automatically stand\\.")
        await update_daily_quest_progress(player, "blackjack", "hitblackjack", 1, context)

        await add_xp(join_game.player, 30, context)
        
        await next_player_turn(update, context)
    elif hand_value > 21:
        insurance = await sync_to_async(PlayerActiveItem.objects.filter)(
            player=join_game.player,
            item_type="insurance_pass",
            is_active=True
        )
        insurance = await sync_to_async(insurance.first)()

        if insurance:
            await sync_to_async(insurance.delete)()

            # Remove last card and save hand
            join_game.hand.pop()
            await sync_to_async(join_game.save)()

            await safe_send_message_async(
                context.bot,
                chat_id,
                f"{mention} busted with {hand_value}, but 🛡️ *Insurance Pass* saved them\\!\nIt's still their turn\\.",
                parse_mode="MarkdownV2"
            )

            # Send updated hand to the player privately
            updated_hand = join_game.hand
            updated_value = calculate_hand_value(updated_hand)
            await safe_send_message_async(
                context.bot,
                user_id,
                f"🛡️ Insurance Pass activated\\!\n{format_hand(updated_hand)}"
            )
            await schedule_player_turn_timeout(update, context, game, user_id)
            return
        else:
            if hand_value >= 30:
                await update_daily_quest_progress(player, "blackjack", "30", 1, context)

                await unlock_achievement(join_game.player, "30_or_more_deck", context)
            await asyncio.sleep(DRAMATIC_BEAT)
            await deduct_xp(join_game.player, 20, context)
            await safe_send_message_async(context.bot, chat_id, f"💥 {mention} busts with {format_hand(player_hand)}")
            await next_player_turn(update, context)

    else:
        # Check for specific achievements (3 Aces or 3 Sixes)
        ace_count = sum(1 for card in player_hand if card == 'A')
        six_count = sum(1 for card in player_hand if card == 6)

        if ace_count == 3:
            await unlock_achievement(join_game.player, "3_A_in_one_deck", context)
        
        if six_count == 3:
            await unlock_achievement(join_game.player, "thriple_6_in_one_deck", context)

        await asyncio.sleep(DRAMATIC_BEAT)
        await context.bot.send_message(
            chat_id, f"🎯 {mention}: hit again or stand?", parse_mode="MarkdownV2",
            reply_markup=blackjack_turn_keyboard(),
        )
        await schedule_player_turn_timeout(update, context, game, user_id)

# Asynchronous stand function
async def stand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return
    # if game.is_round_starting:
    #     await update.message.reply_text("⏳ Please wait, the round is still starting.")
    #     return

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    try:
        join_game = await sync_to_async(JoinGame.objects.get)(player=player, game=game, is_active=True)
    except JoinGame.DoesNotExist:
        await update.message.reply_text("You are not part of the game.")
        return
    if join_game.has_stood:
        await update.message.reply_text("You have already chosen to stand and cannot take further actions.")
        return
    # Check if it's the player's turn
    try:
        if user_id != game.turn_order[0]:
            await update.message.reply_text("It's not your turn!")
            return
    except:
        player_hand = join_game.hand
        hand_value = calculate_hand_value(player_hand)

        # Prevent the player from standing if they have already busted
        if hand_value > 21:
            await update.message.reply_text("You have already busted and cannot stand.")
            return
        if hand_value == 21:
            await update.message.reply_text("You are automatically standing")
            return
        # Check if the player has already chosen to stand
    if await is_on_cooldown(join_game):
        await update.message.reply_text("⏳ Please wait a few seconds before taking your next action.")
        return

    await record_player_action_async(game.id, user_id)
    join_game.consecutive_timeouts = 0
    join_game.turn_token = ""

    join_game.last_action_time = timezone.now()
    await sync_to_async(join_game.save)()

    # Mark the player as having stood
    join_game.has_stood = True
    await sync_to_async(join_game.save)()

    # user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', user_name)
    escaped_user_name = escape_markdown(user_name, version=2)

    mention = f"[{escaped_user_name}](tg://user?id={user_id})"

    await safe_send_message_async(context.bot, chat_id, f"{mention} has chosen to stand\\.")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    if hand_value == 15:
        await update_daily_quest_progress(player, "blackjack", "15", 1, context)
    if hand_value == 5:
        await update_daily_quest_progress(player, "blackjack", "5", 1, context)
    if hand_value == 10:
        await update_daily_quest_progress(player, "blackjack", "10", 1, context)
    await asyncio.sleep(BEAT)

    await safe_send_message_async(context.bot, user_id, f"✋ You stand\n{format_hand(player_hand)}")

    # Move to the next player's turn
    await next_player_turn(update, context)


# # Function to move to the next player's turn
# # Move to the next player's turn by removing the current player from the turn order
async def safe_send_message_next_player_turn(bot, chat_id, text, max_retries=10):  # Increased timeout
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking sleep before retrying
    print("Failed to send the message after retries.")

# Asynchronous version of next_player_turn
async def next_player_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return
    # game.is_round_starting = False
    # await sync_to_async(game.save)()
    if not game.turn_order:
        # If no players are left in the turn order, proceed to the dealer's turn
        await dealer_turn(update, context)
        return

    # Remove the current player from the turn order
    game.turn_order.pop(0)
    await sync_to_async(game.save)()

    # Check if there are more players left to take their turn
    if game.turn_order:
        next_player_id = game.turn_order[0]
        next_player = await sync_to_async(Player.objects.get)(id=next_player_id)
        # user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', next_player.name)
        escaped_user_name = escape_markdown(next_player.name, version=2)
            
        mention = f"[{escaped_user_name}](tg://user?id={next_player_id})"
        await asyncio.sleep(DRAMATIC_BEAT)  # Non-blocking sleep

        await safe_send_message_next_player_turn(context.bot, chat_id, f"{mention}, it's your turn\\! You have 30 seconds\\. Type \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your hand\\.")
        await schedule_player_turn_timeout(update, context, game, next_player_id)
    else:
        # All players have finished their turns, now it's the dealer's turn
        await dealer_turn(update, context)

# Asynchronous version of safe_send_message_dealer
async def safe_send_message_dealer(bot, chat_id, text, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking sleep before retrying
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Non-blocking wait for the RetryAfter period before retrying
            retries += 1
    print("Failed to send the message after retries.")
# Dealer bust reactions
bust_reactions = [
    "Oops! I went over! 😅",
    "Busted! What a surprise! 😬",
    "Uh-oh! I got too greedy. Who would’ve thought? 😳",
    "Looks like I miscalculated. Shocking, right? 😟",
    "Oh no! I’m out! Guess I should have seen that coming! 😖",
    "Well, that didn’t work. Who knew? 😓",
    "I guess I went too far. Wow, what a revelation! 😔",
    "Oops, over the limit! You win this round. How original! 🙈",
    "I should’ve stopped sooner. Classic me! 🤦"
]


# Dealer win reactions
win_reactions = [
    "Better luck next time! Or, you know, maybe just give up! 😎",
    "I win! Care to try again, or is this a one-time deal? 😏",
    "The house always wins! Shocking, right? 🤑",
    "Nice try, but I’ve got this one. How cute! 😌",
    "I told you, I’m unbeatable! You really thought otherwise? 😈",
    "Dealer takes the round! Guess I’ll be here all night! 💪",
    "I got you this time! How unexpected! 😁",
    "Victory is mine! Not that anyone’s surprised! 🎉",
    "A win for the dealer! Ready for another round of disappointment? 🃏",
    "I came out on top this time! Who could’ve seen that coming? 💥"
]


blackjack_reactions = [
    "Blackjack! I’m unbeatable! Shocking, right? 😏",
    "21! Looks like I’ve won this one. What a twist! 🎯",
    "Boom! A perfect 21! Who would’ve guessed? 💥",
    "Blackjack! Can’t do better than that! But hey, keep trying! 🃏",
    "I hit 21! You didn’t stand a chance! Surprise! 😎",
    "Blackjack! The perfect hand. Who knew luck could be this one-sided? 🤑",
    "21! That’s as good as it gets! Try not to cry! 💣",
    "A flawless 21! I win! Again, who saw that coming? 👑",
    "Blackjack! I’m on fire today! Bet you wish you were too! 🔥",
    "21! The perfect game! You know, for me! ✨"
]

all_players_bust_reactions = [
    "Looks like everyone’s out! Guess I’ll just stand here. 😎",
    "Oh, you all busted? Easy win for me! What a surprise! 🃏",
    "Everyone busted? Guess I’ll take this one. How original! 😏",
    "Well, that was quick! I didn’t even have to try. Shocking! 😌",
    "All players busted! I’ll stand and take the win. How unexpected! 👑",
    "I didn’t even need to draw. You made it easy! Thanks for that! 🎉",
    "No cards left for me! You all busted! What a twist! 🃏",
    "Wow, everyone went over! I guess I’ll keep my cards. What a surprise! 💼",
    "Everyone busted? I’ll just take the win, no problem! Not even close! 😎",
    "No need to play it out, I win by default! Shocking outcome! 😈",
    "Well, well, well... looks like you couldn’t keep up! How surprising! 💥",
    "All of you busted? I guess the house wins again! Not that anyone saw that coming! 🏠",
    "Looks like I didn't need to try! I'll take the win. How original! 🎯",
    "You all went over 21? I guess I’ll stand here as the winner. Shocking! 👑",
    "That’s a wrap! Easy win for me. What a surprise! 💥"
]



async def dealer_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await safe_send_message_dealer(context.bot, chat_id, "No active game or the game has not started.")
        return
    if game.current_round == 1:
        await send_vote_results(update, context,chat_id,game.poll_id)

    await asyncio.sleep(BEAT)
    await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer's turn\\.\\.\\.")

    dealer_hand = game.dealer_hand
    dealer_value = calculate_hand_value(dealer_hand)

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(list)(JoinGame.objects.filter(game=game, is_active=True).select_related("player"))

    # If all players are busted, dealer automatically wins and stands
    if all_players_busted(entry.hand for entry in joined_players):
        await asyncio.sleep(BEAT)
        await safe_send_message_dealer(context.bot, chat_id, "🤖 All players have busted\\.")
        await asyncio.sleep(BEAT)

        reaction = random.choice(all_players_bust_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        await asyncio.sleep(BEAT)

        await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer wins🥇 this round\\!")
        
        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
        
        # Move to next round or end game
        game.current_round += 1
        await sync_to_async(game.save)()
        await check_for_next_round(update, context, game, joined_players)
        return  # Exit early since no more actions are needed

    # Fair casino rule: hit through 16 and stand on all 17s. The dealer does
    # not alter its decision after inspecting the players' totals.
    while dealer_should_hit(dealer_hand):
        # Draw a new card
        new_card = deal_card()
        dealer_hand.append(new_card)
        dealer_value = calculate_hand_value(dealer_hand)
        await asyncio.sleep(BEAT)
        await safe_send_message_dealer(context.bot, chat_id, f"🎩 Dealer draws 『{new_card}』\n{format_hand(dealer_hand)}")
        
        if dealer_value == 21:
            reaction = random.choice(blackjack_reactions)
            await safe_send_reaction(context.bot, chat_id, reaction)
            break

    # If dealer busts (> 21)
    if dealer_value > 21:
        await asyncio.sleep(BEAT)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer busts with a total of {dealer_value}\\!❌")
        reaction = random.choice(bust_reactions)
        await asyncio.sleep(BEAT)
        await safe_send_reaction(context.bot, chat_id, reaction)
    elif dealer_value == 21:
        await asyncio.sleep(BEAT)
    else:
        await asyncio.sleep(BEAT)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer stands with a total of {dealer_value}\\.")

    # Save the updated dealer hand
    game.dealer_hand = dealer_hand
    await sync_to_async(game.save)()

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(list)(JoinGame.objects.filter(game=game, is_active=True).select_related("player"))

    result = resolve_round(
        dealer_hand, [(entry.player, entry.hand) for entry in joined_players]
    )
    round_winners = list(result.winners)
    highest_valid_score = result.winning_value
    # Announce the winner(s)
    if not round_winners:
        await asyncio.sleep(BEAT)
        await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer wins🥇 this round\\!")
        reaction = random.choice(win_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
    else:
        for winner in round_winners:
            await asyncio.sleep(BEAT)
            try:
                # Try to tag the winner using their name

                try:
                    escaped_name = escape_markdown(winner.name, version=2)
                    mention = f"[{escaped_name}](tg://user?id={winner.id})"
                except Exception as e:
                    print(f"[WARN] Failed to escape or build MarkdownV2 mention for {winner.name}: {e}")
                    # user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', winner.name)
                    escaped_user_name = escape_markdown(winner.name, version=2)

                    mention = f"[{escaped_user_name}](tg://user?id={winner.id})"

                # mention = f"[{winner.name}](tg://user?id={winner.id})"
            except Exception as e:
                # Fallback to just using the player's name if tagging fails
                mention = winner.name
                print(f"Error tagging player {winner.name}: {str(e)}")
            await add_xp(winner, 5, context)

            await safe_send_message_dealer(context.bot, chat_id, f"{mention} 🥇wins this round with a hand of {highest_valid_score}\\!")
            if highest_valid_score == 10:
                await unlock_achievement(winner, "win_with_10", context)

            await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, winner=winner)

    # Proceed to the next round or end the game if all rounds are done
    game.current_round += 1
    await check_for_next_round(update, context, game, joined_players)


# Asynchronous version of reset_game
async def reset_game(chat_id):
    try:
        # Get the active game with the given chat_id
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)

        # Mark the game as ended and reset its fields
        game.ended = True
        game.started = False
        game.betting = False
        game.join_time = False
        await sync_to_async(game.save)()

        # Reset all players' is_active status to False for the current game
        await sync_to_async(JoinGame.objects.filter(game=game, is_active=True).update)(is_active=False)

    except Game.DoesNotExist:
        pass
async def end_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await context.bot.send_message(chat_id=chat_id, text="No active game to end.")
        return

    # Get the group's real money and VIP status
    try:
        group_game = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        await context.bot.send_message(chat_id=chat_id, text="Group not found.")
        return

    is_real_token_game = group_game.vip and group_game.real_money
    currency_type = "$" if is_real_token_game else "chips💰"

    # Get round winners and determine the final winner
    dealer_rounds_won = await sync_to_async(RoundWinner.objects.filter(game=game, is_dealer=True, rounds_ended=False).count)()
    player_rounds = await sync_to_async(list)(RoundWinner.objects.filter(game=game, is_dealer=False, rounds_ended=False))

    round_wins = {}
    for round_win in player_rounds:
        # Wrap access to the foreign key field in sync_to_async
        winner_player = await sync_to_async(lambda: round_win.winner)()
        if winner_player in round_wins:
            round_wins[winner_player] += 1
        else:
            round_wins[winner_player] = 1

    # Determine the highest number of rounds won
    max_rounds_won = max(max(round_wins.values(), default=0), dealer_rounds_won)

    # Check if any player won all 5 rounds
    if max_rounds_won == 5:
        # If dealer won all 5 rounds
        if dealer_rounds_won == 5:
            # Get all players who joined this game
            participants = await sync_to_async(list)(
                JoinGame.objects.filter(game=game).select_related("player")
            )

            for participant in participants:
                await unlock_achievement(participant.player, "Dealer_wins_5_rounds", context)

            await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer won all 5 rounds!")
        else:
            # If any player won all 5 rounds
            for winner, wins in round_wins.items():
                if wins == 5:
                    await unlock_achievement(winner, "win_5_rounds", context)
    # Find all winners (both dealer and players) who won the maximum number of rounds
    winners = [winner for winner, wins in round_wins.items() if wins == max_rounds_won]
    if dealer_rounds_won == max_rounds_won:
        winners.append('dealer')  # Include the dealer in the winners if they won the max rounds

    # Split the pot evenly among all winners
    if winners:
        MAIN_GROUP_ID = -1002424411318
        # MAIN_GROUP_ID = -1002568101357
    
        if int(chat_id) == MAIN_GROUP_ID:
            # Get all active players in this game
            all_players = await sync_to_async(list)(
                JoinGame.objects.filter(game=game, is_active=True).select_related("player")
            )

            winner_ids = [w.id for w in winners if w != "dealer"]

            # Calculate 10% cashback for each loser
            for join_entry in all_players:
                player = await sync_to_async(lambda: join_entry.player)()

                if player.id not in winner_ids:
                    cashback = int(game.bet_amount * 0.1)

                    if is_real_token_game:
                        player.real_tokens += cashback
                        await sync_to_async(player.save)(update_fields=("real_tokens",))
                    else:
                        await adjust_balance_async(
                            player,
                            cashback,
                            category=ChipTransaction.Category.REFUND,
                            description="Main group blackjack cashback",
                            reference_type="blackjack_game",
                            reference_id=game.id,
                            idempotency_key=f"blackjack:{game.id}:player:{player.id}:cashback",
                        )

                    await context.bot.send_message(
                        chat_id=player.id,
                        text=f"🪙 Since you played in the *Main Group*, you’ve received 10% ({cashback} {currency_type}) of your lost bet back!",
                        parse_mode="Markdown"
                    )

        split_pot = game.pot // len(winners)
        
        if 'dealer' in winners:
            winners.remove('dealer')
            dealer = await sync_to_async(Dealer.objects.get)(id=1)
            
            if is_real_token_game:
                dealer.real_tokens += split_pot
            else:
                dealer.chips += split_pot

            await sync_to_async(dealer.save)()
            await context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer wins {split_pot} {currency_type}!")

        for winner in winners:
            multiplier = 1
            active_items = await sync_to_async(list)(
                PlayerActiveItem.objects.filter(player=winner, is_active=True)
            )

            for item in active_items:
                if item.item_type == "double_chip_potion":
                    multiplier = 2
                elif item.item_type == "triple_chip_potion":
                    multiplier = 3
                elif item.item_type == "10x_chip_potion":
                    multiplier = 10

                if multiplier > 1:
                    await sync_to_async(item.delete)()
                    break  # Only one potion should apply

            final_reward = apply_potion_multiplier(split_pot, multiplier)

            if is_real_token_game:
                winner.real_tokens += final_reward
                await sync_to_async(winner.save)(update_fields=("real_tokens",))
                payout_applied = True
            else:
                payout_change = await adjust_balance_async(
                    winner,
                    final_reward,
                    category=ChipTransaction.Category.BLACKJACK_PAYOUT,
                    description="Blackjack game payout",
                    reference_type="blackjack_game",
                    reference_id=game.id,
                    idempotency_key=f"blackjack:{game.id}:player:{winner.id}:payout",
                    metadata={"multiplier": multiplier, "split_pot": split_pot},
                )
                payout_applied = payout_change.applied
            if payout_applied:
                await apply_referral_bonus(winner, final_reward, context)

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{winner.name} wins {final_reward} {currency_type}!"
            )


    else:
        await context.bot.send_message(chat_id=chat_id, text="No one won this game.")

    # Mark the game as ended
    game.ended = True
    game.started = False
    game.betting = False
    game.join_time = False
    await sync_to_async(game.save)()
    
# Asynchronous version of reset_round_state
async def reset_round_state(game):
    # Reset the hands and necessary state for the next round
    await sync_to_async(JoinGame.objects.filter(game=game, is_active=True).update)(hand=[])
    game.dealer_hand = []
    await sync_to_async(game.save)()



# Asynchronous version of get_player_instance
async def get_player_instance(user_id):
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        return player
    except ObjectDoesNotExist:
        return None

# Asynchronous version of get_player_chips
def format_number(n):
    units = [
        (10**33, 'D'),  # Decillion
        (10**30, 'N'),  # Nonillion
        (10**27, 'O'),  # Octillion
        (10**24, 'S'),  # Septillion
        (10**21, 's'),  # Sextillion
        (10**18, 'q'),  # Quintillion
        (10**15, 'Q'),  # Quadrillion
        (10**12, 'T'),  # Trillion
        (10**9,  'B'),  # Billion
        (10**6,  'M'),  # Million
        (10**3,  'K'),  # Thousand
    ]

    for value, suffix in units:
        if n >= value:
            return f"{n:,} ({n / value:.1f}{suffix})"

    return f"{n:,}"

async def get_player_chips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # Fetch the player instance
    player = await get_player_instance(user_id)

    if player:
        chips_display = format_number(player.chips)
        tokens_display = format_number(player.real_tokens)

        stats_message = (
            f"💰 Chips: {chips_display}\n"
            # f"💵 Real Tokens: {tokens_display}\n"
        )

        await context.bot.send_message(chat_id=update.message.chat_id, text=stats_message)
    else:
        await context.bot.send_message(
            chat_id=update.message.chat_id,
            text="You don't have a player profile yet. Start the bot in private to create one."
        )

# Asynchronous version of get_dealer_blackjack_stats
async def get_dealer_blackjack_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        dealer = await sync_to_async(Dealer.objects.first)()  # Assuming there's only one dealer
        if dealer is None:
            await context.bot.send_message(chat_id=chat_id, text="No dealer stats found.")
            return

        # Format the dealer stats into a readable format
        stats_message = (
            f"🤖 Dealer's Blackjack Stats:\n"
            f"💰 Chips: {dealer.chips}\n"
            f"💵 Real Tokens: {dealer.real_tokens}\n"
            f"Wins: {dealer.wins}\n"
            f"Losses: {dealer.loses}\n"
            f"💥 Blackjacks: {dealer.blackjack_count}"
        )
        
        # Send the stats message to the chat
        await context.bot.send_message(chat_id=chat_id, text=stats_message)

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error retrieving dealer stats: {str(e)}")
async def flee_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=True, ended=False)

        if game.started:
            await update.message.reply_text("The game has already started, you can no longer flee.")
            return

        join_instance = await sync_to_async(JoinGame.objects.get)(player_id=user_id, game=game, is_active=True)
        player = await sync_to_async(Player.objects.get)(id=user_id)
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)

        # Refund the player's bet (based on whether it was real tokens or chips)
        if group.vip and group.real_money:
            player.real_tokens += game.bet_amount
            await sync_to_async(player.save)(update_fields=("real_tokens",))
            await sync_to_async(join_instance.delete)()
        else:
            await refund_joined_player_async(
                join_instance.id,
                description="Player fled before blackjack started",
            )

        user_name_escaped = escape_markdown(update.message.from_user.first_name, version=2)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"[{user_name_escaped}](tg://user?id={user_id}) has fled the game and is no longer part of it\\.",
            parse_mode="MarkdownV2"
        )

    except Game.DoesNotExist:
        await update.message.reply_text("No active game to flee from in this chat.")
    except JoinGame.DoesNotExist:
        await update.message.reply_text("You are not currently part of the game.")


async def nextgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Add the user to the next game notification list
    _, created = await sync_to_async(NextGameNotification.objects.get_or_create)(user_id=user_id, chat_id=chat_id)

    if created:
        await update.message.reply_text("You will be notified when the next game starts!")
    else:
        await update.message.reply_text("You're already signed up to be notified when the next game starts.")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return

    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    chat_id = update.message.chat_id

    # Notify in group that help is in private chat
    if chat_id != user_id:
        await update.message.reply_text(
            "📩 A message with all available commands and instructions has been sent to your private chat."
        )

    # Full help text (plain text, no Markdown formatting)
    full_help = """
Blackjack Bot Help & Command Reference

How to Play a Group Blackjack Game:
  1. Any member types /startblackjack → bot opens a join window.  
  2. Players type /join (in that group) to reserve their seat and lock in their bet.  
  3. Once enough players have joined, use /forcestart to begin.  
  4. The bot deals two cards to each player privately, and two to itself (one face-down).  
  5. In turn order, each player privately chooses /hit or /stand.  
      – If a player’s hand > 21, they bust and lose immediately.  
  6. After all players finish, the dealer reveals the hidden card and draws until ≥ 17.  
  7. Settlement:
      – Dealer higher or tie → player loses.   
  8. XP is awarded/lost accordingly (see “XP & Leveling”).  
      – Winners gain XP, losers lose XP.

────────────────────────────────────────
Getting Started:
  • /start  
    – Register yourself with the bot. You’ll receive 200 chips to begin.

  • /help  
    – Show this help message again (sent to your private chat).

  • /rules  
    – Display detailed rules of the Blackjack game.

  • /stats  
    – View your personal statistics (wins, losses, XP, level, etc.).

  • /nextgame  
    – Ask the bot to send you a private reminder when the next game starts.

────────────────────────────────────────
Blackjack Game Flow:
1) /startblackjack  
   – Initiate a new Blackjack game in the group. The bot will open a “join” period during which players can enter.

2) /join  
   – Join the current game (during the join window). You must have at least the minimum bet in your chips to enter.  
   – As soon as you tap /join, the bot will deduct the required amount from your chips.

3) /forcestart  
   –  Use this command to start the game. Once forced, no new players can join.  
   – The dealer (bot) also contributes the same bet amount. Cards are dealt to each player.

4) During your turn:
   • /hit  
     – Draw one more card. If your hand exceeds 21, you bust and lose immediately.

   • /stand  
     – Keep your current hand and end your turn. The next player goes, and eventually the dealer completes their hand.

   • /flee  
     – Leave the current Blackjack game (forfeit your bet).



────────────────────────────────────────
Minigames & Side Games:
  These can be played anytime in private chat or group. Use /minigames to see a detailed list of them.
  • /dice [betamount]  
    – Roll two dice and guess the outcome. Win up to 6× your bet.

  • /slot [betamount]  
    – Pull the slot machine lever. Match symbols to win big.

  • /coin [heads/tails] [betamount]  
    – Flip a coin. Guess correctly for a 1.9× gross payout.

  • /draw [betamount]  
    – Draw a random card. Higher card wins against the bot’s draw.

  • /rps [rock/paper/scissors] [betamount]  
    – Play Rock-Paper-Scissors against the bot. Win or tie.

  • /dart  
    – /dart [chip amount]
  
  • /spin - Spin the wheel once a day for a chance to win chips, XP, or levels! Type /spin <low/mid/high> and let the wheel decide your fate
    
  • /roulette - Bet on red, black, or a number (0-36). Usage: /roulette <red|black|0-36> <bet amount>
       If you guess the color, you win double; if you guess the number, you win 35 times your bet! Good luck!
────────────────────────────────────────
Economy & Token Commands:
  • /my_tokens  
    – Show your current chip balance.

  • /claim_tokens  
    – Claim free chips twice per day (if available).

────────────────────────────────────────
Achievements & Rewards:
  • /achievements  
    – View your unlocked achievements and progress toward new ones.

  • /achievements_info  
    – Display how to unlock each achievement (conditions and icons).

  – Achievements grant bonus XP when unlocked (+20 XP each).

────────────────────────────────────────
XP & Leveling System:
  – You earn XP by playing and winning:
      • Play any game: +10 XP  
      • Win a Blackjack round: +5 XP  
      • Win a full Blackjack game: +25 XP  
      • Get Blackjack: +30 XP  
      • Unlock an achievement: +20 XP  

  – You lose XP for poor performance:
      • Bust in a hand: –20 XP  
      • Lose a full Blackjack game: –25 XP  

  – Each level requires 50 XP × current level. Example:
      • Level 1 → need 50 XP to reach Level 2  
      • Level 2 → need 100 XP to reach Level 3 (and so on)

  – Check your progress with /stats (shows “XP to next level”).

────────────────────────────────────────
Loan System:
  • /loan [amount]  
    – Borrow chips. For every 100 chips borrowed, you lose 5 XP.  
      • If you don’t have enough XP, you may lose levels instead.

  • /repay_loan  
    – Repay your outstanding loan plus 3% interest.  
      • E.g., if you borrowed 100 chips, you must repay 103 chips.


────────────────────────────────────────
Use these commands any time the bot is in a chat. If you need more help, type /help again.

Good luck and have fun! 🃏🎉
"""

    # Split into 4000-character chunks
    max_length = 4000
    chunks = []
    text = full_help.strip()
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Find last newline before max_length to avoid splitting mid-line
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        chunks.append(text[:split_pos].rstrip())
        text = text[split_pos:].lstrip()

    # Send each chunk as plain text
    for chunk in chunks:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=chunk
            )
        except Exception as e:
            await record_telegram_failure(
                e, player_id=user_id, chat_id=user_id, message_type="help_message"
            )
            break


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return

    user_id = update.message.from_user.id

    # Inform user in the group chat
    await update.message.reply_text("📩 A message with the game rules has been sent to your private chat.")

    # Send the rules message to the user's private chat
    rules_text = """
    🎮 *Blackjack Game Rules* 🎮
    
    The goal of the game is to get as close to 21 as possible without going over.
    
    *Basic Rules*:
    
    1. Each player is dealt two cards, and they can choose to "hit" to get more cards or "stand" to keep their hand.
    2. Numbered cards (2-10) are worth their face value.
    3. Face cards (Jack, Queen, King) are worth 10 points each.
    4. Aces can be worth either 1 or 11 points, depending on what benefits the player.
    
    *Game Flow*:
    
    - Players take turns to either hit or stand.
    - The goal is to reach 21 or as close to it as possible without going over (busting).
    - If a player’s total goes over 21, they lose automatically (bust).
    - If all players bust, the dealer wins the round.

    *Dealer Rules*:
    
    - The dealer will also draw cards but must stand if their total is 18 or higher.
    - The dealer must hit if their total is 16 or lower.
    
    *Betting*:
    
    - Players can place bets before the game starts.
    - The total bet amount is divided among the winners, or goes to the dealer if all players bust.
    
    *Winning*:
    
    - The player closest to 21 without busting wins the round.
    - If the dealer busts and all players stand with a valid hand, the highest hand wins.
    
    Enjoy the game, and good luck! 🍀
    """
    await context.bot.send_message(chat_id=user_id, text=rules_text, parse_mode="Markdown")








async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    chat_name = update.message.chat.title  # Get the group's name
    args = context.args

    if len(args) != 1 or args[0] not in ["real_token", "chips"]:
        await update.message.reply_text(
            "Invalid usage. Use /set_status real_token or /set_status chips."
        )
        return

    try:
        # Fetch the group from the database based on chat_id
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        # If group doesn't exist, create a new one and set the name
        group = await sync_to_async(Group.objects.create)(group_chat_id=chat_id, group_name=chat_name)

    # Update the group name if it has changed
    if group.group_name != chat_name:
        group.group_name = chat_name

    # Check if the group is VIP
    if group.vip:
        # Set status based on the command argument
        if args[0] == "real_token":
            group.real_money = True
            await update.message.reply_text("This group is now using 💵real tokens for the next games.")
        else:
            group.real_money = False
            await update.message.reply_text("This group is now using 💰chips for the next games.")
    else:
        # If group is not VIP, always use chips
        group.real_money = False
        await update.message.reply_text("This group is not VIP. Using chips for the next games.")

    # Save the updated group settings
    await sync_to_async(group.save)()







ADMIN_CHAT_ID = '1628536823'

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Ensure the message is sent in private chat (user_id == chat_id)
    if chat_id == user_id:
        # Get the player's profile information
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
            profile_info = (
                f"Player Profile:\n"
                f"Name: {player.name}\n"
                f"Chips: {player.chips}\n"
                f"Games Played: {player.games}\n"
                f"Real Tokens: {player.real_tokens}\n"
            )
        except ObjectDoesNotExist:
            profile_info = "Player profile not found."

        # Get the highest resolution of the photo
        photo_file = update.message.photo[-1].file_id
        caption = update.message.caption if update.message.caption else "No caption"

        # Combine the caption with the player's profile info
        message_text = f"Photo from {update.message.from_user.first_name} (ID: {user_id})\n\n{profile_info}\nCaption: {caption}"

        # Forward the photo to your own private chat
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file,
            caption=message_text
        )

        # Optionally, send a confirmation message to the user
        await update.message.reply_text("Your photo and profile have been forwarded to the admin.")
    else:
        pass
        # await update.message.reply_text("Please send the photo in private chat.")


# Only new private messages: edited messages carry no ``update.message`` and
# group photos are ignored by handle_photo anyway.
photo_handler = MessageHandler(
    filters.PHOTO & filters.ChatType.PRIVATE & filters.UpdateType.MESSAGE,
    handle_photo,
)


async def buy_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_name = update.message.from_user.first_name

    # Define the credit card number and token buying details
    credit_card_info = "Credit Card Number: \n6219 8619 4904 7871\nهیربد افلاکی "
    token_info = "💵Each 100 real tokens is : 10 Toman\\."

    # Check if the message was sent in a group or private chat
    if chat_id != user_id:
        # If in a group, notify the user that the message will be sent privately
        await context.bot.send_message(chat_id=chat_id, text="A message has been sent to your private chat with the payment details.")
    
    # Send the message with credit card info and token buying options to the user's private chat
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Hello {user_name},\n\n{token_info}\n{credit_card_info}",
        parse_mode="MarkdownV2"
    )

    # Optionally log or notify in case of failure to send to private chat
    try:
        await context.bot.send_message(chat_id=user_id, text="Send the image here, after the PURCHASE was DONE")
    except Exception as e:
        print(f"Error sending message to user {user_id}: {e}")
# Function to give tokens (real or fake) only if the player is admin
async def give_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    try:
        # Check if the player exists and is an admin
        player = await sync_to_async(Player.objects.get)(id=user_id)
        
        if not player.admin:
            await update.message.reply_text("You do not have permission to use this command.")
            return

        # Parse arguments: token type, target player id, and amount
        args = context.args
        if len(args) != 3 or args[0] not in ["real_token", "chips"]:
            await update.message.reply_text("Usage: /give_token real_token|chips [user_id] [amount]")
            return
        
        token_type = args[0]
        target_user_id = args[1]
        amount = int(args[2])

        # Fetch the target player
        try:
            target_player = await sync_to_async(Player.objects.get)(id=target_user_id)
        except ObjectDoesNotExist:
            await update.message.reply_text(f"Player with ID {target_user_id} does not exist.")
            return

        # Update the player's tokens
        if token_type == "real_token":
            target_player.real_tokens += amount
            await update.message.reply_text(f"{amount} 💵 real tokens have been given to {target_player.name}.")
        else:
            await adjust_balance_async(
                target_player,
                amount,
                category=ChipTransaction.Category.ADMIN_ADJUSTMENT,
                description=f"Telegram admin adjustment by player {player.id}",
                reference_type="telegram_admin",
                reference_id=player.id,
            )
            await update.message.reply_text(f"{amount} 💰 chips have been given to {target_player.name}.")

        # Save the changes
        if token_type == "real_token":
            await sync_to_async(target_player.save)(update_fields=("real_tokens",))

        # Send a private message to the target player
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"{amount} {'💵 real tokens' if token_type == 'real_token' else '💰 chips'} have been given to you by the admin."
        )
    except ObjectDoesNotExist:
        await update.message.reply_text("You are not registered as a player.")

async def get_player_user_id(player_name: str):
    try:
        # Fetch the player by name
        player = await sync_to_async(Player.objects.get)(name=player_name)
        return player.id  # The user_id from the Player model
    except ObjectDoesNotExist:
        return None

# Command handler for /get_user_id
async def get_user_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Please provide a player name. Usage: /get_user_id [player_name]")
        return
    
    player_name = context.args[0]
    
    # Retrieve the user ID
    user_id = await get_player_user_id(player_name)

    if user_id:
        await update.message.reply_text(f"User ID for {player_name} is {user_id}.")
    else:
        await update.message.reply_text(f"Player with the name {player_name} was not found.")
