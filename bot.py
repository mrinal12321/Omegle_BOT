import asyncio
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command ,CommandObject
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from database import init_db,add_or_update_user,can_user_match,increment_match_count,add_premium_days,make_user_vip

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp= Dispatcher()
waitlist={}
active_matches={}
message_map = {} #Provides the delete sent between users so they can delete their own messages and the bot will delete the partner's message as well
ADMIN_ID = 1108826094

# Preferences for the bot

class ProfileSetup(StatesGroup):
    gender = State()
    age = State()
    pref_gender = State()

#START_Phase command to add the user to the database and send a welcome message
@dp.message(CommandStart())
async def start(message: types.Message):
    await add_or_update_user(message.from_user.id)
    
    # 1. Build the persistent menu keyboard
    menu = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Match"), KeyboardButton(text="🛑 Stop")],
            [KeyboardButton(text="⭐ Subscribe"),KeyboardButton(text="🗑️ Unsend")]
        ],
        resize_keyboard=True, # Makes the buttons smaller and cleaner
        is_persistent=True    # Keeps the menu open at the bottom of the screen
    )
    
    # 2. Attach the menu to the welcome message
    await message.answer(
        "Welcome to the Matching Bot!\n"
        "Use the menu below to navigate.",
        reply_markup=menu
    )
    #When user starts the bot, we add them to the database and send a welcome

#Matching phase, we check if the user is eligible to match and then either match them or put them in the waitlist

#Start the Match Wizard ---
@dp.message(Command("match"))
@dp.message(F.text == "🔍 Match")
async def match_user(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await add_or_update_user(user_id)

    can_match = await can_user_match(user_id)
    if not can_match:
        await message.answer(
            "⏳ You've used all 3 of your free matches for today!\n"
            "Use /subscribe to unlock unlimited matches, or come back tomorrow."
        )
        return

    if user_id in active_matches:
        await message.answer("You are already chatting with someone! Use /stop to leave your current chat.")
        return
        
    if user_id in waitlist:
        await message.answer("You are already in the waitlist. Please wait for a partner...")
        return

    # Ask the first question
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Male", callback_data="user_gender_M")],
        [InlineKeyboardButton(text="🙋‍♀️ Female", callback_data="user_gender_F")]
    ])
    await message.answer("Let's find you a match!\nWhat is your gender?", reply_markup=keyboard)
    
    # Move to the "gender" state
    await state.set_state(ProfileSetup.gender)

# Catch Gender, Ask for Age ---
@dp.callback_query(ProfileSetup.gender, F.data.startswith("user_gender_"))
async def set_gender(callback: types.CallbackQuery, state: FSMContext):
    selected_gender = callback.data.split("_")[2]  # Extracts "M" or "F"
    
    await state.update_data(gender=selected_gender)
    await callback.answer()
    
    await callback.message.edit_text("How old are you?")
    await state.set_state(ProfileSetup.age)

#Catch Age, Ask for Preference ---
@dp.message(ProfileSetup.age, F.text)
async def set_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (18 <= int(message.text) <= 99):
        await message.answer("Please enter a valid age between 18 and 99.")
        return

    await state.update_data(age=int(message.text))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🙋‍♂️ Men", callback_data="target_gender_M")],
        [InlineKeyboardButton(text="🙋‍♀️ Women", callback_data="target_gender_F")],
        [InlineKeyboardButton(text="🎲 Anyone", callback_data="target_gender_ANY")]
    ])
    await message.answer("Who do you want to connect with?", reply_markup=keyboard)
    await state.set_state(ProfileSetup.pref_gender)

#FINISH: Catch Preference and Run Matchmaker ---
@dp.callback_query(ProfileSetup.pref_gender, F.data.startswith("target_gender_"))
async def set_target_gender(callback: types.CallbackQuery, state: FSMContext):
    target = callback.data.split("_")[2]  # Extracts "M", "F", or "ANY"
    
    # Retrieve the answers they just provided
    data = await state.get_data()
    await state.clear() # Wizard complete, clear memory
    await callback.answer()

    # Package it into a dictionary
    profile = {"gender": data["gender"], "age": data["age"], "pref_gender": target}
    
    await callback.message.edit_text("✅ Searching for a match!!...")
    
    # Run the engine
    await run_matchmaker(callback.from_user.id, profile, callback.message)

# --- THE MATCHMAKER ENGINE ---
async def run_matchmaker(user_id: int, profile: dict, context_msg: types.Message):
    matched_partner_id = None

    # Search through the dictionary of waiting users
    for pid, p_pref in list(waitlist.items()):
        # Does the NEW user match what the WAITING partner wants?
        partner_accepts_user = (p_pref["pref_gender"] in ("ANY", profile["gender"]))
        
        # Does the WAITING partner match what the NEW user wants?
        user_accepts_partner = (profile["pref_gender"] in ("ANY", p_pref["gender"]))

        # If it's a mutual match, select them!
        if partner_accepts_user and user_accepts_partner:
            matched_partner_id = pid
            partner_profile = p_pref
            break

    if matched_partner_id:
        # Remove partner from waitlist
        del waitlist[matched_partner_id]

        # Link both users
        active_matches[user_id] = matched_partner_id
        active_matches[matched_partner_id] = user_id

        await increment_match_count(user_id)
        await increment_match_count(matched_partner_id)

        # Build friendly gender strings for the notification
        u_gender = "Male" if profile["gender"] == "M" else "Female"
        p_gender = "Male" if partner_profile["gender"] == "M" else "Female"

        await bot.send_message(
            user_id,
            f"🔗 Matched! \nSay hi!"
        )
        await bot.send_message(
            matched_partner_id,
            f"🔗 Matched! \nSay hi!"
        )
    else:
        # No compatible partner found yet. Add them to the waitlist dictionary.
        waitlist[user_id] = profile
#STOP_Phase command to leave the current match or waitlist

@dp.message(Command("stop"))
@dp.message(F.text == "🛑 Stop")
#Stop the current match and remove them from the active_matches dictionary
async def stop_chat(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in active_matches:
        partner_id = active_matches.pop(user_id)
        active_matches.pop(partner_id, None) # Remove the cross-link
        message_map.pop(user_id, None)
        message_map.pop(partner_id, None)
        
        await message.answer("You disconnected from the chat. Use /match to find a new partner.")
        await bot.send_message(partner_id, "Your partner left the chat. Use /match to find a new one.")
    elif user_id in waitlist:
        del waitlist[user_id]  # Use 'del' for dictionaries instead of '.remove()'
        await message.answer("You left the waitlist.")
    else:
        await message.answer("You aren't in a chat or on the waitlist right now.")

#Subscription phase, we check if the user is already premium and then upgrade them to premium if they are not

@dp.message(Command("subscribe"))
@dp.message(F.text == "⭐ Subscribe")
async def show_subscription_plans(message: types.Message):
    # Create the 3 plan buttons
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ 1 Week - 119 Stars", callback_data="plan_7")],
        [InlineKeyboardButton(text="🌟 1 Month - 299 Stars", callback_data="plan_30")],
        [InlineKeyboardButton(text="💫 3 Months - 499 Stars", callback_data="plan_90")]
    ])
    
    await message.answer("Choose a Premium plan to unlock unlimited matches:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("plan_"))
async def send_plan_invoice(callback: types.CallbackQuery):
    """Sends the actual invoice when they click a plan button."""
    plan_days = callback.data.split("_")[1] # Extracts "7", "30", or "90"
    
    # Configure the price based on their choice
    if plan_days == "7":
        price = 119
        title = "1 Week Premium"
    elif plan_days == "30":
        price = 299
        title = "1 Month Premium"
    elif plan_days == "90":
        price = 499
        title = "3 Months Premium"
    
    # We put the days in the payload so we remember what they bought after they pay
    payload = f"sub_{plan_days}" 
    
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=title,
        description=f"Unlock unlimited matches and image sharing for {plan_days} days.",
        payload=payload, 
        currency="XTR",
        prices=[LabeledPrice(label="XTR", amount=price)],
        provider_token="",
    )
    # Acknowledge the button click so it stops loading
    await callback.answer()

# Pre-checkout phase, we confirm to Telegram that we are ready to process the payment        


@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery):
    # Confirm to Telegram that we are ready to process the payment
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    # Updates the database using our clean helper function
    user_id = message.from_user.id
    
    # Extract the days from the invoice payload (e.g., "sub_7")
    payload = message.successful_payment.invoice_payload
    days = int(payload.split("_")[1])
    
    # Pass BOTH the user ID and the number of days to the database function
    await add_premium_days(user_id, days)
        
    await message.answer(f"🎉 Payment successful! You have been granted {days} days of Premium. Enjoy unlimited matches!")
# --- VIP ADMIN COMMANDS ---

@dp.message(Command("my_id"))
async def show_user_id(message: types.Message):
    """Allows anyone to easily copy their ID to send to you."""
    await message.answer(f"Your Telegram ID is: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message(Command("grant"))
async def grant_vip_command(message: types.Message, command: CommandObject):
    """Secret admin command to grant VIP access."""
    if message.from_user.id != ADMIN_ID:
        return # Silently ignore non-admins

    if not command.args:
        await message.answer("⚠️ Please provide a user ID. Example: `/grant 123456789`", parse_mode="Markdown")
        return
        
    try:
        target_user_id = int(command.args.strip())
        await make_user_vip(target_user_id)
        await message.answer(f"✅ User {target_user_id} now has lifetime VIP access!")
    except ValueError:
        await message.answer("❌ That doesn't look like a valid ID.")


#Delete functionality phase, to provide delete support for users.
@dp.message(Command("del"))
@dp.message(F.text == "🗑️ Unsend")
async def unsend_message(message: types.Message):
    user_id = message.from_user.id
    
    # Check if they are in an active chat
    if user_id not in active_matches:
        return
        
    # Check if they actually replied to a message
    if not message.reply_to_message:
        await message.answer("To unsend, you must **reply** to the message you want to delete and type /del")
        return
        
    partner_id = active_matches[user_id]
    original_msg_id = message.reply_to_message.message_id
    
    # Check if we have a record of this message being sent to the partner
    if user_id in message_map and original_msg_id in message_map[user_id]:
        partner_msg_id = message_map[user_id][original_msg_id]
        
        try:
            # 1. Delete it from the partner's chat
            await bot.delete_message(chat_id=partner_id, message_id=partner_msg_id)
            
            # 2. Delete the user's original message
            await bot.delete_message(chat_id=user_id, message_id=original_msg_id)
            
            # 3. Delete the "/del" command message to keep the chat clean
            await bot.delete_message(chat_id=user_id, message_id=message.message_id)
            
            # Remove from memory
            del message_map[user_id][original_msg_id]
            
        except Exception as e:
            await message.answer("Could not delete message. It might be too old.")
    else:
        await message.answer("Could not find that message. (You can only delete messages sent after this feature was added).")

#Photo&text forwarding phase, we check if the user is in an active match and then forward the message to their partner
@dp.message(F.content_type.in_({"text", "photo","document", "sticker", "animation"}))
async def relay_message(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in active_matches:
        partner_id = active_matches[user_id]
        
        # 1. Forward the message and capture the result
        copied_msg = await bot.copy_message(
            chat_id=partner_id, 
            from_chat_id=message.chat.id, 
            message_id=message.message_id
        )
        
        # 2. Save the mapping so we know which message is which
        if user_id not in message_map:
            message_map[user_id] = {}
            
        message_map[user_id][message.message_id] = copied_msg.message_id
    else:
        await message.answer("You are not currently in a chat. Use 🔍 Match to find a partner.")

#Main function to start the bot and initialize the database
async def main():
    await init_db()
    print("Database initialized.")  # Initialize the database
    await dp.start_polling(bot)
if __name__ == "__main__":
    asyncio.run(main())    
#End of the bot.py file, we can always add more features like preferences, reporting, etc.    