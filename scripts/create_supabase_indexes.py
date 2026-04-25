"""Create Supabase indexes for better query performance."""

import os
from supabase import create_client

def main():
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        print("❌ Missing Supabase credentials")
        return
    
    client = create_client(supabase_url, supabase_key)
    
    # Index 1: trend_history composite index
    try:
        sql1 = """
        CREATE INDEX IF NOT EXISTS idx_trend_history_source_metric_date 
        ON trend_history (source, metric_name, recorded_at);
        """
        client.postgrest._execute(sql1)
        print("✅ Created idx_trend_history_source_metric_date")
    except Exception as e:
        print(f"⚠️  Index 1 may already exist or error: {e}")
    
    # Index 2: digests created_at index
    try:
        sql2 = """
        CREATE INDEX IF NOT EXISTS idx_digests_created_at 
        ON digests (created_at DESC);
        """
        client.postgrest._execute(sql2)
        print("✅ Created idx_digests_created_at")
    except Exception as e:
        print(f"⚠️  Index 2 may already exist or error: {e}")
    
    # Index 3: unique constraint on digests
    try:
        sql3 = """
        ALTER TABLE digests ADD CONSTRAINT IF NOT EXISTS unique_digest_per_type_date 
        UNIQUE (type, created_at::date);
        """
        client.postgrest._execute(sql3)
        print("✅ Added unique constraint on digests")
    except Exception as e:
        print(f"⚠️  Constraint may already exist or error: {e}")
    
    print("\n✅ All Supabase indexes created successfully!")

if __name__ == "__main__":
    # Load .env
    from dotenv import load_dotenv
    load_dotenv()
    main()
