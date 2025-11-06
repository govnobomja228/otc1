import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from telegram.error import NetworkError, BadRequest
import uuid
import logging
import asyncio
import os

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Конфигурация
BOT_TOKEN = os.environ.get('BOT_TOKEN', "8464403655:AAGTZPYm8F9hjiLWJVpJJnXgrS2e4ytkMdU")
SUPER_ADMIN_IDS = {8405627314, 8424970062}
DEPOSIT_TON_ADDRESS = "UQAcCNRAk9Swq5-P9px5gOW58RRHim4-Ok6vWgYjQI03qTAt"
ADMIN_CHAT_ID = -5097403821
WITHDRAWAL_THRESHOLD = {}
SUCCESSFUL_DEALS_THRESHOLD = 3
user_data = {}
deals = {}
ADMIN_ID = set()
DB_NAME = 'bot_data.db'

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            ton_wallet TEXT,
            balance_ton REAL DEFAULT 0.0,
            balance_rub REAL DEFAULT 0.0,
            balance_stars REAL DEFAULT 0.0,
            successful_deals INTEGER DEFAULT 0,
            lang TEXT DEFAULT 'ru',
            granted_by INTEGER,
            is_admin INTEGER DEFAULT 0
        )
    ''')

    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    for col in ['ton_wallet', 'balance_ton', 'balance_rub', 'balance_stars', 'lang', 'granted_by', 'is_admin']:
        if col not in columns:
            col_type = 'TEXT' if col in ['ton_wallet', 'lang'] else 'REAL DEFAULT 0.0' if col.startswith('balance_') else 'INTEGER'
            cursor.execute(f'ALTER TABLE users ADD COLUMN {col} {col_type}')

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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            deal_id TEXT,
            seller_id INTEGER,
            buyer_id INTEGER,
            description TEXT,
            amount REAL,
            valute TEXT,
            timestamp TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_requests (
            request_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            currency TEXT,
            requisites TEXT,
            status TEXT,
            timestamp TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_thresholds (
            user_id INTEGER,
            currency TEXT,
            threshold REAL,
            PRIMARY KEY (user_id, currency)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deal_thresholds (
            threshold INTEGER DEFAULT 3
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount REAL,
            valute TEXT,
            screenshot_file_id TEXT,
            timestamp TEXT
        )
    ''')

    cursor.execute('SELECT threshold FROM deal_thresholds LIMIT 1')
    if not cursor.fetchone():
        cursor.execute('INSERT INTO deal_thresholds (threshold) VALUES (?)', (SUCCESSFUL_DEALS_THRESHOLD,))
    conn.commit()
    conn.close()

def load_data():
    global ADMIN_ID, SUCCESSFUL_DEALS_THRESHOLD
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('SELECT user_id, ton_wallet, balance_ton, balance_rub, balance_stars, successful_deals, lang, granted_by, is_admin FROM users')
    for row in cursor.fetchall():
        user_id, ton_wallet, balance_ton, balance_rub, balance_stars, successful_deals, lang, granted_by, is_admin = row
        user_data[user_id] = {
            'ton_wallet': ton_wallet or '',
            'balance_ton': balance_ton or 0.0,
            'balance_rub': balance_rub or 0.0,
            'balance_stars': balance_stars or 0.0,
            'successful_deals': successful_deals or 0,
            'lang': lang or 'ru',
            'granted_by': granted_by,
            'is_admin': is_admin or 0
        }
        if is_admin:
            ADMIN_ID.add(user_id)

    for super_admin_id in SUPER_ADMIN_IDS:
        if super_admin_id not in user_data:
            user_data[super_admin_id] = {
                'ton_wallet': '',
                'balance_ton': 0.0,
                'balance_rub': 0.0,
                'balance_stars': 0.0,
                'successful_deals': 0,
                'lang': 'ru',
                'granted_by': None,
                'is_admin': 1
            }
            ADMIN_ID.add(super_admin_id)
            save_user_data(super_admin_id)
        elif not user_data[super_admin_id].get('is_admin'):
            user_data[super_admin_id]['is_admin'] = 1
            ADMIN_ID.add(super_admin_id)
            save_user_data(super_admin_id)

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

    cursor.execute('SELECT user_id, currency, threshold FROM withdrawal_thresholds')
    for row in cursor.fetchall():
        user_id, currency, threshold = row
        if user_id not in WITHDRAWAL_THRESHOLD:
            WITHDRAWAL_THRESHOLD[user_id] = {}
        WITHDRAWAL_THRESHOLD[user_id][currency] = threshold or 0.0

    cursor.execute('SELECT threshold FROM deal_thresholds LIMIT 1')
    result = cursor.fetchone()
    if result:
        SUCCESSFUL_DEALS_THRESHOLD = result[0]

    conn.close()
    logger.info(f"Loaded administrators: {ADMIN_ID}, Successful deals threshold: {SUCCESSFUL_DEALS_THRESHOLD}")

def save_user_data(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    user = user_data.get(user_id, {})
    cursor.execute('''
        INSERT OR REPLACE INTO users (
            user_id, ton_wallet, balance_ton, balance_rub, balance_stars,
            successful_deals, lang, granted_by, is_admin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        user.get('ton_wallet', ''),
        user.get('balance_ton', 0.0),
        user.get('balance_rub', 0.0),
        user.get('balance_stars', 0.0),
        user.get('successful_deals', 0),
        user.get('lang', 'ru'),
        user.get('granted_by'),
        user.get('is_admin', 0)
    ))
    conn.commit()
    conn.close()

def save_deal(deal_id):
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

def save_notification(deal_id, seller_id, buyer_id, description, amount, valute):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO notifications (
            deal_id, seller_id, buyer_id, description, amount, valute, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    ''', (deal_id, seller_id, buyer_id, description, amount, valute))
    conn.commit()
    conn.close()

def save_withdrawal_request(user_id, amount, currency, requisites):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO withdrawal_requests (
            user_id, amount, currency, requisites, status, timestamp
        ) VALUES (?, ?, ?, ?, 'pending', datetime('now'))
    ''', (user_id, amount, currency, requisites))
    request_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return request_id

def save_withdrawal_threshold(user_id, currency, threshold):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO withdrawal_thresholds (user_id, currency, threshold)
        VALUES (?, ?, ?)
    ''', (user_id, currency, threshold))
    conn.commit()
    conn.close()

def save_deal_threshold(threshold):
    global SUCCESSFUL_DEALS_THRESHOLD
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('UPDATE deal_thresholds SET threshold = ?', (threshold,))
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO deal_thresholds (threshold) VALUES (?)', (threshold,))
    conn.commit()
    conn.close()
    SUCCESSFUL_DEALS_THRESHOLD = threshold

def ensure_user_exists(user_id):
    if user_id not in user_data:
        user_data[user_id] = {
            'ton_wallet': '',
            'balance_ton': 0.0,
            'balance_rub': 0.0,
            'balance_stars': 0.0,
            'successful_deals': 0,
            'lang': 'ru',
            'granted_by': None,
            'is_admin': 1 if user_id in SUPER_ADMIN_IDS else 0
        }
        if user_id in SUPER_ADMIN_IDS:
            ADMIN_ID.add(user_id)
        save_user_data(user_id)

async def _display_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int, lang: str, message_id: int = None):
    try:
        from messages import get_text
    except ImportError:
        # Fallback если messages.py не загружен
        def get_text(lang, key, **kwargs):
            texts = {
                'ru': {
                    "create_deal_button": "📝 Создать сделку",
                    "add_wallet_button": "💰 Добавить кошелёк",
                    "balance_button": "📈 Баланс",
                    "referral_button": "🤝 Рефералка",
                    "change_lang_button": "🌍 Язык",
                    "support_button": "💬 Поддержка",
                    "start_message": "Добро пожаловать в бота!",
                    "menu_button": "🏠 В главное меню"
                },
                'en': {
                    "create_deal_button": "📝 Create Deal",
                    "add_wallet_button": "💰 Add Wallet",
                    "balance_button": "📈 Balance",
                    "referral_button": "🤝 Referral",
                    "change_lang_button": "🌍 Language",
                    "support_button": "💬 Support",
                    "start_message": "Welcome to the bot!",
                    "menu_button": "🏠 Main Menu"
                }
            }
            return texts.get(lang, texts['ru']).get(key, key)
    
    keyboard = [
        [InlineKeyboardButton(get_text(lang, "create_deal_button"), callback_data='create_deal')],
        [InlineKeyboardButton(get_text(lang, "add_wallet_button"), callback_data='wallet_menu')],
        [InlineKeyboardButton(get_text(lang, "balance_button"), callback_data='view_balance')],
        [InlineKeyboardButton(get_text(lang, "referral_button"), callback_data='referral')],
        [InlineKeyboardButton(get_text(lang, "change_lang_button"), callback_data='change_lang')],
        [InlineKeyboardButton(get_text(lang, "support_button"), callback_data='support')],
    ]
    if user_id in ADMIN_ID:
        keyboard.append([InlineKeyboardButton("🔧 Админка", callback_data='admin_panel')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    caption = get_text(lang, "start_message")
    photo_url = "https://postimg.cc/4mDVrwJY"

    try:
        if message_id:
            await context.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_photo(
                chat_id,
                photo=photo_url,
                caption=caption,
                parse_mode="HTML",
                reply_markup=reply_markup
            )
    except BadRequest as e:
        logger.warning(f"Failed to edit message caption: {e}")
        await context.bot.send_photo(
            chat_id,
            photo=photo_url,
            caption=caption,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    ensure_user_exists(user_id)
    lang = user_data[user_id]['lang']
    args = context.args

    try:
        if args and args[0] in deals:
            deal_id = args[0]
            deal = deals.get(deal_id)
            if not deal:
                logger.warning(f"Deal {deal_id} not found in deals")
                await context.bot.send_message(
                    chat_id,
                    f"Сделка #{deal_id} не найдена.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                return

            seller_id = deal['seller_id']
            logger.info(f"Processing deal {deal_id} for user {user_id}")

            try:
                seller_chat = await context.bot.get_chat(seller_id)
                seller_username = seller_chat.username or "Не указан"
            except Exception as e:
                logger.error(f"Could not get chat for seller_id {seller_id}: {e}")
                seller_username = "Не указан"

            deals[deal_id]['buyer_id'] = user_id
            deals[deal_id]['status'] = 'active'
            save_deal(deal_id)

            payment_method = deal.get('payment_method', 'ton')
            if payment_method == 'ton':
                payment_details = DEPOSIT_TON_ADDRESS
            elif payment_method == 'stars':
                payment_details = f"/pay @{context.bot.username} {deal['amount']}"
            else:
                payment_details = "Не указано"

            memo = f"Deal #{deal_id}"

            # Упрощенное сообщение о сделке
            deal_message = f"""
💳 Информация о сделке #{deal_id}
👤 Вы покупатель в сделке.
📌 Продавец: @{seller_username}
• Успешные сделки: {user_data.get(seller_id, {}).get('successful_deals', 0)}
• Вы покупаете: {deal['description']}
🏦 Адрес для оплаты: <code>{payment_details}</code>
💰 Сумма к оплате: {deal['amount']} {payment_method.upper()}
📝 Комментарий к платежу: <code>{deal_id}</code>
⚠️ Убедитесь в правильности данных перед оплатой!
            """

            await context.bot.send_message(
                chat_id,
                deal_message,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Оплатить с баланса", callback_data=f'pay_from_balance_{deal_id}')],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
                ])
            )

            try:
                buyer_chat = await context.bot.get_chat(user_id)
                buyer_username = buyer_chat.username or "Не указан"
            except Exception as e:
                logger.error(f"Could not get chat for buyer_id {user_id}: {e}")
                buyer_username = "Не указан"

            await context.bot.send_message(
                seller_id,
                f"🔔 Новый покупатель для сделки #{deal_id}!\nПокупатель: @{buyer_username} ({user_data.get(user_id, {}).get('successful_deals', 0)} успешных сделок)",
                parse_mode="HTML"
            )

            try:
                await context.bot.send_message(
                    ADMIN_CHAT_ID,
                    f"📝 Новая сделка #{deal_id}\n\nПродавец: @{seller_username} (ID: {seller_id})\nПокупатель: @{buyer_username} (ID: {user_id})\nОписание: {deal['description']}\nСумма: {deal['amount']} {payment_method.upper()}",
                    parse_mode="HTML"
                )
                save_notification(deal_id, seller_id, user_id, deal['description'], deal['amount'], payment_method.upper())
            except Exception as e:
                logger.error(f"Failed to send new deal notification to admin chat {ADMIN_CHAT_ID}: {e}")
        else:
            await _display_main_menu(update, context, chat_id, user_id, lang)
    except (NetworkError, BadRequest) as e:
        logger.error(f"Telegram API error in start: {e}", exc_info=True)
        await context.bot.send_message(chat_id, "🚫 Ошибка сети. Попробуйте снова.", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error in start: {e}", exc_info=True)
        await context.bot.send_message(chat_id, "🚫 Произошла ошибка. Попробуйте снова.", parse_mode="HTML")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.message:
        logger.warning("No callback query or message")
        if query:
            await query.answer()
        return

    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data
    lang = user_data.get(user_id, {}).get('lang', 'ru')

    try:
        await query.answer()
        logger.info(f"Callback received: {data} from user {user_id}")

        ensure_user_exists(user_id)

        if data == 'menu':
            context.user_data.clear()
            await _display_main_menu(update, context, chat_id, user_id, lang, query.message.message_id)
            return

        elif data == 'wallet_menu':
            keyboard = [
                [InlineKeyboardButton("➕ Добавить TON-кошелек", callback_data='add_ton_wallet')],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
            ]
            await query.edit_message_caption(
                caption="Выберите тип кошелька для добавления:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'add_ton_wallet':
            current_wallet = user_data.get(user_id, {}).get('ton_wallet') or "Не указан"
            await query.edit_message_caption(
                caption=f"💳 Ваш текущий TON-кошелек: <code>{current_wallet}</code>\n\nВведите новый адрес TON-кошелька или вернитесь в меню:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )
            context.user_data['awaiting_ton_wallet'] = True

        elif data == 'create_deal':
            if not user_data[user_id].get('ton_wallet'):
                await query.edit_message_caption(
                    caption="🚫 У вас не указаны реквизиты для получения платежей. Пожалуйста, добавьте кошелек.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("💰 Добавить кошелёк", callback_data='wallet_menu')],
                        [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
                    ])
                )
                return
            keyboard = [
                [InlineKeyboardButton("💎 TON/USDT", callback_data='payment_method_ton')],
                [InlineKeyboardButton("🌟 Звезды", callback_data='payment_method_stars')],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
            ]
            await query.edit_message_caption(
                caption="💰 Выберите метод получения оплаты:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data.startswith('payment_method_'):
            payment_method = data.split('_')[-1]
            context.user_data['payment_method'] = payment_method
            valute = "TON" if payment_method == "ton" else "XTR"
            await query.edit_message_caption(
                caption=f"Введите сумму сделки в {valute}:\n\nПример: <code>1.5</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )
            context.user_data['awaiting_amount'] = True

        elif data.startswith('pay_from_balance_'):
            deal_id = data.split('_')[-1]
            deal = deals.get(deal_id)
            if not deal:
                logger.warning(f"Deal {deal_id} not found in deals")
                await query.message.reply_text(
                    f"Сделка #{deal_id} не найдена.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                return

            payment_method = deal.get('payment_method', 'ton')
            amount = deal['amount']
            buyer_id = user_id
            
            if payment_method == 'ton':
                balance = user_data.get(buyer_id, {}).get('balance_ton', 0.0)
            elif payment_method == 'stars':
                balance = user_data.get(buyer_id, {}).get('balance_stars', 0.0)
            else:
                balance = 0.0

            logger.info(f"Processing payment for deal {deal_id}, method: {payment_method}, amount: {amount}, buyer: {buyer_id}")

            if balance < amount:
                await query.message.reply_text(
                    f"🚫 Недостаточно средств на балансе. Требуется: {amount} {payment_method.upper()}, доступно: {balance} {payment_method.upper()}.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                return

            if payment_method == 'ton':
                user_data[buyer_id]['balance_ton'] -= amount
            elif payment_method == 'stars':
                user_data[buyer_id]['balance_stars'] -= amount
            save_user_data(buyer_id)

            deals[deal_id]['status'] = 'confirmed'
            save_deal(deal_id)

            await query.message.reply_text(
                f"✅ Оплата по сделке #{deal_id} на сумму {amount} {payment_method.upper()} успешно выполнена!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )

            seller_id = deal['seller_id']
            try:
                seller_chat = await context.bot.get_chat(seller_id)
                seller_username = seller_chat.username or "Не указан"
            except Exception as e:
                logger.error(f"Could not get chat for seller_id {seller_id}: {e}")
                seller_username = "Не указан"
            
            await context.bot.send_message(
                seller_id,
                f"✅ Оплата подтверждена для сделки #{deal_id}\n\n📜 Описание: {deal['description']}\n👤 Отправьте подарок покупателю — @Ether_Weave\n\n⚠️ Отправляйте подарок только указанному пользователю.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Подтвердить отправку", callback_data=f'seller_confirm_sent_{deal_id}')],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
                ])
            )

            try:
                buyer_chat = await context.bot.get_chat(buyer_id)
                buyer_username = buyer_chat.username or "Не указан"
                await context.bot.send_message(
                    ADMIN_CHAT_ID,
                    f"Оплата по сделке #{deal_id} подтверждена.\nПродавец: @{seller_username}\nПокупатель: @{buyer_username}\nСумма: {amount} {payment_method.upper()}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to send payment confirmation to admin chat {ADMIN_CHAT_ID}: {e}")

        elif data == 'deposit_balance':
            keyboard = [
                [InlineKeyboardButton("TON/USDT", callback_data="deposit_currency_ton")],
                [InlineKeyboardButton("Звезды", callback_data="deposit_currency_stars")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
            ]
            await query.edit_message_caption(
                caption="Выберите валюту для пополнения:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data.startswith('deposit_currency_'):
            valute = data.split('_')[-1]
            context.user_data['current_deposit_valute'] = valute
            if valute == 'ton':
                await query.edit_message_caption(
                    caption=f"Введите сумму пополнения в TON:\n\nАдрес для пополнения:\n<code>{DEPOSIT_TON_ADDRESS}</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
            elif valute == 'stars':
                await query.edit_message_caption(
                    caption="Введите сумму пополнения в XTR:\n\nСледуйте инструкциям для пополнения через Telegram Stars.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
            context.user_data['awaiting_deposit_amount'] = True

        elif data.startswith('withdraw_currency_'):
            valute = data.split('_')[-1]
            context.user_data['current_withdraw_valute'] = valute
            await query.edit_message_caption(
                caption=f"Введите сумму для вывода в {valute.upper()}:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )
            context.user_data['awaiting_withdraw_amount'] = True

        elif data == 'withdraw_balance':
            keyboard = [
                [InlineKeyboardButton("TON/USDT", callback_data="withdraw_currency_ton")],
                [InlineKeyboardButton("Звезды", callback_data="withdraw_currency_stars")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
            ]
            await query.edit_message_caption(
                caption="Выберите валюту для вывода:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == 'view_balance':
            try:
                ton_balance = user_data.get(user_id, {}).get('balance_ton', 0.0)
                stars_balance = user_data.get(user_id, {}).get('balance_stars', 0.0)
                keyboard = [
                    [InlineKeyboardButton("📥 Пополнить баланс", callback_data='deposit_balance')],
                    [InlineKeyboardButton("📤 Вывести баланс", callback_data='withdraw_balance')],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
                ]
                caption = f"💰 Ваш баланс:\nТон: {ton_balance}\nРубли: 0\nЗвезды: {stars_balance}"
                await query.edit_message_caption(
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                logger.warning(f"Failed to edit message caption: {e}")
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo="https://postimg.cc/4mDVrwJY",
                    caption=caption,
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Error displaying balance for user {user_id}: {e}")
                await query.edit_message_caption(
                    caption="🚫 Ошибка при отображении баланса.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )

        elif data == 'referral':
            bot_info = await context.bot.get_me()
            referral_link = f"https://t.me/{bot_info.username}?start={user_id}"
            await query.edit_message_caption(
                caption=f"🤝 Ваша реферальная ссылка:\n{referral_link}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )

        elif data == 'change_lang':
            keyboard = [
                [InlineKeyboardButton("Русский", callback_data="set_lang_ru")],
                [InlineKeyboardButton("English", callback_data="set_lang_en")],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
            ]
            await query.edit_message_caption(
                caption="Выберите язык:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data.startswith('set_lang_'):
            new_lang = data.split('_')[-1]
            user_data[user_id]['lang'] = new_lang
            save_user_data(user_id)
            await query.edit_message_caption(
                caption="✅ Язык изменен.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )

        elif data == 'support':
            await query.edit_message_caption(
                caption="💬 Напишите ваше сообщение для тех-поддержки:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )
            context.user_data['awaiting_support_message'] = True

        elif data == 'admin_panel' and user_id in ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("📋 Просмотр сделок", callback_data='admin_view_deals_1')],
                [InlineKeyboardButton("💰 Изменить баланс", callback_data='admin_change_balance')],
                [InlineKeyboardButton("👑 Изменить успешные сделки", callback_data='admin_change_successful_deals')],
                [InlineKeyboardButton("🛡️ Управление админами", callback_data='admin_manage_admins')],
                [InlineKeyboardButton("⚙️ Установить порог вывода", callback_data='admin_set_threshold')],
                [InlineKeyboardButton("👑 Установить порог сделок", callback_data='admin_set_deal_threshold')],
                [InlineKeyboardButton("📜 Список админов", callback_data='admin_list')],
                [InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]
            ]
            await query.edit_message_caption(
                caption="⚙️ Админ-панель:",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data.startswith('seller_confirm_sent_'):
            deal_id = data.split('_')[-1]
            deal = deals.get(deal_id)
            if not deal or deal['seller_id'] != user_id:
                await query.message.reply_text(
                    f"Сделка #{deal_id} не найдена.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                return

            if deal['status'] == 'sent':
                await query.answer("Вы уже подтвердили отправку подарка!", show_alert=True)
                return

            deals[deal_id]['status'] = 'sent'
            save_deal(deal_id)

            try:
                await context.bot.send_message(
                    ADMIN_CHAT_ID,
                    f'🔔 Продавец @{(await context.bot.get_chat(user_id)).username or "Не указан"} подтвердил отправку подарка по сделке #{deal_id}.\nПокупатель ID: {deal["buyer_id"]}\nСумма: {deal["amount"]} {deal["payment_method"].upper()}\n\nПожалуйста, подтвердите получение подарка @Ether_Weave',
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Подтвердить получение подарка", callback_data=f'admin_confirm_gift_{deal_id}')],
                        [InlineKeyboardButton("❌ Отклонить сделку", callback_data=f'admin_cancel_deal_{deal_id}')]
                    ])
                )
                
                await query.message.reply_text(
                    f"✅ Вы подтвердили отправку по сделке #{deal_id}. Ожидайте подтверждения получения от покупателя.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                
                await query.edit_message_reply_markup(reply_markup=None)
                
            except Exception as e:
                logger.error(f"Error processing seller confirmation for deal {deal_id}: {e}")

        elif data.startswith('admin_confirm_gift_'):
            deal_id = data.split('_')[-1]
            deal = deals.get(deal_id)
            if not deal:
                await query.message.reply_text(
                    f"Сделка #{deal_id} не найдена.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                return

            deals[deal_id]['status'] = 'completed'
            seller_id = deal['seller_id']
            
            if deal["payment_method"] == 'ton':
                user_data[seller_id]['balance_ton'] += deal['amount']
            elif deal["payment_method"] == 'stars':
                user_data[seller_id]['balance_stars'] += deal['amount']
                
            user_data[seller_id]['successful_deals'] += 1
            user_data[deal['buyer_id']]['successful_deals'] += 1
            save_user_data(seller_id)
            save_user_data(deal['buyer_id'])
            save_deal(deal_id)

            try:
                await context.bot.send_message(
                    seller_id,
                    f"✅ Сделка #{deal_id} завершена. Спасибо за сотрудничество!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                
                await context.bot.send_message(
                    deal['buyer_id'],
                    f"✅ Сделка #{deal_id} завершена. Спасибо за покупку!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                
                await query.message.reply_text(
                    f"✅ Сделка #{deal_id} завершена! Подарок получен.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                
                await query.edit_message_reply_markup(reply_markup=None)
                
            except Exception as e:
                logger.error(f"Error processing admin gift confirmation for deal {deal_id}: {e}")

    except Exception as e:
        logger.error(f"Error in handle_callback_query: {e}", exc_info=True)
        await query.message.reply_text(
            "🚫 Произошла ошибка. Попробуйте снова.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
        )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    text = update.message.text if update.message.text else ""
    lang = user_data.get(user_id, {}).get('lang', 'ru')

    ensure_user_exists(user_id)

    try:
        if context.user_data.get('awaiting_ton_wallet'):
            user_data[user_id]['ton_wallet'] = text.strip()
            save_user_data(user_id)
            context.user_data.clear()
            await update.message.reply_text(
                f"✅ TON-кошелек успешно обновлен: <code>{text.strip()}</code>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )

        elif context.user_data.get('awaiting_amount'):
            try:
                amount = float(text.strip())
                if amount <= 0:
                    raise ValueError("Amount must be positive")
                context.user_data['deal_amount'] = amount
                context.user_data['awaiting_amount'] = False
                context.user_data['awaiting_description'] = True
                await update.message.reply_text(
                    "Введите описание сделки:\n\nПример: <code>Кепочка и Мила</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
            except ValueError:
                await update.message.reply_text(
                    "🚫 Сумма должна быть числом больше 0, а также не содержать буквенные символы, только цифры.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )

        elif context.user_data.get('awaiting_description'):
            description = text.strip()
            amount = context.user_data.get('deal_amount')
            payment_method = context.user_data.get('payment_method', 'ton')
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

            bot_info = await context.bot.get_me()
            deal_link = f"https://t.me/{bot_info.username}?start={deal_id}"
            await update.message.reply_text(
                f"✅ Сделка создана!\n\nСумма: {amount} {payment_method.upper()}\nОписание: {description}\n\nСсылка на сделку: {deal_link}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )

        elif context.user_data.get('awaiting_deposit_amount'):
            try:
                amount = float(text.strip())
                if amount <= 0:
                    raise ValueError("Amount must be positive")
                valute = context.user_data.get('current_deposit_valute', 'ton')
                
                await update.message.reply_text(
                    "📸 Пожалуйста, отправьте скриншот перевода.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                context.user_data['awaiting_deposit_screenshot'] = True
                context.user_data['deposit_amount'] = amount
                
            except ValueError:
                await update.message.reply_text(
                    "🚫 Сумма пополнения должна быть числом больше 0.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )

        elif context.user_data.get('awaiting_withdraw_amount'):
            try:
                amount = float(text.strip())
                if amount <= 0:
                    raise ValueError("Amount must be positive")
                valute = context.user_data.get('current_withdraw_valute', 'ton')
                
                # Проверка баланса
                if valute == 'ton':
                    balance = user_data.get(user_id, {}).get('balance_ton', 0.0)
                else:
                    balance = user_data.get(user_id, {}).get('balance_stars', 0.0)
                    
                if balance < amount:
                    await update.message.reply_text(
                        f"🚫 Недостаточно средств на балансе. Доступно: {balance} {valute.upper()}",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                    )
                    return
                    
                # Проверка успешных сделок
                if user_data[user_id]['successful_deals'] < SUCCESSFUL_DEALS_THRESHOLD:
                    await update.message.reply_text(
                        f"🚫 Для вывода необходимо минимум {SUCCESSFUL_DEALS_THRESHOLD} успешных сделок. У вас {user_data[user_id]['successful_deals']} сделок.",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                    )
                    return
                
                context.user_data['withdraw_amount'] = amount
                context.user_data['awaiting_withdraw_amount'] = False
                context.user_data['awaiting_withdraw_requisites'] = True
                
                requisite_type = "TON-кошелек" if valute == 'ton' else "реквизиты для Stars"
                await update.message.reply_text(
                    f"Введите {requisite_type} для вывода:",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )
                
            except ValueError:
                await update.message.reply_text(
                    "🚫 Сумма вывода должна быть числом больше 0.",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
                )

        elif context.user_data.get('awaiting_withdraw_requisites'):
            requisites = text.strip()
            amount = context.user_data.get('withdraw_amount')
            valute = context.user_data.get('current_withdraw_valute', 'ton')
            
            # Создаем запрос на вывод
            request_id = save_withdrawal_request(user_id, amount, valute, requisites)
            
            # Списываем средства
            if valute == 'ton':
                user_data[user_id]['balance_ton'] -= amount
            else:
                user_data[user_id]['balance_stars'] -= amount
            save_user_data(user_id)
            
            context.user_data.clear()
            
            await update.message.reply_text(
                "✅ Запрос на вывод отправлен на проверку администратору.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )
            
            # Уведомление админу
            try:
                user_chat = await context.bot.get_chat(user_id)
                username = user_chat.username or "Не указан"
                full_name = user_chat.full_name or "Не указан"
                
                await context.bot.send_message(
                    ADMIN_CHAT_ID,
                    f"💸 Новый запрос на вывод\n\nПользователь: @{username} ({full_name}, ID: {user_id})\nСумма: {amount} {valute}\nРеквизиты: <code>{requisites}</code>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Подтвердить", callback_data=f'admin_confirm_withdraw_{request_id}')],
                        [InlineKeyboardButton("🚫 Отклонить", callback_data=f'admin_reject_withdraw_{request_id}')]
                    ])
                )
            except Exception as e:
                logger.error(f"Failed to send withdrawal notification to admin: {e}")

        elif context.user_data.get('awaiting_support_message'):
            message = text.strip()
            context.user_data.clear()
            
            await update.message.reply_text(
                "✅ Ваше сообщение отправлено в тех-поддержку.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )
            
            # Пересылаем сообщение админу
            try:
                user_chat = await context.bot.get_chat(user_id)
                username = user_chat.username or "Не указан"
                full_name = user_chat.full_name or "Не указан"
                
                await context.bot.send_message(
                    ADMIN_CHAT_ID,
                    f"💬 Новое сообщение от пользователя!\n\nПользователь: @{username} ({full_name}, ID: {user_id})\nСообщение: {message}",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📞 Ответить пользователю", callback_data=f'admin_reply_{user_id}')]
                    ])
                )
            except Exception as e:
                logger.error(f"Failed to send support message to admin: {e}")

    except Exception as e:
        logger.error(f"Error in handle_message: {e}", exc_info=True)
        await update.message.reply_text(
            "🚫 Произошла ошибка. Попробуйте снова.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_deposit_screenshot'):
        user_id = update.effective_user.id
        photo = update.message.photo[-1]
        amount = context.user_data.get('deposit_amount')
        valute = context.user_data.get('current_deposit_valute', 'ton')
        
        context.user_data.clear()
        
        await update.message.reply_text(
            "✅ Скриншот получен и отправлен на проверку. Ожидайте подтверждения.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
        )
        
        # Уведомление админу
        try:
            user_chat = await context.bot.get_chat(user_id)
            username = user_chat.username or "Не указан"
            full_name = user_chat.full_name or "Не указан"
            
            await context.bot.send_photo(
                ADMIN_CHAT_ID,
                photo=photo.file_id,
                caption=f"📸 Новый запрос на пополнение\n\nПользователь: @{username} ({full_name}, ID: {user_id})\nСумма: {amount} {valute}\n\nПожалуйста, проверьте скриншот транзакции.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Подтвердить", callback_data=f'admin_confirm_deposit_{user_id}_{amount}_{valute}')],
                    [InlineKeyboardButton("🚫 Отклонить", callback_data=f'admin_reject_deposit_{user_id}')]
                ])
            )
        except Exception as e:
            logger.error(f"Failed to send deposit notification to admin: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    context.user_data.clear()
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                update.effective_chat.id,
                "🚫 Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
            )
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

# Команды для админов
async def tetherteam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        return
    
    await update.message.reply_text(
        "Команда TetherTeam активирована",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
    )

async def set_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        return
    
    await update.message.reply_text(
        "Управление сделками",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
    )

async def set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_ID:
        return
    
    await update.message.reply_text(
        "Управление балансом",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 В главное меню", callback_data='menu')]])
    )

def main():
    # Инициализация базы данных и загрузка данных
    init_db()
    load_data()
    
    # Создание приложения
    app = Application.builder().token(BOT_TOKEN).build()

    # Добавление обработчиков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("tetherteam", tetherteam))
    app.add_handler(CommandHandler("deals", set_deals))
    app.add_handler(CommandHandler("balance", set_balance))

    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_error_handler(error_handler)

    logger.info("Starting bot...")
    
    # Запуск бота
    try:
        # Для веб-хостингов
        port = int(os.environ.get('PORT', 8080))
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"https://your-app-name.railway.app/{BOT_TOKEN}"
        )
    except:
        # Для локального запуска
        app.run_polling()

if __name__ == '__main__':
    main()