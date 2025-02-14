import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.utils import executor
from configs import API_TOKEN, ADMIN_CHAT_ID, DB_PATH, COFFEE_LIST, PAYMENT_NUMBER
import logging


# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# Helper functions
def db_connect(func):
    """Decorator to handle database connection and closing."""
    def with_connection(*args, **kwargs):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            result = func(cursor, *args, **kwargs)
            conn.commit()
        finally:
            conn.close()
        return result
    return with_connection

@db_connect
def save_order(cursor, user_id, fio, drink, sugar):
    cursor.execute('''
        INSERT INTO orders (user_id, fio, drink, sugar, order_count)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, fio, drink, sugar, 1))

@db_connect
def update_order_count(cursor, user_id):
    cursor.execute('''
        UPDATE orders
        SET order_count = order_count + 1
        WHERE user_id = ?
    ''', (user_id,))

@db_connect
def get_user_info(cursor, user_id):
    cursor.execute('SELECT fio, order_count FROM orders WHERE user_id = ?', (user_id,))
    return cursor.fetchone() or (None, 0)

@db_connect
def user_exists(cursor, user_id):
    cursor.execute('SELECT COUNT(*) FROM orders WHERE user_id = ?', (user_id,))
    return cursor.fetchone()[0] > 0

def get_drink_price(drink_name):
    prices = {
        'Эспрессо': 30,
        'Двойной эспрессо': 40,
        'Американо': 35,
        'Латте': 50,
        'Двойной латте': 70,
        'Капучино': 60,
        'Двойной капучино': 80,
        'Флэт Уайт': 70,
    }
    return prices.get(drink_name, 0)

async def send_payment_confirmation(message, user_id, fio, drink, sugar_amount, drink_price):
    confirmation_keyboard = types.InlineKeyboardMarkup().add(
        types.InlineKeyboardButton("Подтвердить оплату", callback_data=f"confirm_payment_{user_id}")
    )
    await bot.send_message(ADMIN_CHAT_ID, f"Новый заказ от {fio}:\n"
                                           f"Напиток: {drink}\n"
                                           f"Сахар: {sugar_amount}\n"
                                           f"Пользователь ID: {user_id}\n"
                                           f"Цена: {drink_price}₽\n"
                                           f"Подтвердите оплату:", reply_markup=confirmation_keyboard)

# Define states
class Form(StatesGroup):
    fio = State()
    coffee_choice = State()
    sugar_choice = State()

# Хранение последнего сообщения для каждого пользователя
user_last_message = {}

# Хранение сообщения "Оплата подтверждена"
payment_confirmed_message = {}

# Хранение сообщения с инструкцией по оплате
payment_instruction_message = {}

# Function to delete and replace previous message (кроме сообщения с заказом)
async def delete_previous_message(user_id, current_message, keep_order_message=False):
    if user_id in user_last_message:
        try:
            if keep_order_message and user_last_message[user_id]['message_type'] == 'order':
                pass
            else:
                await bot.delete_message(user_id, user_last_message[user_id]['message_id'])
        except Exception as e:
            logging.warning(f"Unable to delete message: {e}")
    user_last_message[user_id] = {'message_id': current_message.message_id, 'message_type': 'general'}

# Удаление сообщения о подтверждении оплаты при новом заказе
async def delete_payment_confirmed_message(user_id):
    if user_id in payment_confirmed_message:
        try:
            await bot.delete_message(user_id, payment_confirmed_message[user_id])
            del payment_confirmed_message[user_id]
        except Exception as e:
            logging.warning(f"Unable to delete payment confirmation message: {e}")

# Удаление сообщения с инструкцией по оплате
async def delete_payment_instruction_message(user_id):
    if user_id in payment_instruction_message:
        try:
            await bot.delete_message(user_id, payment_instruction_message[user_id])
            del payment_instruction_message[user_id]
        except Exception as e:
            logging.warning(f"Unable to delete payment instruction message: {e}")

# Start command handler
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await delete_payment_confirmed_message(message.from_user.id)
    keyboard = types.InlineKeyboardMarkup(row_width=1)
    
    for coffee, price in COFFEE_LIST.items():
        keyboard.insert(types.InlineKeyboardButton(text=f"{coffee} - {price}₽", callback_data=coffee))

    sent_message = await message.answer("Выберете напиток:", reply_markup=keyboard)
    await delete_previous_message(message.from_user.id, sent_message)
    await Form.coffee_choice.set()

# Coffee choice handler
@dp.callback_query_handler(lambda c: True, state=Form.coffee_choice)
async def process_coffee_choice(callback_query: types.CallbackQuery, state: FSMContext):
    coffee_name = callback_query.data
    await callback_query.answer()
    await state.update_data(drink=coffee_name)

    # Создание inline клавиатуры для выбора сахара
    sugar_keyboard = types.InlineKeyboardMarkup(row_width=4)
    for i in range(4):
        sugar_keyboard.insert(types.InlineKeyboardButton(text=str(i), callback_data=f"sugar_{i}"))

    await callback_query.message.edit_text(f"Вы выбрали {coffee_name}.")
    sent_message = await callback_query.message.answer("Выберете сколько ложек сахара вам положить:", reply_markup=sugar_keyboard)
    await delete_previous_message(callback_query.from_user.id, sent_message)
    await Form.sugar_choice.set()

# Sugar choice handler
@dp.callback_query_handler(lambda c: c.data.startswith("sugar_"), state=Form.sugar_choice)
async def process_sugar_choice(callback_query: types.CallbackQuery, state: FSMContext):
    sugar_amount = int(callback_query.data.split("_")[1])
    user_data = await state.get_data()
    drink = user_data.get('drink')

    logging.info(f"User {callback_query.from_user.id} selected {sugar_amount} sugar.")

    # Удаление сообщения с выбором сахара после выбора
    await bot.delete_message(callback_query.from_user.id, callback_query.message.message_id)

    if not user_exists(callback_query.from_user.id):
        sent_message = await callback_query.message.answer("Пожалуйста, введите своё имя и первую букву фамилии для проверки оплаты.")
        await delete_previous_message(callback_query.from_user.id, sent_message)
        await state.update_data(sugar=sugar_amount)
        await Form.fio.set()
    else:
        fio, order_count = get_user_info(callback_query.from_user.id)
        update_order_count(callback_query.from_user.id)
        drink_price = get_drink_price(drink)
        save_order(callback_query.from_user.id, fio, drink, sugar_amount)

        # Вывод информации о заказе и количестве сахара
        sent_message = await callback_query.message.answer(f"Ваш заказ: {drink}, ложек сахара: {sugar_amount}.")
        user_last_message[callback_query.from_user.id] = {'message_id': sent_message.message_id, 'message_type': 'order'}

        await send_payment_confirmation(callback_query.message, callback_query.from_user.id, fio, drink, sugar_amount, drink_price)
        sent_message = await callback_query.message.answer(f"Пожалуйста, переведите {drink_price}₽ по СБП на т-банк: +79125780217.")
        
        # Сохраняем ID сообщения с инструкцией по оплате
        payment_instruction_message[callback_query.from_user.id] = sent_message.message_id
        await delete_previous_message(callback_query.from_user.id, sent_message, keep_order_message=True)
        await state.finish()

# FIO handler
@dp.message_handler(state=Form.fio)
async def process_fio(message: types.Message, state: FSMContext):
    fio = message.text
    user_data = await state.get_data()
    drink = user_data.get('drink')
    sugar_amount = user_data.get('sugar')

    save_order(message.from_user.id, fio, drink, sugar_amount)
    drink_price = get_drink_price(drink)

    # Вывод информации о заказе и количестве сахара
    sent_message = await message.answer(f"Ваш заказ: {drink}, сахар: {sugar_amount} ложек.")
    user_last_message[message.from_user.id] = {'message_id': sent_message.message_id, 'message_type': 'order'}

    await send_payment_confirmation(message, message.from_user.id, fio, drink, sugar_amount, drink_price)
    sent_message = await message.answer(f"Пожалуйста, переведите {drink_price}₽ по СБП на т-банк: {PAYMENT_NUMBER}.")
    
    # Сохраняем ID сообщения с инструкцией по оплате
    payment_instruction_message[message.from_user.id] = sent_message.message_id
    await delete_previous_message(message.from_user.id, sent_message, keep_order_message=True)
    await state.finish()

# Payment confirmation handler
@dp.callback_query_handler(lambda c: c.data.startswith("confirm_payment_"))
async def confirm_payment(callback_query: types.CallbackQuery):
    user_id = int(callback_query.data.split("_")[2])
    await callback_query.answer("Оплата подтверждена!")
    
    # Удаляем сообщение с инструкцией по оплате
    await delete_payment_instruction_message(user_id)
    
    confirmed_message = await bot.send_message(user_id, "Оплата подтверждена, ваш напиток будет готов через пару минут. Подходите в квартиру 60, 9 этаж (комната слева)")
    payment_confirmed_message[user_id] = confirmed_message.message_id

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
