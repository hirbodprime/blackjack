from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler
from telegram.constants import ChatAction
import asyncio

# List of commands for bot
async def start(update: Update, context):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Hello! I'm a tagger bot. Use /tagall to mention everyone!")

async def tag_all(update: Update, context):
    # Get chat members (you need admin privileges for the bot in the group)
    chat_id = update.effective_chat.id
    members = await context.bot.get_chat_administrators(chat_id)

    # Send a message tagging each user individually
    for member in members:
        if member.user.username:
            user_tag = f"@{member.user.username}"
        else:
            user_tag = f"{member.user.first_name}"

        # Send individual message for each user
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        await context.bot.send_message(chat_id=chat_id, text=f"{user_tag}")
        
        # Optionally add a short delay between messages
        await asyncio.sleep(1)


if __name__ == '__main__':
    # Add your bot token here
    BOT_TOKEN = "7777229902:AAHeyjHFlPmgRB9qk-0iuBD93UTIihnWU_Y"

    # Build the application
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tagall", tag_all))

    # Run the bot
    app.run_polling()
