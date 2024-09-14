import random
from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, PollAnswerHandler, ContextTypes
from telegram.helpers import escape_markdown
import asyncio
from telegram.error import TimedOut,RetryAfter

import os
import django

# Set the environment variable to point to your Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blackjack.settings')

# Initialize Django
django.setup()
import time
import re
from game.models import Game, Player, JoinGame,Stats,Dealer,RoundWinner,Group
from django.core.exceptions import ObjectDoesNotExist
from asgiref.sync import sync_to_async
import random
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




async def check_player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Try to get the Player instance from the database
        player = await sync_to_async(Player.objects.get)(id=user_id)
        return True  # Player exists, return True
    except ObjectDoesNotExist:
        # If no player exists, prompt the user to start the bot in private chat
        await update.message.reply_text(
            "It looks like you don't have a player profile. Please start the bot in private chat to create one. "
            "Use the following link: t.me/blackjack_21_game_bot"
        )
        return False  # Player does not exist


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Check if the player already exists (using sync_to_async)
        player = await sync_to_async(Player.objects.get)(id=user_id)
        await update.message.reply_text("Welcome back to Blackjack!")

    except ObjectDoesNotExist:
        # If the player does not exist, create the Player and Stats instance (using sync_to_async)
        player = await sync_to_async(Player.objects.create)(id=user_id, name=user_name, chips=200)
        await sync_to_async(Stats.objects.create)(wins=0, loses=0, how_many_21=0, player=player)
        await update.message.reply_text(f"Welcome to Blackjack, {user_name}! You have been given 200 💰chips to start.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Check if the player already exists
        player = await sync_to_async(Player.objects.get)(id=user_id)
        stats = await sync_to_async(Stats.objects.get)(player=player)
        await update.message.reply_text(f"here is your stats: \nwins: {stats.wins}\nloses: {stats.loses}\n💥Blackjacks: {stats.how_many_21}")

    except ObjectDoesNotExist:
        # If the player does not exist, create the Player and Stats instance
        player = await sync_to_async(Player.objects.create)(id=user_id, name=user_name, chips=20)
        stats = await sync_to_async(Stats.objects.create)(wins=0, loses=0, how_many_21=0,player=player)

        await update.message.reply_text(f"Welcome to Blackjack, {user_name}! You have been given 20 💰chips to start.\here is your stats: \nwins: {stats.wins}\nloses: {stats.loses}\n21: {stats.how_many_21}")


# # Deck of cards
deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 'J', 'Q', 'K', 'A'] * 4

# Function to deal cards
def deal_card():
    return random.choice(deck)

# # Function to calculate hand value
def calculate_hand_value(hand):
    value = 0
    aces = 0

    for card in hand:
        if card in ['J', 'Q', 'K']:
            value += 10
        elif card == 'A':
            aces += 1  # Count Aces separately
        else:
            value += card

    # Now calculate the value of Aces
    for _ in range(aces):
        if value + 11 <= 21:  # Try to count the Ace as 11
            value += 11
        else:
            value += 1  # If counting as 11 would bust, count as 1

    return value

    
async def start_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return
    chat_id = update.message.chat_id
    # Use sync_to_async to interact with Django ORM asynchronously
    # game = await sync_to_async(Game.objects.filter)(chat_id=chat_id).order_by('-id').first()
    game = await sync_to_async(lambda: Game.objects.filter(chat_id=chat_id).order_by('-id').first())()

    # If no game exists or the last game has ended, create a new game
    if not game or game.ended:
        print("No existing active game found or the last game has ended. Creating a new game...")
        game, created = await sync_to_async(Game.objects.get_or_create)(chat_id=chat_id, ended=False)
        game.betting = True
        game.started = False
        await sync_to_async(game.save)()

        await asyncio.sleep(2)  # Non-blocking sleep
        await context.bot.send_message(chat_id=chat_id, text="🃏 Set the bet amount for the blackjack game to start.")

        await create_poll(update, context)  # Assume this is an async function
        await asyncio.sleep(2)  # Non-blocking sleep
        await context.bot.send_message(chat_id=chat_id, text="🃏 Betting process has started!")
        return

    print(f"Game found: {game}")

    # Check the game state and respond accordingly
    if game.betting:
        await update.message.reply_text("A Blackjack game is in betting progress. Wait for the betting process to end and use /join to join the game.")
    elif game.started:
        await update.message.reply_text("A game has already started. Use the /next command to be prompted when the next game starts.")
    elif game.join_time:
        await update.message.reply_text("A game is in join time. Use the /join command to join the game.")
    else:
        await update.message.reply_text("An error occurred, please try again.")

async def safe_send_poll(bot, chat_id, question, options, max_retries=5):
    retries = 0
    while retries < max_retries:
        try:
            message = await bot.send_poll(chat_id=chat_id, question=question, options=options, is_anonymous=False)
            return message  # Exit if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending poll. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(3)  # Use async sleep
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Use async sleep
            retries += 1
    print("Failed to send the poll after retries.")
# Create poll function for setting bet amounts
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id

    # Retrieve or create Group instance using sync_to_async
    try:
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        group = await sync_to_async(Group.objects.create)(group_chat_id=chat_id)
    
    # Check the number of games and update options
    if group.games >= 100:
        options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰", "10000 chips💰", "20000 chips💰", "50000 chips💰"]
    else:
        options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰"]

    question = "How much do you want to bet?"

    # Send a poll asynchronously
    message = await safe_send_poll(context.bot, chat_id, question, options)

    # Store poll data in context.bot_data using poll_id as key
    if 'poll_data' not in context.bot_data:
        context.bot_data['poll_data'] = {}
    
    context.bot_data['poll_data'][message.poll.id] = {
        'chat_id': chat_id,
        'poll_message_id': message.message_id
    }

# Poll answer handler function to process poll results
async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    user_name = poll_answer.user.first_name
    selected_option = poll_answer.option_ids[0]  # Get the index of the selected option

    # Retrieve the poll data from context using poll_id
    poll_data = context.bot_data.get('poll_data', {}).get(poll_answer.poll_id)

    if not poll_data:
        print("Poll data not found.")
        return

    chat_id = poll_data['chat_id']

    # Process the answer based on the selected option
    options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰", "10000 chips💰", "20000 chips💰", "50000 chips💰"]
    chosen_option = options[selected_option]
    bet_amount = int(chosen_option.split()[0])

    # Retrieve the game using sync_to_async
    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, betting=True, started=False, ended=False)
    except Game.DoesNotExist:
        print("Game not found?")
        return

    # Update game state using sync_to_async
    game.bet_amount = bet_amount
    game.betting = False
    game.join_time = True
    await sync_to_async(game.save)()

    # Escape special characters in user_name
    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', user_name)
    mention = f"[{user_name_escaped}](tg://user?id={user_id})"
    
    # Send a message to notify the chat
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"{mention} has set the bet amount to {chosen_option}\nUse /join to join the game", 
        parse_mode="MarkdownV2"
    )


async def safe_send_message_join(bot, chat_id, text, max_retries=3):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(3)  # Non-blocking sleep
    print("Failed to send the message after retries.")


# Players join the game
async def join_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    if not await check_player(update, context):
        return
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Find a game that is in the join time
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=True, started=False, ended=False, betting=False)
    except Game.DoesNotExist:
        try:
            game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=False, started=False, ended=False, betting=True)
            await safe_send_message_join(context.bot, chat_id, "The game is in the betting process. Please wait for it to end, then use /join to join the game.")
            return
        except Game.DoesNotExist:
            try:
                game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=False, started=True, ended=False, betting=False)
                await safe_send_message_join(context.bot, chat_id, "A game has already started you cannot join. Use /nextgame to be prompted when another game is started.")
                return
            except Game.DoesNotExist:
                await safe_send_message_join(context.bot, chat_id, "No active Blackjack game. Start one by typing /startblackjack.")
                return

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return
    player_id = update.message.from_user.id
    current_chat_id = update.message.chat_id

    if await is_player_in_another_game(player_id, current_chat_id):
        await update.message.reply_text("You are already joined in another game in a different group.")
        return
    # Check if the player already joined
    if await sync_to_async(JoinGame.objects.filter(game=game, player=player, is_active=True).exists)():
        await update.message.reply_text(f"{user_name}, you are already in the game!")
        return

    # Check if the player has enough chips
    if player.chips < game.bet_amount:
        await update.message.reply_text(f"{user_name}, you do not have enough 💰chips to join the game.\nMinimum bet is {game.bet_amount} 💰chips.")
        return

    # Add the player to the game
    await sync_to_async(JoinGame.objects.create)(player=player, game=game, is_active=True)

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
# Force start the Blackjack game
# Force start the Blackjack game
async def force_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=True, started=False, ended=False, betting=False)
    except Game.DoesNotExist:
        try:
            game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=False, started=False, ended=False, betting=True)
            await safe_send_message_join(context.bot, chat_id, "The game is in the betting process. Please wait for it to end, then forcestart the game.")
            return
        except Game.DoesNotExist:
            try:
                game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=False, started=True, ended=False, betting=False)
                await safe_send_message_join(context.bot, chat_id, "A game has already started. You cannot forcestart the game, use /nextgame to be prompted when another game is started.")
                return
            except Game.DoesNotExist:
                await safe_send_message_join(context.bot, chat_id, "No active Blackjack game. Start one by typing /startblackjack.")
                return

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(lambda: list(JoinGame.objects.filter(game=game, is_active=True)))()

    # Check if there are enough players
    if len(joined_players) < 1:
        await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()
        await update.message.reply_text('At least 1 player is required to start the game, ending the game!')
        return

    dealer = await sync_to_async(Dealer.objects.first)()
    group_game, created = await sync_to_async(Group.objects.get_or_create)(group_chat_id=chat_id)
    group_game.games += 1
    await sync_to_async(group_game.save)()

    # Handle the dealer's chips deduction
    if dealer:
        dealer.chips -= game.bet_amount
        dealer.games += 1
        await sync_to_async(dealer.save)()
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"🤖 Dealer is in the game with {game.bet_amount} 💰chips on the table\\.",
            parse_mode="MarkdownV2"
        )

    for join_entry in joined_players:
        # Fetch the player related to the join_entry asynchronously
        player = await sync_to_async(lambda: join_entry.player)()

        player.chips -= game.bet_amount
        player.games += 1
        await sync_to_async(player.save)()
        
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', player.name)
        mention = f"[{user_name_escaped}](tg://user?id={player.id})"
        await asyncio.sleep(2)  # Non-blocking sleep
        
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"{mention} has bet {game.bet_amount} chips\\.\nRemaining chips: 💰{player.chips}", 
            parse_mode="MarkdownV2"
        )


    # Initialize turn order with the list of player IDs
    game.turn_order = [join_entry.player.id for join_entry in joined_players]
    game.current_round = 1  # Start with round 1
    players_count = len(joined_players) + 1
    game.pot = game.bet_amount * players_count  # Track total pot across rounds

    game.started = True
    game.join_time = False
    await sync_to_async(game.save)()

    # Proceed to the first round
    await start_round(update, context, game, joined_players)




# # Function to start each round
async def safe_pin_chat_message(bot, chat_id, message_id, max_retries=3):
    retries = 0
    while retries < max_retries:
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=message_id)  # Assuming timeout is 20
            return  # Exit the loop if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while pinning message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(2 ** retries)  # Non-blocking exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Rate limit exceeded. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Wait for the retry after time
            retries += 1

    print("Failed to pin message after multiple retries.")

async def start_round(update: Update, context: ContextTypes.DEFAULT_TYPE, game, joined_players):
    chat_id = update.message.chat_id

    print(game.current_round)

    if game.current_round >= 2:
        print('in hereadf')

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

        await asyncio.sleep(2)
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

        if bot_member.status in ['administrator', 'creator']:
            await safe_pin_chat_message(context.bot, chat_id, message.message_id)

    await asyncio.sleep(2)

    await context.bot.send_message(chat_id=chat_id, text=f"Starting round {game.current_round}...")
    await asyncio.sleep(3)

    player_blackjacks = []

    for join_entry in joined_players:
        player_hand = [deal_card(), deal_card()]
        join_entry.hand = player_hand
        await sync_to_async(join_entry.save)()

        print(f"Dealt hand {player_hand} to player {join_entry.player.name}")

        # Fetch player's name asynchronously
        player_hand_value = calculate_hand_value(player_hand)
        if player_hand_value == 21:
            player_blackjacks.append(join_entry)
        else:
            await context.bot.send_message(chat_id=join_entry.player.id, text=f"🃏Your hand: {player_hand}.\n♠️Total value: {player_hand_value}")

    dealer_hand = [deal_card(), deal_card()]
    game.dealer_hand = dealer_hand
    await sync_to_async(game.save)()

    await context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer's visible card: ♠️{dealer_hand[0]}")

    dealer_value = calculate_hand_value(dealer_hand)
    dealer_has_blackjack = dealer_value == 21

    if dealer_has_blackjack:
        await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer has a Blackjack! 💥")
        dealer = await sync_to_async(Dealer.objects.get)(id=1)
        dealer.blackjack_count += 1
        await sync_to_async(dealer.save)()

        for join_entry in player_blackjacks:
            await context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} had Blackjack💥 too. It's a push.")

        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
        game.current_round += 1
        await check_for_next_round(update, context, game, joined_players)
        return

    if player_blackjacks:
        for join_entry in player_blackjacks:
            await context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} has a natural Blackjack!💥 They win the round.")
            stats = await sync_to_async(Stats.objects.get)(player=join_entry.player)
            stats.how_many_21 += 1
            await sync_to_async(stats.save)()

            await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, winner=join_entry.player)

        game.current_round += 1
        await check_for_next_round(update, context, game, joined_players)
        return

    for join_entry in joined_players:
        if join_entry not in player_blackjacks:
            stats = await sync_to_async(Stats.objects.get)(player=join_entry.player)
            await sync_to_async(stats.save)()

    await player_turn(update, context)





async def update_statistics(winners, dealer_wins, joined_players):
    print("Starting update_statistics function")
    
    # Initialize a list for non-winners
    non_winners = []
    print("Initialized non_winners list")

    # Update stats for each winner
    for winner in winners:
        if winner == 'dealer':
            dealer = await sync_to_async(Dealer.objects.first)()  # Assuming only one dealer
            dealer.wins += 1
            await sync_to_async(dealer.save)()
            print(f"Dealer wins updated: {dealer.wins}")
        else:
            player = await sync_to_async(Player.objects.get)(id=winner.id)
            stats, created = await sync_to_async(Stats.objects.get_or_create)(player=player)
            stats.wins += 1
            await sync_to_async(stats.save)()
            print(f"Player {player.id} wins updated: {stats.wins}")

    # Determine non-winners
    winners_ids = {winner.id for winner in winners if winner != 'dealer'}
    non_winners = [player.player for player in joined_players if player.player.id not in winners_ids and player.player != 'dealer']
    print(f"Non-winners determined: {[player.id for player in non_winners]}")

    # Remove duplicates in non_winners list
    non_winners = list(set(non_winners))
    print(f"Non-winners list after removing duplicates: {[player.id for player in non_winners]}")

    # Update losses for each non-winner
    for player in non_winners:
        stats, created = await sync_to_async(Stats.objects.get_or_create)(player=player)
        stats.loses += 1
        await sync_to_async(stats.save)()
        print(f"Player {player.id} losses updated: {stats.loses}")

    # Update dealer's losses if dealer did not win
    if not dealer_wins:
        dealer = await sync_to_async(Dealer.objects.first)()  # Assuming only one dealer
        dealer.loses += 1  # Ensure you have a `loses` field in your Dealer model
        await sync_to_async(dealer.save)()
        print(f"Dealer losses updated: {dealer.loses}")

    print("Finished update_statistics function")

async def check_for_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE, game, joined_players):
    chat_id = update.message.chat_id
    await asyncio.sleep(3)

    if game.current_round > game.total_rounds:
        # Determine the overall winner
        round_winners = await sync_to_async(list)(RoundWinner.objects.filter(game=game))

        # Count wins for each player and the dealer
        winner_count = {}
        for winner in round_winners:
            # Fetch the related 'winner' field asynchronously
            winner_player = await sync_to_async(lambda: winner.winner)()
            if winner_player:
                if winner_player in winner_count:
                    winner_count[winner_player] += 1
                else:
                    winner_count[winner_player] = 1

        dealer_wins = await sync_to_async(RoundWinner.objects.filter(game=game, is_dealer=True).count)()
        if dealer_wins > 0:
            winner_count['dealer'] = dealer_wins

        print(f"Winner counts (including dealer): {winner_count}")

        if winner_count:
            # Determine the overall winner(s)
            max_wins = max(winner_count.values())
            overall_winners = [winner for winner, wins in winner_count.items() if wins == max_wins]

            if len(overall_winners) == 1:
                # One clear winner
                overall_winner = overall_winners[0]

                if overall_winner == 'dealer':
                    await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer is the overall winner of the game! 🏆")
                else:
                    await context.bot.send_message(chat_id=chat_id, text=f"{overall_winner.name} is the overall winner of the game! 🏆")
            elif len(overall_winners) > 1:
                # Multiple winners (tie)
                winner_names = ', '.join([f"[{winner.name}](tg://user?id={winner.id})" if winner != 'dealer' else "🤖 Dealer" for winner in overall_winners])
                await context.bot.send_message(chat_id=chat_id, text=f"{winner_names} tied and shared the pot\\! 🏆", parse_mode="MarkdownV2")

            # Update statistics for winners and losers
            await update_statistics(overall_winners, dealer_wins, joined_players)
        else:
            await context.bot.send_message(chat_id=chat_id, text="No overall winner was determined.")

        # Call the end_game function to finalize the game
        await end_game(update, context)

        # Prepare standings message
        bot_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        round_winners = await sync_to_async(list)(RoundWinner.objects.filter(game=game, is_dealer=False))
        dealer_wins = await sync_to_async(RoundWinner.objects.filter(game=game, is_dealer=True).count)()
        winner_count = {}

        for winner in round_winners:
            winner_player = await sync_to_async(lambda: winner.winner)()
            if winner_player in winner_count:
                winner_count[winner_player] += 1
            else:
                winner_count[winner_player] = 1

        winners = []
        no_wins = []

        for player in joined_players:
            player_name = await sync_to_async(lambda: player.player.name)()
            player_id = await sync_to_async(lambda: player.player.id)()
            wins = winner_count.get(player.player, 0)

            if wins > 0:
                winners.append((player_name, wins, player_id))
            else:
                no_wins.append((player_name, player_id))

        winners = sorted(winners, key=lambda x: x[1], reverse=True)
        await asyncio.sleep(2)

        standings_message = "📊 Current standings:\n"

        if dealer_wins > 0:
            standings_message += f"🤖 Dealer: {dealer_wins} round\\(s\\) won\n"
        else:
            standings_message += f"🤖 Dealer: No wins yet\n"

        for winner_name, wins, user_id in winners:
            user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', winner_name)
            mention = f"[{user_name_escaped}](tg://user?id={user_id})"
            standings_message += f"🏆 {mention}: {wins} round\\(s\\) won\n"

        for player_name, player_id in no_wins:
            user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', player_name)
            mention = f"[{user_name_escaped}](tg://user?id={player_id})"
            standings_message += f"🎲 {mention}: No wins yet\n"

        message = await context.bot.send_message(chat_id=chat_id, text=standings_message, parse_mode="MarkdownV2")

        if bot_member.status in ['administrator', 'creator']:
            await safe_pin_chat_message(context.bot, chat_id, message.message_id)

        await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()
        await context.bot.send_message(chat_id=chat_id, text="The game has ended. You can start a new game by typing /startblackjack.")

    else:
        # Prepare for the next round
        game.hands_reset = False
        await sync_to_async(game.save)()

        await asyncio.sleep(3)
        await start_round(update, context, game, joined_players)


async def player_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        # Fetch the active game in the chat
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return

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

    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', current_player.name)
    mention = f"[{user_name_escaped}](tg://user?id={current_player.id})"

    if update.message.from_user.id == current_player_id:
        # Notify the current player it is their turn
        await asyncio.sleep(2)  # Non-blocking sleep
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"{mention}, it's your turn\\! Type:\n/hit 🎰 to draw a card or \n\n/stand❗ to keep your hand\\.",
            parse_mode="MarkdownV2"
        )
    else:
        # Notify others that the current player is making a decision
        await asyncio.sleep(2)  # Non-blocking sleep
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"Waiting for {mention}'s decision\\.\\.\\. Type: \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your current hand\\.",
            parse_mode="MarkdownV2"
        )


# # Escape special characters in the player's name

# Asynchronous version of safe_send_message
async def safe_send_message_async(bot, chat_id, text, parse_mode="MarkdownV2", max_retries=5):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(2 ** retries)  # Non-blocking exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Non-blocking wait for the RetryAfter period before retrying
            retries += 1
    print(f"Failed to send the message after {max_retries} retries.")

async def hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return

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
    if user_id != game.turn_order[0]:
        await update.message.reply_text("It's not your turn!")
        return

    # Add a card to the player's hand
    new_card = deal_card()
    join_game.hand.append(new_card)
    await sync_to_async(join_game.save)()

    user_name_escaped = re.sub(r'([_*[\]()~>#+\-=|{}.!])', r'\\\1', user_name)
    mention = f"[{user_name_escaped}](tg://user?id={user_id})"

    await safe_send_message_async(context.bot, chat_id, f"{mention} drew: {new_card}")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)

    await safe_send_message_async(context.bot, user_id, f"Your full hand: {player_hand}\\. Total value: {hand_value}")

    # Check for bust or 21
    if hand_value == 21:
        await asyncio.sleep(3)
        stats = await sync_to_async(Stats.objects.get)(player=join_game.player)
        stats.how_many_21 += 1
        await sync_to_async(stats.save)()
        await safe_send_message_async(context.bot, chat_id, f"{mention} Reached BlackJack💥\\! \n They automatically stand\\.")
        await next_player_turn(update, context)
    elif hand_value > 21:
        await asyncio.sleep(3)
        await safe_send_message_async(context.bot, chat_id, f"{mention} busted with a total of {hand_value}\\. ")
        await next_player_turn(update, context)
    else:
        await asyncio.sleep(3)
        await safe_send_message_async(context.bot, chat_id, f"{mention} Type: \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your current hand\\.")

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

    # Check if it's the player's turn
    if user_id != game.turn_order[0]:
        await update.message.reply_text("It's not your turn!")
        return

    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', user_name)
    mention = f"[{user_name_escaped}](tg://user?id={user_id})"

    await safe_send_message_async(context.bot, chat_id, f"{mention} has chosen to stand\\.")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    await asyncio.sleep(2)

    await safe_send_message_async(context.bot, user_id, f"You have chosen to stand\\. Your final hand: {player_hand}\\. Total value: {hand_value}")

    # Move to the next player's turn
    await next_player_turn(update, context)


# # Function to move to the next player's turn
# # Move to the next player's turn by removing the current player from the turn order
async def safe_send_message_next_player_turn(bot, chat_id, text, max_retries=5):  # Increased timeout
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(3)  # Non-blocking sleep before retrying
    print("Failed to send the message after retries.")

# Asynchronous version of next_player_turn
async def next_player_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return

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
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', next_player.name)

        mention = f"[{user_name_escaped}](tg://user?id={next_player_id})"
        await asyncio.sleep(3)  # Non-blocking sleep
        await safe_send_message_next_player_turn(context.bot, chat_id, f"{mention}, it's your turn\\! Type \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your hand\\.")
    else:
        # All players have finished their turns, now it's the dealer's turn
        await dealer_turn(update, context)

# Asynchronous version of safe_send_message_dealer
async def safe_send_message_dealer(bot, chat_id, text, max_retries=5):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(3)  # Non-blocking sleep before retrying
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Non-blocking wait for the RetryAfter period before retrying
            retries += 1
    print("Failed to send the message after retries.")
async def dealer_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await safe_send_message_dealer(context.bot, chat_id, "No active game or the game has not started.")
        return

    await asyncio.sleep(2)
    await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer's turn\\.\\.\\.")

    dealer_hand = game.dealer_hand
    dealer_value = calculate_hand_value(dealer_hand)

    # Dealer's logic: drawing until reaching at least 17
    while dealer_value < 17:
        new_card = deal_card()
        dealer_hand.append(new_card)
        dealer_value = calculate_hand_value(dealer_hand)
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer draws a 🂾{new_card}\\. 🤖 Dealer's hand: {dealer_hand}")

    # If dealer busts (> 21)
    if dealer_value > 21:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer busts with a total of {dealer_value}\\!❌")
        dealer_busted = True
    else:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer stands with a total of {dealer_value}\\.")
        dealer_busted = False

    # Save the updated dealer hand
    game.dealer_hand = dealer_hand
    await sync_to_async(game.save)()

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(list)(JoinGame.objects.filter(game=game, is_active=True))

    # Track the player(s) who win this round
    highest_valid_score = 0
    round_winners = []

    for join_entry in joined_players:
        # Fetch the player asynchronously
        player = await sync_to_async(lambda: join_entry.player)()
        
        player_hand_value = calculate_hand_value(join_entry.hand)
        
        # If player busted, skip them
        if player_hand_value > 21:
            continue
        
        # Track the highest valid hand that beats the dealer (if dealer didn't bust)
        if dealer_busted or player_hand_value > dealer_value:
            if player_hand_value > highest_valid_score:
                highest_valid_score = player_hand_value
                round_winners = [player]
            elif player_hand_value == highest_valid_score:
                round_winners.append(player)

    if not round_winners:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer wins🥇 this round\\!")
        
        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
    else:
        for winner in round_winners:
            await asyncio.sleep(2)
            try:
                # Try to tag the winner using their name
                mention = f"[{winner.name}](tg://user?id={winner.id})"
            except Exception as e:
                # Fallback to just using the player's name if tagging fails
                mention = winner.name
                print(f"Error tagging player {winner.name}: {str(e)}")

            await safe_send_message_dealer(context.bot, chat_id, f"{mention} wins this round with a hand of {highest_valid_score}\\!")
            await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, winner=winner)
    if not round_winners:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer won🥇 round {game.current_round}\\!")
    else:
        for winner in round_winners:
            await asyncio.sleep(2)
            try:
                # Try to tag the winner using their name
                mention = f"[{winner.name}](tg://user?id={winner.id})"
            except Exception as e:
                # Fallback to just using the player's name if tagging fails
                mention = winner.name
                print(f"Error tagging player {winner.name}: {str(e)}")

            await safe_send_message_dealer(context.bot, chat_id, f"{mention} won🥇 round {game.current_round}\\!")

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

    # Find all winners (both dealer and players) who won the maximum number of rounds
    winners = [winner for winner, wins in round_wins.items() if wins == max_rounds_won]
    if dealer_rounds_won == max_rounds_won:
        winners.append('dealer')  # Include the dealer in the winners if they won the max rounds

    # Split the pot evenly among all winners
    if winners:
        split_pot = game.pot // len(winners)
        
        if 'dealer' in winners:
            winners.remove('dealer')
            dealer = await sync_to_async(Dealer.objects.get)(id=1)
            dealer.chips += split_pot
            await sync_to_async(dealer.save)()
            await context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer wins {split_pot} chips💰!")

        for winner in winners:
            winner.chips += split_pot
            await sync_to_async(winner.save)()
            await context.bot.send_message(chat_id=chat_id, text=f"{winner.name} wins {split_pot} chips💰!")

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

# Asynchronous version of start_next_round
async def start_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(2)
    chat_id = update.message.chat_id
    game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)

    # Deal new hands to players and start the next round
    joined_players = await sync_to_async(list)(JoinGame.objects.filter(game=game, is_active=True))

    for join_entry in joined_players:
        player_hand = [deal_card(), deal_card()]
        join_entry.hand = player_hand
        await sync_to_async(join_entry.save)()

        # Inform the player about their new hand
        player = join_entry.player
        hand_value = calculate_hand_value(player_hand)
        await context.bot.send_message(chat_id=chat_id, text=f"Your new 🃏hand: {player_hand}. Total value: {hand_value}")

    # Deal cards to the dealer for the next round
    dealer_hand = [deal_card(), deal_card()]
    game.dealer_hand = dealer_hand
    await sync_to_async(game.save)()

    # Send the dealer's visible card
    await context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer's visible 🃏card: {dealer_hand[0]}")

    # Continue to the first player's turn for the next round
    await player_turn(update, context)

# Asynchronous version of get_player_instance
async def get_player_instance(user_id):
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        return player
    except ObjectDoesNotExist:
        return None

# Asynchronous version of get_player_chips
async def get_player_chips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Fetch the player instance
    player = await get_player_instance(user_id)
    
    if player:
        # If the player exists, return their chips or use them in logic
        await context.bot.send_message(chat_id=update.message.chat_id, text=f"{player.name} has {player.chips} 💰chips.")
    else:
        # Handle the case where the player does not exist
        await context.bot.send_message(chat_id=update.message.chat_id, text="You don't have a player profile yet. Start the bot in private to create one.")

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
            f"Wins: {dealer.wins}\n"
            f"Losses: {dealer.loses}\n"
            f"💥 Blackjacks: {dealer.blackjack_count}"
        )
        
        # Send the stats message to the chat
        await context.bot.send_message(chat_id=chat_id, text=stats_message)

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error retrieving dealer stats: {str(e)}")



app = ApplicationBuilder().token("7041648826:AAFMkq1-fX740ZTT3OVbPowzbzJooMCi118").concurrent_updates(True).build()
# real token 7041648826:AAFMkq1-fX740ZTT3OVbPowzbzJooMCi118
# test token 7094966045:AAEbis5HH6W20Gg1vvziCmc0f9imO2FQ47Q
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("startblackjack", start_blackjack, block=False))
app.add_handler(CommandHandler("join", join_blackjack))
app.add_handler(CommandHandler("forcestart", force_start))
app.add_handler(PollAnswerHandler(poll_answer_handler))  # PollAnswerHandler for poll answers
app.add_handler(CommandHandler("my_tokens", get_player_chips))
app.add_handler(CommandHandler("stand", stand))
app.add_handler(CommandHandler("hit", hit))
app.add_handler(CommandHandler("dealer_stats", get_dealer_blackjack_stats))

app.run_polling()


