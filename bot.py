import asyncio
import os
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from database import init_db, add_or_update_user, can_user_match, increment_match_count, add_premium_days, make_user_vip

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
waitlist = {}
active_matches = {}
message_map = {} 
ADMIN_ID = 1108826094

class ProfileSetup(StatesGroup):
    gender = State()
    age = State()
    pref_gender = State()

@dp.message(CommandStart())
async def start(message: types.Message):
    await add_or_update_user(message.from_user.id)
    
    menu = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔗 Connect"), KeyboardButton(text="⛓️‍💥 Disconnect")],
            [KeyboardButton(text="✯ Premium"), KeyboardButton(text="↩️ Delete")]
        ],
        resize_keyboard=True, 
        is_persistent=True    
    )
    
    await message.answer(
        "Welcome to the Matching Bot!\n"
        "Use the menu below to navigate.",
        reply_markup=menu
    )

@dp.message(Command("match"))
@dp.message(F.text == "🔗 Connect")
async def match_user(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await add_or_update_user(user_id)

    can_match = await can_user_match(user_id)
    if not can_match:
        await message.answer(
            "⏳ You've used your free match!\n"
            "Use /subscribe to unlock unlimited matches, or wait for future updates."
        )
        return

    if user_id in active_matches:
        await message.answer("You are already chatting with someone! Use /stop to leave your current chat.")
        return
        
    if user_id in waitlist:
        await message.answer("You are already in the waitlist. Please wait for a partner...")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Male", callback_data="user_gender_M")],
        [InlineKeyboardButton(text="👩 Female", callback_data="user_gender_F")]
    ])
    await message.answer("Let's find you a match!\nWhat is your gender?", reply_markup=keyboard)
    
    await state.set_state(ProfileSetup.gender)

@dp.callback_query(ProfileSetup.gender, F.data.startswith("user_gender_"))
async def set_gender(callback: types.CallbackQuery, state: FSMContext):
    selected_gender = callback.data.split("_")[2]  
    
    await state.update_data(gender=selected_gender)
    await callback.answer()
    
    await callback.message.edit_text("How old are you?")
    await state.set_state(ProfileSetup.age)

@dp.message(ProfileSetup.age, F.text)
async def set_age(message: types.Message, state: FSMContext):
    if not message.text.isdigit() or not (18 <= int(message.text) <= 99):
        await message.answer("Please enter a valid age between 18 and 99.")
        return

    await state.update_data(age=int(message.text))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨 Men", callback_data="target_gender_M")],
        [InlineKeyboardButton(text="👩 Women", callback_data="target_gender_F")],
        [InlineKeyboardButton(text="🌐 Anyone", callback_data="target_gender_ANY")]
    ])
    await message.answer("Who do you want to connect with?", reply_markup=keyboard)
    await state.set_state(ProfileSetup.pref_gender)

@dp.callback_query(ProfileSetup.pref_gender, F.data.startswith("target_gender_"))
async def set_target_gender(callback: types.CallbackQuery, state: FSMContext):
    target = callback.data.split("_")[2]  
    
    data = await state.get_data()
    await state.clear() 
    await callback.answer()

    profile = {"gender": data["gender"], "age": data["age"], "pref_gender": target}
    
    await callback.message.edit_text("🔎︎ Searching for a match!...\n Send text or messages.\n Type /stop to stop.")
    
    await run_matchmaker(callback.from_user.id, profile, callback.message)

async def run_matchmaker(user_id: int, profile: dict, context_msg: types.Message):
    matched_partner_id = None

    for pid, p_pref in list(waitlist.items()):
        partner_accepts_user = (p_pref["pref_gender"] in ("ANY", profile["gender"]))
        user_accepts_partner = (profile["pref_gender"] in ("ANY", p_pref["gender"]))

        if partner_accepts_user and user_accepts_partner:
            matched_partner_id = pid
            partner_profile = p_pref
            break

    if matched_partner_id:
        del waitlist[matched_partner_id]

        active_matches[user_id] = matched_partner_id
        active_matches[matched_partner_id] = user_id

        await increment_match_count(user_id)
        await increment_match_count(matched_partner_id)

        await bot.send_message(
            user_id,
            f"🔗 Matched!\nSay hi!\nType /stop to disconnect."
        )
        await bot.send_message(
            matched_partner_id,
            f"🔗 Matched!\nSay hi!\nType /stop to disconnect."
        )
    else:
        waitlist[user_id] = profile

@dp.message(Command("stop"))
@dp.message(F.text == "⛓️‍💥 Disconnect")
async def stop_chat(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in active_matches:
        partner_id = active_matches.pop(user_id)
        active_matches.pop(partner_id, None) 
        message_map.pop(user_id, None)
        message_map.pop(partner_id, None)
        
        await message.answer("You disconnected from the chat. Use 🔗 Connect or type /match to find a new partner.")
        await bot.send_message(partner_id, "Your partner left the chat. Use 🔗 Connect or type /match to find a new one.")
    elif user_id in waitlist:
        del waitlist[user_id]  
        await message.answer("You left the waitlist.")
    else:
        await message.answer("You aren't in a chat or on the waitlist right now.")


@dp.message(Command("subscribe"))
@dp.message(F.text == "✯ Premium")
async def show_subscription_plans(message: types.Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✩ 1 Week - 119 Stars", callback_data="plan_7")],
        [InlineKeyboardButton(text="✭ 1 Month - 299 Stars", callback_data="plan_30")],
        [InlineKeyboardButton(text="✮ 3 Months - 499 Stars", callback_data="plan_90")]
    ])
    
    await message.answer("Choose a Premium plan to unlock unlimited matches:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("plan_"))
async def send_plan_invoice(callback: types.CallbackQuery):
    plan_days = callback.data.split("_")[1] 
    
    if plan_days == "7":
        price = 119
        title = "1 Week Premium"
    elif plan_days == "30":
        price = 299
        title = "1 Month Premium"
    elif plan_days == "90":
        price = 499
        title = "3 Months Premium"
    
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
    await callback.answer()

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):
    user_id = message.from_user.id
    
    payload = message.successful_payment.invoice_payload
    days = int(payload.split("_")[1])
    
    await add_premium_days(user_id, days)
        
    await message.answer(f"🎉 Payment successful! You have been granted {days} days of Premium. Enjoy unlimited matches!")

@dp.message(Command("my_id"))
async def show_user_id(message: types.Message):
    await message.answer(f"Your Telegram ID is: `{message.from_user.id}`", parse_mode="Markdown")

@dp.message(Command("grant"))
async def grant_vip_command(message: types.Message, command: CommandObject):
    if message.from_user.id != ADMIN_ID:
        return 

    if not command.args:
        await message.answer("⚠️ Please provide a user ID. Example: `/grant 123456789`", parse_mode="Markdown")
        return
        
    try:
        target_user_id = int(command.args.strip())
        await make_user_vip(target_user_id)
        await message.answer(f"✅ User {target_user_id} now has lifetime VIP access!")
    except ValueError:
        await message.answer("❌ That doesn't look like a valid ID.")

@dp.message(Command("del"))
@dp.message(F.text == "↩️ Delete")
async def unsend_message(message: types.Message):
    user_id = message.from_user.id
    
    if user_id not in active_matches:
        return
        
    if not message.reply_to_message:
        await message.answer("To unsend, you must **reply** to the message you want to delete and press ↩️ Delete")
        return
        
    partner_id = active_matches[user_id]
    original_msg_id = message.reply_to_message.message_id
    
    if user_id in message_map and original_msg_id in message_map[user_id]:
        partner_msg_id = message_map[user_id][original_msg_id]
        
        try:
            await bot.delete_message(chat_id=partner_id, message_id=partner_msg_id)
            await bot.delete_message(chat_id=user_id, message_id=original_msg_id)
            await bot.delete_message(chat_id=user_id, message_id=message.message_id)
            
            del message_map[user_id][original_msg_id]
            
        except Exception as e:
            await message.answer("Could not delete message. It might be too old.")
    else:
        await message.answer("Could not find that message. (You can only delete messages sent after this feature was added).")

@dp.message(F.content_type.in_({"text", "photo","document", "sticker", "animation"}))
async def relay_message(message: types.Message):
    user_id = message.from_user.id
    
    if user_id in active_matches:
        partner_id = active_matches[user_id]
        
        copied_msg = await bot.copy_message(
            chat_id=partner_id, 
            from_chat_id=message.chat.id, 
            message_id=message.message_id
        )
        
        if user_id not in message_map:
            message_map[user_id] = {}
            
        message_map[user_id][message.message_id] = copied_msg.message_id
    else:
        await message.answer("You are not currently in a chat. Use 🔗 Connect to find a partner.")

async def main():
    await init_db()
    print("Database initialized.") 
    await dp.start_polling(bot)
if __name__ == "__main__":
    asyncio.run(main())