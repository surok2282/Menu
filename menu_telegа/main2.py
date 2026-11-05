# -*- coding: utf-8 -*-
"""
Телеграм-бот ресторана: меню, заказ, модификаторы, чаевые, рейтинг, ИИ-истории блюд.
Запуск: заполните BOT_TOKEN (и при желании PAYMENTS_TOKEN, OPENAI_KEY) и запустите файл.
"""
import os
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from telegram import (
    InlineKeyboardButton as B,
    InlineKeyboardMarkup as M,
    LabeledPrice,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# ======================== НАСТРОЙКИ ========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8629018449:AAH4EWlXMLUQuWxm1YAbsmmh6J5mJkwGtZs")          # от @BotFather
PAYMENTS_TOKEN = os.getenv("PAYMENTS_TOKEN", "")               # провайдер платежей от @BotFather
OPENAI_KEY = os.getenv("OPENAI_KEY", "")                       # опционально, для ИИ-историй

openai_client = None
if OPENAI_KEY:
    from openai import OpenAI
    openai_client = OpenAI(api_key=OPENAI_KEY)

# ======================== МЕНЮ ========================
MENU = {
    "carbonara": {
        "name": "Паста Карбонара",
        "price": 590,
        "desc": "Спагетти, гуанчиале, желток, пармезан, чёрный перец",
        "modifiers": ["Убрать майонез", "Убрать перец", "Убрать пармезан"],
        "history": ("Карбонара — римская классика XX века. Считается, что блюдо родилось "
                    "в 1940-х: паста, яйца, сыр и гуанчиале — сытный набор из тех продуктов, "
                    "что всегда были под рукой у римских поваров. Сливки в аутентичном рецепте "
                    "не используются вовсе."),
        "video_query": "карбонала рецепт видео",
    },
    "salad": {
        "name": "Салат с тунцом",
        "price": 450,
        "desc": "Тунец, микс-салат, черри, яйцо, оливки, соус винегрет",
        "modifiers": ["Убрать майонез", "Убрать лук", "Убрать яйцо"],
        "history": ("Прообраз салата — салат «Ницца» с юга Франции. Изначально это была еда "
                    "бедняков с Английской набережной Ниццы: анчоусы, оливки, яйца и овощи. "
                    "Тунец в банке закрепился в рецепте позже, в XX веке."),
        "video_query": "салат нисуаз рецепт видео",
    },
    "burger": {
        "name": "Бургер «Классический»",
        "price": 520,
        "desc": "Котлета из мраморной говядины, сыр чеддер, соус бургер, маринованный огурец",
        "modifiers": ["Убрать майонез", "Убрать перец", "Убрать огурец"],
        "history": ("Считается, что гамбургер «приехал» в США с немецкими иммигрантами из "
                    "Гамбурга. Первый бургер между булочками подали на ярмарке в Сент-Луисе "
                    "в 1904 году, а мировую славу ему обеспечила сеть White Castle в 1920-х."),
        "video_query": "бургер домашний рецепт видео",
    },
}

# Модификатор «Убрать перец» недоступен в блюде, где перца нет — можно менять на своё усмотрение
EXCLUDED_MODIFIERS = {"salad": {"Убрать перец"}}

# ======================== СОСТОЯНИЕ ========================
orders: dict[int, dict] = {}     
carts: dict[int, list] = {}      
pending: dict[int, dict] = {}    
ratings: dict[str, list] = {}    

# ======================== ХЕЛПЕРЫ ========================
def menu_keyboard():
    rows = [[B(f"🍽 {d['name']} — {d['price']} ₽", callback_data=f"dish:{i}")]
            for i, d in enumerate(MENU)]
    rows.append([B("🛒 Корзина", callback_data="cart")])
    return M(rows)

def dish_keyboard(dish_id: str):
    dish = MENU[dish_id]
    mods = pending.setdefault(dish_id, {"mods": set()})
    rows = []
    for i, mod in enumerate(dish["modifiers"]):
        if mod in EXCLUDED_MODIFIERS.get(dish_id, set()):
            continue
        mark = "✅" if mod in mods["mods"] else "➕"
        rows.append([B(f"{mark} {mod}", callback_data=f"mod:{dish_id}:{i}")])
    rows.append([B("✔️ Добавить в заказ", callback_data=f"add:{dish_id}")])
    rows.append([B("◀️ В меню", callback_data="menu")])
    return M(rows)

def cart_keyboard():
    return M([
        [B("💳 Оплатить заказ", callback_data="checkout")],
        [B("🗑 Очистить корзину", callback_data="clear")],
        [B("◀️ В меню", callback_data="menu")],
    ])

def cart_total(uid: int) -> int:
    return sum(MENU[i]["price"] for i in carts.get(uid, []))

def dish_keyboard_ai(dish_id: str):
    return M([
        [B("📖 История блюда (ИИ)", callback_data=f"aihistory:{dish_id}")],
        [B("🎥 Видео приготовления", url=f"https://www.youtube.com/results?search_query={quote_plus(MENU[dish_id]['video_query'])}")],
        [B("◀️ В меню", callback_data="menu")],
    ])

# ======================== КОМАНДЫ ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать в «Аромат»! 🍽\n\n"
        "• Выбирайте блюда из меню\n"
        "• Указывайте рекомендации (убрать майонез, перец и т.д.)\n"
        "• Оплачивайте картой и оставляйте чаевые официанту\n"
        "• Ставьте рейтинг блюдам и узнавайте их историю\n\n"
        "Нажмите «Меню», чтобы начать.",
        reply_markup=M([[B("📋 Меню", callback_data="menu")]]),
    )

async def my_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    o = orders.get(update.effective_user.id)
    if not o:
        await update.message.reply_text("У вас пока нет активных заказов. Загляните в меню: /start")
        return
    mins_passed = int((datetime.now() - o["created"]).total_seconds() // 60)
    left = max(0, o["eta_min"] - mins_passed)
    status = "🚚 Заказ уже готовится!" if left > 0 else "✅ Заказ должен быть готов!"
    await update.message.reply_text(
        f"{status}\nЗаказ от {o['created'].strftime('%H:%M')}\n"
        f"Ожидаемая готовность: ~{o['eta_min']} мин (осталось {left} мин)"
    )

# ======================== CALLBACK-КНОПКИ ========================
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    data = q.data

    if data == "menu":
        await q.edit_message_text("📋 Меню ресторана:", reply_markup=menu_keyboard())

    elif data.startswith("dish:"):
        dish_id = data.split(":")[1]
        pending[uid] = {"dish": dish_id, "mods": set()}
        d = MENU[dish_id]
        await q.edit_message_text(
            f"<b>{d['name']}</b> — {d['price']} ₽\n<i>{d['desc']}</i>\n\n"
            "Выберите рекомендации к блюду:",
            reply_markup=dish_keyboard(dish_id),
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("mod:"):
        _, dish_id, idx = data.split(":")
        mod = MENU[dish_id]["modifiers"][int(idx)]
        mods = pending[uid]["mods"]
        mods.discard(mod) if mod in mods else mods.add(mod)
        await q.edit_message_reply_markup(reply_markup=dish_keyboard(dish_id))

    elif data.startswith("add:"):
        dish_id = data.split(":")[1]
        carts.setdefault(uid, []).append({"id": dish_id, "mods": sorted(pending.get(uid, {}).get("mods", set()))})
        await q.edit_message_text(
            f"✅ «{MENU[dish_id]['name']}» добавлено в заказ.\nЧто-нибудь ещё?",
            reply_markup=M([[B("📋 Меню", callback_data="menu")], [B("🛒 Корзина", callback_data="cart")]]),
        )

    elif data == "cart":
        items = carts.get(uid, [])
        if not items:
            await q.edit_message_text("🛒 Корзина пуста.", reply_markup=M([[B("📋 Меню", callback_data="menu")]]))
            return
        text = "🛒 Ваш заказ:\n"
        for i, item in enumerate(items, 1):
            mods = ", ".join(item["mods"]) if item["mods"] else "без изменений"
            text += f"{i}. {MENU[item['id']]['name']} — {MENU[item['id']]['price']} ₽\n   ↳ {mods}\n"
        text += f"\nИтого: <b>{cart_total(uid)} ₽</b>"
        await q.edit_message_text(text, reply_markup=cart_keyboard(), parse_mode=ParseMode.HTML)

    elif data == "clear":
        carts.pop(uid, None)
        await q.edit_message_text("Корзина очищена.", reply_markup=M([[B("📋 Меню", callback_data="menu")]]))

    elif data == "checkout":
        if not carts.get(uid):
            await q.edit_message_text("Сначала выберите блюда из меню 🙂")
            return
        if not PAYMENTS_TOKEN:
            await q.edit_message_text(
                "Оплата пока не подключена: вставьте PAYMENTS_TOKEN (провайдер платежей) в код.\n"
                "Как получить — инструкция в комментарии к боту."
            )
            return
        total = cart_total(uid)
        await context.bot.send_invoice(
            chat_id=uid,
            title=f"Заказ в «Аромате» ({len(carts[uid])} поз.)",
            description=", ".join(MENU[i["id"]]["name"] for i in carts[uid]),
            payload=f"order_{uid}",
            provider_token=PAYMENTS_TOKEN,
            currency="RUB",
            prices=[LabeledPrice("Заказ", total * 100)],
        )

    elif data.startswith("tip:"):
        if not PAYMENTS_TOKEN:
            await q.edit_message_text("Оплата не подключена — чаевые пока недоступны.")
            return
        amount = int(data.split(":")[1])
        await context.bot.send_invoice(
            chat_id=uid,
            title="Чаевые официанту",
            description="Спасибо за щедрость! 💛",
            payload=f"tip_{uid}_{amount}",
            provider_token=PAYMENTS_TOKEN,
            currency="RUB",
            prices=[LabeledPrice("Чаевые", amount * 100)],
        )

    elif data.startswith("rate:"):
        _, dish_id, score = data.split(":")
        ratings.setdefault(dish_id, []).append(int(score))
        avg = sum(ratings[dish_id]) / len(ratings[dish_id])
        await q.edit_message_text(
            f"Спасибо за оценку «{MENU[dish_id]['name']}»: {score} ⭐\n"
            f"Средний рейтинг блюда: {avg:.1f} (по {len(ratings[dish_id])} оценкам)",
            reply_markup=M([[B("📋 В меню", callback_data="menu")]]),
        )

    elif data.startswith("aihistory:"):
        dish_id = data.split(":")[1]
        await q.answer("Сочиняю историю…", show_alert=False)
        text = await ai_history(dish_id)
        await q.edit_message_text(f"📖 <b>{MENU[dish_id]['name']}</b>\n\n{text}",
                                  reply_markup=dish_keyboard_ai(dish_id), parse_mode=ParseMode.HTML)

# ======================== ОПЛАТА ========================
async def pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload

    if payload.startswith("tip_"):
        amount = payload.split("_")[2]
        await update.message.reply_text(f"💛 Чаевые {amount} ₽ приняты! Официант узнает об этом сразу.")
        return

    # это оплата заказа
    eta_min = 25
    orders[uid] = {"items": carts.get(uid, []), "created": datetime.now(), "eta_min": eta_min}
    carts[uid] = []
    names = ", ".join(MENU[i["id"]]["name"] for i in orders[uid]["items"])
    await update.message.reply_text(
        f"✅ Заказ оплачен и принят!\n\n🍽 {names}\n"
        f"🧑‍🍳 Официант: Алексей\n"
        f"⏱ Заказ оформлен в {orders[uid]['created'].strftime('%H:%M')}, "
        f"ожидайте ~{eta_min} минут (узнать статус: /status)\n\n"
        "Хотите оставить чаевые или оценить блюда?",
        reply_markup=M([
            [B("💰 Чаевые 50 ₽", callback_data="tip:50"),
             B("💰 100 ₽", callback_data="tip:100"),
             B("💰 200 ₽", callback_data="tip:200")],
            [B("⭐ Оценить блюда", callback_data=f"rate_menu:{uid}")],
        ]),
    )
    context.job_queue.run_once(
        lambda c: c.bot.send_message(uid, "⏱ Прошло 25 минут — заказ должен быть готов! Приятного аппетита!"),
        eta_min * 60,
    )

async def rate_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rows = [[B(f"⭐ {MENU[d]['name']}", callback_data=f"pick_dish_for_rating:{d}")] for d in MENU]
    await q.edit_message_text("Выберите блюдо для оценки:", reply_markup=M(rows))

async def pick_dish_for_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    dish_id = q.data.split(":")[1]
    rows = [[B(f"{score} ⭐", callback_data=f"rate:{dish_id}:{score}")] for score in (1, 2, 3, 4, 5)]
    await q.edit_message_text(f"Оцените «{MENU[dish_id]['name']}»:", reply_markup=M(rows))

# ======================== ИИ: ИСТОРИЯ БЛЮДА ========================
async def ai_history(dish_id: str) -> str:
    dish = MENU[dish_id]
    if openai_client:
        try:
            resp = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": f"Расскажи коротко (4-5 предложений) живую историю происхождения блюда «{dish['name']}»: когда и где появилось, любопытный факт.",
                }],
            )
            return resp.choices[0].message.content
        except Exception:
            pass
    return dish["history"]

# ======================== ЗАПУСК ========================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", my_status))
    app.add_handler(CallbackQueryHandler(on_button, pattern=r"^(menu|dish:|mod:|add:|cart|clear|checkout|tip:|aihistory:)$"))
    app.add_handler(CallbackQueryHandler(rate_menu, pattern=r"^rate_menu:"))
    app.add_handler(CallbackQueryHandler(pick_dish_for_rating, pattern=r"^pick_dish_for_rating:"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, paid))
    app.add_handler(MessageHandler(filters.COMMAND, start))  # неизвестные команды -> подсказка

    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
