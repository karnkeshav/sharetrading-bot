import asyncio
import os
from supabase import acreate_client

async def test():
    url = "https://jjdychkwfjqweeydizwm.supabase.co"
    key = "sb_publishable_yw60mJfCp94475rmm64sgQ_bm0vdhqY"
    
    print("Attempting to connect to Supabase...")
    try:
        client = await acreate_client(url, key)
        # Try a simple select to test authentication
        res = await client.table("config_versions").select("*").limit(1).execute()
        print("Connection successful! Config versions data:", res.data)
    except Exception as e:
        print("Connection status: Checked, but encountered exception:", str(e))
        print("This is normal if the tables do not exist yet. Let's check table list next.")

if __name__ == "__main__":
    asyncio.run(test())
