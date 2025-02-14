import sqlite3

def create_db():
    conn = sqlite3.connect('coffee_bot.db')
    cursor = conn.cursor()
    
    # Создание таблицы заказов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            fio TEXT,
            drink TEXT,
            sugar INTEGER,
            order_count INTEGER
        )
    ''')
    
    # Создание таблицы пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            fio TEXT,
            orders_count INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()


if __name__ == "__main__":
    create_db()
