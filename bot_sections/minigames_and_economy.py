from django.db import transaction




async def save_player(player):
    """Ensures player data is saved asynchronously."""
    await sync_to_async(player.save)()

async def validate_bet_amount(update, bet_amount):
    if bet_amount <= 0:
        await update.message.reply_text("❌ Invalid bet amount. It must be a positive number.")
        return False
    return True


async def place_minigame_bet(player, amount, game_name, operation_id):
    await ensure_betting_open_async()
    return await adjust_balance_async(
        player,
        -amount,
        category=ChipTransaction.Category.BET,
        description=f"{game_name} bet",
        reference_type="minigame",
        reference_id=game_name,
        idempotency_key=f"minigame:{game_name}:{operation_id}:bet",
    )


async def settle_minigame(player, amount, game_name, operation_id, *, refund=False):
    return await adjust_balance_async(
        player,
        amount,
        category=(
            ChipTransaction.Category.REFUND
            if refund
            else ChipTransaction.Category.MINIGAME_PAYOUT
        ),
        description=f"{game_name} {'refund' if refund else 'payout'}",
        reference_type="minigame",
        reference_id=game_name,
        idempotency_key=f"minigame:{game_name}:{operation_id}:settlement",
    )

# games------------------------------
async def slot_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)
    
    user_id = update.message.from_user.id
    bet_amount = int(context.args[0]) if context.args else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips to spin the slot machine!")
        return

    # Deduct the bet amount
    try:
        await place_minigame_bet(player, bet_amount, "slot", update.update_id)
    except BettingPaused:
        await update.message.reply_text("New bets are temporarily paused by an operator.")
        return
    except InsufficientChips:
        await update.message.reply_text("You don't have enough chips to spin the slot machine!")
        return

    # Possible slot symbols
    slot_symbols = ['🍒', '🍋', '💰', '🍀', '🔔', '⭐']

    # Send the initial message
    message = await update.message.reply_text('🎰 Spinning...')

    # Simulate spinning effect
    spinning_texts = [
        '🎰 Spinning... 🍒 | 🍋 | 💰',
        '🎰 Spinning... 🍀 | 💰 | 🔔',
        '🎰 Spinning... ⭐ | 🍋 | 🍒',
        '🎰 Spinning... 🔔 | ⭐ | 🍀',
        '🎰 Spinning... 🍒 | 💰 | ⭐'
    ]

    for text in spinning_texts:
        await message.edit_text(text)
        await asyncio.sleep(1)

    # Final result
    slot_result = [random.choice(slot_symbols) for _ in range(3)]
    result_text = ' | '.join(slot_result)

    winnings = 0  # Initialize winnings

    # Check winning conditions
    if len(set(slot_result)) == 1:  # Jackpot (all symbols match)
        winnings = bet_amount * SLOT_JACKPOT_MULTIPLIER
    elif slot_result[0] == slot_result[1] or slot_result[1] == slot_result[2]:  # Two match
        winnings = bet_amount * SLOT_PAIR_MULTIPLIER

    # Update player chips if won
    if winnings > 0:
        settlement = await settle_minigame(player, winnings, "slot", update.update_id)
        if settlement.applied:
            await apply_referral_bonus(player, winnings, context)
        await update_daily_quest_progress(player, "minigames", "slot", 1, context)

        await message.edit_text(f"🎰 {result_text} 🎰\nYou win {winnings} chips! 🎉")
    else:
        await message.edit_text(f"🎰 {result_text} 🎰\nNo match! You lose your bet. 😢")




async def coinflip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(1)

    user_id = update.message.from_user.id
    guess = context.args[0].lower() if context.args else 'heads'  # Default to heads if no argument
    bet_amount = int(context.args[1]) if len(context.args) > 1 else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if guess not in ['heads', 'tails']:
        await update.message.reply_text("Please choose either 'heads' or 'tails'.")
        return

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Deduct the bet amount
    try:
        await place_minigame_bet(player, bet_amount, "coin", update.update_id)
    except BettingPaused:
        await update.message.reply_text("New bets are temporarily paused by an operator.")
        return
    except InsufficientChips:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Send the initial "spinning" message
    message = await update.message.reply_text("🪙 Flipping the coin...")

    # Simulate the flipping effect with several edits
    flip_animation = ['🪙 Heads...', '🪙 Tails...']

    for flip in flip_animation:
        await message.edit_text(flip)
        await asyncio.sleep(1.5)

    # Final coin flip result
    flip_result = random.choice(['heads', 'tails'])

    if flip_result == guess:
        winnings = standard_win_payout(bet_amount)
        settlement = await settle_minigame(player, winnings, "coin", update.update_id)
        if settlement.applied:
            await apply_referral_bonus(player, winnings, context)
        await update_daily_quest_progress(player, "minigames", "coin", 1, context)

        await message.edit_text(f"🪙 Coin landed on {flip_result.capitalize()}! You win {winnings} chips!")
    else:
        await message.edit_text(f"🪙 Coin landed on {flip_result.capitalize()}! You lose your bet.")

cards = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
card_values = {card: index for index, card in enumerate(cards, start=2)}

async def lucky_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)

    user_id = update.message.from_user.id
    bet_amount = int(context.args[0]) if context.args else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Deduct the bet amount
    try:
        await place_minigame_bet(player, bet_amount, "draw", update.update_id)
    except BettingPaused:
        await update.message.reply_text("New bets are temporarily paused by an operator.")
        return
    except InsufficientChips:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Send the initial message
    message = await update.message.reply_text("🃏 Drawing your card...")

    # Draw player's card
    await asyncio.sleep(2)  # Wait to build suspense
    player_card = random.choice(cards)
    await message.edit_text(f"🃏 You drew: {player_card}")

    # Wait a bit and simulate dealer's turn
    await asyncio.sleep(2)
    await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer is drawing a card...")

    # Draw dealer's card
    await asyncio.sleep(2)  # More suspense before revealing
    bot_card = random.choice(cards)
    await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}")

    # Compare card values
    player_card_value = card_values[player_card]
    bot_card_value = card_values[bot_card]

    # Determine the result after a short pause
    await asyncio.sleep(2)

    if player_card_value > bot_card_value:
        winnings = standard_win_payout(bet_amount)
        settlement = await settle_minigame(player, winnings, "draw", update.update_id)
        if settlement.applied:
            await apply_referral_bonus(player, winnings, context)

        await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}\n\nYou win {winnings} chips!")
    elif player_card_value == bot_card_value:
        await settle_minigame(
            player, bet_amount, "draw", update.update_id, refund=True
        )
        await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}\n\nIt's a tie! You get your bet back.")
    else:
        await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}\n\nYou lose your bet.")



choices = ['rock', 'paper', 'scissors']
choice_emojis = {'rock': '🪨', 'paper': '📄', 'scissors': '✂️'}

# Rock-Paper-Scissors game
async def rps_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)

    user_id = update.message.from_user.id
    # Parse the player's choice and the bet amount from the command
    player_choice = context.args[0].lower() if len(context.args) > 0 else 'rock'  # Default to rock
    bet_amount = int(context.args[1]) if len(context.args) > 1 else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if player_choice not in choices:
        await update.message.reply_text("Please choose either 'rock', 'paper', or 'scissors'.")
        return

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    # Check if the player has enough chips for the bet
    if player.chips < bet_amount:
        await update.message.reply_text(f"You don't have enough chips to place a bet of {bet_amount}!")
        return

    # Deduct the bet amount
    try:
        await place_minigame_bet(player, bet_amount, "rps", update.update_id)
    except BettingPaused:
        await update.message.reply_text("New bets are temporarily paused by an operator.")
        return
    except InsufficientChips:
        await update.message.reply_text(f"You don't have enough chips to place a bet of {bet_amount}!")
        return

    # Initial message
    message = await update.message.reply_text(f"👊 You chose {choice_emojis[player_choice]} {player_choice.capitalize()}!\nWaiting for the dealer...")

    # Simulate dealer's choice with suspense
    await asyncio.sleep(2)
    # The opponent learns only from previous rounds and deliberately predicts
    # correctly at a limited rate; it never counters the current command by peeking.
    bot_choice = await sync_to_async(choose_and_record_rps, thread_sensitive=True)(user_id, player_choice)
    await message.edit_text(f"👊 You chose {choice_emojis[player_choice]} {player_choice.capitalize()}!\n🤖 Dealer is thinking...")

    await asyncio.sleep(2)
    await message.edit_text(f"👊 You chose {choice_emojis[player_choice]} {player_choice.capitalize()}!\n🤖 Dealer chose {choice_emojis[bot_choice]} {bot_choice.capitalize()}!")

    # Compare choices and determine the outcome
    await determine_rps_winner(
        player_choice, bot_choice, player, message, bet_amount, context, update.update_id
    )


# Determine the winner of the Rock-Paper-Scissors game
async def determine_rps_winner(
    player_choice, bot_choice, player, message, bet_amount, context, operation_id
):
    # Rules of Rock-Paper-Scissors
    win_conditions = {
        'rock': 'scissors',
        'scissors': 'paper',
        'paper': 'rock'
    }

    # Win, lose, or tie
    if player_choice == bot_choice:
        await settle_minigame(player, bet_amount, "rps", operation_id, refund=True)
        await asyncio.sleep(2)
        await message.edit_text(f"🤝 It's a tie! You get your bet of {bet_amount} chips back!")
    elif win_conditions[player_choice] == bot_choice:
        winnings = standard_win_payout(bet_amount)
        settlement = await settle_minigame(player, winnings, "rps", operation_id)
        await asyncio.sleep(2)
        if settlement.applied:
            await apply_referral_bonus(player, winnings, context)

        await message.edit_text(f"🎉 You win! {choice_emojis[player_choice]} beats {choice_emojis[bot_choice]}!\nYou win {winnings} chips!")
    else:
        await asyncio.sleep(2)
        await message.edit_text(f"😔 You lose! {choice_emojis[bot_choice]} beats {choice_emojis[player_choice]}!\nYou lose your bet of {bet_amount} chips.")

CRASH_SPEED = 0.6  # seconds per tick

async def simulate_crash_game(game_id, bot, chat_id):
    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)
    try:
        game = await sync_to_async(CrashGame.objects.get)(id=game_id)
    except CrashGame.DoesNotExist:
        return

    # Every player uses the same range. Operators may explicitly enable a
    # temporary event range; outcomes never depend on hardcoded user IDs.
    minimum = params.crash_min if params.crash_event else params.crash_min_unrigged
    maximum = params.crash_max if params.crash_event else params.crash_max_unrigged
    crash_point = round(random.uniform(minimum, maximum), 2)


    print(f"Crash point: {crash_point}")

    multiplier = 0.6
    try:
        msg = await bot.send_message(chat_id=chat_id, text=f"🚀 Starting at {multiplier}x")
    except Exception as e:
        print(f"❌ Failed to send start message: {e}")
        return


    while multiplier < crash_point:
        multiplier = round(multiplier + 0.6, 2)
        await asyncio.sleep(CRASH_SPEED)

        game_exists = await sync_to_async(CrashGame.objects.filter(id=game_id).exists)()
        if not game_exists:
            return

        await sync_to_async(CrashGame.objects.filter(id=game_id).update)(multiplier=multiplier)

        is_cashed_out = await sync_to_async(
            lambda: CrashGame.objects.filter(id=game_id, cashed_out=True).exists()
        )()
        if is_cashed_out:
            return

        try:
            await msg.edit_text(f"🚀 {multiplier}x")
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Exception:
            continue

    if not await mark_crash_game_crashed_async(game_id):
        return

    final_text = f"💥 Crashed at {crash_point}x! You lost your bet."
    try:
        await msg.edit_text(final_text)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await msg.edit_text(final_text)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=final_text)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=final_text)

    await sync_to_async(CrashGame.objects.filter(id=game_id).delete)()

# Your command
async def crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    bet = int(context.args[0]) if context.args else 100

    if not await validate_bet_amount(update, bet):
        return

    try:
        crash_game = await start_crash_game_async(user_id, bet)
    except ActiveCrashGame:
        return await update.message.reply_text(
            "🚫 You already have a crash game running. Use /cashout to end it."
        )
    except BettingPaused:
        return await update.message.reply_text(
            "New bets are temporarily paused by an operator."
        )
    except InsufficientChips:
        return await update.message.reply_text("❌ Not enough chips.")

    # Don't send "Game started" here – it's now inside simulate_crash_game
    asyncio.create_task(simulate_crash_game(crash_game.id, context.bot, chat_id))


async def cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    try:
        settlement = await cash_out_crash_game_async(user_id)
    except NoActiveCrashGame:
        return await update.message.reply_text("⚠️ You have no active game to cash out from.")
    winnings = settlement.winnings
    cashout_point = settlement.multiplier
    player = await sync_to_async(Player.objects.get)(id=user_id)
    if settlement.balance_change.applied:
        await apply_referral_bonus(player, winnings, context)
    if cashout_point == 1.6:
        await update_daily_quest_progress(player, "minigames", "1.6", 1, context)
    if cashout_point == 1.8:
        await update_daily_quest_progress(player, "minigames", "1.8", 1, context)
    if cashout_point == 1.4:
        await update_daily_quest_progress(player, "minigames", "1.4", 1, context)
    if cashout_point == 2.4:
        await update_daily_quest_progress(player, "minigames", "2.4", 1, context)
    await update.message.reply_text(
        f"✅ Cashed out at {settlement.multiplier}x!\n💰 You won {winnings} chips!"
    )




async def double_or_nothing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Parse bet amount
    bet_amount = int(context.args[0]) if context.args else 50
    if not await validate_bet_amount(update, bet_amount):
        return

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("❌ You don't have enough chips for that bet.")
        return

    # Deduct the bet
    try:
        await place_minigame_bet(player, bet_amount, "double", update.update_id)
    except BettingPaused:
        await update.message.reply_text("New bets are temporarily paused by an operator.")
        return
    except InsufficientChips:
        await update.message.reply_text("❌ You don't have enough chips for that bet.")
        return

    # await asyncio.sleep(0.5)  # Short suspense
    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)

    win_chance = min(max(params.double_chance, 0.0), 0.52)
    if random.random() >= win_chance:
        await update.message.reply_text("😵 You lost your bet. Nothing ❌doubled today.")
    else:
        winnings = standard_win_payout(bet_amount)
        settlement = await settle_minigame(player, winnings, "double", update.update_id)
        if settlement.applied:
            await apply_referral_bonus(player, winnings, context)
        if bet_amount >= 50000:
            await update_daily_quest_progress(player, "minigames", "double50", 1, context)
        if bet_amount >= 200000:
            await update_daily_quest_progress(player, "minigames", "double200", 1, context)
        if bet_amount >= 500000:
            await update_daily_quest_progress(player, "minigames", "double500", 1, context)
        await update.message.reply_text(
            f"🎉 Lucky! You doubled your bet and won {winnings} chips💰!\n"

        )

async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)
    user_id = update.message.from_user.id
    bet_amount = int(context.args[0]) if context.args else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Deduct the bet amount
    try:
        await place_minigame_bet(player, bet_amount, "dice", update.update_id)
    except BettingPaused:
        await update.message.reply_text("New bets are temporarily paused by an operator.")
        return
    except InsufficientChips:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Roll the dice using Telegram's dice feature
    message = await context.bot.send_dice(chat_id=update.message.chat_id, emoji="🎲")

    # Wait for a second for dice to roll
    await asyncio.sleep(4)

    dice_value = message.dice.value  # Get the dice value (1-6)

    # Determine win/loss based on the dice value
    if dice_value > 4:
        winnings = bet_amount * 2
        settlement = await settle_minigame(player, winnings, "dice", update.update_id)
        if settlement.applied:
            await apply_referral_bonus(player, winnings, context)
        await update_daily_quest_progress(player, "minigames", "dice", 1, context)

        await update.message.reply_text(f"🎲 Dice rolled a {dice_value}!\nYou win {winnings} chips!")
    else:
        await update.message.reply_text(f"🎲 Dice rolled a {dice_value}!\nYou lose your bet of {bet_amount} chips.")


from django.db.models import F, Sum, Count
from asgiref.sync import sync_to_async

# Utility function to truncate player names and ensure it doesn't exceed 8 characters
def format_name(name, max_length=8):
    truncated_name = (name[:max_length - 3] + '...') if len(name) > max_length else name
    return f"{truncated_name:<{max_length}}"

# Utility function to format the leaderboard row with monospaced text
def format_leaderboard_row(index, name, wins, tokens):
    # Adjust spacing to account for emojis and varying name lengths
    return f"`{index:<2}. {name:<8} 🏆 Wins: {wins:<3}  💰 Chips: {tokens:<7}`"

# Function to fetch the global leaderboard with top 5 players
async def get_global_leaderboard():
    # Fetching top players based on total wins
    top_players = await sync_to_async(list)(
        Stats.objects.select_related('player')
        .annotate(total_wins=F('wins'))  # Total wins
        .order_by('-total_wins')[:5]  # Fetch top 5 players
    )

    leaderboard = []
    for index, stats in enumerate(top_players, 1):
        formatted_name = format_name(stats.player.name)
        leaderboard.append(
            format_leaderboard_row(
                index=index,
                name=formatted_name,
                wins=stats.wins,
                tokens=stats.player.chips
            )
        )

    return leaderboard

# Function to fetch the user's position and show 2 players above and 2 below
async def get_user_rank(user_id):
    # Fetch all players ordered by wins
    all_players = await sync_to_async(list)(
        Stats.objects.select_related('player')
        .annotate(total_wins=F('wins'))
        .order_by('-total_wins')
    )

    # Find the user's position
    user_rank = None
    leaderboard = []
    for index, stats in enumerate(all_players, 1):
        if stats.player.id == user_id:
            # Get two players above and two below
            start = max(index - 3, 0)
            end = min(index + 2, len(all_players))
            nearby_players = all_players[start:end]

            # Format the leaderboard for nearby players
            for idx, player_stats in enumerate(nearby_players, start=start+1):
                formatted_name = format_name(player_stats.player.name)
                leaderboard.append(
                    format_leaderboard_row(
                        index=idx,
                        name=formatted_name,
                        wins=player_stats.wins,
                        tokens=player_stats.player.chips
                    )
                )

            user_rank = index
            break

    return leaderboard, user_rank
# Command to show the global leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # Get top 5 players
    top_5_leaderboard = await get_global_leaderboard()

    # Get the user's rank and nearby players
    user_leaderboard, user_rank = await get_user_rank(user_id)

    # Build the leaderboard message
    if top_5_leaderboard:
        top_5_text = "\n".join(top_5_leaderboard)
        message = f"🌍 *Global Leaderboard* 🌍\n\n{top_5_text}\n\n"
    else:
        message = "No players have ranked yet.\n\n"

    # Add user's position to the message
    if user_leaderboard:
        user_leaderboard_text = "\n".join(user_leaderboard)
        message += f"🏅 *Your Position* (Rank {user_rank}):\n{user_leaderboard_text}"
    else:
        message += "You haven't played enough games to be ranked yet."

    # Send the formatted leaderboard message
    await update.message.reply_text(message)

async def minigames(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    text = (
        "🎮 *Available Minigames* 🎮\n\n"
        "🎲 `/dice` – Roll a dice and test your luck! (`/dice [chips amount]`)\n\n"
        "🎰 `/slot` – Try your luck at the slot machine. Will you hit the jackpot? (`/slot [chips amount]`)\n\n"
        "🪙 `/coin` – Flip a coin and see if it’s heads or tails. (`/coin [heads/tails] [chips amount]`)\n\n"
        "🎟 `/draw` – Participate in a lucky draw. Will you be the lucky one? (`/draw [chips amount]`)\n\n"
        "🎯 `/dart` – /dart [chip amount].\n\n"
        "✊🖐✌️ `/rps` – Play Rock, Paper, Scissors against the bot. (`/rps [rock/paper/scissors] [chips amount]`)\n\n"
        "🎡 `/spin` – Spin the wheel once a day for a chance to win chips, XP, or levels! Type `/spin <low/mid/high>` and let the wheel decide your fate.\n\n"
        "🎲 `/roulette` – Bet on red, black, or a number (`0–36`).\n"
        "Usage: `/roulette <red|black|0–36> <bet amount>`.\n"
        "If you guess the color, you win double; if you guess the number, you win 35× your bet. Good luck!\n\n"
        "📈 `/crash` – Bet chips and watch the multiplier rise. Type `/cashout` before it crashes to lock in your winnings!\n\n"
        "🟥 `/double` – Feeling lucky? Bet to win double your chips or lose it all. (`/double [amount]`)\n\n"
        "🐎 `/horserace` – Start a new horse race.\n"
        "🐎 `/joinrace` – Join the ongoing race with your horse. (`/joinrace <horse_number> <amount>`)\n"
        "🐎 `/startrace` – Start the race and watch it live!"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
    )

async def request_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.message.from_user.id
    loan_amount = int(context.args[0]) if context.args else 0

    if loan_amount <= 0:
        await update.message.reply_text("Please specify a valid loan amount.")
        return

    # Charge 25 XP per *started* 100 chips,
    # so even loan_amount=1..100 costs 25 XP.
    xp_cost = math.ceil(loan_amount / 100) * 25

    try:
        await issue_loan_async(user_id, loan_amount, xp_cost)

        await update.message.reply_text(
            f"You've received a loan of {loan_amount} 💰 chips.\n"
            f"XP cost: {xp_cost} XP. Don't forget to repay with 3% interest!"
        )

    except InsufficientDealerChips:
        await update.message.reply_text("The Casino doesn't have enough chips to give you this loan.")
    except InsufficientExperience:
        await update.message.reply_text("You don't have enough XP to take this loan.")
    except Player.DoesNotExist:
        await update.message.reply_text("You need to register with /start first.")

async def repay_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.message.from_user.id

    try:
        _, total_repayment = await repay_loan_async(user_id)

        await update.message.reply_text(f"Loan repaid successfully! You paid back {total_repayment} 💰 with interest.")

    except NoOutstandingLoan:
        await update.message.reply_text("You don't have any outstanding loans to repay.")
    except InsufficientChips:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        total_repayment = int(player.loan * 1.03)
        await update.message.reply_text(
            f"You don't have enough chips to repay the loan. You need {total_repayment} 💰."
        )
    except Player.DoesNotExist:
        await update.message.reply_text("You need to register with /start first.")





async def give_chips2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Debug entry
    print(f"[DEBUG] give_chips triggered by user {update.effective_user.id} in chat {update.effective_chat.id}")
    print(f"[DEBUG] Message text: {update.message.text!r}")

    # Admin check
    if not await is_player_admin_async(update.effective_user.id):
        return await update.message.reply_text("🚫 You are not authorized to run this command.")

    # Reply check
    if not update.message.reply_to_message:
        print("[DEBUG] No reply_to_message found, prompting usage.")
        await update.message.reply_text(
            "❗️ Reply to a user's message and type `/chips <amount>`.",
            parse_mode="Markdown"
        )
        return

    # Args parsing
    args = context.args
    print(f"[DEBUG] context.args = {args}")
    if len(args) != 1:
        print("[DEBUG] Wrong number of args, sending usage.")
        await update.message.reply_text(
            "Usage: `/chips <amount>`",
            parse_mode="Markdown"
        )
        return

    # Amount check
    amount_str = args[0]
    if not amount_str.isdigit():
        print(f"[DEBUG] args[0]={amount_str!r} is not a digit.")
        await update.message.reply_text(
            "❗️ Amount must be a number.",
            parse_mode="Markdown"
        )
        return

    amount = int(amount_str)
    print(f"[DEBUG] Parsed amount = {amount}")

    # Identify target
    target_user = update.message.reply_to_message.from_user
    target_id = target_user.id
    print(f"[DEBUG] Target user is {target_user.full_name} with ID {target_id}")

    # Fetch Player
    try:
        player = await sync_to_async(Player.objects.get)(id=target_id)
        print(f"[DEBUG] Found Player record: {player}")
    except ObjectDoesNotExist:
        print(f"[DEBUG] No Player found with id={target_id}")
        await update.message.reply_text(f"❌ No player with ID {target_id}.")
        return

    # Update and save
    original = player.chips
    await adjust_balance_async(
        player,
        amount,
        category=ChipTransaction.Category.ADMIN_ADJUSTMENT,
        description=f"Telegram /chips adjustment by {update.effective_user.id}",
        reference_type="telegram_admin",
        reference_id=update.update_id,
        idempotency_key=f"telegram-update:{update.update_id}:admin-chips",
    )
    print(f"[DEBUG] Updating chips: {original} -> {player.chips}")
    print("[DEBUG] Player.save() completed")

    # Confirm to admin
    resp_admin = f"✅ {amount} 💰 given to {player.name or target_user.full_name}."
    print(f"[DEBUG] Replying to admin: {resp_admin}")
    await update.message.reply_text(resp_admin)

    # Notify the target
    notify_text = f"You've received {amount} 💰 from the admin!"
    print(f"[DEBUG] Sending message to target {target_id}: {notify_text}")
    await context.bot.send_message(chat_id=target_id, text=notify_text)
    print("[DEBUG] Notification sent to target")

async def claim_daily_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)
    now = timezone.now()

    # If already claimed today, bail out
    if player.last_claimed_tokens and player.last_claimed_tokens.date() == now.date():
        await update.message.reply_text("🎁 You’ve already claimed your daily 200 chips! Come back tomorrow.")
        return

    # Grant daily 200 chips
    reward = await adjust_balance_async(
        player,
        200,
        category=ChipTransaction.Category.DAILY_REWARD,
        description="Daily chip claim",
        reference_type="daily_reward",
        reference_id=now.date().isoformat(),
        idempotency_key=f"daily:{player.id}:{now.date().isoformat()}",
    )
    player.last_claimed_tokens = now
    await sync_to_async(player.save)(update_fields=("last_claimed_tokens",))

    await update.message.reply_text(f"🎉 Here are your 200 daily chips! You now have 💰{player.chips} chips.")
async def group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_link = "https://t.me/+JLQINcmYLZg3NDM0"  # ← replace with your real link
    await update.message.reply_text(
        f"🎲 Join our main Blackjack group here:\n{group_link}"
    )




async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # only allow admin to run
    if not await is_player_admin_async(update.effective_user.id):
        return await update.message.reply_text("🚫 You are not authorized to run this command.")

    if (await get_bot_control_async()).broadcasts_muted:
        await update.message.reply_text("Broadcasts are currently muted in Bot Control.")
        return

    # require a message
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <your message here>")
        return

    text = " ".join(context.args)

    # get all player IDs (which are the chat_ids for private chats)
    player_ids = await sync_to_async(
        lambda: list(Player.objects.values_list("id", flat=True))
    )()

    sent = 0
    for uid in player_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
            # small pause to respect flood limits
            await asyncio.sleep(0.05)
        except Exception as e:
            await record_telegram_failure(
                e, player_id=uid, chat_id=uid, message_type="player_broadcast"
            )

    await update.message.reply_text(f"Broadcast sent to {sent} players.")
SPIN_TIERS = {
    "low": {
        "cost": 200,
        "slices": [
            # Positive‐chip rewards
            ("💰 +5 000 chips",  5000,   0,   0),
            ("🎉 +2 500 chips",  2500,   0,   0),
            ("✨ +1 000 chips",  1000,   0,   0),
            ("👍  +500 chips",    500,   0,   0),

            # Exact negative “mirrors” of the above
            ("💸 -5 000 chips", -5000,   0,   0),
            ("💸 -2 500 chips", -2500,   0,   0),
            ("🛑 -1 000 chips", -1000,   0,   0),
            ("🛑 -500 chips",    -500,   0,   0),

            # Neutral / XP / level slots
            ("😐 Nothing happens",   0,    0,   0),
            ("😐 Nothing happens",   0,    0,   0),
            ("🌟 +50 XP",            0,   50,   0),
            ("🧟 -50 XP",            0,  -50,   0),
            ("⭐ +1 level",          0,    0,  +1),
            ("⬇️ -1 level",          0,    0,  -1),
        ],
    },

    "mid": {
        "cost": 2000,
        "slices": [
            ("💰 +25 000 chips",  25000,   0,   0),
            ("🎉 +10 000 chips",  10000,   0,   0),
            ("✨ +5 000 chips",    5000,   0,   0),
            ("👍  +1 000 chips",   1000,   0,   0),

            # Exact negative “mirrors”
            ("💸 -25 000 chips", -25000,   0,   0),
            ("💸 -10 000 chips", -10000,   0,   0),
            ("🛑 -5 000 chips",   -5000,   0,   0),
            ("🛑 -1 000 chips",   -1000,   0,   0),

            ("😐 Nothing happens",   0,    0,   0),
            ("🌟 +200 XP",           0,   200,  0),
            ("🧟 -200 XP",           0,  -200,  0),
            ("⭐ +1 level",          0,    0,  +1),
            ("⬇️ -1 level",          0,    0,  -1),
        ],
    },

    "high": {
        "cost": 20000,
        "slices": [
            ("💰 +100 000 chips", 100000,   0,   0),
            ("🎉 +50 000 chips",   50000,   0,   0),
            ("✨ +25 000 chips",   25000,   0,   0),
            ("👍  +5 000 chips",    5000,   0,   0),

            # Exact negative “mirrors”
            ("💸 -100 000 chips", -100000,   0,   0),
            ("💸 -50 000 chips",  -50000,   0,   0),
            ("🛑 -25 000 chips",  -25000,   0,   0),
            ("🛑 -5 000 chips",    -5000,   0,   0),

            ("😐 Nothing happens",    0,     0,   0),
            ("🌟 +500 XP",            0,   500,  0),
            ("🧟 -500 XP",            0,  -500,  0),
            ("⭐ +2 levels",          0,     0,  +2),
            ("⬇️ -2 levels",          0,     0,  -2),
        ],
    },
}


async def _spin_sequence_longer(bot, chat_id, message_id, slices, result):
    """
    Show 3 intermediate “spin” frames (each lasting ~0.5 s),
    then pick one final outcome, update the player, and edit the same message.
    """
    last_label = None
    frames = 3            # <-- only 3 frames now
    sleep_interval = 0.2  # half a second per intermediate frame

    for _ in range(frames):
        label, _, _, _ = random.choice(slices)

        if label != last_label:
            try:
                await bot.edit_message_text(
                    f"🎡 Spinning… {label}",
                    chat_id=chat_id,
                    message_id=message_id
                )
            except RetryAfter as e:
                # If rate-limited, wait exactly e.retry_after then retry once
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.edit_message_text(
                        f"🎡 Spinning… {label}",
                        chat_id=chat_id,
                        message_id=message_id
                    )
                except Exception:
                    pass  # skip if it fails again

            last_label = label

        await asyncio.sleep(sleep_interval)

    final_label = result.label
    chips_d = result.chips_delta
    xp_d = result.xp_delta
    lvl_d = result.level_delta

    # Build & send the final text in the same message
    final_text = (
        f"🛑 You landed on **{final_label}**!\n"
        f"Chips: {'+' if chips_d >= 0 else ''}{chips_d}\n"
        f"XP:    {'+' if xp_d   >= 0 else ''}{xp_d}\n"
        f"Level: {'+' if lvl_d  >= 0 else ''}{lvl_d}"
    )
    try:
        await bot.edit_message_text(
            final_text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="Markdown"
        )
    except RetryAfter as e:
        # If Telegram asks us to wait, honor it and retry once
        await asyncio.sleep(e.retry_after)
        try:
            await bot.edit_message_text(
                final_text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="Markdown"
            )
        except Exception:
            pass  # give up if it still fails


async def spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    """
    /spin <tier>
    Tiers: low (cost 200), mid (cost 2 000), high (cost 20 000)
    Now shows 3 intermediate labels (~1.5 s of animation) before final.
    """
    user = update.effective_user
    user_id = user.id

    if not context.args:
        return await update.message.reply_text(
            "❗️ You must specify a tier: `low`, `mid`, or `high`.\n"
            "Example: `/spin low`",
            parse_mode="Markdown"
        )

    tier_name = context.args[0].lower()
    if tier_name not in SPIN_TIERS:
        return await update.message.reply_text(
            "❗️ Invalid tier. Choose one of: `low`, `mid`, `high`.",
            parse_mode="Markdown"
        )

    tier_info = SPIN_TIERS[tier_name]
    cost = tier_info["cost"]

    try:
        result = await settle_spin_async(
            user_id,
            tier_name,
            cost,
            random.choice(tier_info["slices"]),
            str(update.update_id),
        )
    except BettingPaused:
        return await update.message.reply_text(
            "New bets are temporarily paused by an operator."
        )
    except InsufficientChips:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        return await update.message.reply_text(
            f"🚫 You need {cost} chips to spin **{tier_name.upper()}**, "
            f"but you only have {player.chips}."
        )

    # Send one “Spinning…” message, then run the 3-frame animation + final result
    msg = await update.message.reply_text(f"🎡 Spinning the **{tier_name.upper()}** wheel…")
    asyncio.create_task(
        _spin_sequence_longer(
            context.bot,
            update.effective_chat.id,
            msg.message_id,
            tier_info["slices"],
            result,
        )
    )

# ─── New /spinrewards command: list each tier, its cost, and possible outcomes ───
async def spinrewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    """
    /spinrewards
    Lists each tier’s cost and all possible outcomes (including negative-chip penalties).
    """
    lines = ["*Available spin tiers & their costs/rewards:*"]
    
    for tier_name, info in SPIN_TIERS.items():
        cost = info["cost"]
        lines.append(f"\n• *{tier_name.upper()}* (Cost: {cost} chips):")
        
        for label, chips_d, xp_d, lvl_d in info["slices"]:
            parts = [label]
            
            # If there is a chip delta (positive or negative), show it
            if chips_d != 0:
                parts.append(f"{chips_d:+} chips")
            
            # If there is an XP delta (positive or negative), show it
            if xp_d != 0:
                parts.append(f"{xp_d:+} XP")
            
            # If there is a level delta (positive or negative), show it
            if lvl_d != 0:
                parts.append(f"{lvl_d:+} level")
            
            # Join the pieces with " | " and indent under the tier name
            lines.append("    – " + " | ".join(parts))
    
    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")



RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
async def _roulette_sequence(bot, chat_id, message_id, result_number, won, bet_amt, winnings):
    # brief pause before animation
    await asyncio.sleep(0.5)

    # spinning animation
    for _ in range(2):
        spun = random.randint(0, 36)
        await bot.edit_message_text(
            f"🎲 Spinning… {spun}",
            chat_id=chat_id,
            message_id=message_id
        )
        await asyncio.sleep(2.5)

    # build result text
    result_text = f"🛑 Landed on **{result_number}**\n"
    if won:
        result_text += f"🎉 You win {winnings} chips!"
    else:
        result_text += f"😢 You lose {bet_amt} chips."

    # pause then edit with final result
    await asyncio.sleep(1)
    await bot.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=result_text,
        parse_mode="Markdown"
    )


async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # small delay for UX
    await asyncio.sleep(1)

    if not await check_player(update, context):
        return

    args = context.args
    if len(args) != 2:
        return await update.message.reply_text("Usage: /roulette <0-36> <bet>")

    bet_str, bet_amt_str = args

    # validate number
    if not bet_str.isdigit() or not (0 <= int(bet_str) <= 36):
        return await update.message.reply_text("❌ Invalid number. Please choose 0–36.")
    bet_number = int(bet_str)

    # validate amount
    try:
        bet_amt = int(bet_amt_str)
    except ValueError:
        return await update.message.reply_text("❌ Invalid bet amount. It must be an integer.")

    if not await validate_bet_amount(update, bet_amt):
        return

    user_id = update.effective_user.id
    try:
        result = await settle_roulette_async(
            user_id,
            bet_number,
            bet_amt,
            random.randint(0, 36),
            str(update.update_id),
        )
    except BettingPaused:
        return await update.message.reply_text(
            "New bets are temporarily paused by an operator."
        )
    except InsufficientChips:
        return await update.message.reply_text("❌ Not enough chips.")

    if result.won and result.payout_change and result.payout_change.applied:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        await apply_referral_bonus(player, result.winnings, context)

    # start the animation & resolution in the background
    msg = await update.message.reply_text("🎲 Starting roulette…")
    asyncio.create_task(
        _roulette_sequence(
            context.bot,
            update.effective_chat.id,
            msg.message_id,
            result.result_number,
            result.won,
            bet_amt,
            result.winnings,
        )
    )






async def give_chips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    # Command format: reply to someone's message with /givechips <amount>
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Check if command has an argument
    if len(context.args) != 1:
        await update.message.reply_text("Usage: reply to a user’s message with /givechips <amount>")
        return

    # Check if the message is a reply
    if not update.message.reply_to_message:
        await update.message.reply_text("You need to reply to the user you want to give chips to.")
        return

    # Validate the amount
    try:
        amount = int(context.args[0])
        if amount <= 0:
            await update.message.reply_text("Amount must be greater than 0.")
            return
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    # Get the giver and receiver
    giver_id = user_id
    receiver_id = update.message.reply_to_message.from_user.id

    # Check if giver and receiver are not the same
    if giver_id == receiver_id:
        await update.message.reply_text("You cannot give chips to yourself.")
        return

    # Get both players
    try:
        giver = await sync_to_async(Player.objects.get)(id=giver_id)
        receiver = await sync_to_async(Player.objects.get)(id=receiver_id)
    except Player.DoesNotExist:
        await update.message.reply_text("Both players must be registered in the game.")
        return

    try:
        _, receiver_credit = await transfer_chips_async(
            giver_id,
            receiver_id,
            amount,
            idempotency_key=f"telegram-update:{update.update_id}:givechips",
        )
    except InsufficientChips:
        await update.message.reply_text("You don’t have enough chips to give.")
        return

    # Escape user names for Markdown
    giver_name = escape_markdown(update.message.from_user.first_name, version=2)
    receiver_name = escape_markdown(update.message.reply_to_message.from_user.first_name, version=2)

    # Send a confirmation message
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"💸 *{giver_name}* has given *{amount} chips* to *{receiver_name}*\\.\n"
            f"🎉 {receiver_name} now has *{receiver_credit.balance} chips*\\!"
        ),
        parse_mode="MarkdownV2"
    )

async def sync_group_names(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /sync_groups  →  For every Group in our database, call get_chat(group_chat_id),
    pull out the chat.title (or username), and save it into group_name.
    Only the superuser (you) should run this command; it will DM back a summary.
    """
    user_id = update.effective_user.id

    # OPTIONAL: Only allow a specific user ID (e.g. your own Telegram ID) to run this.
    # Replace YOUR_TELEGRAM_ID with your actual numeric user ID.
    if not await is_player_admin_async(user_id):
        return await update.message.reply_text("🚫 You are not authorized to run this command.")

    all_groups = await sync_to_async(lambda: list(Group.objects.all()))()
    if not all_groups:
        return await update.message.reply_text("⚠️ No groups found in the database.")

    updated = 0
    skipped = 0
    errors = []

    for group in all_groups:
        chat_id = group.group_chat_id

        try:
            # get_chat is async in python-telegram-bot v13.5
            chat = await context.bot.get_chat(chat_id)
        except Exception as e:
            errors.append(f" • Failed to fetch {chat_id!r}: {e}")
            skipped += 1
            # Optional: wait a tiny bit to avoid spamming Telegram
            await asyncio.sleep(0.1)
            continue

        # Telegram’s Chat object might have:
        #   - title (for group/supergroup/channel)
        #   - first_name/last_name (for a private chat)
        #   - username (if it’s a public channel or bot)
        new_title = ""
        if hasattr(chat, "title") and chat.title:
            new_title = chat.title
        elif hasattr(chat, "first_name") and chat.first_name:
            new_title = chat.first_name
            if getattr(chat, "last_name", None):
                new_title += " " + chat.last_name
        elif getattr(chat, "username", None):
            new_title = chat.username
        else:
            new_title = str(chat_id)

        # If we got a valid title, update group_name
        if new_title and new_title != group.group_name:
            group.group_name = new_title
            await sync_to_async(group.save)()
            updated += 1
        else:
            skipped += 1

        # Small pause in case you have many groups, to avoid hitting rate limits
        await asyncio.sleep(0.1)

    # Build a summary message
    summary = [
        f"✅ Synced {len(all_groups)} groups.",
        f"🔄 Updated: {updated}",
        f"⏭️ Skipped (already up‐to‐date or failed): {skipped}",
    ]
    if errors:
        summary.append("\nSome errors:")
        summary.extend(errors[:10])  # show up to 10 errors
        if len(errors) > 10:
            summary.append(f"…and {len(errors)-10} more errors.")

    await update.message.reply_text("\n".join(summary))



async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Triggered whenever someone joins (or a bot is added to) a chat.
    If the bot itself is among new_chat_members, register that group.
    """
    bot_id = context.bot.id
    chat = update.effective_chat  # the group where this happened

    # Loop through update.message.new_chat_members to see if the bot was added
    for new_member in update.message.new_chat_members:
        if new_member.id == bot_id:
            # The bot was just added to this chat. Save it in your Group model.
            group_chat_id = str(chat.id)
            group_title   = chat.title or ""  # e.g. “My Cool Group”

            # Use get_or_create so we don’t overwrite an existing Group
            group_obj, created = await sync_to_async(Group.objects.get_or_create)(
                group_chat_id=group_chat_id,
                defaults={"group_name": group_title},
            )
            # If it already existed but the title changed, update it
            if not created and group_obj.group_name != group_title:
                group_obj.group_name = group_title
                await sync_to_async(group_obj.save)()

            # (Optionally) announce in the group that you're now watching it:
            await context.bot.send_message(
                chat_id=chat.id,
                text="👋 Thanks for adding me! Use /help to see how to play "
            )
            break




async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /listgroups
    Only list groups where the bot is still present. Do NOT delete stale rows.
    """
    user_id = update.effective_user.id

    # (Optional) restrict usage to your own ID:
    if not await is_player_admin_async(user_id):
        return await update.message.reply_text("🚫 You’re not authorized to run this command.")

    # Fetch all stored Group rows
    all_groups = await sync_to_async(lambda: list(Group.objects.all()))()
    if not all_groups:
        return await update.message.reply_text("ℹ️ No groups recorded in the database.")

    valid_lines = []

    for g in all_groups:
        chat_id = g.group_chat_id
        try:
            # Try to fetch the chat. If the bot was removed, this will raise.
            await context.bot.get_chat(chat_id)
        except Exception:
            # Skip this group (bot is not in it), but do not delete from DB
            continue

        # If we got here, the bot is still in that chat
        name = g.group_name or "(no name)"
        valid_lines.append(f" • `{chat_id}` → {name}")

        # Small pause to avoid rate limits
        await asyncio.sleep(0.05)

    if not valid_lines:
        return await update.message.reply_text("ℹ️ I’m not currently in any of the stored groups.")

    # Build the response in Markdown
    header = "*I’m currently in the following groups:*"
    message_text = "\n".join([header] + valid_lines)

    # Send in one or more chunks (≤4000 chars each)
    max_length = 4000
    text = message_text
    while text:
        if len(text) <= max_length:
            await update.message.reply_text(text, parse_mode="Markdown")
            break
        # Find a safe newline split
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        await update.message.reply_text(text[:split_pos], parse_mode="Markdown")
        text = text[split_pos:].lstrip()
async def broadcastgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /broadcast <message>
    Send <message> only to groups where the bot is still a member.
    Do NOT delete stale rows from the database.
    """
    user_id = update.effective_user.id

    # (Optional) restrict to your ID:
    if not await is_player_admin_async(user_id):
        return await update.message.reply_text("🚫 You’re not authorized to run this command.")

    if (await get_bot_control_async()).broadcasts_muted:
        return await update.message.reply_text(
            "Broadcasts are currently muted in Bot Control."
        )

    if not context.args:
        return await update.message.reply_text("❗️ Usage: /broadcast <message text>")

    text_to_send = " ".join(context.args)

    all_groups = await sync_to_async(lambda: list(Group.objects.all()))()
    if not all_groups:
        return await update.message.reply_text("ℹ️ No groups recorded to broadcast to.")

    success = 0
    failures = 0

    for g in all_groups:
        chat_id = g.group_chat_id
        try:
            # Verify bot is still in chat
            await context.bot.get_chat(chat_id)

            # Send the broadcast
            await context.bot.send_message(chat_id=chat_id, text=text_to_send)
            success += 1

        except Exception as e:
            # Skip (bot not in chat or sending failed), but do NOT delete the row
            failures += 1
            await record_telegram_failure(
                e, chat_id=chat_id, message_type="group_broadcast"
            )

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"✅ Message sent to {success} groups, skipped {failures} invalid groups."
    )


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /admin
    Sends brief descriptions of all admin commands to your private chat.
    """
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    if not await is_player_admin_async(user_id):
        return await update.message.reply_text("🚫 You’re not authorized to run this command.")
    # Notify in group that details are in private chat
    # if chat_id != user_id:
    #     await update.message.reply_text(
    #         "📩 Sent you a summary of admin commands in private chat."
    #     )

    help_text = """
*Admin Commands* (use in private chat unless noted):

• `/sync_groups`  
  Sync stored group IDs → names from Telegram.  
  _Example:_ `/sync_groups`

• `/listgroups`  
  List all groups the bot is still in.  
  _Example:_ `/listgroups`

• `/broadcastgroup <text>`  
  Send `<text>` to every group.  
  _Example:_ `/broadcastgroup Hello everyone!`

• `/broadcast <text>`  
  DM `<text>` to every registered player.  
  _Example:_ `/broadcast Maintenance in 5 min.`

• `/give_token <user_id> <amount>`  
  Add `<amount>` chips to that user.  
  _Example:_ `/give_token 123456789 1000`

• `/user_id`  
  Show your Telegram user ID (works anywhere).  
  _Example:_ `/user_id`
"""

    # Send as plain text (fits under 4096 chars)
    await context.bot.send_message(
        chat_id=user_id,
        text=help_text,
        parse_mode="Markdown"
    )


# ─── Helper: Escape MarkdownV2 ───
