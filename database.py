import sqlite3

def init_db():
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Table for users (optional, but good for tracking active trip)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        active_trip_id INTEGER
    )
    ''')
    
    # Table for trips
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trips (
        trip_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        home_currency TEXT,
        target_currency TEXT,
        exchange_rate REAL,
        home_balance REAL,
        target_balance REAL,
        budget_limit REAL DEFAULT 0.0,
        notification_threshold REAL DEFAULT 0.0,
        FOREIGN KEY(user_id) REFERENCES users(user_id)
    )
    ''')
    
    # Table for multiple currencies in a trip
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trip_currencies (
        currency_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id INTEGER,
        currency_code TEXT,
        balance REAL,
        exchange_rate_to_home REAL,
        FOREIGN KEY(trip_id) REFERENCES trips(trip_id)
    )
    ''')
    
    # Table for expense categories
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS expense_categories (
        category_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT
    )
    ''')
    
    # Insert default categories
    default_categories = [
        ("Транспорт", "Расходы на транспорт (автобус, метро, такси и т.д.)"),
        ("Жилье", "Расходы на проживание (отель, аренда и т.д.)"),
        ("Еда", "Расходы на питание (рестораны, продукты и т.д.)"),
        ("Развлечения", "Расходы на развлечения (музеи, экскурсии и т.д.)"),
        ("Покупки", "Расходы на покупки (сувениры, одежда и т.д.)"),
        ("Прочее", "Другие расходы")
    ]
    
    cursor.executemany('''
        INSERT OR IGNORE INTO expense_categories (name, description) 
        VALUES (?, ?)
    ''', default_categories)
    
    # Table for expenses
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS expenses (
        expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id INTEGER,
        amount_target REAL,
        amount_home REAL,
        currency_target TEXT,
        currency_home TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(trip_id) REFERENCES trips(trip_id)
    )
    ''')
    
    # Check if category_id column exists, if not - add it
    cursor.execute("PRAGMA table_info(expenses)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'category_id' not in columns:
        cursor.execute('ALTER TABLE expenses ADD COLUMN category_id INTEGER DEFAULT 6')
        # Also add foreign key constraint
        # Note: SQLite doesn't support ALTER TABLE ADD CONSTRAINT, so we need to recreate the table
        # But for now, just adding the column is sufficient
    
    # Make sure foreign key relationship is established
    # Create category_budgets table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS category_budgets (
        budget_id INTEGER PRIMARY KEY AUTOINCREMENT,
        trip_id INTEGER,
        category_id INTEGER,
        planned_amount REAL,
        spent_amount REAL DEFAULT 0.0,
        currency_code TEXT,
        FOREIGN KEY(trip_id) REFERENCES trips(trip_id),
        FOREIGN KEY(category_id) REFERENCES expense_categories(category_id)
    )
    ''')
    
    conn.commit()
    conn.close()


def get_all_categories():
    """Получить все доступные категории расходов"""
    conn = sqlite3.connect('travel_bot.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    categories = cursor.execute('SELECT * FROM expense_categories ORDER BY category_id').fetchall()
    conn.close()
    return [dict(cat) for cat in categories]


def update_all_old_expenses():
    """Обновить все старые расходы, у которых нет категории, установив им значение по умолчанию (Прочее - 6)"""
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Обновляем все расходы, у которых category_id равен NULL или пустой
    cursor.execute('''
        UPDATE expenses 
        SET category_id = 6 
        WHERE category_id IS NULL OR category_id = '' OR category_id = 0
    ''')
    
    conn.commit()
    conn.close()


def delete_trip(trip_id):
    """Удалить путешествие и все связанные с ним данные"""
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Удаляем все расходы, связанные с этим путешествием
    cursor.execute('DELETE FROM expenses WHERE trip_id = ?', (trip_id,))
    
    # Удаляем все валюты путешествия
    cursor.execute('DELETE FROM trip_currencies WHERE trip_id = ?', (trip_id,))
    
    # Удаляем все бюджеты по категориям для этого путешествия
    cursor.execute('DELETE FROM category_budgets WHERE trip_id = ?', (trip_id,))
    
    # Удаляем само путешествие
    cursor.execute('DELETE FROM trips WHERE trip_id = ?', (trip_id,))
    
    # Если это активное путешествие у пользователя, убираем его
    cursor.execute('UPDATE users SET active_trip_id = NULL WHERE active_trip_id = ?', (trip_id,))
    
    conn.commit()
    conn.close()


def get_trip_categories_with_budgets(trip_id):
    """Получить все категории с запланированными и потраченными суммами для конкретного путешествия"""
    conn = sqlite3.connect('travel_bot.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Получаем все категории с информацией о бюджете
    query = '''
    SELECT ec.category_id, ec.name, ec.description, 
           COALESCE(cb.planned_amount, 0) as planned_amount,
           COALESCE(cb.spent_amount, 0) as spent_amount,
           COALESCE(cb.currency_code, '') as currency_code
    FROM expense_categories ec
    LEFT JOIN category_budgets cb ON ec.category_id = cb.category_id AND cb.trip_id = ?
    ORDER BY ec.category_id
    '''
    result = cursor.execute(query, (trip_id,)).fetchall()
    
    conn.close()
    return [dict(row) for row in result]


def update_old_expenses_category(trip_id):
    """Обновить старые расходы, у которых нет категории (category_id), установив им значение по умолчанию (Прочее - 6)"""
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Обновляем все расходы в указанном путешествии, у которых category_id равен NULL или 0
    cursor.execute('''
        UPDATE expenses 
        SET category_id = 6 
        WHERE trip_id = ? AND (category_id IS NULL OR category_id = '' OR category_id = 0)
    ''', (trip_id,))
    
    conn.commit()
    conn.close()


def set_category_budget(trip_id, category_id, planned_amount, currency_code):
    """Установить бюджет для конкретной категории в путешествии"""
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Проверяем, существует ли уже бюджет для этой категории в этом путешествии
    existing = cursor.execute('''
        SELECT budget_id FROM category_budgets 
        WHERE trip_id = ? AND category_id = ?
    ''', (trip_id, category_id)).fetchone()
    
    if existing:
        # Обновляем существующий бюджет
        cursor.execute('''
            UPDATE category_budgets 
            SET planned_amount = ?, currency_code = ?
            WHERE trip_id = ? AND category_id = ?
        ''', (planned_amount, currency_code, trip_id, category_id))
    else:
        # Создаем новый бюджет
        cursor.execute('''
            INSERT INTO category_budgets (trip_id, category_id, planned_amount, currency_code)
            VALUES (?, ?, ?, ?)
        ''', (trip_id, category_id, planned_amount, currency_code))
    
    conn.commit()
    conn.close()


def add_expense_to_category(trip_id, category_id, amount_home, amount_target, currency_home, currency_target):
    """Добавить расход в определенную категорию и обновить потраченную сумму в бюджете"""
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Добавляем расход в таблицу expenses
    cursor.execute('''
        INSERT INTO expenses (trip_id, amount_target, amount_home, currency_target, currency_home, category_id)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (trip_id, amount_target, amount_home, currency_target, currency_home, category_id))
    
    # Обновляем потраченную сумму в бюджете категории
    cursor.execute('''
        UPDATE category_budgets 
        SET spent_amount = spent_amount + ?
        WHERE trip_id = ? AND category_id = ?
    ''', (amount_home, trip_id, category_id))
    
    # Если записи о бюджете категории нет, создаем её с нулевым планом
    cursor.execute('''
        INSERT OR IGNORE INTO category_budgets (trip_id, category_id, planned_amount, spent_amount, currency_code)
        VALUES (?, ?, 0, ?, ?)
    ''', (trip_id, category_id, amount_home, currency_home))
    
    conn.commit()
    conn.close()


def ensure_category_id_column():
    """Функция для обеспечения наличия столбца category_id в таблице expenses и обновления старых записей"""
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Проверяем, есть ли столбец category_id
    cursor.execute("PRAGMA table_info(expenses)")
    columns = [column[1] for column in cursor.fetchall()]
    
    if 'category_id' not in columns:
        # Добавляем столбец category_id со значением по умолчанию 6 (Прочее)
        cursor.execute('ALTER TABLE expenses ADD COLUMN category_id INTEGER DEFAULT 6')
    
    # Обновляем все старые записи, у которых category_id равен NULL
    cursor.execute('''
        UPDATE expenses 
        SET category_id = 6 
        WHERE category_id IS NULL OR category_id = ''
    ''')
    
    conn.commit()
    conn.close()


def get_expenses_by_category(trip_id, category_id=None):
    """Получить расходы по категориям для конкретного путешествия"""
    conn = sqlite3.connect('travel_bot.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if category_id:
        # Получаем расходы по конкретной категории
        query = '''
        SELECT e.*, ec.name as category_name
        FROM expenses e
        LEFT JOIN expense_categories ec ON e.category_id = ec.category_id
        WHERE e.trip_id = ? AND e.category_id = ?
        ORDER BY e.timestamp DESC
        '''
        result = cursor.execute(query, (trip_id, category_id)).fetchall()
    else:
        # Получаем расходы по всем категориям
        query = '''
        SELECT e.*, ec.name as category_name
        FROM expenses e
        LEFT JOIN expense_categories ec ON e.category_id = ec.category_id
        WHERE e.trip_id = ?
        ORDER BY e.timestamp DESC
        '''
        result = cursor.execute(query, (trip_id,)).fetchall()
    
    conn.close()
    return [dict(row) for row in result]


def reset_category_spending(trip_id):
    """Сбросить потраченные суммы для всех категорий в путешествии (используется при изменении курса и пересчете)"""
    conn = sqlite3.connect('travel_bot.db')
    cursor = conn.cursor()
    
    # Сбрасываем все потраченные суммы в бюджете категорий для данного путешествия
    cursor.execute('''
        UPDATE category_budgets 
        SET spent_amount = 0.0
        WHERE trip_id = ?
    ''', (trip_id,))
    
    # Пересчитываем потраченные суммы на основе существующих расходов
    # Получаем сумму расходов по каждой категории
    sums = cursor.execute('''
        SELECT category_id, SUM(amount_home) as total_spent
        FROM expenses
        WHERE trip_id = ? AND category_id IS NOT NULL
        GROUP BY category_id
    ''', (trip_id,)).fetchall()
    
    # Обновляем значения в бюджете категорий
    for sum_row in sums:
        if sum_row[0] is not None:  # Убедиться, что category_id не равен NULL
            cursor.execute('''
                UPDATE category_budgets 
                SET spent_amount = ?
                WHERE trip_id = ? AND category_id = ?
            ''', (sum_row[1], trip_id, sum_row[0]))
    
    conn.commit()
    conn.close()


def get_expense_by_id(expense_id):
    """Получить расход по ID"""
    conn = sqlite3.connect('travel_bot.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    expense = cursor.execute('''
        SELECT e.*, ec.name as category_name
        FROM expenses e
        LEFT JOIN expense_categories ec ON e.category_id = ec.category_id
        WHERE e.expense_id = ?
    ''', (expense_id,)).fetchone()
    
    conn.close()
    return dict(expense) if expense else None


def update_expense(expense_id, new_amount_home, new_amount_target, new_category_id):
    """Обновить расход и пересчитать балансы и бюджеты категорий"""
    conn = sqlite3.connect('travel_bot.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Получаем старый расход
    old_expense = cursor.execute('SELECT * FROM expenses WHERE expense_id = ?', (expense_id,)).fetchone()
    if not old_expense:
        conn.close()
        return False
    
    old_expense = dict(old_expense)
    
    trip_id = old_expense['trip_id']
    old_amount_home = old_expense['amount_home']
    old_amount_target = old_expense['amount_target']
    old_category_id = old_expense['category_id']
    currency_target = old_expense['currency_target']
    currency_home = old_expense['currency_home']
    
    # Обновляем расход
    cursor.execute('''
        UPDATE expenses 
        SET amount_home = ?, amount_target = ?, category_id = ?
        WHERE expense_id = ?
    ''', (new_amount_home, new_amount_target, new_category_id, expense_id))
    
    # Обновляем потраченную сумму в бюджете старой категории (вычитаем старую сумму)
    cursor.execute('''
        UPDATE category_budgets 
        SET spent_amount = spent_amount - ?
        WHERE trip_id = ? AND category_id = ?
    ''', (old_amount_home, trip_id, old_category_id))
    
    # Обновляем потраченную сумму в бюджете новой категории (добавляем новую сумму)
    cursor.execute('''
        UPDATE category_budgets 
        SET spent_amount = spent_amount + ?
        WHERE trip_id = ? AND category_id = ?
    ''', (new_amount_home, trip_id, new_category_id))
    
    # Если записи о бюджете новой категории нет, создаем её
    cursor.execute('''
        INSERT OR IGNORE INTO category_budgets (trip_id, category_id, planned_amount, spent_amount, currency_code)
        VALUES (?, ?, 0, ?, ?)
    ''', (trip_id, new_category_id, new_amount_home, currency_home))
    
    # Получаем информацию о путешествии
    trip = cursor.execute('SELECT * FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
    if trip:
        trip = dict(zip([col[0] for col in cursor.description], trip))
        
        # Обновляем балансы путешествия (возвращаем старую сумму, вычитаем новую)
        if currency_target == trip['target_currency']:
            new_target_balance = trip['target_balance'] + old_amount_target - new_amount_target
            new_home_balance = trip['home_balance'] + old_amount_home - new_amount_home
            cursor.execute('''
                UPDATE trips 
                SET target_balance = ?, home_balance = ?
                WHERE trip_id = ?
            ''', (new_target_balance, new_home_balance, trip_id))
    
    # Обновляем балансы в trip_currencies если используется мультивалютность
    currency_row = cursor.execute('''
        SELECT * FROM trip_currencies WHERE trip_id = ? AND currency_code = ?
    ''', (trip_id, currency_target)).fetchone()
    
    if currency_row:
        currency_row = dict(zip([col[0] for col in cursor.description], currency_row))
        new_balance = currency_row['balance'] + old_amount_target - new_amount_target
        cursor.execute('''
            UPDATE trip_currencies 
            SET balance = ?
            WHERE currency_id = ?
        ''', (new_balance, currency_row['currency_id']))
    
    conn.commit()
    conn.close()
    return True


def delete_expense(expense_id):
    """Удалить расход и пересчитать балансы и бюджеты категорий"""
    conn = sqlite3.connect('travel_bot.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Получаем расход перед удалением
    expense = cursor.execute('SELECT * FROM expenses WHERE expense_id = ?', (expense_id,)).fetchone()
    if not expense:
        conn.close()
        return False
    
    expense = dict(expense)
    
    trip_id = expense['trip_id']
    amount_home = expense['amount_home']
    amount_target = expense['amount_target']
    category_id = expense['category_id']
    currency_target = expense['currency_target']
    
    # Удаляем расход
    cursor.execute('DELETE FROM expenses WHERE expense_id = ?', (expense_id,))
    
    # Обновляем потраченную сумму в бюджете категории (вычитаем сумму)
    cursor.execute('''
        UPDATE category_budgets 
        SET spent_amount = spent_amount - ?
        WHERE trip_id = ? AND category_id = ?
    ''', (amount_home, trip_id, category_id))
    
    # Получаем информацию о путешествии
    trip = cursor.execute('SELECT * FROM trips WHERE trip_id = ?', (trip_id,)).fetchone()
    if trip:
        trip = dict(trip)
        
        # Возвращаем балансы путешествия
        if currency_target == trip['target_currency']:
            new_target_balance = trip['target_balance'] + amount_target
            new_home_balance = trip['home_balance'] + amount_home
            cursor.execute('''
                UPDATE trips 
                SET target_balance = ?, home_balance = ?
                WHERE trip_id = ?
            ''', (new_target_balance, new_home_balance, trip_id))
    
    # Обновляем балансы в trip_currencies если используется мультивалютность
    currency_row = cursor.execute('''
        SELECT * FROM trip_currencies WHERE trip_id = ? AND currency_code = ?
    ''', (trip_id, currency_target)).fetchone()
    
    if currency_row:
        currency_row = dict(currency_row)
        new_balance = currency_row['balance'] + amount_target
        cursor.execute('''
            UPDATE trip_currencies 
            SET balance = ?
            WHERE currency_id = ?
        ''', (new_balance, currency_row['currency_id']))
    
    conn.commit()
    conn.close()
    return True


if __name__ == "__main__":
    init_db()
    print("Database initialized.")
