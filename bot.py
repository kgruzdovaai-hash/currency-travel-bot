import telebot
from telebot import types
import sqlite3
import os
from dotenv import load_dotenv
import current_api as api_client
import database
import visualization

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# --- Database Helpers ---

def get_db_connection():
    """
    Создает соединение с базой данных SQLite.
    Возвращает объект соединения с установленным row_factory для доступа к полям по имени.
    """
    conn = sqlite3.connect('travel_bot.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_user_active_trip(user_id):
    """
    Получает информацию об активном путешествии пользователя.
    
    Args:
        user_id: ID пользователя в Telegram
    
    Returns:
        Словарь с информацией о путешествии и его валютах или None, если нет активного путешествия
    """
    conn = get_db_connection()
    user = conn.execute('SELECT active_trip_id FROM users WHERE user_id = ?', (user_id,)).fetchone()
    if user and user['active_trip_id']:
        trip = conn.execute('SELECT * FROM trips WHERE trip_id = ?', (user['active_trip_id'],)).fetchone()
        # Get all currencies for this trip
        currencies = conn.execute('SELECT * FROM trip_currencies WHERE trip_id = ?', (user['active_trip_id'],)).fetchall()
        trip_dict = dict(trip)
        trip_dict['currencies'] = currencies
        conn.close()
        return trip_dict
    conn.close()
    return None

def add_currency_to_trip(trip_id, currency_code, balance, exchange_rate_to_home):
    """
    Добавляет новую валюту к существующему путешествию.
    
    Args:
        trip_id: ID путешествия
        currency_code: Код валюты (например: USD, EUR)
        balance: Баланс в этой валюте
        exchange_rate_to_home: Курс обмена относительно домашней валюты
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trip_currencies (trip_id, currency_code, balance, exchange_rate_to_home)
        VALUES (?, ?, ?, ?)
    ''', (trip_id, currency_code, balance, exchange_rate_to_home))
    conn.commit()
    conn.close()

def set_active_trip(user_id, trip_id):
    """
    Устанавливает активное путешествие для пользователя.
    
    Args:
        user_id: ID пользователя в Telegram
        trip_id: ID путешествия, которое нужно сделать активным
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, active_trip_id) VALUES (?, ?)', (user_id, trip_id))
    conn.commit()
    conn.close()

# --- Keyboards ---

def main_menu_keyboard():
    """
    Создает главное меню бота с кнопками для основных действий.
    
    Returns:
        Объект ReplyKeyboardMarkup с основными кнопками меню
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🆕 Создать новое путешествие", "🌍 Мои путешествия","🗑 Удалить путешествие")
    markup.row("📊 Настройки бюджета", "💰 Баланс")
    markup.row("📈 Графики расходов", "📜 История расходов")
    markup.row("📈 Изменить курс", "✏️ Редактировать расходы")
    # markup.row("📈 Изменить курс")
    return markup

def budget_settings_keyboard():
    """
    Создает клавиатуру с кнопками для настройки бюджета.
    
    Returns:
        Объект ReplyKeyboardMarkup с кнопками настройки бюджета
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📊 Установить лимит бюджета", "🔔 Установить порог уведомления")
    markup.row("💰 Просмотреть бюджет", "📋 План по категориям")
    markup.row("💱 Валюты путешествия")
    markup.row("📈 Установить бюджеты по категориям", "🔙 Назад в меню")
    return markup

def inline_confirm_expense(amount, trip_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Да", callback_data=f"exp_yes_{amount}_{trip_id}"),
        types.InlineKeyboardButton("❌ Нет", callback_data="exp_no")
    )
    return markup

def inline_confirm_expense_multi(amount, currency_code, trip_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Да", callback_data=f"exp_multi_yes_{amount}_{currency_code}_{trip_id}"),
        types.InlineKeyboardButton("❌ Нет", callback_data="exp_no")
    )
    return markup

# --- Handlers ---

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    """
    Обработчик команд /start и /menu.
    Отправляет приветственное сообщение и главное меню.
    Если у пользователя нет активных путешествий, предлагает создать первое.
    """
    # Проверяем, есть ли у пользователя активное путешествие
    trip = get_user_active_trip(message.from_user.id)
    
    if not trip:
        welcome_text = "Привет! Я твой кошелек для путешествий. \nЯ помогу тебе следить за расходами в разных валютах и по категориям.\n\nУ вас пока нет активных путешествий. Давайте создадим первое!"
    else:
        welcome_text = "Привет! Я твой кошелек для путешествий. \nЯ помогу тебе следить за расходами в разных валютах и по категориям."
    
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=main_menu_keyboard()
    )

# --- Create Trip Flow ---

user_data = {} # Temporary storage for trip creation state

@bot.message_handler(func=lambda message: message.text == "🆕 Создать новое путешествие" or message.text == "/newtrip")
def start_new_trip(message):
    user_id = message.from_user.id
    user_data[user_id] = {'step': 'home_country'}
    bot.send_message(message.chat.id, "Откуда вы выезжаете? (Введите название страны, например: Россия, США, Германия)")

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'home_country')
def process_home_country(message):
    user_id = message.from_user.id
    country = message.text
    user_data[user_id]['home_place_name'] = country
    currency = api_client.guess_currency(country)
    
    if not currency:
        bot.send_message(message.chat.id, f"Не удалось автоматически определить валюту для '{country}'. Пожалуйста, введите код валюты вручную (3 буквы, например: RUB, USD, EUR):")
        user_data[user_id]['step'] = 'home_currency_manual'
    else:
        user_data[user_id]['home_currency'] = currency
        user_data[user_id]['step'] = 'target_country'
        bot.send_message(message.chat.id, f"💰 Валюта: {currency}. \n\nКуда вы направляетесь?")

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'home_currency_manual')
def process_home_currency_manual(message):
    user_id = message.from_user.id
    currency = message.text.upper()
    # Simple validation
    if len(currency) != 3:
        bot.send_message(message.chat.id, "Код валюты должен состоять из 3 букв. Попробуйте еще раз:")
        return
    user_data[user_id]['home_currency'] = currency
    user_data[user_id]['step'] = 'target_country'
    bot.send_message(message.chat.id, "Принято. Куда вы направляетесь?")

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'target_country')
def process_target_country(message):
    user_id = message.from_user.id
    country = message.text
    user_data[user_id]['target_place_name'] = country
    currency = api_client.guess_currency(country)
    
    if not currency:
        bot.send_message(message.chat.id, f"Не удалось автоматически определить валюту для '{country}'. Введите код валюты вручную (например: CNY, TRY, THB):")
        user_data[user_id]['step'] = 'target_currency_manual'
    else:
        user_data[user_id]['target_currency'] = currency
        user_data[user_id]['target_country_name'] = country
        fetch_rate_and_ask(message)

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'target_currency_manual')
def process_target_currency_manual(message):
    user_id = message.from_user.id
    currency = message.text.upper()
    if len(currency) != 3:
        bot.send_message(message.chat.id, "Код валюты должен состоять из 3 букв. Попробуйте еще раз:")
        return
    user_data[user_id]['target_currency'] = currency
    user_data[user_id]['target_country_name'] = currency # Use code as name if unknown
    fetch_rate_and_ask(message)

def fetch_rate_and_ask(message):
    user_id = message.from_user.id
    home_cur = user_data[user_id]['home_currency']
    target_cur = user_data[user_id]['target_currency']

    # Если валюта выезда и валюта назначения совпадают — курс = 1, и
    # название путешествия берём из введённого "города/места назначения".
    if home_cur == target_cur:
        user_data[user_id]['rate'] = 1.0
        # Приоритет: введённое место назначения, иначе fallback на target_country_name
        trip_name = user_data[user_id].get('target_place_name') or user_data[user_id].get('target_country_name') or target_cur
        user_data[user_id]['target_country_name'] = trip_name
        user_data[user_id]['step'] = 'initial_balance'
        bot.send_message(
            message.chat.id,
            f"Валюта выезда и назначения совпадает ({home_cur}). Курс обмена не нужен.\n"
            f"Какую сумму в {home_cur} вы берете с собой?"
        )
        return
    
    rate = api_client.get_exchange_rate(home_cur, target_cur)
    
    if rate is None:
        bot.send_message(message.chat.id, f"Не удалось получить курс для пары {home_cur} -> {target_cur}. Пожалуйста, введите курс вручную (сколько {target_cur} дают за 1 {home_cur}):")
        user_data[user_id]['step'] = 'manual_rate'
    else:
        user_data[user_id]['rate'] = rate
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("Да, подходит", callback_data="rate_ok"),
            types.InlineKeyboardButton("Нет, введу сам", callback_data="rate_manual")
        )
        bot.send_message(message.chat.id, f"Текущий курс: 1 {home_cur} = {rate} {target_cur}. Подходит?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "rate_ok")
def rate_ok_callback(call):
    user_id = call.from_user.id
    user_data[user_id]['step'] = 'initial_balance'
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Отлично. Курс 1 {user_data[user_id]['home_currency']} = {user_data[user_id]['rate']} {user_data[user_id]['target_currency']} подтвержден.")
    bot.send_message(call.message.chat.id, f"Какую сумму в {user_data[user_id]['home_currency']} вы берете с собой?")

@bot.callback_query_handler(func=lambda call: call.data == "rate_manual")
def rate_manual_callback(call):
    user_id = call.from_user.id
    user_data[user_id]['step'] = 'manual_rate'
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Хорошо, введите курс обмена вручную (сколько единиц валюты назначения дают за 1 единицу домашней валюты):")

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'manual_rate')
def process_manual_rate(message):
    try:
        rate = float(message.text.replace(',', '.'))
        user_id = message.from_user.id
        user_data[user_id]['rate'] = rate
        user_data[user_id]['step'] = 'initial_balance'
        bot.send_message(message.chat.id, f"Курс установлен: 1 {user_data[user_id]['home_currency']} = {rate} {user_data[user_id]['target_currency']}. Какую сумму в {user_data[user_id]['home_currency']} вы берете с собой?")
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'initial_balance')
def process_initial_balance(message):
    try:
        home_amount = float(message.text.replace(',', '.'))
        user_id = message.from_user.id
        user_data[user_id]['home_initial_amount'] = home_amount # Store for later
        
        # Рассчитываем баланс в валюте страны пребывания
        target_currency = user_data[user_id]['target_currency']
        exchange_rate = user_data[user_id]['rate']
        target_amount = home_amount * exchange_rate
        
        user_data[user_id]['step'] = 'budget_limit'
        bot.send_message(
            message.chat.id, 
            f"💰 Начальный баланс:\n🏠 <b>{home_amount} {user_data[user_id]['home_currency']}</b>\n"
            f"🌍 <b>{target_amount:.2f} {target_currency}</b>\n\n"
            f"Какой лимит бюджета (в валюте <b>{target_currency}</b>) вы устанавливаете для этого путешествия? Введите 0, если лимит не нужен.",
            parse_mode="HTML"
        )
        
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'budget_limit')
def process_budget_limit(message):
    try:
        budget_limit = float(message.text.replace(',', '.'))
        user_id = message.from_user.id
        user_data[user_id]['budget_limit'] = budget_limit
        
        # Устанавливаем порог уведомления (80% от лимита бюджета)
        if budget_limit > 0:
            notification_threshold = budget_limit * 0.8
            user_data[user_id]['notification_threshold'] = notification_threshold
            bot.send_message(message.chat.id, f"Лимит бюджета установлен: {budget_limit} {user_data[user_id]['target_currency']}\nПорог уведомления: {notification_threshold} {user_data[user_id]['target_currency']} (80% от лимита)\n\nХотите установить бюджеты по категориям? Нажмите 'Да' или 'Нет'.")
            # Запрашиваем выбор
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("Да", callback_data="set_category_budgets_yes"),
                types.InlineKeyboardButton("Нет", callback_data="set_category_budgets_no")
            )
            bot.send_message(message.chat.id, "Установить бюджеты по категориям?", reply_markup=markup)
        else:
            user_data[user_id]['notification_threshold'] = 0
            bot.send_message(message.chat.id, "Лимит бюджета не установлен.")
            # Продолжаем без установки бюджетов по категориям
            continue_trip_creation(user_id, message.chat.id)
        
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")


def continue_trip_creation(user_id, chat_id):
    """Продолжает создание путешествия после установки бюджетов"""
    # Создаем путешествие в базе данных
    conn = get_db_connection()
    cursor = conn.cursor()
    target_initial_amount = user_data[user_id]['home_initial_amount'] * user_data[user_id]['rate']
    
    cursor.execute('''
        INSERT INTO trips (user_id, name, home_currency, target_currency, exchange_rate, home_balance, target_balance, budget_limit, notification_threshold)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        user_data[user_id]['target_country_name'],
        user_data[user_id]['home_currency'],
        user_data[user_id]['target_currency'],
        user_data[user_id]['rate'],
        user_data[user_id]['home_initial_amount'],
        target_initial_amount,
        user_data[user_id]['budget_limit'],
        user_data[user_id]['notification_threshold']
    ))
    
    trip_id = cursor.lastrowid
    conn.commit()
    
    # Добавляем основную валюту путешествия
    add_currency_to_trip(trip_id, user_data[user_id]['target_currency'], target_initial_amount, user_data[user_id]['rate'])
    
    conn.close()
    
    # Устанавливаем это путешествие как активное
    set_active_trip(user_id, trip_id)
    
    bot.send_message(chat_id, f"🎉 Путешествие '{user_data[user_id]['target_country_name']}' создано!\n"
                     f"Начальный баланс: {target_initial_amount:.2f} {user_data[user_id]['target_currency']} = {user_data[user_id]['home_initial_amount']:.2f} {user_data[user_id]['home_currency']}\n"
                     f"Курс: 1 {user_data[user_id]['home_currency']} = {user_data[user_id]['rate']} {user_data[user_id]['target_currency']}")
    
    # Очищаем данные пользователя
    if user_id in user_data:
        del user_data[user_id]


@bot.callback_query_handler(func=lambda call: call.data == "set_category_budgets_yes")
def handle_category_budgets_yes(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Запрашиваем установку бюджетов по категориям
    user_data[user_id] = {'step': 'select_category_for_budget', 'trip_id': None}
    
    # Отправляем сообщение с выбором категории
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.message_id,
        text="Выберите категорию для установки бюджета:",
        reply_markup=select_category_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data == "set_category_budgets_no")
def handle_category_budgets_no(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Просто продолжаем создание путешествия
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.message_id,
        text="Хорошо, бюджеты по категориям не установлены."
    )
    continue_trip_creation(user_id, chat_id)

# --- My Trips & Switch ---

@bot.message_handler(func=lambda message: message.text == "🌍 Мои путешествия" or message.text == "/switch")
def list_trips(message):
    conn = get_db_connection()
    trips = conn.execute('SELECT * FROM trips WHERE user_id = ?', (message.from_user.id,)).fetchall()
    conn.close()
    
    if not trips:
        bot.send_message(message.chat.id, "У вас пока нет созданных путешествий. Нажмите '🆕 Создать новое путешествие'.")
        return
    
    markup = types.InlineKeyboardMarkup()
    for trip in trips:
        markup.add(types.InlineKeyboardButton(f"{trip['name']} ({trip['target_currency']})", callback_data=f"switch_{trip['trip_id']}"))
    
    bot.send_message(message.chat.id, "Выберите активное путешествие:", reply_markup=markup)


@bot.message_handler(func=lambda message: message.text == "🗑 Удалить путешествие")
def delete_trip_prompt(message):
    conn = get_db_connection()
    trips = conn.execute('SELECT * FROM trips WHERE user_id = ?', (message.from_user.id,)).fetchall()
    conn.close()
    
    if not trips:
        bot.send_message(message.chat.id, "У вас пока нет созданных путешествий.")
        return
    
    markup = types.InlineKeyboardMarkup()
    for trip in trips:
        markup.add(types.InlineKeyboardButton(f"{trip['name']} ({trip['target_currency']})", callback_data=f"delete_trip_{trip['trip_id']}"))
    
    bot.send_message(message.chat.id, "Выберите путешествие для удаления:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_trip_"))
def confirm_delete_trip_callback(call):
    trip_id = int(call.data.split('_')[2])
    
    # Показываем подтверждение
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("❌ Да, удалить", callback_data=f"confirm_delete_{trip_id}"),
        types.InlineKeyboardButton("✅ Нет, отмена", callback_data="cancel_delete")
    )
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="⚠️ Вы уверены, что хотите удалить это путешествие? Все данные будут потеряны!",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_"))
def delete_trip_callback(call):
    trip_id = int(call.data.split('_')[2])
    
    # Получаем информацию о путешествии перед удалением
    conn = get_db_connection()
    trip = conn.execute('SELECT name FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
    
    if trip:
        # Удаляем путешествие и все связанные данные
        database.delete_trip(trip_id)
        
        # Проверяем, не является ли это активным путешествием у пользователя
        user_active_trip = conn.execute('SELECT active_trip_id FROM users WHERE user_id = ?', (call.from_user.id,)).fetchone()
        if user_active_trip and user_active_trip['active_trip_id'] == trip_id:
            # Если это было активное путешествие, сбрасываем его
            conn.execute('UPDATE users SET active_trip_id = NULL WHERE user_id = ?', (call.from_user.id,))
        
        conn.commit()
        conn.close()
        
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Путешествие '{trip['name']}' удалено."
        )
    else:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Путешествие не найдено."
        )


@bot.callback_query_handler(func=lambda call: call.data == "cancel_delete")
def cancel_delete_callback(call):
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="❌ Удаление отменено."
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("switch_"))
def switch_trip_callback(call):
    trip_id = int(call.data.split('_')[1])
    set_active_trip(call.from_user.id, trip_id)
    
    conn = get_db_connection()
    trip = conn.execute('SELECT name FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
    conn.close()
    
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"Активное путешествие переключено на: {trip['name']}")

# --- Balance ---

@bot.message_handler(func=lambda message: message.text == "💰 Баланс" or message.text == "/balance")
def show_balance(message):
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Show balance for all currencies in the trip
    balance_text = f"🌍 Путешествие: {trip['name']}\n"
    balance_text += f"🏠 Домашняя валюта: {trip['home_currency']}\n"
    balance_text += f"📊 Курсы обмена:\n"
    balance_text += f"  1 {trip['home_currency']} = {trip['exchange_rate']} {trip['target_currency']}\n"
    
    # Show balances for each currency
    balance_text += f"\n💳 Балансы валют:\n"
    for currency in trip['currencies']:
        home_equivalent = currency['balance'] / currency['exchange_rate_to_home']
        balance_text += f"  {currency['currency_code']}: {currency['balance']:.2f} (эквивалент {home_equivalent:.2f} {trip['home_currency']})\n"
    
    # Add budget information if set
    if trip['budget_limit'] > 0:
        spent_result = get_db_connection().execute('SELECT SUM(amount_home) as total_spent FROM expenses WHERE trip_id = ?', (trip['trip_id'],)).fetchone()
        total_spent = spent_result['total_spent'] or 0
        remaining_budget = trip['budget_limit'] - (total_spent * trip['exchange_rate'])
        percentage_spent = min((total_spent * trip['exchange_rate']) / trip['budget_limit'] * 100, 100)
        
        balance_text += f"\n📊 Общий бюджет: {trip['budget_limit']:.2f} {trip['target_currency']}\n"
        balance_text += f"📈 Потрачено: {(total_spent * trip['exchange_rate']):.2f} {trip['target_currency']} ({percentage_spent:.1f}%)\n"
        balance_text += f"📉 Осталось: {remaining_budget:.2f} {trip['target_currency']}\n"
        balance_text += f"🔔 Порог уведомления: {trip['notification_threshold']:.2f} {trip['target_currency']}"
    
    # Add category budget information if any category budgets are set
    cat_budgets = database.get_trip_categories_with_budgets(trip['trip_id'])
    if any(cat['planned_amount'] > 0 for cat in cat_budgets):
        balance_text += f"\n📋 Бюджеты по категориям:\n"
        for cat in cat_budgets:
            if cat['planned_amount'] > 0:
                spent_pct = 0
                if cat['planned_amount'] > 0:
                    spent_pct = min((cat['spent_amount'] / cat['planned_amount']) * 100, 100)
                balance_text += f"  {cat['name']}: {cat['spent_amount']:.2f}/{cat['planned_amount']:.2f} {cat['currency_code']} ({spent_pct:.1f}%)\n"
    
    bot.send_message(message.chat.id, balance_text)

# --- History ---

@bot.message_handler(func=lambda message: message.text == "📜 История расходов" or message.text == "/history")
def show_history(message):
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    conn = get_db_connection()
    expenses = conn.execute('SELECT * FROM expenses WHERE trip_id = ? ORDER BY timestamp DESC LIMIT 10', (trip['trip_id'],)).fetchall()
    conn.close()
    
    if not expenses:
        bot.send_message(message.chat.id, "В этом путешествии еще нет расходов.")
        return
    
    text = f"Последние 10 расходов ({trip['name']}):\n\n"
    for exp in expenses:
        # Получаем имя категории
        category = database.get_all_categories()[exp['category_id']-1]['name']
        text += f"- {exp['amount_target']:.2f} {exp['currency_target']} ({exp['amount_home']:.2f} {exp['currency_home']})\n"
        text += f"  Категория: {category}\n"
        text += f"  Дата: {exp['timestamp'][:16]}\n\n"
    
    bot.send_message(message.chat.id, text)


# --- Visualization ---

@bot.message_handler(func=lambda message: message.text == "📈 Графики расходов")
def show_charts_menu(message):
    """
    Показывает меню выбора типа графика.
    """
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Проверяем наличие расходов
    expenses = database.get_expenses_by_category(trip['trip_id'])
    if not expenses:
        bot.send_message(message.chat.id, "В этом путешествии еще нет расходов. Невозможно построить графики.")
        return
    
    # Создаем клавиатуру с выбором типа графика
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🥧 По категориям", callback_data="chart_category"),
        types.InlineKeyboardButton("📊 По дням", callback_data="chart_daily")
    )
    markup.add(
        types.InlineKeyboardButton("📈 Динамика", callback_data="chart_trend"),
        types.InlineKeyboardButton("📉 Сравнение", callback_data="chart_comparison")
    )
    markup.add(types.InlineKeyboardButton("🔄 Все графики", callback_data="chart_all"))
    
    bot.send_message(
        message.chat.id,
        "Выберите тип графика для визуализации расходов:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("chart_"))
def handle_chart_request(call):
    """
    Обрабатывает запросы на создание графиков.
    """
    user_id = call.from_user.id
    trip = get_user_active_trip(user_id)
    
    if not trip:
        bot.answer_callback_query(call.id, "Ошибка: активное путешествие не найдено")
        return
    
    # Проверяем наличие расходов
    expenses = database.get_expenses_by_category(trip['trip_id'])
    if not expenses:
        bot.answer_callback_query(call.id, "В этом путешествии еще нет расходов")
        return
    
    chart_type = call.data.replace("chart_", "")
    currency_code = trip['target_currency']
    trip_name = trip['name']
    trip_id = trip['trip_id']
    
    # Очищаем старые графики перед созданием новых
    visualization.cleanup_old_charts()
    
    try:
        if chart_type == "category":
            # Круговая диаграмма по категориям
            bot.answer_callback_query(call.id, "Создаю график...")
            filepath = visualization.create_category_pie_chart(trip_id, trip_name, currency_code)
            if filepath and os.path.exists(filepath):
                with open(filepath, 'rb') as photo:
                    bot.send_photo(call.message.chat.id, photo, 
                                 caption="📊 Круговая диаграмма расходов по категориям")
                os.remove(filepath)  # Удаляем файл после отправки
            else:
                bot.send_message(call.message.chat.id, "Не удалось создать график.")
                
        elif chart_type == "daily":
            # Столбчатая диаграмма по дням
            bot.answer_callback_query(call.id, "Создаю график...")
            filepath = visualization.create_daily_expenses_bar_chart(trip_id, trip_name, currency_code)
            if filepath and os.path.exists(filepath):
                with open(filepath, 'rb') as photo:
                    bot.send_photo(call.message.chat.id, photo,
                                 caption="📊 Расходы по дням")
                os.remove(filepath)
            else:
                bot.send_message(call.message.chat.id, "Не удалось создать график.")
                
        elif chart_type == "trend":
            # Линейный график динамики
            bot.answer_callback_query(call.id, "Создаю график...")
            filepath = visualization.create_expense_trend_line_chart(trip_id, trip_name, currency_code)
            if filepath and os.path.exists(filepath):
                with open(filepath, 'rb') as photo:
                    bot.send_photo(call.message.chat.id, photo,
                                 caption="📈 Динамика расходов (накопительная сумма)")
                os.remove(filepath)
            else:
                bot.send_message(call.message.chat.id, "Не удалось создать график.")
                
        elif chart_type == "comparison":
            # Столбчатая диаграмма сравнения категорий
            bot.answer_callback_query(call.id, "Создаю график...")
            filepath = visualization.create_category_comparison_chart(trip_id, trip_name, currency_code)
            if filepath and os.path.exists(filepath):
                with open(filepath, 'rb') as photo:
                    bot.send_photo(call.message.chat.id, photo,
                                 caption="📉 Сравнение расходов по категориям")
                os.remove(filepath)
            else:
                bot.send_message(call.message.chat.id, "Не удалось создать график.")
                
        elif chart_type == "all":
            # Все графики
            bot.answer_callback_query(call.id, "Создаю все графики...")
            
            charts = [
                ("Круговая диаграмма по категориям", visualization.create_category_pie_chart),
                ("Расходы по дням", visualization.create_daily_expenses_bar_chart),
                ("Динамика расходов", visualization.create_expense_trend_line_chart),
                ("Сравнение категорий", visualization.create_category_comparison_chart)
            ]
            
            for chart_name, chart_func in charts:
                filepath = chart_func(trip_id, trip_name, currency_code)
                if filepath and os.path.exists(filepath):
                    with open(filepath, 'rb') as photo:
                        bot.send_photo(call.message.chat.id, photo, caption=f"📊 {chart_name}")
                    os.remove(filepath)
            
            bot.send_message(call.message.chat.id, "✅ Все графики созданы!")
            
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка при создании графика: {str(e)}")
        bot.send_message(call.message.chat.id, f"Произошла ошибка при создании графика. Попробуйте позже.")


@bot.message_handler(func=lambda message: message.text == "✏️ Редактировать расходы")
def edit_expenses_menu(message):
    """Показать список расходов для редактирования"""
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    expenses = database.get_expenses_by_category(trip['trip_id'])
    
    if not expenses:
        bot.send_message(message.chat.id, "В этом путешествии еще нет расходов.")
        return
    
    # Показываем последние 20 расходов с кнопками редактирования
    text = f"Выберите расход для редактирования ({trip['name']}):\n\n"
    markup = types.InlineKeyboardMarkup()
    
    # Ограничиваем до 20 расходов для удобства
    for exp in expenses[:20]:
        category_name = exp.get('category_name', 'Прочее')
        date_str = exp['timestamp'][:16] if exp['timestamp'] else 'Неизвестно'
        text_line = f"{exp['amount_target']:.2f} {exp['currency_target']} - {category_name} ({date_str})"
        
        # Создаем кнопку для каждого расхода
        btn_text = f"{exp['amount_target']:.2f} {exp['currency_target']} ({date_str[:10]})"
        if len(btn_text) > 64:  # Telegram ограничение на длину текста кнопки
            btn_text = btn_text[:61] + "..."
        
        markup.add(types.InlineKeyboardButton(
            btn_text,
            callback_data=f"edit_exp_{exp['expense_id']}"
        ))
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    
    bot.send_message(message.chat.id, "Выберите расход для редактирования:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_exp_amount_"))
def edit_expense_amount_prompt(call):
    """Запросить новую сумму расхода"""
    try:
        # Формат: edit_exp_amount_{expense_id}
        # При split("_") получаем: ['edit', 'exp', 'amount', '123']
        expense_id = int(call.data.split("_")[3])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID расхода")
        return
    
    expense = database.get_expense_by_id(expense_id)
    if not expense:
        bot.answer_callback_query(call.id, "Ошибка: расход не найден")
        return
    
    user_id = call.from_user.id
    user_data[user_id] = {
        'step': 'editing_expense_amount',
        'expense_id': expense_id,
        'trip_id': expense['trip_id']
    }
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Введите новую сумму расхода в валюте {expense['currency_target']}:\n\n"
             f"Текущая сумма: {expense['amount_target']:.2f} {expense['currency_target']}"
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_exp_category_"))
def edit_expense_category_prompt(call):
    """Запросить новую категорию расхода"""
    try:
        # Формат: edit_exp_category_{expense_id}
        # При split("_") получаем: ['edit', 'exp', 'category', '123']
        expense_id = int(call.data.split("_")[3])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID расхода")
        return
    
    expense = database.get_expense_by_id(expense_id)
    if not expense:
        bot.answer_callback_query(call.id, "Ошибка: расход не найден")
        return
    
    user_id = call.from_user.id
    user_data[user_id] = {
        'step': 'editing_expense_category',
        'expense_id': expense_id,
        'trip_id': expense['trip_id']
    }
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Выберите новую категорию для расхода:\n\n"
             f"Текущая категория: {expense.get('category_name', 'Прочее')}",
        reply_markup=select_category_keyboard()
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_exp_") and not call.data.startswith("edit_exp_amount_") and not call.data.startswith("edit_exp_category_"))
def select_expense_to_edit(call):
    """Обработчик выбора расхода для редактирования"""
    try:
        # Формат: edit_exp_{expense_id}
        # При split("_") получаем: ['edit', 'exp', '123']
        expense_id = int(call.data.split("_")[2])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID расхода")
        return
    
    expense = database.get_expense_by_id(expense_id)
    if not expense:
        bot.answer_callback_query(call.id, "Ошибка: расход не найден")
        return
    
    user_id = call.from_user.id
    trip = get_user_active_trip(user_id)
    if not trip or trip['trip_id'] != expense['trip_id']:
        bot.answer_callback_query(call.id, "Ошибка: расход не принадлежит вашему активному путешествию")
        return
    
    # Сохраняем информацию о редактируемом расходе
    user_data[user_id] = {
        'step': 'editing_expense',
        'expense_id': expense_id,
        'trip_id': trip['trip_id']
    }
    
    category_name = expense.get('category_name', 'Прочее')
    date_str = expense['timestamp'][:16] if expense['timestamp'] else 'Неизвестно'
    
    text = f"📝 Редактирование расхода:\n\n"
    text += f"💰 Сумма: {expense['amount_target']:.2f} {expense['currency_target']}\n"
    text += f"   ({expense['amount_home']:.2f} {expense['currency_home']})\n"
    text += f"📂 Категория: {category_name}\n"
    text += f"📅 Дата: {date_str}\n\n"
    text += f"Что вы хотите изменить?"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💰 Изменить сумму", callback_data=f"edit_exp_amount_{expense_id}"))
    markup.add(types.InlineKeyboardButton("📂 Изменить категорию", callback_data=f"edit_exp_category_{expense_id}"))
    markup.add(types.InlineKeyboardButton("🗑 Удалить расход", callback_data=f"delete_exp_{expense_id}"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_edit_list"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'editing_expense_amount')
def process_expense_amount_edit(message):
    """Обработать новую сумму расхода"""
    try:
        new_amount_target = float(message.text.replace(',', '.'))
        if new_amount_target <= 0:
            bot.send_message(message.chat.id, "Сумма должна быть положительным числом.")
            return
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")
        return
    
    user_id = message.from_user.id
    user_data_entry = user_data.get(user_id, {})
    expense_id = user_data_entry.get('expense_id')
    
    if not expense_id:
        bot.send_message(message.chat.id, "Ошибка: данные о редактировании не найдены.")
        return
    
    expense = database.get_expense_by_id(expense_id)
    if not expense:
        bot.send_message(message.chat.id, "Ошибка: расход не найден.")
        return
    
    trip = get_user_active_trip(user_id)
    if not trip:
        bot.send_message(message.chat.id, "Ошибка: активное путешествие не найдено.")
        return
    
    # Рассчитываем новую сумму в домашней валюте
    # Используем курс из путешествия или из самого расхода
    if expense['currency_target'] == trip['target_currency']:
        # Используем курс из путешествия
        exchange_rate = trip['exchange_rate']
        new_amount_home = new_amount_target / exchange_rate
    else:
        # Используем курс из расхода (если мультивалютность)
        # Находим курс для этой валюты
        conn = get_db_connection()
        currency_row = conn.execute('''
            SELECT exchange_rate_to_home FROM trip_currencies 
            WHERE trip_id = ? AND currency_code = ?
        ''', (trip['trip_id'], expense['currency_target'])).fetchone()
        conn.close()
        
        if currency_row:
            exchange_rate = currency_row['exchange_rate_to_home']
            # exchange_rate_to_home хранится как: 1 HOME = rate TARGET
            # значит HOME = TARGET / rate
            new_amount_home = new_amount_target / exchange_rate
        else:
            # Используем пропорцию из старого расхода
            old_rate = expense['amount_home'] / expense['amount_target'] if expense['amount_target'] > 0 else 1
            new_amount_home = new_amount_target * old_rate
    
    # Обновляем расход
    success = database.update_expense(
        expense_id,
        new_amount_home,
        new_amount_target,
        expense['category_id']
    )
    
    if success:
        bot.send_message(
            message.chat.id,
            f"✅ Сумма расхода обновлена:\n"
            f"💰 {new_amount_target:.2f} {expense['currency_target']}\n"
            f"   ({new_amount_home:.2f} {expense['currency_home']})"
        )
    else:
        bot.send_message(message.chat.id, "❌ Ошибка при обновлении расхода.")
    
    # Очищаем состояние
    if user_id in user_data:
        del user_data[user_id]




@bot.callback_query_handler(func=lambda call: call.from_user.id in user_data and user_data[call.from_user.id].get('step') == 'editing_expense_category' and call.data.startswith('cat_'))
def process_expense_category_edit(call):
    """Обработать новую категорию расхода"""
    try:
        new_category_id = int(call.data.split('_')[1])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный формат данных")
        return
    
    user_id = call.from_user.id
    user_data_entry = user_data.get(user_id, {})
    expense_id = user_data_entry.get('expense_id')
    
    if not expense_id:
        bot.answer_callback_query(call.id, "Ошибка: данные о редактировании не найдены")
        return
    
    expense = database.get_expense_by_id(expense_id)
    if not expense:
        bot.answer_callback_query(call.id, "Ошибка: расход не найден")
        return
    
    # Проверяем валидность категории
    categories = database.get_all_categories()
    if new_category_id < 1 or new_category_id > len(categories):
        bot.answer_callback_query(call.id, "Ошибка: категория не найдена")
        return
    
    # Обновляем расход
    success = database.update_expense(
        expense_id,
        expense['amount_home'],
        expense['amount_target'],
        new_category_id
    )
    
    if success:
        category_name = categories[new_category_id-1]['name']
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Категория расхода обновлена на: {category_name}"
        )
        bot.answer_callback_query(call.id, f"Категория изменена на: {category_name}")
    else:
        bot.answer_callback_query(call.id, "❌ Ошибка при обновлении категории")
    
    # Очищаем состояние
    if user_id in user_data:
        del user_data[user_id]


@bot.callback_query_handler(func=lambda call: call.data.startswith("delete_exp_"))
def delete_expense_confirm(call):
    """Подтверждение удаления расхода"""
    try:
        expense_id = int(call.data.split("_")[2])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID расхода")
        return
    
    expense = database.get_expense_by_id(expense_id)
    if not expense:
        bot.answer_callback_query(call.id, "Ошибка: расход не найден")
        return
    
    category_name = expense.get('category_name', 'Прочее')
    date_str = expense['timestamp'][:16] if expense['timestamp'] else 'Неизвестно'
    
    text = f"⚠️ Вы уверены, что хотите удалить этот расход?\n\n"
    text += f"💰 {expense['amount_target']:.2f} {expense['currency_target']}\n"
    text += f"📂 Категория: {category_name}\n"
    text += f"📅 Дата: {date_str}\n\n"
    text += f"Это действие нельзя отменить!"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delete_exp_{expense_id}"))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data=f"edit_exp_{expense_id}"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=text,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_exp_"))
def confirm_delete_expense(call):
    """Подтвердить удаление расхода"""
    try:
        expense_id = int(call.data.split("_")[3])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID расхода")
        return
    
    expense = database.get_expense_by_id(expense_id)
    if not expense:
        bot.answer_callback_query(call.id, "Ошибка: расход не найден")
        return
    
    success = database.delete_expense(expense_id)
    
    if success:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"✅ Расход удален:\n"
                 f"💰 {expense['amount_target']:.2f} {expense['currency_target']}"
        )
        bot.answer_callback_query(call.id, "Расход удален")
    else:
        bot.answer_callback_query(call.id, "❌ Ошибка при удалении расхода")


@bot.callback_query_handler(func=lambda call: call.data == "back_to_edit_list")
def back_to_edit_list(call):
    """Вернуться к списку расходов для редактирования"""
    user_id = call.from_user.id
    trip = get_user_active_trip(user_id)
    if not trip:
        bot.answer_callback_query(call.id, "Ошибка: активное путешествие не найдено")
        return
    
    expenses = database.get_expenses_by_category(trip['trip_id'])
    
    if not expenses:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="В этом путешествии еще нет расходов."
        )
        bot.answer_callback_query(call.id)
        return
    
    markup = types.InlineKeyboardMarkup()
    
    for exp in expenses[:20]:
        date_str = exp['timestamp'][:16] if exp['timestamp'] else 'Неизвестно'
        btn_text = f"{exp['amount_target']:.2f} {exp['currency_target']} ({date_str[:10]})"
        if len(btn_text) > 64:
            btn_text = btn_text[:61] + "..."
        
        markup.add(types.InlineKeyboardButton(
            btn_text,
            callback_data=f"edit_exp_{exp['expense_id']}"
        ))
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="Выберите расход для редактирования:",
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: message.text == "📦 Расходы по категориям")
def show_expenses_by_categories(message):
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Получаем расходы по категориям
    expenses_by_cat = database.get_expenses_by_category(trip['trip_id'])
    
    if not expenses_by_cat:
        bot.send_message(message.chat.id, "В этом путешествии еще нет расходов.")
        return
    
    # Группируем расходы по категориям
    cat_expenses = {}
    for exp in expenses_by_cat:
        cat_name = exp['category_name']
        if cat_name not in cat_expenses:
            cat_expenses[cat_name] = {'total_target': 0, 'total_home': 0, 'count': 0, 'details': []}
        cat_expenses[cat_name]['total_target'] += exp['amount_target']
        cat_expenses[cat_name]['total_home'] += exp['amount_home']
        cat_expenses[cat_name]['count'] += 1
        cat_expenses[cat_name]['details'].append({
            'amount_target': exp['amount_target'],
            'amount_home': exp['amount_home'],
            'timestamp': exp['timestamp'],
            'currency_target': exp['currency_target']
        })
    
    text = f"Расходы по категориям ({trip['name']}):\n\n"
    for cat_name, stats in cat_expenses.items():
        text += f"{cat_name}:\n"
        text += f"  - Всего: {stats['total_target']:.2f} {trip['target_currency']} ({stats['total_home']:.2f} {trip['home_currency']})\n"
        text += f"  - Количество покупок: {stats['count']}\n"
        text += f"  - Средний чек: {stats['total_target']/stats['count']:.2f} {trip['target_currency']}\n\n"
    
    bot.send_message(message.chat.id, text)

# --- Budget Settings Menu ---

@bot.message_handler(func=lambda message: message.text == "📊 Настройки бюджета")
def budget_settings_menu(message):
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    bot.send_message(message.chat.id, "🔧 Настройки бюджета:", reply_markup=budget_settings_keyboard())


@bot.message_handler(func=lambda message: message.text == "📈 Установить бюджеты по категориям")
def start_category_budget_setup(message):
    """
    Начинает процесс установки бюджетов по категориям для активного путешествия.
    """
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Сохраняем состояние пользователя
    user_data[message.from_user.id] = {'step': 'select_category_for_budget', 'trip_id': trip['trip_id']}
    
    # Отправляем сообщение с выбором категории
    bot.send_message(message.chat.id, "Выберите категорию для установки бюджета:", reply_markup=select_category_keyboard())


@bot.message_handler(func=lambda message: message.text == "💱 Валюты путешествия")
def manage_trip_currencies(message):
    """
    Меню управления валютами в активном путешествии:
    - показать список валют и балансов
    - добавить валюту
    - изменить баланс валюты
    - удалить валюту (кроме основной)
    """
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return

    text = f"💱 Валюты путешествия: {trip['name']}\n"
    text += f"🏠 Домашняя валюта: {trip['home_currency']}\n\n"
    text += "💳 Доступные валюты:\n"

    markup = types.InlineKeyboardMarkup()

    for cur in trip['currencies']:
        home_eq = cur['balance'] / cur['exchange_rate_to_home'] if cur['exchange_rate_to_home'] else 0
        text += f"- {cur['currency_code']}: {cur['balance']:.2f} (≈ {home_eq:.2f} {trip['home_currency']})\n"
        markup.add(
            types.InlineKeyboardButton(f"✏️ Баланс {cur['currency_code']}", callback_data=f"cur_setbal_{cur['currency_id']}")
        )
        # Нельзя удалять основную валюту путешествия (target_currency)
        if cur['currency_code'] != trip['target_currency']:
            markup.add(
                types.InlineKeyboardButton(f"🗑 Удалить {cur['currency_code']}", callback_data=f"cur_del_{cur['currency_id']}")
            )

    markup.add(types.InlineKeyboardButton("➕ Добавить валюту", callback_data="add_currency"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))

    bot.send_message(message.chat.id, text, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cur_setbal_"))
def currency_set_balance_prompt(call):
    user_id = call.from_user.id
    try:
        currency_id = int(call.data.split("_")[2])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID валюты")
        return

    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM trip_currencies WHERE currency_id = ?", (currency_id,)).fetchone()
    conn.close()
    if not cur:
        bot.answer_callback_query(call.id, "Ошибка: валюта не найдена")
        return

    user_data[user_id] = {'step': 'set_currency_balance', 'currency_id': currency_id}
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Введите новый баланс для {cur['currency_code']} (текущее: {cur['balance']:.2f}):"
    )
    bot.answer_callback_query(call.id)


@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'set_currency_balance')
def process_currency_set_balance(message):
    user_id = message.from_user.id
    try:
        new_balance = float(message.text.replace(',', '.'))
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")
        return

    currency_id = user_data.get(user_id, {}).get('currency_id')
    if not currency_id:
        bot.send_message(message.chat.id, "Ошибка: данные валюты не найдены. Откройте меню валют заново.")
        return

    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM trip_currencies WHERE currency_id = ?", (currency_id,)).fetchone()
    if not cur:
        conn.close()
        bot.send_message(message.chat.id, "Ошибка: валюта не найдена.")
        return

    conn.execute("UPDATE trip_currencies SET balance = ? WHERE currency_id = ?", (new_balance, currency_id))
    conn.commit()
    conn.close()

    bot.send_message(message.chat.id, f"✅ Баланс {cur['currency_code']} обновлен: {new_balance:.2f}")
    if user_id in user_data:
        del user_data[user_id]


@bot.callback_query_handler(func=lambda call: call.data.startswith("cur_del_"))
def currency_delete_confirm(call):
    try:
        currency_id = int(call.data.split("_")[2])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID валюты")
        return

    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM trip_currencies WHERE currency_id = ?", (currency_id,)).fetchone()
    conn.close()
    if not cur:
        bot.answer_callback_query(call.id, "Ошибка: валюта не найдена")
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"cur_del_ok_{currency_id}"))
    markup.add(types.InlineKeyboardButton("❌ Отмена", callback_data="back_to_main"))
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Удалить валюту {cur['currency_code']} из путешествия?\n\n⚠️ Если есть расходы в этой валюте, редактирование балансов может стать неконсистентным.",
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("cur_del_ok_"))
def currency_delete_execute(call):
    try:
        currency_id = int(call.data.split("_")[3])
    except (ValueError, IndexError):
        bot.answer_callback_query(call.id, "Ошибка: некорректный ID валюты")
        return

    conn = get_db_connection()
    cur = conn.execute("SELECT * FROM trip_currencies WHERE currency_id = ?", (currency_id,)).fetchone()
    if not cur:
        conn.close()
        bot.answer_callback_query(call.id, "Ошибка: валюта не найдена")
        return

    # Не удаляем валюту, если по ней есть расходы
    exp_cnt = conn.execute("SELECT COUNT(1) as cnt FROM expenses WHERE trip_id = ? AND currency_target = ?", (cur['trip_id'], cur['currency_code'])).fetchone()
    if exp_cnt and exp_cnt['cnt'] > 0:
        conn.close()
        bot.answer_callback_query(call.id, "Нельзя удалить: есть расходы в этой валюте")
        return

    conn.execute("DELETE FROM trip_currencies WHERE currency_id = ?", (currency_id,))
    conn.commit()
    conn.close()

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"✅ Валюта {cur['currency_code']} удалена."
    )
    bot.answer_callback_query(call.id)

# --- Budget Settings Handlers ---

@bot.message_handler(func=lambda message: message.text == "📊 Установить лимит бюджета")
def set_budget_limit(message):
    """
    Обработчик команды "📊 Установить лимит бюджета".
    Запрашивает у пользователя новый лимит бюджета для активного путешествия.
    """
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Сохраняем ID пользователя и информацию о путешествии
    user_id = message.from_user.id
    user_data[user_id] = {'state': 'setting_budget_limit', 'trip_id': trip['trip_id'], 'target_currency': trip['target_currency']}
    
    bot.send_message(message.chat.id, f"Текущий лимит бюджета: {trip['budget_limit']} {trip['target_currency']}\nВведите новый лимит бюджета (в {trip['target_currency']}), или 0, чтобы отключить:")


@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('state') == 'setting_budget_limit')
def process_set_budget_limit(message):
    """
    Обработчик ввода нового лимита бюджета.
    Обновляет лимит бюджета для активного путешествия и автоматически устанавливает порог уведомления.
    """
    user_id = message.from_user.id
    user_state = user_data.get(user_id, {})
    
    if 'trip_id' not in user_state:
        bot.send_message(message.chat.id, "Ошибка: данные пользователя повреждены. Начните заново.")
        if user_id in user_data:
            del user_data[user_id]
        return
    
    try:
        new_limit = float(message.text.replace(',', '.'))
        trip_id = user_state['trip_id']
        
        conn = get_db_connection()
        # Получаем целевую валюту из базы данных
        target_currency_result = conn.execute('SELECT target_currency FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
        if target_currency_result:
            target_currency = target_currency_result[0]
        else:
            bot.send_message(message.chat.id, "Ошибка: не удалось найти информацию о путешествии.")
            conn.close()
            if user_id in user_data:
                del user_data[user_id]
            return
        
        # Обновляем лимит бюджета
        conn.execute('UPDATE trips SET budget_limit = ? WHERE trip_id = ?', (new_limit, trip_id))
        
        # Автоматически устанавливаем порог уведомления (80% от лимита, если лимит > 0)
        if new_limit > 0:
            new_threshold = new_limit * 0.8
            conn.execute('UPDATE trips SET notification_threshold = ? WHERE trip_id = ?', (new_threshold, trip_id))
            bot.send_message(message.chat.id, f"Лимит бюджета обновлен: {new_limit} {target_currency}\nПорог уведомления: {new_threshold} {target_currency} (80% от лимита)")
        else:
            conn.execute('UPDATE trips SET notification_threshold = 0 WHERE trip_id = ?', (trip_id,))
            bot.send_message(message.chat.id, f"Лимит бюджета отключен.")
        
        conn.commit()
        conn.close()
        
        # Очищаем состояние пользователя
        if user_id in user_data:
            del user_data[user_id]
            
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректное число.")


@bot.message_handler(func=lambda message: message.text == "🔔 Установить порог уведомления")
def set_notification_threshold(message):
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Сохраняем ID пользователя и информацию о путешествии
    user_id = message.from_user.id
    user_data[user_id] = {'state': 'setting_notification_threshold', 'trip_id': trip['trip_id'], 'target_currency': trip['target_currency']}
    
    bot.send_message(message.chat.id, f"Текущий порог уведомления: {trip['notification_threshold']} {trip['target_currency']}\nВведите новый порог уведомления (в {trip['target_currency']}):")


@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('state') == 'setting_notification_threshold')
def process_set_notification_threshold(message):
    user_id = message.from_user.id
    user_state = user_data.get(user_id, {})
    
    if 'trip_id' not in user_state:
        bot.send_message(message.chat.id, "Ошибка: данные пользователя повреждены. Начните заново.")
        if user_id in user_data:
            del user_data[user_id]
        return
    
    try:
        new_threshold = float(message.text.replace(',', '.'))
        trip_id = user_state['trip_id']
        
        conn = get_db_connection()
        # Получаем целевую валюту из базы данных
        target_currency_result = conn.execute('SELECT target_currency FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
        if target_currency_result:
            target_currency = target_currency_result[0]
        else:
            bot.send_message(message.chat.id, "Ошибка: не удалось найти информацию о путешествии.")
            conn.close()
            if user_id in user_data:
                del user_data[user_id]
            return
        
        # Обновляем порог уведомления
        conn.execute('UPDATE trips SET notification_threshold = ? WHERE trip_id = ?', (new_threshold, trip_id))
        bot.send_message(message.chat.id, f"Порог уведомления обновлен: {new_threshold} {target_currency}")
        conn.commit()
        conn.close()
        
        # Очищаем состояние пользователя
        if user_id in user_data:
            del user_data[user_id]
            
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите корректное число.")


@bot.message_handler(func=lambda message: message.text == "💰 Просмотреть бюджет")
def view_budget(message):
    """
    Обработчик команды "💰 Просмотреть бюджет".
    Отображает статистику по общему бюджету для активного путешествия.
    """
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    if trip['budget_limit'] > 0:
        # Calculate total spent across all currencies
        conn = get_db_connection()
        total_spent_result = conn.execute('''
            SELECT SUM(amount_home) as total_spent FROM expenses WHERE trip_id = ?
        ''', (trip['trip_id'],)).fetchone()
        conn.close()
        total_spent = total_spent_result['total_spent'] or 0
        
        # Convert to target currency for comparison with budget
        total_spent_in_target = total_spent * trip['exchange_rate']
        remaining = trip['budget_limit'] - total_spent_in_target
        percentage_spent = min((total_spent_in_target / trip['budget_limit']) * 100, 100)
        
        bot.send_message(message.chat.id, f"📊 Статистика бюджета для {trip['name']}:\n"
                         f"Лимит: {trip['budget_limit']} {trip['target_currency']}\n"
                         f"Потрачено: {total_spent_in_target:.2f} {trip['target_currency']} ({percentage_spent:.1f}%)\n"
                         f"Осталось: {remaining:.2f} {trip['target_currency']}\n"
                         f"Порог уведомления: {trip['notification_threshold']} {trip['target_currency']}")
    else:
        bot.send_message(message.chat.id, f"Лимит бюджета не установлен для {trip['name']}.")


@bot.message_handler(func=lambda message: message.text == "📋 План по категориям")
def view_category_budgets(message):
    """
    Обработчик команды "📋 План по категориям".
    Отображает информацию о бюджетах по категориям для активного путешествия.
    """
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Получаем информацию о бюджетах по категориям
    cat_budgets = database.get_trip_categories_with_budgets(trip['trip_id'])
    
    if not cat_budgets:
        bot.send_message(message.chat.id, f"Для путешествия {trip['name']} не установлены бюджеты по категориям.")
        return
    
    text = f"Бюджеты по категориям для {trip['name']}:\n\n"
    has_budgets = False
    
    for cat in cat_budgets:
        if cat['planned_amount'] > 0:
            has_budgets = True
            spent_pct = 0
            if cat['planned_amount'] > 0:
                spent_pct = min((cat['spent_amount'] / cat['planned_amount']) * 100, 100)
            
            text += f"{cat['name']}:\n"
            text += f"  Запланировано: {cat['planned_amount']:.2f} {cat['currency_code']}\n"
            text += f"  Потрачено: {cat['spent_amount']:.2f} {cat['currency_code']} ({spent_pct:.1f}%)\n"
            remaining = cat['planned_amount'] - cat['spent_amount']
            text += f"  Осталось: {remaining:.2f} {cat['currency_code']}\n\n"
    
    if not has_budgets:
        text += "Пока не установлено бюджетов по категориям. Используйте команду /setcatbudget или кнопку 'Установить бюджеты по категориям' для установки."
    else:
        # Добавим общую статистику
        total_planned = sum(cat['planned_amount'] for cat in cat_budgets if cat['planned_amount'] > 0)
        total_spent = sum(cat['spent_amount'] for cat in cat_budgets if cat['planned_amount'] > 0)
        overall_pct = 0
        if total_planned > 0:
            overall_pct = min((total_spent / total_planned) * 100, 100)
        
        text += f"📊 Общий бюджет по категориям: {total_planned:.2f} {trip['target_currency']}\n"
        text += f"📈 Потрачено: {total_spent:.2f} {trip['target_currency']} ({overall_pct:.1f}%)"
    
    bot.send_message(message.chat.id, text)


@bot.message_handler(func=lambda message: message.text == "🔙 Назад в меню")
def back_to_main_menu(message):
    """
    Обработчик команды "🔙 Назад в меню".
    Возвращает пользователя в главное меню.
    """
    bot.send_message(message.chat.id, "Возвращаемся в главное меню.", reply_markup=main_menu_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_callback(call):
    """Обработчик callback для кнопки 'Назад' - возвращает в главное меню"""
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="Возвращаемся в главное меню."
    )
    bot.send_message(call.message.chat.id, "Главное меню:", reply_markup=main_menu_keyboard())
    bot.answer_callback_query(call.id)


# --- Change Rate ---


# --- Multi-Currency Support ---

def select_currency_keyboard(trip):
    """
    Создает inline-клавиатуру для выбора валюты из списка валют путешествия.
    
    Args:
        trip: Словарь с информацией о путешествии, включая список валют
    
    Returns:
        Объект InlineKeyboardMarkup с кнопками для выбора валют
    """
    markup = types.InlineKeyboardMarkup()
    for currency in trip['currencies']:
        markup.add(
            types.InlineKeyboardButton(f"{currency['currency_code']} - {currency['balance']:.2f}",
                                    callback_data=f"sel_curr_{currency['currency_code']}_{currency['currency_id']}"),
        )
    # Add option to add new currency
    markup.add(types.InlineKeyboardButton("➕ Добавить новую валюту", callback_data="add_currency"))
    return markup


def select_category_keyboard():
    """
    Создает inline-клавиатуру для выбора категории расхода.
    
    Returns:
        Объект InlineKeyboardMarkup с кнопками категорий расходов
    """
    categories = database.get_all_categories()
    markup = types.InlineKeyboardMarkup()
    
    for cat in categories:
        markup.add(
            types.InlineKeyboardButton(cat['name'], callback_data=f"cat_{cat['category_id']}")
        )
    
    return markup


def check_category_budget_limits(trip_id, category_id, amount_home):
    """
    Проверяет, не превышены ли лимиты бюджета по категории, и возвращает список уведомлений.
    
    Args:
        trip_id: ID путешествия
        category_id: ID категории расхода
        amount_home: Сумма расхода в домашней валюте
    
    Returns:
        Список уведомлений о приближении или превышении лимита бюджета по категории
    """
    notifications = []
    
    # Получаем информацию о бюджете для данной категории
    conn = get_db_connection()
    cat_budget = conn.execute('''
        SELECT planned_amount, spent_amount, currency_code
        FROM category_budgets
        WHERE trip_id = ? AND category_id = ?
    ''', (trip_id, category_id)).fetchone()
    
    if cat_budget and cat_budget['planned_amount'] > 0:
        planned = cat_budget['planned_amount']
        spent_before = cat_budget['spent_amount']
        spent_after = spent_before + amount_home
        currency_code = cat_budget['currency_code']
        
        # Проверяем, не превышен ли порог уведомления (обычно 80% от лимита)
        notification_threshold = planned * 0.8
        if spent_before <= notification_threshold < spent_after:
            pct = (spent_after / planned) * 100
            notifications.append(
                f"⚠️ Вы приближаетесь к лимиту бюджета по категории '{database.get_all_categories()[category_id-1]['name']}'! "
                f"Потрачено: {spent_after:.2f} {currency_code} из {planned:.2f} {currency_code} ({pct:.1f}%)"
            )
        elif spent_before < planned <= spent_after:
            # Превышен лимит бюджета по категории
            exceeded_amount = spent_after - planned
            notifications.append(
                f"⚠️ Вы превысили лимит бюджета по категории '{database.get_all_categories()[category_id-1]['name']}'! "
                f"Превышение: {exceeded_amount:.2f} {currency_code}"
            )
    
    conn.close()
    return notifications

# --- Expense Tracking ---
#
# Обрабатываем только не-командные текстовые сообщения, чтобы команды
# (например, /setcatbudget) не перехватывались этим обработчиком.
# Также не обрабатываем сообщения, когда пользователь редактирует расход или находится в других специальных режимах.
@bot.message_handler(func=lambda message: not message.text.startswith('/') and 
                     user_data.get(message.from_user.id, {}).get('step') not in 
                     ('editing_expense_amount', 'editing_expense_category', 'enter_budget_amount_for_category',
                      'add_currency_code', 'add_currency_balance', 'select_category_for_budget'))
def handle_text(message):
    # Try to see if it's a number
    try:
        amount = float(message.text.replace(',', '.'))
        trip = get_user_active_trip(message.from_user.id)
        if not trip:
            bot.send_message(message.chat.id, "Вижу число, но у вас нет активного путешествия. Создайте его через меню.")
            return
        
        # If there's only one currency, use it directly
        if len(trip['currencies']) == 1:
            currency = trip['currencies'][0]
            home_amount = amount / currency['exchange_rate_to_home']
            bot.send_message(
                message.chat.id,
                f"{amount} {currency['currency_code']} = {home_amount:.2f} {trip['home_currency']}\nУчесть как расход?",
                reply_markup=inline_confirm_expense_multi(amount, currency['currency_code'], trip['trip_id'])
            )
        else:
            # Ask user to select currency
            bot.send_message(
                message.chat.id,
                f"Вы ввели сумму: {amount}. В какую валюту из ваших путешествий хотите записать расход?",
                reply_markup=select_currency_keyboard(trip)
            )
            # Store the amount for later use
            user_data[message.from_user.id] = {'temp_expense_amount': amount}
    except ValueError:
        # Not a number, just ignore or send help
        if message.text.startswith('/'):
            bot.send_message(message.chat.id, "Неизвестная команда.")
        else:
            bot.send_message(message.chat.id, "Я понимаю только числа (как расходы) или команды из меню.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("exp_yes_"))
def confirm_expense_callback(call):
    parts = call.data.split('_')
    amount_target = float(parts[2])
    trip_id = int(parts[3])
    
    conn = get_db_connection()
    trip = conn.execute('SELECT * FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
    
    if trip:
        amount_home = amount_target / trip['exchange_rate']
        
        # Store expense data temporarily and ask for category
        user_data[call.from_user.id] = {
            'temp_expense_data': {
                'trip_id': trip_id,
                'amount_target': amount_target,
                'amount_home': amount_home,
                'currency_target': trip['target_currency'],
                'currency_home': trip['home_currency']
            }
        }
        
        # Ask user to select a category
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Выберите категорию расхода:",
            reply_markup=select_category_keyboard()
        )
    
    conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("sel_curr_"))
def select_currency_callback(call):
    user_id = call.from_user.id
    temp_data = user_data.get(user_id, {})
    amount = temp_data.get('temp_expense_amount')
    
    if not amount:
        bot.answer_callback_query(call.id, "Ошибка: сумма расхода не найдена")
        return
    
    # Parse the selected currency
    parts = call.data.split('_')
    currency_code = parts[2]
    currency_id = int(parts[3])
    
    # Get trip info
    trip = get_user_active_trip(user_id)
    if not trip:
        bot.answer_callback_query(call.id, "Ошибка: активное путешествие не найдено")
        return
    
    # Find the selected currency
    selected_currency = None
    for curr in trip['currencies']:
        if curr['currency_code'] == currency_code:
            selected_currency = curr
            break
    
    if not selected_currency:
        bot.answer_callback_query(call.id, "Ошибка: валюта не найдена")
        return
    
    home_amount = amount / selected_currency['exchange_rate_to_home']
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"{amount} {selected_currency['currency_code']} = {home_amount:.2f} {trip['home_currency']}\nУчесть как расход?",
        reply_markup=inline_confirm_expense_multi(amount, currency_code, trip['trip_id'])
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("exp_multi_yes_"))
def confirm_multi_expense_callback(call):
    parts = call.data.split('_')
    amount = float(parts[3])
    currency_code = parts[4]
    trip_id = int(parts[5])
    
    conn = get_db_connection()
    trip = conn.execute('SELECT * FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
    
    if trip:
        # Get currency info
        currency_info = conn.execute(
            'SELECT * FROM trip_currencies WHERE trip_id = ? AND currency_code = ?',
            (trip_id, currency_code)
        ).fetchone()
        
        if not currency_info:
            bot.answer_callback_query(call.id, "Ошибка: валюта не найдена")
            conn.close()
            return
        
        exchange_rate_to_home = currency_info['exchange_rate_to_home']
        home_amount = amount / exchange_rate_to_home
        
        # Store expense data temporarily and ask for category
        user_data[call.from_user.id] = {
            'temp_expense_data': {
                'trip_id': trip_id,
                'amount_target': amount,
                'amount_home': home_amount,
                'currency_target': currency_code,
                'currency_home': trip['home_currency'],
                'currency_id': currency_info['currency_id'],
                'new_balance': currency_info['balance'] - amount
            }
        }
        
        # Ask user to select a category
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Выберите категорию расхода:",
            reply_markup=select_category_keyboard()
        )
    
    conn.close()

@bot.callback_query_handler(func=lambda call: call.data.startswith("cat_") and not (call.from_user.id in user_data and user_data[call.from_user.id].get('step') in ('select_category_for_budget', 'editing_expense_category')))
def select_category_callback(call):
    user_id = call.from_user.id
    temp_data = user_data.get(user_id, {}).get('temp_expense_data')
    
    if not temp_data:
        bot.answer_callback_query(call.id, "Ошибка: данные расхода не найдены")
        return
    
    category_id = int(call.data.split('_')[1])
    
    # Extract expense data
    trip_id = temp_data['trip_id']
    amount_target = temp_data['amount_target']
    amount_home = temp_data['amount_home']
    currency_target = temp_data['currency_target']
    currency_home = temp_data['currency_home']
    
    # Connect to database
    conn = get_db_connection()
    trip = conn.execute('SELECT * FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
    
    if not trip:
        bot.answer_callback_query(call.id, "Ошибка: путешествие не найдено")
        conn.close()
        return
    
    # Add expense to category using our database helper function
    database.add_expense_to_category(
        trip_id, 
        category_id, 
        amount_home, 
        amount_target, 
        currency_home, 
        currency_target
    )
    
    # Update currency balance if this is multi-currency
    if 'currency_id' in temp_data and 'new_balance' in temp_data:
        conn.execute(
            'UPDATE trip_currencies SET balance = ? WHERE currency_id = ?',
            (temp_data['new_balance'], temp_data['currency_id'])
        )
    
    # Update main trip balance if this is the target currency
    if currency_target == trip['target_currency']:
        new_target_balance = trip['target_balance'] - amount_target
        new_home_balance = trip['home_balance'] - amount_home
        conn.execute(
            'UPDATE trips SET target_balance = ?, home_balance = ? WHERE trip_id = ?',
            (new_target_balance, new_home_balance, trip_id)
        )
    
    conn.commit()
    
    # Check category budget limits and collect notifications
    category_budget_notifications = check_category_budget_limits(trip_id, category_id, amount_home)
    
    # Also check the overall trip budget limit
    overall_budget_notifications = []
    if trip['budget_limit'] > 0 and trip['notification_threshold'] > 0:
        # Calculate total spent across all currencies
        total_spent_result = conn.execute('''
            SELECT SUM(amount_home) as total_spent FROM expenses WHERE trip_id = ?
        ''', (trip_id,)).fetchone()
        total_spent = total_spent_result['total_spent'] or 0
        
        if total_spent > 0:
            total_spent_in_target = total_spent * trip['exchange_rate']
            
            if total_spent_in_target >= trip['notification_threshold'] and total_spent_in_target - (amount_home * trip['exchange_rate']) < trip['notification_threshold']:
                # Just crossed the notification threshold
                overall_budget_notifications.append(
                    f"⚠️ Вы приближаетесь к лимиту бюджета! Потрачено: {total_spent_in_target:.2f} {trip['target_currency']} из {trip['budget_limit']:.2f} {trip['target_currency']} (лимит)"
                )
            elif total_spent_in_target >= trip['budget_limit']:
                # Exceeded budget limit
                exceeded_amount = total_spent_in_target - trip['budget_limit']
                overall_budget_notifications.append(
                    f"⚠️ Вы превысили лимит бюджета! Превышение: {exceeded_amount:.2f} {trip['target_currency']}"
                )
    
    conn.close()
    
    # Clear temporary data
    if user_id in user_data and 'temp_expense_data' in user_data[user_id]:
        del user_data[user_id]['temp_expense_data']
    
    # Send confirmation message
    message_text = f"✅ Расход учтен: {amount_target} {currency_target}\nКатегория: {database.get_all_categories()[category_id-1]['name']}"
    
    # Send the main confirmation
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=message_text
    )
    
    # Send "Записано" message as requested
    bot.send_message(call.message.chat.id, "Записано")
    
    # Send all budget notifications
    for notification in overall_budget_notifications + category_budget_notifications:
        bot.send_message(call.message.chat.id, notification)


@bot.callback_query_handler(func=lambda call: call.data == "exp_no")
def cancel_expense_callback(call):
    # Clear temporary data if exists
    user_id = call.from_user.id
    if user_id in user_data and 'temp_expense_amount' in user_data[user_id]:
        del user_data[user_id]['temp_expense_amount']
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="❌ Расход не учтен.")

@bot.callback_query_handler(func=lambda call: call.data == "add_currency")
def add_currency_callback(call):
    user_id = call.from_user.id
    trip = get_user_active_trip(user_id)
    
    if not trip:
        bot.answer_callback_query(call.id, "Ошибка: активное путешествие не найдено")
        return
    
    user_data[user_id] = {'step': 'add_currency_code', 'trip_id': trip['trip_id']}
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="Введите код валюты, которую хотите добавить (например: USD, EUR, JPY):"
    )

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'add_currency_code')
def process_add_currency_code(message):
    user_id = message.from_user.id
    currency_code = message.text.strip().upper()
    
    if len(currency_code) != 3:
        bot.send_message(message.chat.id, "Код валюты должен состоять из 3 букв. Попробуйте еще раз:")
        return
    
    user_data[user_id]['step'] = 'add_currency_balance'
    user_data[user_id]['new_currency_code'] = currency_code
    bot.send_message(message.chat.id, f"Введите начальный баланс для {currency_code}:")

@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'add_currency_balance')
def process_add_currency_balance(message):
    try:
        user_id = message.from_user.id
        balance = float(message.text.replace(',', '.'))
        currency_code = user_data[user_id]['new_currency_code']
        trip_id = user_data[user_id]['trip_id']
        
        # Get the home currency of the trip to calculate exchange rate
        conn = get_db_connection()
        trip = conn.execute('SELECT home_currency FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
        
        # Get exchange rate from API
        exchange_rate = api_client.get_exchange_rate(trip['home_currency'], currency_code)
        if exchange_rate is None:
            bot.send_message(message.chat.id, f"Не удалось получить курс для {currency_code}. Валюта не добавлена.")
            conn.close()
            del user_data[user_id]
            return
        
        # Add the new currency
        add_currency_to_trip(trip_id, currency_code, balance, exchange_rate)
        
        bot.send_message(
            message.chat.id,
            f"Валюта {currency_code} с балансом {balance} добавлена к путешествию!"
        )
        conn.close()
        del user_data[user_id]
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")

# --- Category Budget Management ---

@bot.message_handler(commands=['setcatbudget'])
def start_set_category_budget(message):
    """
    Обработчик команды /setcatbudget.
    Начинает процесс установки бюджета для конкретной категории расходов.
    """
    trip = get_user_active_trip(message.from_user.id)
    if not trip:
        bot.send_message(message.chat.id, "Сначала выберите или создайте путешествие.")
        return
    
    # Сохраняем состояние пользователя
    user_data[message.from_user.id] = {'step': 'select_category_for_budget', 'trip_id': trip['trip_id']}
    
    # Отправляем сообщение с выбором категории
    bot.send_message(message.chat.id, "Выберите категорию для установки бюджета:", reply_markup=select_category_keyboard())


@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'select_category_for_budget')
def process_category_budget_selection(message):
    """
    Обработчик выбора категории для установки бюджета.
    Если пользователь ввел число сразу после запроса выбора категории, 
    напоминает ему выбрать категорию из предложенных вариантов.
    """
    try:
        planned_amount = float(message.text.replace(',', '.'))
        user_id = message.from_user.id
        if user_id in user_data and 'trip_id' in user_data[user_id]:
            trip_id = user_data[user_id]['trip_id']
            
            # Если пользователь ввел число сразу после запроса, значит он не выбрал категорию
            bot.send_message(message.chat.id, "Сначала выберите категорию из предложенных вариантов.")
            
            # Повторно отправляем выбор категории
            bot.send_message(message.chat.id, "Выберите категорию для установки бюджета:", reply_markup=select_category_keyboard())
        else:
            bot.send_message(message.chat.id, "Пожалуйста, сначала начните процесс установки бюджета по категории.")
    except ValueError:
        # Это сообщение не является числом, возможно, пользователь пытается использовать другую команду
        bot.send_message(message.chat.id, "Пожалуйста, сначала выберите категорию из предложенных вариантов.")


# Callback handler для кнопок "Другая категория" и "Готово" при установке бюджета
@bot.callback_query_handler(func=lambda call: call.data in ("cat_budget_again", "cat_budget_done"))
def category_budget_next_action(call):
    user_id = call.from_user.id
    if call.data == "cat_budget_again":
        trip = get_user_active_trip(user_id)
        if not trip:
            bot.answer_callback_query(call.id, "Ошибка: активное путешествие не найдено")
            return
        # Очищаем старые данные и устанавливаем новый step
        user_data[user_id] = {'step': 'select_category_for_budget', 'trip_id': trip['trip_id']}
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Выберите категорию для установки бюджета:",
            reply_markup=select_category_keyboard()
        )
        bot.answer_callback_query(call.id)
        return

    # cat_budget_done
    if user_id in user_data:
        # Проверяем, есть ли у пользователя данные о путешествии
        if 'trip_id' in user_data[user_id]:
            trip_id = user_data[user_id]['trip_id']
            # Удаляем все данные пользователя
            del user_data[user_id]
            # Показываем сообщение о завершении
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Готово. Возвращаю в настройки бюджета."
            )
            bot.send_message(call.message.chat.id, "Настройки бюджета:", reply_markup=budget_settings_keyboard())
        else:
            # Если нет данных о путешествии, просто удаляем и возвращаем в меню
            del user_data[user_id]
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Готово. Возвращаю в настройки бюджета."
            )
            bot.send_message(call.message.chat.id, "Настройки бюджета:", reply_markup=budget_settings_keyboard())
    else:
        # Если нет данных пользователя, просто возвращаем в меню
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Готово. Возвращаю в настройки бюджета."
        )
        bot.send_message(call.message.chat.id, "Настройки бюджета:", reply_markup=budget_settings_keyboard())
    bot.answer_callback_query(call.id)


# Callback handler для выбора категории при установке бюджета
@bot.callback_query_handler(func=lambda call: call.from_user.id in user_data and (user_data[call.from_user.id].get('step') == 'select_category_for_budget' or 'select_category_for_budget' in str(user_data[call.from_user.id])))
def select_category_for_budget_callback(call):
    """
    Обработчик callback-запроса при выборе категории для установки бюджета.
    Запрашивает у пользователя сумму бюджета для выбранной категории.
    """
    user_id = call.from_user.id
    # Parse the category ID from callback data
    if call.data.startswith('cat_'):
        try:
            category_id = int(call.data.split('_')[1])
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id, "Ошибка: некорректный формат данных")
            return
    else:
        # Fallback in case of unexpected format
        bot.answer_callback_query(call.id, "Ошибка: некорректный формат данных")
        return
    
    # Проверяем наличие активного путешествия
    trip = get_user_active_trip(user_id)
    if not trip:
        bot.answer_callback_query(call.id, "Ошибка: активное путешествие не найдено")
        return
    
    # Получаем список категорий
    try:
        categories = database.get_all_categories()
        if category_id < 1 or category_id > len(categories):
            bot.answer_callback_query(call.id, "Ошибка: категория не найдена")
            return
        category_name = categories[category_id-1]['name']
    except (IndexError, TypeError):
        bot.answer_callback_query(call.id, "Ошибка: категория не найдена")
        return
    
    # Обновляем состояние пользователя: выбрали категорию, теперь ждём сумму
    # Проверяем, есть ли уже step, если нет, то создаём его
    if 'step' not in user_data[user_id]:
        user_data[user_id]['step'] = 'enter_budget_amount_for_category'
    else:
        user_data[user_id]['step'] = 'enter_budget_amount_for_category'
    user_data[user_id]['selected_category_id'] = category_id
    user_data[user_id]['trip_id'] = trip['trip_id']
    
    # Отвечаем на callback запрос
    bot.answer_callback_query(call.id, f"Выбрана категория: {category_name}")
    
    # Запрашиваем сумму бюджета
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=f"Введите сумму бюджета для категории '{category_name}' (в {trip['target_currency']}):"
    )


@bot.message_handler(func=lambda message: user_data.get(message.from_user.id, {}).get('step') == 'enter_budget_amount_for_category')
def process_category_budget_amount(message):
    """
    Обработчик ввода суммы бюджета для выбранной категории.
    Устанавливает бюджет для указанной категории в активном путешествии.
    """
    try:
        planned_amount = float(message.text.replace(',', '.'))
        user_id = message.from_user.id
        if user_id not in user_data or 'trip_id' not in user_data[user_id] or 'selected_category_id' not in user_data[user_id]:
            bot.send_message(message.chat.id, "Произошла ошибка при установке бюджета. Пожалуйста, начните заново.")
            return

        trip_id = user_data[user_id]['trip_id']
        category_id = user_data[user_id]['selected_category_id']
        
        # Получаем код валюты из активного путешествия
        trip = get_user_active_trip(user_id)
        if not trip:
            bot.send_message(message.chat.id, "Ошибка: активное путешествие не найдено. Начните заново.")
            if user_id in user_data:
                del user_data[user_id]
            return

        currency_code = trip['target_currency']
        
        # Устанавливаем бюджет для категории
        database.set_category_budget(trip_id, category_id, planned_amount, currency_code)
        
        # Получаем название категории
        categories = database.get_all_categories()
        category_name = categories[category_id-1]['name'] if 1 <= category_id <= len(categories) else "Категория"
            
        bot.send_message(message.chat.id, f"✅ Бюджет записан в категорию '{category_name}': {planned_amount:.2f} {currency_code}")
        
        # Очищаем step, чтобы кнопки работали правильно
        if user_id in user_data:
            # Сохраняем информацию о последней выбранной категории для правильной работы кнопок
            last_category_id = user_data[user_id].get('selected_category_id')
            last_trip_id = user_data[user_id].get('trip_id')
            del user_data[user_id]
            # Восстанавливаем необходимую информацию для следующего шага
            user_data[user_id] = {
                'step': 'select_category_for_budget',
                'trip_id': last_trip_id
            }
            
        # Предложим установить бюджет для другой категории (по желанию)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("➕ Другая категория", callback_data="cat_budget_again"))
        markup.add(types.InlineKeyboardButton("✅ Готово", callback_data="cat_budget_done"))
        bot.send_message(message.chat.id, "Хотите установить бюджет для другой категории?", reply_markup=markup)
        
    except ValueError:
        bot.send_message(message.chat.id, "Пожалуйста, введите число.")


if __name__ == "__main__":
    database.init_db() # Ensure tables exist
    database.ensure_category_id_column()  # Ensure category_id column exists
    database.update_all_old_expenses()  # Update all old expenses without category
    print("Бот запущен...")
    bot.infinity_polling()
