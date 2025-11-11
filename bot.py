import sqlite3
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
import logging
import asyncio
import os
from datetime import datetime, time
import threading
import time as time_module

TOKEN = os.getenv('TELEGRAM_TOKEN','8588010905:AAF5cA-5YfNkrPCnGoxfkFaTHlLKIOblLws')

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

DB_NAME = 'subscribers.db'
LESSONS_DIR = 'lessons'

# ===== НАСТРОЙКА АДМИНИСТРАТОРОВ =====
# Добавьте сюда ID администраторов после того как их получите
# Например: admin_ids = [123456789, 987654321]
admin_ids_str = os.getenv('ADMIN_IDS', '')
admin_ids = [int(id.strip()) for id in admin_ids_str.split(',') if id.strip()] if admin_ids_str else []

# ===== Загрузка уроков из файлов =====
def load_lessons():
    lessons = []
    os.makedirs(LESSONS_DIR, exist_ok=True)
    
    for i in range(6):
        filename = os.path.join(LESSONS_DIR, f'lesson_{i}.txt')
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    lessons.append(content)
                else:
                    lessons.append(f"Урок {i} пустой. Заполните файл {filename}")
                    logger.warning(f"Файл урока {i} пустой")
        except FileNotFoundError:
            template = f"""Урок {i}

Здесь должен быть текст урока {i}.

Заполните файл: {filename}

После заполнения файлов перезапустите бота."""
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(template)
            lessons.append(template)
            logger.info(f"Создан шаблонный файл для урока {i}")
    
    return lessons

LESSONS = load_lessons()

# ===== Работа с БД =====
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            current_lesson INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, current_lesson) VALUES (?, 0)", (user_id,))
    conn.commit()
    conn.close()

def get_users_for_lessons():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, current_lesson FROM users WHERE current_lesson < ?", (len(LESSONS)-1,))
    users = cursor.fetchall()
    conn.close()
    return users

def increment_lesson(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET current_lesson = current_lesson + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_user_current_lesson(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT current_lesson FROM users WHERE user_id = ?", (user_id,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else 0

def get_db_stats():
    """Получить статистику базы данных"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT current_lesson, COUNT(*) 
        FROM users 
        GROUP BY current_lesson 
        ORDER BY current_lesson
    """)
    lesson_stats = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE current_lesson >= ?", (len(LESSONS)-1,))
    completed_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT user_id, current_lesson FROM users ORDER BY rowid DESC LIMIT 5")
    recent_users = cursor.fetchall()
    
    conn.close()
    
    return {
        'total_users': total_users,
        'lesson_stats': lesson_stats,
        'completed_users': completed_users,
        'recent_users': recent_users
    }

def get_all_users():
    """Получить всех пользователей"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, current_lesson FROM users ORDER BY current_lesson DESC")
    users = cursor.fetchall()
    conn.close()
    return users

# ===== Хэндлеры =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    add_user(user_id)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET current_lesson = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    await context.bot.send_message(
        chat_id=user_id, 
        text=LESSONS[0]
    )
    logger.info(f"Пользователь {user_id} начал обучение")

async def getmyid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получить свой ID"""
    user_id = update.effective_chat.id
    user = update.effective_user
    
    message = f"""
📋 Ваши данные:

🆔 **Ваш ID:** `{user_id}`
👤 **Username:** @{user.username if user.username else 'не указан'}
📛 **Имя:** {user.first_name or 'не указано'}
📚 **Текущий урок:** {get_user_current_lesson(user_id)}
    """
    
    await context.bot.send_message(
        chat_id=user_id,
        text=message.strip()
    )

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id not in admin_ids and admin_ids:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="У вас нет прав для использования этой команды"
        )
        return
    
    if not context.args:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Использование: /broadcast ваше сообщение"
        )
        return
        
    message = ' '.join(context.args)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    success_count = 0
    fail_count = 0
    
    for row in users:
        uid = row[0]
        try:
            await context.bot.send_message(chat_id=uid, text=message)
            success_count += 1
        except Exception as e:
            logger.warning(f'Не удалось отправить сообщение пользователю {uid}: {e}')
            fail_count += 1
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Рассылка завершена: Успешно: {success_count}, Ошибок: {fail_count}"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    current_lesson = get_user_current_lesson(user_id)
    
    if current_lesson >= len(LESSONS) - 1:
        status_text = "Вы завершили все уроки!"
    else:
        status_text = f"Ваш прогресс: урок {current_lesson} из {len(LESSONS)-1}. Следующий урок: завтра в 10:00"
    
    await context.bot.send_message(chat_id=user_id, text=status_text)

async def db_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать статистику базы данных"""
    if update.effective_chat.id not in admin_ids and admin_ids:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="У вас нет прав для использования этой команды"
        )
        return
    
    stats = get_db_stats()
    
    message = f"""📊 **Статистика базы данных:**

👥 **Общая информация:**
• Всего пользователей: {stats['total_users']}
• Завершили обучение: {stats['completed_users']}

📚 **Прогресс по урокам:**
"""
    
    for lesson, count in stats['lesson_stats']:
        if lesson >= len(LESSONS) - 1:
            lesson_text = "Завершили"
        else:
            lesson_text = f"Урок {lesson}"
        message += f"• {lesson_text}: {count} чел.\n"
    
    message += "\n🆕 **Последние 5 пользователей:**\n"
    for user_id, current_lesson in stats['recent_users']:
        if current_lesson >= len(LESSONS) - 1:
            progress = "завершил"
        else:
            progress = f"урок {current_lesson}"
        message += f"• ID {user_id} - {progress}\n"
    
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message
    )

async def db_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать всех пользователей"""
    if update.effective_chat.id not in admin_ids and admin_ids:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="У вас нет прав для использования этой команды"
        )
        return
    
    users = get_all_users()
    
    if not users:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="В базе данных нет пользователей."
        )
        return
    
    message = "👥 **Все пользователи:**\n\n"
    
    for i, (user_id, current_lesson) in enumerate(users, 1):
        if current_lesson >= len(LESSONS) - 1:
            progress = "✅ Завершил"
        else:
            progress = f"📚 Урок {current_lesson}"
        message += f"{i}. ID {user_id} - {progress}\n"
        
        if i % 20 == 0:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=message
            )
            message = ""
    
    if message:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message
        )

async def db_export(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспортировать базу данных в текстовом формате"""
    if update.effective_chat.id not in admin_ids and admin_ids:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="У вас нет прав для использования этой команды"
        )
        return
    
    users = get_all_users()
    stats = get_db_stats()
    
    export_text = f"""ЭКСПОРТ БАЗЫ ДАННЫХ
Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Всего пользователей: {stats['total_users']}

ДАННЫЕ ПОЛЬЗОВАТЕЛЕЙ:
{"ID":<15} Урок
{"-"*25}
"""
    
    for user_id, current_lesson in users:
        export_text += f"{user_id:<15} {current_lesson}\n"
    
    export_text += f"\nСТАТИСТИКА:\n"
    for lesson, count in stats['lesson_stats']:
        export_text += f"Урок {lesson}: {count} пользователей\n"
    
    filename = f"db_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(export_text)
    
    with open(filename, 'rb') as f:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=f,
            filename=filename,
            caption=f"Экспорт базы данных ({stats['total_users']} пользователей)"
        )
    
    os.remove(filename)

async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    current_lesson = get_user_current_lesson(user_id)
    
    if current_lesson >= len(LESSONS) - 1:
        response = "Вы завершили все уроки! Спасибо за участие!"
    else:
        response = f"Ваш текущий урок: {current_lesson}. Следующий урок будет отправлен завтра в 10:00"
    
    await context.bot.send_message(chat_id=user_id, text=response)

async def error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.warning(f'Update {update} caused error {context.error}')

# ===== Простой планировщик =====
def should_send_lessons():
    now = datetime.now()
    return now.hour == 10 and now.minute == 0

async def send_daily_lessons(application):
    logger.info("Проверка необходимости отправки уроков")
    
    if not should_send_lessons():
        return
    
    users = get_users_for_lessons()
    if not users:
        logger.info("Нет пользователей для рассылки")
        return
    
    logger.info(f"Начало рассылки уроков для {len(users)} пользователей")
    
    for user_id, current_lesson in users:
        next_lesson_num = current_lesson + 1
        if 0 <= next_lesson_num < len(LESSONS):
            try:
                await application.bot.send_message(
                    chat_id=user_id,
                    text=LESSONS[next_lesson_num]
                )
                increment_lesson(user_id)
                logger.info(f"Отправлен урок {next_lesson_num} пользователю {user_id}")
            except Exception as e:
                logger.warning(f'Не удалось отправить урок пользователю {user_id}: {e}')

def schedule_loop(application):
    logger.info("Планировщик запущен - проверка каждую минуту")
    
    while True:
        try:
            asyncio.run_coroutine_threadsafe(
                send_daily_lessons(application), 
                application._get_running_loop()
            )
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
        
        time_module.sleep(60)

def start_scheduler(application):
    thread = threading.Thread(target=schedule_loop, args=(application,), daemon=True)
    thread.start()
    logger.info("Планировщик запущен в отдельном потоке")

def main():
    init_db()
    
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('getmyid', getmyid))
    application.add_handler(CommandHandler('broadcast', broadcast))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('db_stats', db_stats))
    application.add_handler(CommandHandler('db_users', db_users))
    application.add_handler(CommandHandler('db_export', db_export))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    application.add_error_handler(error)

    start_scheduler(application)
    
    logger.info("Бот запущен и готов к работе!")
    print("=" * 50)
    print("Бот успешно запущен!")
    print(f"Загружено уроков: {len(LESSONS)}")
    print("Рассылка настроена на 10:00 ежедневно")
    print("=" * 50)
    print("📋 КАК ПОЛУЧИТЬ ID АДМИНИСТРАТОРОВ:")
    print("1. Попросите будущих админов написать боту команду /getmyid")
    print("2. Они получат свой ID")
    print("3. Добавьте эти ID в переменную admin_ids в коде")
    print("4. Перезапустите бота")
    print("=" * 50)
    print("Команды для пользователей:")
    print("/start - начать обучение")
    print("/getmyid - получить свой ID")
    print("/status - статус обучения")
    print("=" * 50)
    print("Команды для админов (после настройки):")
    print("/db_stats - статистика БД")
    print("/db_users - список пользователей")
    print("/db_export - экспорт БД")
    print("/broadcast - рассылка")
    print("=" * 50)
    
    application.run_polling()

if __name__ == '__main__':
    main()