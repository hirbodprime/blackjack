from telegram import Update, Bot,ParseMode,User,Message,Chat
from telegram.ext import Updater, CommandHandler, CallbackContext,PollAnswerHandler
from telegram.error import TimedOut,RetryAfter,Unauthorized

import django
import os

# Set the environment variable to point to your Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blackjack.settings')

# Initialize Django
django.setup()
blackjack_games = {}

import time
import re
import random
import datetime
import threading
from datetime import timedelta

from game.models import Game, Player, JoinGame,Stats,Dealer,RoundWinner,Group
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

Testing_mode = True


def check_join_time(update: Update, context: CallbackContext, game_id):
    try:
        game = Game.objects.get(chat_id=game_id)
        if game.join_start_time and not game.started and game.join_time:
            elapsed_time = timezone.now() - game.join_start_time
            if elapsed_time.total_seconds() > 120:
                # Automatically start the game if join time exceeds 120 seconds
                print("Asdafsdfashhhhhhhhhhhhhh")
                force_start(update, context,game.chat_id)
    except Game.DoesNotExist:
        print("Game not found for chat_id:", game_id)

def send_time_left_reminder(update: Update, context: CallbackContext, game_id):
    try:
        game = Game.objects.get(chat_id=game_id)
        
        if game.join_start_time and not game.started:
            elapsed_time = timezone.now() - game.join_start_time
            remaining_time = 120 - elapsed_time.total_seconds()
            
            if remaining_time > 0:
                # Send message about remaining time
                message = f"Time left to join: {int(remaining_time)} seconds.\n use /join to join the game"
                context.bot.send_message(
                    chat_id=game.chat_id,
                    text=message,
                )
                # Schedule the next reminder
                threading.Timer(30, send_time_left_reminder, args=(update, context, game_id)).start()
            else:
                # Time has run out
                context.bot.send_message(
                    chat_id=game.chat_id,
                    text="The time to join has expired.",
                )
                # Automatically start the game if join time exceeds 120 seconds
                threading.Thread(target=check_join_time, args=(update, context, game_id), daemon=True).start()
        else:
            pass
            # Join start time is not set
            # context.bot.send_message(
            #     chat_id=game.chat_id,
            #     text="Join start time is not properly set.",
            # )
    except Game.DoesNotExist:
        print("Game not found for chat_id:", game_id)
def tag_users(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    # Default number of tags
    repeat_count = 1
    
    # Parse the command arguments
    if context.args:
        try:
            repeat_count = int(context.args[0])
            if repeat_count < 1:
                repeat_count = 1
        except ValueError:
            context.bot.send_message(
                chat_id=chat_id,
                text="Invalid number. Please enter a valid integer.",
                timeout=20
            )
            return

    # Get the list of chat members
    members = context.bot.get_chat_administrators(chat_id)
    mentions = [f"[{member.user.full_name}](tg://user?id={member.user.id})" for member in members]

    # Helper function to send a message with retry logic
    def send_message_with_retry(mention):
        retries = 3
        while retries > 0:
            try:
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"{mention} Lets play and win some money\\!\nuse the /join command to join a game of 💥BlackJack",
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                break  # Exit loop if message sent successfully
            except TimedOut:
                # Handle timeout error, retry after a short delay
                time.sleep(1)
                retries -= 1
            except RetryAfter as e:
                # Handle flood control exceeded, retry after the specified time
                time.sleep(e.retry_after)
                retries -= 1
            except Exception as e:
                # Handle other exceptions
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"An error occurred: {e}",
                    timeout=20
                )
                break

    # Send each mention as a separate message
    for _ in range(repeat_count):
        for mention in mentions:
            send_message_with_retry(mention)
            time.sleep(1)  # Wait for 1 second before sending the next tag

def check_player(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    chat_id = update.message.chat_id
    group_name = context.bot.get_chat(chat_id).title  # Get the group name

    try:
        # Try to get the Player instance from the database
        player = Player.objects.get(id=user_id)
        
        # If the player exists, check if the bot can message them
        try:
            # Send a personalized message with the group name
            context.bot.send_message(
                chat_id=user_id, 
                text=f"You've joined a game that has started in the group '{group_name}'!", 
                timeout=20
            )
        except Unauthorized:
            # Bot cannot message the user, prompt them to start the bot in private chat
            update.message.reply_text(
                "Please start the bot in private chat so I can message you. Use the following link: "
                "t.me/blackjack_21_game_bot"
            )
            return False
        return True
    except ObjectDoesNotExist:
        # If no player exists, prompt the user to start the bot in private chat
        update.message.reply_text(
            "It looks like you don't have a player profile. Please start the bot in private chat to create one. "
            "Use the following link: t.me/blackjack_21_game_bot"
        )
        return False



# When the user starts the bot in private chat, create a Player and Stats instance
def start(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Check if the player already exists
        player = Player.objects.get(id=user_id)
        update.message.reply_text("Welcome back to Blackjack!")

    except ObjectDoesNotExist:
        # If the player does not exist, create the Player and Stats instance
        player = Player.objects.create(id=user_id, name=user_name, chips=200)
        stats = Stats.objects.create(wins=0, loses=0, how_many_21=0,player=player)
        update.message.reply_text(f"Welcome to Blackjack, {user_name}! You have been given 200 💰chips to start.")

def stats(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Check if the player already exists
        player = Player.objects.get(id=user_id)
        stats = Stats.objects.get(player=player)
        update.message.reply_text(f"here is your stats: \nwins: {stats.wins}\nloses: {stats.loses}\n💥Blackjacks: {stats.how_many_21}")

    except ObjectDoesNotExist:
        # If the player does not exist, create the Player and Stats instance
        player = Player.objects.create(id=user_id, name=user_name, chips=20)
        stats = Stats.objects.create(wins=0, loses=0, how_many_21=0,player=player)

        update.message.reply_text(f"Welcome to Blackjack, {user_name}! You have been given 20 💰chips to start.\here is your stats: \nwins: {stats.wins}\nloses: {stats.loses}\n21: {stats.how_many_21}")


# Deck of cards
deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 'J', 'Q', 'K', 'A'] * 4

# Function to deal cards
def deal_card():
    return random.choice(deck)

# Function to calculate hand value
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



# Wrapper function to handle retries with exponential backoff
def safe_start_blackjack(update: Update, context: CallbackContext, max_retries=3, initial_backoff=2):
    retries = 0
    backoff = initial_backoff  # Start with a 2-second backoff

    while retries < max_retries:
        try:
            # Attempt to start the Blackjack game
            start_blackjack(update, context)
            return  # Exit if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while starting Blackjack. Retrying in {backoff} seconds...")
            time.sleep(backoff)  # Wait for backoff time before retrying
            backoff *= 2  # Exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            time.sleep(retry_after)  # Wait for the RetryAfter period before retrying
            retries += 1

    print(f"Failed to start the Blackjack game after {max_retries} retries.")
    update.message.reply_text("Unable to start the Blackjack game due to repeated timeouts. Please try again later.")

# Start Blackjack game (retries handled in safe_start_blackjack)
def start_blackjack(update: Update, context: CallbackContext):
    global chat_id

    # Check if the user has a Player profile
    if not check_player(update, context):
        return

    chat_id = update.message.chat_id
    print(f"Chat ID: {chat_id}")

    # Check if a game exists for the current chat ID
    game = Game.objects.filter(chat_id=chat_id).order_by('-id').first()

    # If no game exists or the last game has ended, create a new game
    if not game or game.ended:
        print("No existing active game found or the last game has ended. Creating a new game...")
        game, created = Game.objects.get_or_create(chat_id=chat_id, ended=False)
        game.betting = True
        game.started = False
        game.save()
        time.sleep(2)

        context.bot.send_message(chat_id=chat_id, text="🃏 Set the bet amount for the blackjack game to start.", timeout=20)
        create_poll(update, context)  # Start the betting poll
        time.sleep(2)
        context.bot.send_message(chat_id=chat_id, text="🃏 Betting process has started!", timeout=20)
        return
    
    print(f"Game found: {game}")

    # Check if the game is in betting progress, started, or in join time
    if game.betting:
        update.message.reply_text("A Blackjack game is in betting progress. Wait for the betting process to end and use /join to join the game.")
        return
    elif game.started:
        update.message.reply_text("A game has already started. Use the /next command to be prompted when the next game starts.")
        return
    elif game.join_time:
        update.message.reply_text("A game is in join time. Use the /join command to join the game.")
        return
    else:
        # If none of the above conditions are met, raise an error
        update.message.reply_text("An error occurred, please try again.")
        return

def safe_send_poll(bot, chat_id, question, options, timeout=20, max_retries=5):
    retries = 0
    while retries < max_retries:
        try:
            message = bot.send_poll(chat_id=chat_id, question=question, options=options, is_anonymous=False)
            return message  # Exit if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending poll. Retrying {retries}/{max_retries}...")
            time.sleep(3)  # Wait before retrying
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            time.sleep(retry_after)  # Wait for the RetryAfter period before retrying
            retries += 1
    print("Failed to send the poll after retries.")

def create_poll(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    # Retrieve or create Group instance
    try:
        group = Group.objects.get(group_chat_id=chat_id)
    except Group.DoesNotExist:
        group = Group(group_chat_id=chat_id)
        group.save()

    # Check the number of games and update options
    if group.games >= 100:
        options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰", "10000 chips💰", "20000 chips💰", "50000 chips💰"]
    else:
        options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰"]

    question = "How much do you want to bet?"

    # Send a poll
    message = safe_send_poll(context.bot, chat_id, question, options)

    # Save the message and poll id so that we can handle the answers later
    context.bot_data['poll_message_id'] = message.message_id
    context.bot_data['poll_chat_id'] = update.message.chat_id
    context.bot_data['poll_id'] = message.poll.id


def poll_answer_handler(update: Update, context: CallbackContext):
    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    user_name = poll_answer.user.first_name
    selected_option = poll_answer.option_ids[0]  # Get the index of the selected option

    # Retrieve the poll data from context
    poll_id = context.bot_data.get('poll_id')
    chat_id = context.bot_data.get('poll_chat_id')

    if poll_answer.poll_id == poll_id:
        # Process the answer based on the selected option
        options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰", "10000 chips💰", "20000 chips💰", "50000 chips💰"]
        chosen_option = options[selected_option]
        bet_amount = int(chosen_option.split()[0])
        
        try:
            game = Game.objects.get(chat_id=chat_id, betting=True, started=False, ended=False)
        except Game.DoesNotExist:
            print("game not found?")
            return
        
        game.bet_amount = bet_amount
        game.betting = False
        game.join_time = True
        time.sleep(2)
        
        
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', user_name)
        mention = f"[{user_name_escaped}](tg://user?id={user_id})"
        
        context.bot.send_message(
            chat_id=chat_id,
            text=f"{mention} has set the bet amount to {chosen_option}\nUse /join to join the game", 
            parse_mode="MarkdownV2", 
            timeout=20
        )
        game.join_start_time = timezone.now()
        game.save()
        # Start threads with proper arguments
        threading.Thread(target=check_join_time, args=(update, context, game.chat_id), daemon=True).start()
        threading.Thread(target=send_time_left_reminder, args=(update, context, game.chat_id), daemon=True).start()

        context.bot.send_message(
            chat_id=chat_id,
            text=f"The game is in join time, you have 120 sec to join", 
            timeout=20
        )

def safe_send_message_join(bot, chat_id, text, timeout=20, max_retries=3):  # Increased timeout
    retries = 0
    while retries < max_retries:
        try:
            bot.send_message(chat_id=chat_id, text=text, timeout=timeout)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            time.sleep(3)  # Wait a bit before retrying
    print("Failed to send the message after retries.")

# Players join the game
def join_blackjack(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # First, try to find a game that is in the join time, not started, and not ended.
        game = Game.objects.get(chat_id=chat_id, join_time=True, started=False, ended=False, betting=False)
    except Game.DoesNotExist:
        try:
            # If no such game exists, check if there's a game in the betting process.
            game = Game.objects.get(chat_id=chat_id, join_time=False, started=False, ended=False, betting=True)
            safe_send_message_join(context.bot, chat_id, "The game is in the betting process. Please wait for it to end, then use /join to join the game.")

            # Inform the user that the game is still in the betting process.
            # update.message.reply_text("The game is in the betting process. Please wait for it to end, then use /join to join the game.")
            return
        except Game.DoesNotExist:
            try:
                game = Game.objects.get(chat_id=chat_id, join_time=False, started=True, ended=False, betting=False)
                safe_send_message_join(context.bot, chat_id, "A game has already started you can not join the game, use /nextgame to be prompted when another game is started")
                # If neither join_time nor betting games exist, inform the user that no game is active.
                # update.message.reply_text("A game has already started you can not join the game, use /nextgame to be prompted when another game is started")
                return
            except Game.DoesNotExist:
                
                safe_send_message_join(context.bot, chat_id, "No active Blackjack game. Start one by typing /startblackjack.")
                
                # update.message.reply_text("No active Blackjack game. Start one by typing /startblackjack.")
                return

    try:
        player = Player.objects.get(id=user_id)
    except Player.DoesNotExist:
        update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    # Check if the player already joined
    if JoinGame.objects.filter(game=game, player=player, is_active=True).exists():
        update.message.reply_text(f"{user_name}, you are already in the game!")
        return

    # Check if the player has enough chips
    if player.chips < game.bet_amount:
        update.message.reply_text(f"{user_name}, you do not have enough 💰chips to join the game.\nMinimum bet is {game.bet_amount} 💰chips.")
        return

    # Add the player to the game
    JoinGame.objects.create(player=player, game=game, is_active=True)
    # update.message.reply_text(f"{user_name} has joined the game!")
    # context.bot.send_message(chat_id=chat_id, text=f"{user_name} has joined the game!")
    # Send a message tagging the user who joined
    from telegram.utils.helpers import escape_markdown

    escaped_user_name = escape_markdown(user_name, version=2)

    context.bot.send_message(
        chat_id=chat_id, 
        text=f"[{escaped_user_name}](tg://user?id={user_id}) has joined the game\\!", 
        parse_mode="MarkdownV2", timeout=20
    )

def force_start(update: Update, context: CallbackContext,game_chat_id=None):
    try:
        chat_id = update.message.chat_id
    except:
        chat_id = game_chat_id
    
    try:
        # First, try to find a game that is in the join time, not started, and not ended.
        game = Game.objects.get(chat_id=chat_id, join_time=True, started=False, ended=False, betting=False)
    except Game.DoesNotExist:
        try:
            # If no such game exists, check if there's a game in the betting process.
            game = Game.objects.get(chat_id=chat_id, join_time=False, started=False, ended=False, betting=True)
            safe_send_message_join(context.bot, chat_id, "The game is in the betting process. Please wait for it to end, then forcestart the game.")

            # Inform the user that the game is still in the betting process.
            # update.message.reply_text("The game is in the betting process. Please wait for it to end, then use /join to join the game.")
            return
        except Game.DoesNotExist:
            try:
                game = Game.objects.get(chat_id=chat_id, join_time=False, started=True, ended=False, betting=False)
                safe_send_message_join(context.bot, chat_id, "A game has already started you can not forcestart the game, use /nextgame to be prompted when another game is started")
                # If neither join_time nor betting games exist, inform the user that no game is active.
                # update.message.reply_text("A game has already started you can not join the game, use /nextgame to be prompted when another game is started")
                return
            except Game.DoesNotExist:
                
                safe_send_message_join(context.bot, chat_id, "No active Blackjack game. Start one by typing /startblackjack.")
                
                # update.message.reply_text("No active Blackjack game. Start one by typing /startblackjack.")
                return

    # Fetch all active players who have joined the game
    joined_players = JoinGame.objects.filter(game=game, is_active=True)

    # Check if there are enough players
    if joined_players.count() < 1:
        message_text = 'Not enough players, ending the game!'
        if update.message:
            update.message.reply_text(message_text)
        else:
            context.bot.send_message(chat_id=chat_id, text=message_text)
        Game.objects.filter(chat_id=chat_id).delete()
        return
    dealer = Dealer.objects.first()  # Assuming there's only one dealer
    group_game,created = Group.objects.get_or_create(group_chat_id=chat_id)
    group_game.games += 1
    group_game.save()
    # Handle the dealer's chips deduction
    if dealer:
        dealer.chips -= game.bet_amount
        dealer.games += 1
        dealer.save()
        context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer is in the game with {game.bet_amount} 💰chips on the table\\.",
            parse_mode="MarkdownV2", timeout=20)
    # Deduct the bet amount from each player's chips
    for join_entry in joined_players:
        player = join_entry.player
        player.chips -= game.bet_amount
        player.games += 1
        player.save()  # Save the updated chips amount to the Player model
        # update.message.reply_text(f"{player.name} has bet {game.bet_amount} chips. Remaining chips: {player.chips}")
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', player.name)

        mention = f"[{user_name_escaped}](tg://user?id={player.id})"
        time.sleep(2)
        context.bot.send_message(chat_id=chat_id, text=f"{mention} has bet {game.bet_amount} chips\\.\nRemaining chips: 💰{player.chips}", 
            parse_mode="MarkdownV2", timeout=20)

    # Initialize turn order with the list of player IDs
    game.turn_order = list(joined_players.values_list('player__id', flat=True))
    game.current_round = 1  # Start with round 1
    players_count = joined_players.count() + 1
    game.pot = game.bet_amount *  players_count # Track total pot across rounds

    # Set the game as started
    game.started = True
    game.join_time = False

    # Proceed to the first round
    start_round(update, context, game, joined_players)
# Function to start each round
def safe_pin_chat_message(bot, chat_id, message_id, timeout=20, max_retries=3):
    retries = 0
    while retries < max_retries:
        try:
            bot.pin_chat_message(chat_id=chat_id, message_id=message_id, timeout=timeout)
            return  # Exit the loop if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while pinning message. Retrying {retries}/{max_retries}...")
            time.sleep(2 ** retries)  # Exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Rate limit exceeded. Retrying in {retry_after} seconds...")
            time.sleep(retry_after)  # Wait for the retry after time
            retries += 1

    print("Failed to pin message after multiple retries.")

def start_round(update: Update, context: CallbackContext, game, joined_players):
    chat_id = update.message.chat_id

    print(game.current_round)
    
    if game.current_round >= 2:
        print('in hereadf')

        # Fetch player round winners and dealer wins
        bot_member = context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)

        round_winners = RoundWinner.objects.filter(game=game, is_dealer=False)
        dealer_wins = RoundWinner.objects.filter(game=game, is_dealer=True).count()
        winner_count = {}

        for winner in round_winners:
            if winner.winner in winner_count:
                winner_count[winner.winner] += 1
            else:
                winner_count[winner.winner] = 1

        # Separate players with wins and without wins
        winners = []
        no_wins = []

        for player in joined_players:
            player_name = player.player.name
            player_id = player.player.id
            wins = winner_count.get(player.player, 0)

            if wins > 0:
                winners.append((player_name, wins, player_id))
            else:
                no_wins.append((player_name, player_id))

        # Sort winners by wins (descending)
        winners = sorted(winners, key=lambda x: x[1], reverse=True)

        # Build the standings message
        standings_message = "📊 Current standings:\n"

        # Add the dealer wins first, if any
        if dealer_wins > 0:
            standings_message += f"🤖 Dealer: {dealer_wins} round\\(s\\) won\n"
        else:
            standings_message += f"🤖 Dealer: No wins yet\n"

        # Add players with wins
        for winner_name, wins, user_id in winners:
            user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', winner_name)
            mention = f"[{user_name_escaped}](tg://user?id={user_id})"
            standings_message += f"🏆 {mention}: {wins} round\\(s\\) won\n"

        # Add players with no wins
        for player_name, player_id in no_wins:
            user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', player_name)
            mention = f"[{user_name_escaped}](tg://user?id={player_id})"
            standings_message += f"🎲 {mention}: No wins yet\n"

        # Send the message with the standings
        message = context.bot.send_message(chat_id=chat_id, text=standings_message, parse_mode="MarkdownV2", timeout=20)


        # Check if the bot is an admin and pin the message if it is
        if bot_member.status in ['administrator', 'creator']:
            # Pin the message
            safe_pin_chat_message(context.bot, chat_id, message.message_id)


    context.bot.send_message(chat_id=chat_id, text=f"Starting round {game.current_round}...",timeout=20)
    time.sleep(3)


    player_blackjacks = []
    # chat_id = update.message.chat_id

    # Deal initial hands to players and save to the JoinGame model
    # Add this after dealing the cards to players
    for join_entry in joined_players:
        player_hand = [deal_card(), deal_card()]
        join_entry.hand = player_hand  # Assuming the 'hand' is a JSONField in JoinGame model
        join_entry.save()

        print(f"Dealt hand {player_hand} to player {join_entry.player.name}")  # Debugging line
    

        # Check for natural Blackjack
        player_hand_value = calculate_hand_value(player_hand)
        if player_hand_value == 21:
            player_blackjacks.append(join_entry)
        else:
            context.bot.send_message(chat_id=join_entry.player.id, text=f"🃏Your hand: {player_hand}.\n♠️Total value: {player_hand_value}",timeout=20)

    # Deal cards to the dealer and save to the Game model
    dealer_hand = [deal_card(), deal_card()]
    game.dealer_hand = dealer_hand  # Assuming 'dealer_hand' is a JSONField in Game model
    game.save()

    # Show only one dealer card
    context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer's visible card: ♠️{dealer_hand[0]}",timeout=20)

    # Check for dealer
    dealer_value = calculate_hand_value(dealer_hand)
    dealer_has_blackjack = dealer_value == 21

    if dealer_has_blackjack:
        context.bot.send_message(chat_id=chat_id, text="🤖 Dealer has a Blackjack! 💥",timeout=20)
        dealer = Dealer.objects.get(id=1)
        dealer.blackjack_count += 1
        # dealer.wins += 1
        dealer.save()

        # Mark losing stats for players who didn't get Blackjack
        # for join_entry in joined_players:
        #     if join_entry not in player_blackjacks:
        #         stats = Stats.objects.get(player=join_entry.player)
        #         stats.loses += 1  # Increment losing stats
        #         stats.save()

        # Check for player Blackjack ties (push)
        for join_entry in player_blackjacks:
            context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} had Blackjack💥 too. It's a push.",timeout=20)

        # Mark dealer as the round winner
        RoundWinner.objects.create(game=game, round_number=game.current_round, is_dealer=True)
        game.current_round += 1
        check_for_next_round(update, context, game, joined_players)
        return

    # If dealer doesn't have a Blackjack but players do
    if player_blackjacks:
        for join_entry in player_blackjacks:
            context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} has a natural Blackjack!💥 They win the round.",timeout=20)
            
            # Update stats (no payout, just marking the win)
            stats = Stats.objects.get(player=join_entry.player)
            # stats.wins += 1
            stats.how_many_21 += 1
            stats.save()

            # Mark the player as the round winner
            RoundWinner.objects.create(game=game, round_number=game.current_round, winner=join_entry.player)

        game.current_round += 1
        check_for_next_round(update, context, game, joined_players)
        return

    # Mark losing stats for players who don't have Blackjack
    for join_entry in joined_players:
        if join_entry not in player_blackjacks:
            stats = Stats.objects.get(player=join_entry.player)
            # stats.loses += 1  # Increment losing stats
            stats.save()

    # Continue to the first player's turn if no Blackjack
    player_turn(update, context)







def update_statistics(winners, dealer_wins, joined_players):
    print("Starting update_statistics function")
    
    # Initialize a list for non-winners
    non_winners = []
    print("Initialized non_winners list")

    # Update stats for each winner
    for winner in winners:
        if winner == 'dealer':
            dealer = Dealer.objects.first()  # Assuming only one dealer
            dealer.wins += 1
            dealer.save()
            print(f"Dealer wins updated: {dealer.wins}")
        else:
            player = Player.objects.get(id=winner.id)
            stats, created = Stats.objects.get_or_create(player=player)
            stats.wins += 1
            stats.save()
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
        stats, created = Stats.objects.get_or_create(player=player)
        stats.loses += 1
        stats.save()
        print(f"Player {player.id} losses updated: {stats.loses}")

    # Update dealer's losses if dealer did not win
    if not dealer_wins:
        dealer = Dealer.objects.first()  # Assuming only one dealer
        dealer.loses += 1  # Ensure you have a `loses` field in your Dealer model
        dealer.save()
        print(f"Dealer losses updated: {dealer.loses}")

    print("Finished update_statistics function")





def check_for_next_round(update: Update, context: CallbackContext, game, joined_players):
    chat_id = update.message.chat_id
    time.sleep(3)
    
    if game.current_round > game.total_rounds:
        # Determine the overall winner
        round_winners = RoundWinner.objects.filter(game=game)
        
        # Count wins for each player and the dealer
        winner_count = {}
        for winner in round_winners:
            if winner.winner:
                if winner.winner in winner_count:
                    winner_count[winner.winner] += 1
                else:
                    winner_count[winner.winner] = 1

        dealer_wins = RoundWinner.objects.filter(game=game, is_dealer=True).count()
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
                    context.bot.send_message(chat_id=chat_id, text="🤖 Dealer is the overall winner of the game! 🏆", timeout=20)
                else:
                    context.bot.send_message(chat_id=chat_id, text=f"{overall_winner.name} is the overall winner of the game! 🏆", timeout=20)
                    
            elif len(overall_winners) > 1:
                # Multiple winners (tie)
                winner_names = ', '.join([f"[{winner.name}](tg://user?id={winner.id})" if winner != 'dealer' else "🤖 Dealer" for winner in overall_winners])
                context.bot.send_message(chat_id=chat_id, text=f"{winner_names} tied and shared the pot\\! 🏆", parse_mode="MarkdownV2", timeout=20)

            # Update statistics for winners and losers
            update_statistics(overall_winners, dealer_wins, joined_players)
            
        else:
            context.bot.send_message(chat_id=chat_id, text="No overall winner was determined.", timeout=20)

        # Call the end_game function to finalize the game
        end_game(update, context)  # Ensure end_game is called after determining the winner

        # Prepare standings message
        bot_member = context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        round_winners = RoundWinner.objects.filter(game=game, is_dealer=False)
        dealer_wins = RoundWinner.objects.filter(game=game, is_dealer=True).count()
        winner_count = {}

        for winner in round_winners:
            if winner.winner in winner_count:
                winner_count[winner.winner] += 1
            else:
                winner_count[winner.winner] = 1

        winners = []
        no_wins = []

        for player in joined_players:
            player_name = player.player.name
            player_id = player.player.id
            wins = winner_count.get(player.player, 0)

            if wins > 0:
                winners.append((player_name, wins, player_id))
            else:
                no_wins.append((player_name, player_id))

        winners = sorted(winners, key=lambda x: x[1], reverse=True)
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

        message = context.bot.send_message(chat_id=chat_id, text=standings_message, parse_mode="MarkdownV2", timeout=20)

        if bot_member.status in ['administrator', 'creator']:
            safe_pin_chat_message(context.bot, chat_id, message.message_id)
            
        Game.objects.filter(chat_id=chat_id).delete()
        context.bot.send_message(chat_id=chat_id, text="The game has ended. You can start a new game by typing /startblackjack.", timeout=20)

    else:
        # Prepare for the next round
        game.hands_reset = False
        game.save()

        time.sleep(3)
        start_round(update, context, game, joined_players)


timers = {}
def send_reminder(chat_id, context, user_id):
    mention = f"[user](tg://user?id={user_id})"
    context.bot.send_message(chat_id=chat_id, text=f"{mention}, 10 seconds left to make your decision\\!", parse_mode='MarkdownV2')

def player_turn(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    try:
        game = Game.objects.get(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        update.message.reply_text("No active game or the game has not started.")
        return

    players_in_game = JoinGame.objects.filter(game=game, is_active=True).order_by('id')
    
    if not game.turn_order or game.current_round > 1:
        game.turn_order = list(players_in_game.values_list('player__id', flat=True))
        game.save()

    current_player_id = game.turn_order[0]
    current_player = Player.objects.get(id=current_player_id)

    # Cancel previous timers if they exist
    if chat_id in timers:
        timers[chat_id]['auto_stand'].cancel()
        timers[chat_id]['reminder'].cancel()

    # Set up and start the timer for the current player
    auto_stand_timer = threading.Timer(30.0, auto_stand, [chat_id, current_player_id, current_player.name, context, update.message.chat.type])
    reminder_timer = threading.Timer(20.0, send_reminder, [chat_id, context, current_player_id])

    auto_stand_timer.start()
    reminder_timer.start()

    # Store the timers in a dictionary for easy access
    timers[chat_id] = {'auto_stand': auto_stand_timer, 'reminder': reminder_timer}

    if update.message.from_user.id == current_player_id:
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', current_player.name)
        mention = f"[{user_name_escaped}](tg://user?id={current_player.id})"
        context.bot.send_message(chat_id=chat_id, text=f"{mention}, it's your turn\\! Type:\n/hit 🎰 to draw a card or \n\n/stand❗ to keep your hand\\.\n\nyou have 30 seconds to make a decision or it will automatically stand\\!", parse_mode="MarkdownV2")
    else:
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', current_player.name)
        mention = f"[{user_name_escaped}](tg://user?id={current_player.id})"
        context.bot.send_message(chat_id=chat_id, text=f"Waiting for {mention}'s decision\\.\\.\\. Type: \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your current hand\\.\n\nyou have 30 seconds to make a decision or it will automatically stand\\!", parse_mode="MarkdownV2")

def escape_markdown_v2(text):
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

def safe_send_message(bot, chat_id, text, parse_mode="MarkdownV2", timeout=20, max_retries=5):
    retries = 0
    while retries < max_retries:
        try:
            bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, timeout=timeout)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            time.sleep(2 ** retries)  # Exponential backoff: 2, 4, 8 seconds, etc.
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            time.sleep(retry_after)  # Wait for the RetryAfter period before retrying
            retries += 1
    print(f"Failed to send the message after {max_retries} retries.")

def auto_stand(chat_id, current_player_id, current_player_name, context, chat_type='private'):
    # Automatically call the stand function if the timer expires
    context.bot.send_message(chat_id=chat_id, text="Time's up! Your turn is now considered a stand.")
    
    # Create a Chat object with dynamic type
    chat = Chat(id=chat_id, type=chat_type)  # chat_type could be 'private', 'group', 'supergroup'

    # Create a Message object
    message = Message(
        message_id=0,  # Dummy values; adjust as needed
        from_user=User(id=current_player_id, first_name=current_player_name, is_bot=False),
        chat=chat,
        date=datetime.datetime.now(),  # Replace with actual date if necessary
        text=""  # Empty text, as it's not used here
    )
    
    # Create the Update object with the Message
    update = Update(update_id=0, message=message)  # Dummy update_id; adjust as needed

    stand(update, context)

def hit(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = Game.objects.get(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        update.message.reply_text("No active game or the game has not started.")
        return

    try:
        player = Player.objects.get(id=user_id)
    except Player.DoesNotExist:
        update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    try:
        join_game = JoinGame.objects.get(player=player, game=game, is_active=True)
    except JoinGame.DoesNotExist:
        update.message.reply_text("You are not part of the game.")
        return

    if user_id != game.turn_order[0]:
        update.message.reply_text("It's not your turn!")
        return

    # Cancel the existing timer if the player makes a move
    if chat_id in timers:
        timers[chat_id].cancel()
        del timers[chat_id]

    new_card = deal_card()
    join_game.hand.append(new_card)
    join_game.save()

    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', user_name)
    mention = f"[{user_name_escaped}](tg://user?id={user_id})"
    safe_send_message(context.bot, chat_id, f"{mention} drew: {new_card}")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)

    safe_send_message(context.bot, user_id, f"Your full hand: {player_hand}\\. Total value: {hand_value}")

    if hand_value == 21:
        stats = Stats.objects.get(player=join_game.player)
        stats.how_many_21 += 1
        stats.save()
        safe_send_message(context.bot, chat_id, f"{mention} Reached BlackJack💥\\! \n They automatically stand\\.")
        next_player_turn(update, context)
    elif hand_value > 21:
        safe_send_message(context.bot, chat_id, f"{mention} busted with a total of {hand_value}\\.")
        next_player_turn(update, context)
    else:
        player_turn(update, context)
        # safe_send_message(context.bot, chat_id, f"{mention} Type: \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your current hand\\.")

def stand(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = Game.objects.get(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        update.message.reply_text("No active game or the game has not started.")
        return

    try:
        player = Player.objects.get(id=user_id)
    except Player.DoesNotExist:
        update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    try:
        join_game = JoinGame.objects.get(player=player, game=game, is_active=True)
    except JoinGame.DoesNotExist:
        update.message.reply_text("You are not part of the game.")
        return

    if user_id != game.turn_order[0]:
        update.message.reply_text("It's not your turn!")
        return

    if chat_id in timers:
        timers[chat_id].cancel()
        del timers[chat_id]

    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', user_name)
    mention = f"[{user_name_escaped}](tg://user?id={user_id})"
    safe_send_message(context.bot, chat_id, f"{mention} has chosen to stand\\.")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    safe_send_message(context.bot, user_id, f"You have chosen to stand\\. Your final hand: {player_hand}\\. Total value: {hand_value}")

    next_player_turn(update, context)


# Function to move to the next player's turn
# Move to the next player's turn by removing the current player from the turn order
def safe_send_message_next_player_turn(bot, chat_id, text, timeout=20, max_retries=5):  # Increased timeout
    retries = 0
    while retries < max_retries:
        try:
            bot.send_message(chat_id=chat_id, text=text, timeout=timeout, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            time.sleep(3)  # Wait a bit before retrying
    print("Failed to send the message after retries.")

def next_player_turn(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    try:
        game = Game.objects.get(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        update.message.reply_text("No active game or the game has not started.")
        return

    if not game.turn_order:
        # If no players are left in the turn order, proceed to the dealer's turn
        dealer_turn(update, context)
        return

    # Remove the current player from the turn order
    game.turn_order.pop(0)
    game.save()

    # Check if there are more players left to take their turn
    if game.turn_order:
        next_player_id = game.turn_order[0]
        next_player = Player.objects.get(id=next_player_id)
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', next_player.name)

        mention = f"[{user_name_escaped}](tg://user?id={next_player_id})"
        time.sleep(3)
        safe_send_message_next_player_turn(context.bot, chat_id, f"{mention}, it's your turn\\! Type \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your hand\\.")
    else:
        # All players have finished their turns, now it's the dealer's turn
        dealer_turn(update, context)



def safe_send_message_dealer(bot, chat_id, text, timeout=20, max_retries=5):
    retries = 0
    while retries < max_retries:
        try:
            bot.send_message(chat_id=chat_id, text=text, timeout=timeout, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            time.sleep(3)  # Wait a bit before retrying
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            time.sleep(retry_after)  # Wait for the RetryAfter period before retrying
            retries += 1

    print("Failed to send the message after retries.")

def dealer_turn(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    try:
        game = Game.objects.get(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        safe_send_message_dealer(context.bot, chat_id, "No active game or the game has not started\\.")
        return
    time.sleep(2)
    safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer's turn\\.\\.\\.")

    dealer_hand = game.dealer_hand
    dealer_value = calculate_hand_value(dealer_hand)

    # Dealer's logic: drawing until reaching at least 17
    while dealer_value < 17:
        new_card = deal_card()
        dealer_hand.append(new_card)
        dealer_value = calculate_hand_value(dealer_hand)
        time.sleep(2)
        safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer draws a 🂾{new_card}\\. 🤖 Dealer's hand: {dealer_hand}")

    # If dealer busts (> 21)
    if dealer_value > 21:
        time.sleep(2)
        safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer busts with a total of {dealer_value}\\!❌")
        dealer_busted = True
    else:
        time.sleep(2)
        safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer stands with a total of {dealer_value}\\.")
        dealer_busted = False

    # Save the updated dealer hand
    game.dealer_hand = dealer_hand
    game.save()

    # Fetch all active players who have joined the game
    joined_players = JoinGame.objects.filter(game=game, is_active=True)

    # Track the player(s) who win this round
    highest_valid_score = 0
    round_winners = []

    for join_entry in joined_players:
        player_hand_value = calculate_hand_value(join_entry.hand)
        
        # If player busted, skip them
        if player_hand_value > 21:
            continue
        
        # Track the highest valid hand that beats the dealer (if dealer didn't bust)
        if dealer_busted or player_hand_value > dealer_value:
            if player_hand_value > highest_valid_score:
                highest_valid_score = player_hand_value
                round_winners = [join_entry.player]
            elif player_hand_value == highest_valid_score:
                round_winners.append(join_entry.player)

    if not round_winners:
        time.sleep(2)

        safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer wins🥇 this round\\!")
        RoundWinner.objects.create(game=game, round_number=game.current_round, is_dealer=True)
    else:
        for winner in round_winners:
            time.sleep(2)
            try:
                # Try to tag winner using their name
                mention = f"[{winner.name}](tg://user?id={winner.id})"
            except Exception as e:
                # Fallback to just using the player's name if tagging fails
                mention = winner.name
                print(f"Error tagging player {winner.name}: {str(e)}")  # Log the error for debugging

            safe_send_message_dealer(context.bot, chat_id, f"{mention} wins🥇 this round with a hand of {highest_valid_score}\\!")
            RoundWinner.objects.create(game=game, round_number=game.current_round, winner=winner)

    # Announce the round winner before starting the next round
    if not round_winners:
        time.sleep(2)
        safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer won🥇 round {game.current_round}\\!")
    else:
        time.sleep(2)
        # Initialize winner_mentions to avoid UnboundLocalError
        winner_mentions = ""

        try:
            winner_mentions = ', '.join([f"[{winner.name}](tg://user?id={winner.id})" for winner in round_winners])
        except Exception as e:
            # Fallback to using plain names if tagging fails
            winner_mentions = ', '.join([winner.name for winner in round_winners])
            print(f"Error tagging winners: {str(e)}")  # Log the error for debugging

        # Send the message with the round winners
        safe_send_message_dealer(context.bot, chat_id, f"{winner_mentions} won🥇 round {game.current_round}\\!")



    # Proceed to the next round or end the game if all rounds are done
    game.current_round += 1
    check_for_next_round(update, context, game, joined_players)

def reset_game(chat_id):
    try:
        # Get the active game with the given chat_id
        game = Game.objects.get(chat_id=chat_id, started=True, ended=False)
        
        # Mark the game as ended and reset its fields
        game.ended = True
        game.started = False
        game.betting = False
        game.join_time = False
        game.save()

        # Reset all players' is_active status to False for the current game
        JoinGame.objects.filter(game=game, is_active=True).update(is_active=False)

    except Game.DoesNotExist:
        pass
def end_game(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    try:
        game = Game.objects.get(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        context.bot.send_message(chat_id=chat_id, text="No active game to end.", timeout=20)
        return

    # Get round winners and determine the final winner
    dealer_rounds_won = RoundWinner.objects.filter(game=game, is_dealer=True, rounds_ended=False).count()
    player_rounds = RoundWinner.objects.filter(game=game, is_dealer=False, rounds_ended=False)

    round_wins = {}
    for round_win in player_rounds:
        if round_win.winner in round_wins:
            round_wins[round_win.winner] += 1
        else:
            round_wins[round_win.winner] = 1

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
            dealer = Dealer.objects.get(id=1)
            dealer.chips += split_pot
            # dealer.wins += 1
            dealer.save()
            context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer wins {split_pot} chips💰!", timeout=20)

        for winner in winners:

            winner.chips += split_pot
            # stats = Stats.objects.get(player=winner)
            # stats.wins +=1
            # stats.save()
            winner.save()
            context.bot.send_message(chat_id=chat_id, text=f"{winner.name} wins {split_pot} chips💰!", timeout=20)

    else:
        context.bot.send_message(chat_id=chat_id, text="No one won this game.", timeout=20)

    # Mark the game as ended
    game.ended = True
    game.started = False
    game.betting = False
    game.join_time = False
    game.save()
    # RoundWinner.objects.filter(game=game, rounds_ended=False).update(rounds_ended=True)

        
def reset_round_state(game):
    # Reset the hands and necessary state for the next round
    JoinGame.objects.filter(game=game, is_active=True).update(hand=[])
    game.dealer_hand = []
    game.save()

def start_next_round(update: Update, context: CallbackContext):
    time.sleep(2)
    chat_id = update.message.chat_id
    game = Game.objects.get(chat_id=chat_id, started=True, ended=False)

    # Deal new hands to players and start the next round
    joined_players = JoinGame.objects.filter(game=game, is_active=True)
    
    for join_entry in joined_players:
        player_hand = [deal_card(), deal_card()]
        join_entry.hand = player_hand
        join_entry.save()

        # Inform the player about their new hand
        player = join_entry.player
        hand_value = calculate_hand_value(player_hand)
        context.bot.send_message(chat_id=chat_id, text=f"Your new 🃏hand: {player_hand}. Total value: {hand_value}", timeout=20)

    # Deal cards to the dealer for the next round
    dealer_hand = [deal_card(), deal_card()]
    game.dealer_hand = dealer_hand
    game.save()

    # update.message.reply_text(f"Dealer's visible card: {dealer_hand[0]}")
    context.bot.send_message(chat_id=player.id, text=f"🤖 Dealer's visible 🃏card: {dealer_hand[0]}", timeout=20)

    # Continue to the first player's turn for the next round
    player_turn(update, context)
from django.core.exceptions import ObjectDoesNotExist

def get_player_instance(user_id):
    try:
        # Attempt to retrieve the Player instance based on user ID
        player = Player.objects.get(id=user_id)
        return player
    except ObjectDoesNotExist:
        # Return None or handle the case where the player does not exist
        return None

# Example usage in the bot:
def get_player_chips(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    
    # Fetch the player instance
    player = get_player_instance(user_id)
    
    if player:
        # If the player exists, return their chips or use them in logic
        context.bot.send_message(chat_id=update.message.chat_id, text=f"{player.name} has {player.chips} 💰chips.", timeout=20)
    else:
        # Handle the case where the player does not exist
        context.bot.send_message(chat_id=update.message.chat_id, text="You don't have a player profile yet. Start the bot in private to create one.", timeout=20)
def get_dealer_blackjack_stats(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id

    try:
        dealer = Dealer.objects.first()  # Assuming there's only one dealer, get the first instance
        if dealer is None:
            update.message.reply_text("No dealer stats found.")
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
        context.bot.send_message(chat_id=chat_id, text=stats_message, timeout=20)

    except Exception as e:
        update.message.reply_text(f"Error retrieving dealer stats: {str(e)}")

# Main function
def main():
    # if Testing_mode:
    #     bot_token = '7094966045:AAEKHTVCZbRS7LPNF2QZlPrPhJQ9GohlE2A'
    # else:
    bot_token = '7041648826:AAFMkq1-fX740ZTT3OVbPowzbzJooMCi118'
    updater = Updater(bot_token, use_context=True)
    dp = updater.dispatcher

    # Handlers for commands
    dp.add_handler(CommandHandler('startblackjack', start_blackjack))
    dp.add_handler(CommandHandler('dealer_stats', get_dealer_blackjack_stats))
    dp.add_handler(CommandHandler('join', join_blackjack))
    dp.add_handler(CommandHandler('forcestart', force_start))
    dp.add_handler(CommandHandler('hit', hit))
    dp.add_handler(CommandHandler('stand', stand))
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('stats', stats))
    dp.add_handler(CommandHandler('my_tokens', get_player_chips))
    dp.add_handler(PollAnswerHandler(poll_answer_handler))
    dp.add_handler(CommandHandler("tag", tag_users))


    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()