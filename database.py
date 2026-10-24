import aiosqlite
from datetime import date, timedelta, datetime

# 1. FIXED PATH for Railway volume
DB_NAME = "/data/test_bot.db" 

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            matches_today INTEGER DEFAULT 0,
            premium_until TEXT, 
            last_match_date TEXT,
            is_vip INTEGER DEFAULT 0
        )''')
        await db.commit()

async def add_or_update_user(user_id: int):
    today = str(date.today())
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT last_match_date FROM users WHERE id=?", (user_id,))
        row = await cursor.fetchone()
        
        if row is None:
            await db.execute("INSERT INTO users (id, last_match_date) VALUES (?, ?)", (user_id, today))
        elif row[0] != today:
            await db.execute("UPDATE users SET last_match_date=? WHERE id=?", (today, user_id))
        
        await db.commit()

async def can_user_match(user_id: int, free_limit: int = 1) -> bool:
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT premium_until, matches_today, is_vip FROM users WHERE id=?", (user_id,))
        row = await cursor.fetchone()
        
        if not row:
            return False
            
        premium_until = row[0]
        matches_today = row[1]
        is_vip = row[2]
        
        # 2. RESTORED BULLETPROOF VIP CHECK
        if is_vip in (1, "1", True):
            return True
            
        is_premium = False
        if premium_until:
            expiration_date = datetime.strptime(premium_until, "%Y-%m-%d").date()
            if date.today() <= expiration_date:
                is_premium = True

        return is_premium or (matches_today < free_limit)

async def increment_match_count(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET matches_today = matches_today + 1 WHERE id=?", (user_id,))
        await db.commit()

async def add_premium_days(user_id: int, days: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT premium_until FROM users WHERE id=?", (user_id,))
        row = await cursor.fetchone()
        
        today = date.today()
        if row and row[0]:
            current_expiration = datetime.strptime(row[0], "%Y-%m-%d").date()
            if current_expiration > today:
                new_expiration = current_expiration + timedelta(days=days)
            else:
                new_expiration = today + timedelta(days=days)
        else:
            new_expiration = today + timedelta(days=days)

        await db.execute("UPDATE users SET premium_until = ? WHERE id = ?", (str(new_expiration), user_id))
        await db.commit()
        
async def make_user_vip(user_id: int): 
    """Admin function to grant lifetime access."""
    async with aiosqlite.connect(DB_NAME) as db:
        # 3. RESTORED NEW USER CREATION LOGIC
        cursor = await db.execute("SELECT id FROM users WHERE id=?", (user_id,))
        row = await cursor.fetchone()
        
        if row is None:
            today = str(date.today())
            await db.execute("INSERT INTO users (id, matches_today, last_match_date, is_vip) VALUES (?, 0, ?, 1)", (user_id, today))
        else:
            await db.execute("UPDATE users SET is_vip = 1 WHERE id = ?", (user_id,))
            
        await db.commit()