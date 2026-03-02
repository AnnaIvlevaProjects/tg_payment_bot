from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import date

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from dotenv import load_dotenv

from db import Database
from keyboards import back_to_main_menu, email_offer_kb, main_menu, month_selector

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
ALLOWED_EXTENSIONS = {"txt", "pdf", "png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff"}


class PayFlow(StatesGroup):
    waiting_for_receipt = State()
    waiting_for_email = State()


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_chat_id: int
    course_chat_id: int
    course_chat_link: str
    db_path: str
    check_interval_hours: int


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        bot_token=os.environ["BOT_TOKEN"],
        admin_chat_id=int(os.environ["ADMIN_CHAT_ID"]),
        course_chat_id=int(os.environ["COURSE_CHAT_ID"]),
        course_chat_link=os.environ["COURSE_CHAT_LINK"],
        db_path=os.getenv("DB_PATH", "bot.db"),
        check_interval_hours=int(os.getenv("CHECK_INTERVAL_HOURS", "24")),
    )


router = Router()


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, db: Database) -> None:
    source = command.args if command and command.args else None
    await db.upsert_user(
        user_id=message.from_user.id,
        user_name=message.from_user.username,
        user_fn=message.from_user.first_name,
        user_ln=message.from_user.last_name,
        source=source,
    )
    await message.answer(
        "Добро пожаловать! 👋\n"
        "Я помогу с оплатой и доступом к учебному чату.\n"
        "Выберите действие в меню ниже.",
        reply_markup=main_menu(),
    )


@router.message(F.text == "⬅️ Главное меню")
async def to_main_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Вы в главном меню.", reply_markup=main_menu())


@router.message(F.text == "О курсе")
async def about_course(message: Message) -> None:
    await message.answer(
        "📚 Курс длится 6 месяцев.\n\n"
        "Структура:\n"
        "1) Месяц 1 — база и подготовка\n"
        "2) Месяц 2 — практика №1\n"
        "3) Месяц 3 — практика №2\n"
        "4) Месяц 4 — углубление\n"
        "5) Месяц 5 — проект\n"
        "6) Месяц 6 — финализация и защита\n\n"
        "Для оплаты перейдите в раздел «Оплатить»."
    )


@router.message(F.text == "Оплатить")
async def pay_menu(message: Message) -> None:
    await message.answer(
        "Реквизиты для оплаты:\n"
        "Банк: Example Bank\n"
        "Карта: 1111 2222 3333 4444\n"
        "Получатель: ИП Пример\n\n"
        "После оплаты выберите месяц:",
        reply_markup=back_to_main_menu(),
    )
    await message.answer("Выберите месяц оплаты:", reply_markup=month_selector())


@router.callback_query(F.data.startswith("month:"))
async def pick_month(callback: CallbackQuery, state: FSMContext, db: Database) -> None:
    month = int(callback.data.split(":", maxsplit=1)[1])
    await db.set_selected_month(callback.from_user.id, month)
    await state.set_state(PayFlow.waiting_for_receipt)
    await state.update_data(month=month)
    await callback.message.answer(
        f"Вы выбрали {month} месяц. Теперь вы можете загрузить документ об оплате ⬇️\n"
        "(txt/pdf/изображение)."
    )
    await callback.answer()


@router.message(PayFlow.waiting_for_receipt, F.document)
@router.message(PayFlow.waiting_for_receipt, F.photo)
async def upload_receipt(message: Message, state: FSMContext, db: Database, bot: Bot, settings: Settings) -> None:
    data = await state.get_data()
    month = data.get("month")
    if not month:
        await message.answer("Сначала выберите месяц через меню «Оплатить».", reply_markup=main_menu())
        await state.clear()
        return

    if message.document:
        ext = (message.document.file_name or "").split(".")[-1].lower()
        if ext and ext not in ALLOWED_EXTENSIONS:
            await message.answer("Неподдерживаемый тип файла. Загрузите txt/pdf/изображение.")
            return

    caption = (
        f"Новый чек об оплате\n"
        f"user_id: {message.from_user.id}\n"
        f"user_name: @{message.from_user.username or '-'}\n"
        f"user_FN: {message.from_user.first_name or '-'}\n"
        f"user_LN: {message.from_user.last_name or '-'}\n"
        f"month: {month}"
    )

    if message.document:
        await bot.send_document(chat_id=settings.admin_chat_id, document=message.document.file_id, caption=caption)
    else:
        await bot.send_photo(chat_id=settings.admin_chat_id, photo=message.photo[-1].file_id, caption=caption)

    await db.mark_payment(message.from_user.id, month)

    try:
        await bot.unban_chat_member(settings.course_chat_id, message.from_user.id, only_if_banned=True)
    except Exception as exc:  # noqa: BLE001
        logging.warning("Could not unban user %s: %s", message.from_user.id, exc)

    await message.answer(
        "Спасибо! Чек отправлен администратору.\n"
        f"Ссылка на учебный чат: {settings.course_chat_link}\n\n"
        "Хотите оставить e-mail для альтернативной связи?"
        " Отправьте e-mail сообщением или нажмите «Пропустить».",
        reply_markup=email_offer_kb(),
    )
    await state.set_state(PayFlow.waiting_for_email)


@router.message(F.document | F.photo)
async def premature_receipt_upload(message: Message) -> None:
    await message.answer(
        "Похоже, месяц оплаты не выбран. Пожалуйста, используйте кнопки меню: «Оплатить» → выбор месяца.",
        reply_markup=main_menu(),
    )


@router.message(PayFlow.waiting_for_email, F.text == "Пропустить")
async def skip_email(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Хорошо, e-mail не сохранён.", reply_markup=main_menu())


@router.message(PayFlow.waiting_for_email, F.text)
async def save_email(message: Message, state: FSMContext, db: Database) -> None:
    email = message.text.strip()
    if not EMAIL_RE.match(email):
        await message.answer("Похоже на некорректный e-mail. Попробуйте ещё раз или нажмите «Пропустить».")
        return
    await db.set_email(message.from_user.id, email)
    await state.clear()
    await message.answer("E-mail сохранён ✅", reply_markup=main_menu())


async def payment_guard_worker(bot: Bot, db: Database, settings: Settings) -> None:
    while True:
        users = await db.iter_users()
        today = date.today()
        for user in users:
            start_date = date.fromisoformat(user.course_start_date)
            months_since_start = (today.year - start_date.year) * 12 + (today.month - start_date.month) + 1
            expected_paid = min(max(months_since_start, 1), 6)
            paid_count = sum(1 for val in user.payments.values() if val == "да")

            if paid_count < expected_paid and not user.removed_from_chat:
                try:
                    await bot.ban_chat_member(settings.course_chat_id, user.user_id)
                    await db.set_removed_flag(user.user_id, True)
                    await bot.send_message(
                        user.user_id,
                        "Срок оплаты следующего месяца истёк, доступ к чату временно приостановлен. "
                        "После загрузки чека мы автоматически вернём доступ.",
                    )
                except Exception as exc:  # noqa: BLE001
                    logging.warning("Could not ban user %s: %s", user.user_id, exc)
            elif paid_count >= expected_paid and user.removed_from_chat:
                try:
                    await bot.unban_chat_member(settings.course_chat_id, user.user_id, only_if_banned=True)
                    await db.set_removed_flag(user.user_id, False)
                except Exception as exc:  # noqa: BLE001
                    logging.warning("Could not unban user %s in worker: %s", user.user_id, exc)

        await asyncio.sleep(settings.check_interval_hours * 3600)


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    db = Database(settings.db_path)
    await db.init()

    bot = Bot(settings.bot_token)
    dp = Dispatcher()

    dp["db"] = db
    dp["settings"] = settings
    dp.include_router(router)

    guard_task = asyncio.create_task(payment_guard_worker(bot, db, settings))
    try:
        await dp.start_polling(bot)
    finally:
        guard_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
