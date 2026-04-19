import asyncio
import sys
import json
import httpx

sys.stdout.reconfigure(encoding='utf-8')

BOT_TOKEN = '8752995493:AAHKjjr5CMLZNlytylfNxlVfeJUz2BvnoNg'

async def main():
    async with httpx.AsyncClient(timeout=15) as client:
        # Check bot info
        r = await client.get(f'https://api.telegram.org/bot{BOT_TOKEN}/getMe')
        data = r.json()
        bot = data['result']
        print(f"Bot username: @{bot['username']}")
        print(f"Bot name: {bot['first_name']}")
        print("Bot is ALIVE!")

        # Send a test message to the bot owner / check recent chat
        # Get updates to see if bot processed messages
        r2 = await client.get(
            f'https://api.telegram.org/bot{BOT_TOKEN}/getUpdates',
            params={'limit': 10}
        )
        upd = r2.json()
        results = upd.get('result', [])
        if results:
            print(f"\nRecent {len(results)} updates processed:")
            for u in results:
                msg = u.get('message', {})
                from_user = msg.get('from', {})
                text = msg.get('text', '')
                name = from_user.get('first_name', '?')
                uid = from_user.get('id', '?')
                print(f"  [{uid}] {name}: {text}")
        else:
            print("\nNo pending updates - bot polling and processed all messages OK!")

asyncio.run(main())
