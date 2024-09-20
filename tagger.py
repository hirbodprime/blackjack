from telethon import TelegramClient, events
import time

# Your API ID and Hash from https://my.telegram.org
api_id = '1723719'
api_hash = 'dce2a0e1a8376fec526b76bb99746238'
phone_number = '+989032292777'

# Create the client
client = TelegramClient('tagger_session', api_id, api_hash)

# Function to tag all users in a group
async def tag_all_users(event):
    chat = await event.get_chat()
    
    # Only allow this in groups and supergroups
    if chat.broadcast or chat.megagroup:
        async for user in client.iter_participants(chat):
            if user.bot:
                continue

            if user.username:
                mention = f"@{user.username}"
            else:
                mention = user.first_name

            # Send mention message
            await client.send_message(chat, mention)
            time.sleep(0.5)  # Adding a delay to avoid spamming

# Event handler for "/tagall" command
@client.on(events.NewMessage(pattern='Tag'))
async def handler(event):
    await tag_all_users(event)

# Start the client
client.start(phone=phone_number)
client.run_until_disconnected()
