"""
JARVIS Telegram Bot — Génération d'images avec monétisation Telegram Stars
"""

import asyncio
import json
import logging
import os
import random
import time
from urllib.parse import quote

import httpx
from telegram import Update, LabeledPrice, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    CallbackQueryHandler,
    filters,
)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]
CHANNEL_ID      = os.environ.get("CHANNEL_ID", "")

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&model={model}&nologo=true"
GEMINI_URL       = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/gemini-2.0-flash:generateContent"
)

MAX_RETRIES      = 3
RETRY_DELAY      = 5
PREMIUM_PRICE    = 50        # 50 Telegram Stars / mois
FREE_AMELIORE    = 3         # utilisations gratuites de /améliore par jour

# ─── STOCKAGE EN MÉMOIRE ──────────────────────────────────────────────────────
# { user_id: { "premium_until": timestamp, "ameliore_today": count, "ameliore_date": "YYYY-MM-DD" } }
USER_DATA: dict = {}

def get_user(user_id: int) -> dict:
    if user_id not in USER_DATA:
        USER_DATA[user_id] = {"premium_until": 0, "ameliore_today": 0, "ameliore_date": ""}
    return USER_DATA[user_id]

def is_premium(user_id: int) -> bool:
    return get_user(user_id)["premium_until"] > time.time()

def can_ameliore(user_id: int) -> bool:
    if is_premium(user_id):
        return True
    user = get_user(user_id)
    today = time.strftime("%Y-%m-%d")
    if user["ameliore_date"] != today:
        user["ameliore_today"] = 0
        user["ameliore_date"] = today
    return user["ameliore_today"] < FREE_AMELIORE

def use_ameliore(user_id: int):
    if not is_premium(user_id):
        user = get_user(user_id)
        today = time.strftime("%Y-%m-%d")
        if user["ameliore_date"] != today:
            user["ameliore_today"] = 0
            user["ameliore_date"] = today
        user["ameliore_today"] += 1

def remaining_ameliore(user_id: int) -> int:
    if is_premium(user_id):
        return 999
    user = get_user(user_id)
    today = time.strftime("%Y-%m-%d")
    if user["ameliore_date"] != today:
        return FREE_AMELIORE
    return max(0, FREE_AMELIORE - user["ameliore_today"])

# ─── STYLES ───────────────────────────────────────────────────────────────────

STYLES_FREE = {
    "realistic": ("🌄 Réaliste",  "flux", 1024, 1024),
    "anime":     ("🎌 Anime",     "flux", 1024, 1024),
    "pixel":     ("👾 Pixel Art", "flux", 1024, 1024),
    "sketch":    ("✏️ Sketch",    "flux", 1024, 1024),
}

STYLES_PREMIUM = {
    "4k":        ("💎 4K Ultra",    "flux", 2048, 2048),
    "cinematic": ("🎬 Cinematic",   "flux", 1920, 1080),
    "3d":        ("🧊 3D Render",   "flux", 1024, 1024),
    "portrait":  ("🖼️ Portrait",   "flux",  832, 1216),
    "landscape": ("🏞️ Paysage",    "flux", 1216,  832),
    "dark":      ("🌑 Dark Art",    "flux", 1024, 1024),
}

STYLES = {**STYLES_FREE, **STYLES_PREMIUM}

STYLE_PROMPTS = {
    "realistic": "photorealistic, ultra detailed, 8k",
    "anime":     "anime style, manga, vibrant colors, studio ghibli",
    "pixel":     "pixel art, 16-bit, retro game style",
    "sketch":    "pencil sketch, hand drawn, black and white, detailed linework",
    "4k":        "8k uhd, ultra high resolution, photorealistic, masterpiece, extremely detailed",
    "cinematic": "cinematic shot, movie still, anamorphic lens, dramatic lighting, film grain",
    "3d":        "3d render, octane render, cinema 4d, ultra realistic",
    "portrait":  "portrait, professional photography, bokeh, sharp focus",
    "landscape": "landscape, wide angle, epic scenery, golden hour",
    "dark":      "dark art, gothic, dramatic shadows, moody atmosphere, dark fantasy",
}

RANDOM_THEMES = [
    "a futuristic city at night with neon lights",
    "a dragon flying over a medieval castle at sunset",
    "an astronaut exploring an alien jungle",
    "a underwater kingdom with bioluminescent creatures",
    "a magical forest with giant glowing mushrooms",
    "a samurai standing in a cherry blossom storm",
    "a steampunk airship battle above the clouds",
    "a wolf howling under a blood moon",
    "a cyberpunk street market in the rain",
    "a phoenix rising from the ashes",
]

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

async def _call_pollinations(client, prompt, model="flux", w=1024, h=1024) -> bytes:
    url = POLLINATIONS_URL.format(prompt=quote(prompt), model=model, w=w, h=h)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        except httpx.RequestError as exc:
            log.warning("Erreur réseau (%d/%d) : %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)
            else:
                raise

async def _call_gemini(client, system, user) -> str:
    payload = {
        "contents": [{"parts": [{"text": user}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"maxOutputTokens": 300},
    }
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    resp = await client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

async def _post_to_channel(ctx, image_bytes, caption):
    if not CHANNEL_ID:
        return
    try:
        await ctx.bot.send_photo(
            chat_id=CHANNEL_ID,
            photo=image_bytes,
            caption=f"🖼️ {caption}\n\n_Généré par @{ctx.bot.username}_",
            parse_mode="Markdown",
        )
    except Exception as e:
        log.warning("Canal : %s", e)

def premium_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ Passer Premium — 50 Stars/mois", callback_data="buy_premium")
    ]])

# ─── COMMANDES ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    uid  = update.effective_user.id
    badge = "💎 Premium" if is_premium(uid) else "🆓 Gratuit"
    msg = (
        f"👋 Salut *{user}* ! Bienvenue sur *JARVIS Image Bot* 🤖\n"
        f"Statut : {badge}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎨 *Commandes :*\n\n"
        "• `/image <desc>` — génère une image\n"
        "• `/imagine <desc> | <style>` — avec un style\n"
        "• `/améliore <desc>` — IA améliore ton prompt _(3x/jour gratuit)_\n"
        "• `/random` — image surprise\n"
        "• `/styles` — liste des styles\n"
        "• `/premium` — passer premium ⭐\n"
        "• `/moi` — voir ton statut\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 `/imagine château hanté | anime`\n"
        "💡 `/améliore dragon feu`\n\n"
        "_Propulsé par Pollinations.ai & Gemini_ 🚀"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)

async def moi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_premium(uid):
        until = time.strftime("%d/%m/%Y", time.localtime(get_user(uid)["premium_until"]))
        status = f"💎 *Premium* jusqu'au {until}\n✅ /améliore illimité\n✅ Styles 4K, Cinematic, Dark Art..."
    else:
        rem = remaining_ameliore(uid)
        status = (
            f"🆓 *Gratuit*\n"
            f"• /améliore restant aujourd'hui : *{rem}/{FREE_AMELIORE}*\n"
            f"• Styles premium : ❌\n\n"
            f"👉 `/premium` pour débloquer tout !"
        )
    await update.message.reply_text(status, parse_mode="Markdown")

async def styles_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    free_list    = "\n".join(f"  `{k}` — {v[0]}" for k, v in STYLES_FREE.items())
    premium_list = "\n".join(f"  `{k}` — {v[0]}" for k, v in STYLES_PREMIUM.items())
    lock = "" if is_premium(uid) else " 🔒"
    msg = (
        f"🎨 *Styles gratuits :*\n{free_list}\n\n"
        f"💎 *Styles premium{lock} :*\n{premium_list}\n\n"
        "_Exemple :_ `/imagine forêt magique | cinematic`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def premium_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if is_premium(uid):
        until = time.strftime("%d/%m/%Y", time.localtime(get_user(uid)["premium_until"]))
        await update.message.reply_text(f"💎 Tu es déjà Premium jusqu'au *{until}* !", parse_mode="Markdown")
        return
    msg = (
        "⭐ *JARVIS Premium — 50 Stars/mois*\n\n"
        "✅ `/améliore` illimité\n"
        "✅ Styles exclusifs : 4K, Cinematic, Dark Art, 3D...\n"
        "✅ Résolutions jusqu'à 2048x2048\n\n"
        "Clique ci-dessous pour t'abonner 👇"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=premium_keyboard())

async def buy_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await ctx.bot.send_invoice(
        chat_id=query.from_user.id,
        title="JARVIS Premium — 1 mois",
        description="✅ /améliore illimité\n✅ Styles 4K, Cinematic, Dark Art\n✅ Résolutions 2048px",
        payload="premium_1month",
        currency="XTR",           # Telegram Stars
        prices=[LabeledPrice("Premium 1 mois", PREMIUM_PRICE)],
        provider_token="",        # vide pour Stars
    )

async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def payment_success(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = get_user(uid)
    now = time.time()
    # Ajoute 30 jours (si déjà premium, prolonge)
    base = max(now, user["premium_until"])
    user["premium_until"] = base + 30 * 24 * 3600
    until = time.strftime("%d/%m/%Y", time.localtime(user["premium_until"]))
    await update.message.reply_text(
        f"🎉 *Merci ! Tu es maintenant Premium jusqu'au {until} !*\n\n"
        "✅ /améliore illimité\n"
        "✅ Styles 4K, Cinematic, Dark Art débloqués\n\n"
        "Tape `/styles` pour voir tous tes styles !",
        parse_mode="Markdown",
    )
    log.info("Premium activé pour user %d jusqu'au %s", uid, until)

async def generate_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(ctx.args).strip() if ctx.args else ""
    if not prompt:
        await update.message.reply_text("⚠️ `/image <description>`", parse_mode="Markdown")
        return
    wait_msg = await update.message.reply_text(f"🎨 Génération…\n`{prompt}`", parse_mode="Markdown")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, prompt)
        await update.message.reply_photo(photo=image_bytes, caption=f"🖼️ *{prompt}*", parse_mode="Markdown")
        await _post_to_channel(ctx, image_bytes, prompt)
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try: await wait_msg.delete()
        except: pass

async def imagine(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(ctx.args).strip() if ctx.args else ""
    if not raw:
        await update.message.reply_text("⚠️ `/imagine <desc> | <style>`", parse_mode="Markdown")
        return

    prompt, style = (raw.split("|", 1)[0].strip(), raw.split("|", 1)[1].strip().lower()) if "|" in raw else (raw, "realistic")

    if style not in STYLES:
        await update.message.reply_text(f"❌ Style `{style}` inconnu. Tape `/styles`.", parse_mode="Markdown")
        return

    uid = update.effective_user.id
    if style in STYLES_PREMIUM and not is_premium(uid):
        await update.message.reply_text(
            f"🔒 Le style `{style}` est *Premium*.\n\nTape `/premium` pour débloquer ! ⭐",
            parse_mode="Markdown",
            reply_markup=premium_keyboard(),
        )
        return

    label, model, w, h = STYLES[style]
    full_prompt = f"{prompt}, {STYLE_PROMPTS[style]}"
    wait_msg = await update.message.reply_text(f"{label} en cours…\n`{prompt}`", parse_mode="Markdown")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, full_prompt, model, w, h)
        await update.message.reply_photo(photo=image_bytes, caption=f"{label} — *{prompt}*", parse_mode="Markdown")
        await _post_to_channel(ctx, image_bytes, f"{prompt} ({style})")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try: await wait_msg.delete()
        except: pass

async def ameliore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    prompt = " ".join(ctx.args).strip() if ctx.args else ""
    if not prompt:
        await update.message.reply_text("⚠️ `/améliore <description>`", parse_mode="Markdown")
        return

    if not can_ameliore(uid):
        await update.message.reply_text(
            f"⏳ Tu as utilisé tes *{FREE_AMELIORE} /améliore* gratuits aujourd'hui.\n\n"
            "Reviens demain ou passe *Premium* pour un accès illimité ! ⭐",
            parse_mode="Markdown",
            reply_markup=premium_keyboard(),
        )
        return

    rem = remaining_ameliore(uid)
    suffix = "" if is_premium(uid) else f" _(encore {rem - 1} utilisations gratuites aujourd'hui)_"
    wait_msg = await update.message.reply_text(f"✨ Amélioration en cours…\n`{prompt}`", parse_mode="Markdown")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            system = (
                "Tu es un expert en génération d'images IA. "
                "Transforme le prompt en un prompt détaillé et épique en anglais avec style, éclairage, ambiance. "
                "Réponds UNIQUEMENT avec le prompt amélioré, rien d'autre."
            )
            improved = await _call_gemini(client, system, prompt)
            use_ameliore(uid)
            await wait_msg.edit_text(
                f"✨ *Prompt amélioré :*\n`{improved[:200]}`\n\n🎨 Génération…{suffix}",
                parse_mode="Markdown",
            )
            image_bytes = await _call_pollinations(client, improved)
        caption = f"✨ *{prompt}*\n_IA : `{improved[:150]}…`_" if len(improved) > 150 else f"✨ *{prompt}*\n_IA : `{improved}`_"
        await update.message.reply_photo(photo=image_bytes, caption=caption, parse_mode="Markdown")
        await _post_to_channel(ctx, image_bytes, f"✨ {prompt}")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try: await wait_msg.delete()
        except: pass

async def random_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    theme     = random.choice(RANDOM_THEMES)
    style_key = random.choice(list(STYLES_FREE.keys()))  # random = styles gratuits
    label, model, w, h = STYLES[style_key]
    full_prompt = f"{theme}, {STYLE_PROMPTS[style_key]}"
    wait_msg = await update.message.reply_text(f"🎲 Image surprise… {label}", parse_mode="Markdown")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, full_prompt, model, w, h)
        await update.message.reply_photo(
            photo=image_bytes,
            caption=f"🎲 *Surprise !* — {label}\n_{theme}_",
            parse_mode="Markdown",
        )
        await _post_to_channel(ctx, image_bytes, f"🎲 {theme}")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try: await wait_msg.delete()
        except: pass

async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❓ Commande inconnue. Tape /help.")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("Démarrage de JARVIS Bot (Premium)…")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_cmd))
    app.add_handler(CommandHandler("styles",   styles_cmd))
    app.add_handler(CommandHandler("moi",      moi))
    app.add_handler(CommandHandler("premium",  premium_cmd))
    app.add_handler(CommandHandler("image",    generate_image))
    app.add_handler(CommandHandler("imagine",  imagine))
    app.add_handler(CommandHandler("ameliore", ameliore))
    app.add_handler(CommandHandler("random",   random_image))
    app.add_handler(CallbackQueryHandler(buy_callback, pattern="buy_premium"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, payment_success))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    log.info("Bot en écoute. Ctrl+C pour arrêter.")
    app.run_polling(poll_interval=1)

if __name__ == "__main__":
    main()
