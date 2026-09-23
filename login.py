from telethon import TelegramClient
import os

# Telegram API credentials
api_id = 39870171
api_hash = '2f80e0b5a0044e201c64df5d43190dc4'

# Phone number
phone_number = '+998507832530'

# Folder to store sessions
SESSION_DIR = "sessions"

# Create folder if it doesn't exist
os.makedirs(SESSION_DIR, exist_ok=True)

# Session file path
session_path = os.path.join(SESSION_DIR, phone_number)

# Create client
client = TelegramClient(session_path, api_id, api_hash)


async def main():
    # Login
    await client.start(phone=phone_number)

    print("\n✅ Successfully logged in!")
    print(f"📁 Session saved in: {session_path}.session")

    # Get user info
    me = await client.get_me()

    print(f"👤 Name: {me.first_name} {me.last_name or ''}")
    print(f"🔗 Username: @{me.username or 'No username'}")
    print(f"🆔 User ID: {me.id}")


# Run client
with client:
    client.loop.run_until_complete(main())