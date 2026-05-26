"""
JARVIS Telegram Bot — Génération d'images avec Pollinations.ai (gratuit, sans clé)
"""

import asyncio
import logging
import os
from urllib.parse import quote

import httpx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&model={model}&nologo=true"

MAX_RETRIES = 3
RETRY_DELAY = 5

# Styles disponibles : nom affiché → modèle Pollinations
STYLES = {
    "realistic": ("🌄 Réaliste",   "flux",        1024, 1024),
    "anime":     ("🎌 Anime",      "flux",        1024, 1024),
    "pixel":     ("👾 Pixel Art",  "flux",        1024, 1024),
    "3d":        ("🧊 3D Render",  "flux",        1024, 1024),
    "sketch":    ("✏️ Sketch",     "flux",        1024, 1024),
    "portrait":  ("🖼️ Portrait",  "flux",         832, 1216),
    "landscape": ("🏞️ Paysage",   "flux",        1216,  832),
}

STYLE_PROMPTS = {
    "realistic": "photorealistic, ultra detailed, 8k",
    "anime":     "anime style, manga, vibrant colors, studio ghibli",
    "pixel":     "pixel art, 16-bit, retro game style",
    "3d":        "3d render, octane render, cinema 4d, ultra realistic",
    "sketch":    "pencil sketch, hand drawn, black and white, detailed linework",
    "portrait":  "portrait, professional photography, bokeh, sharp focus",
    "landscape": "landscape, wide angle, epic scenery, golden hour",
}

STYLES_HELP = "\n".join(
    f"  `{key}` — {label}" for key, (label, *_) in STYLES.items()
)

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── HELPER ───────────────────────────────────────────────────────────────────

async def _call_pollinations(client: httpx.AsyncClient, prompt: str, model: str, w: int, h: int) -> bytes:
    full_prompt = quote(prompt)
    url = POLLINATIONS_URL.format(prompt=full_prompt, model=model, w=w, h=h)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
        except httpx.RequestError as exc:
            log.warning("Erreur réseau (tentative %d/%d) : %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY * attempt)
            else:
                raise

# ─── COMMANDES ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *JARVIS Image Bot* en ligne !\n\n"
        "Commandes disponibles :\n"
        "• `/image <description>` — génère une image\n"
        "• `/imagine <description> | <style>` — génère avec un style\n"
        "• `/styles` — liste les styles disponibles\n"
        "• `/help` — affiche cette aide\n\n"
        "_Exemple :_ `/imagine un château hanté | anime`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)


async def styles_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🎨 *Styles disponibles pour /imagine :*\n\n"
        f"{STYLES_HELP}\n\n"
        "_Exemple :_ `/imagine une forêt magique | pixel`"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def generate_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(ctx.args).strip() if ctx.args else ""

    if not prompt:
        await update.message.reply_text(
            "⚠️ Merci de fournir une description.\n"
            "_Exemple :_ `/image un chat astronaute sur la lune`",
            parse_mode="Markdown",
        )
        return

    wait_msg = await update.message.reply_text(
        f"🎨 Génération en cours…\n`{prompt}`",
        parse_mode="Markdown",
    )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, prompt, "flux", 1024, 1024)

        await update.message.reply_photo(
            photo=image_bytes,
            caption=f"🖼️ *{prompt}*",
            parse_mode="Markdown",
        )
        log.info("Image envoyée pour : %s", prompt)

    except Exception as e:
        log.error("Erreur : %s", e)
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass


async def imagine(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    raw = " ".join(ctx.args).strip() if ctx.args else ""

    if not raw:
        await update.message.reply_text(
            "⚠️ Utilisation : `/imagine <description> | <style>`\n"
            "Tape `/styles` pour voir les styles disponibles.",
            parse_mode="Markdown",
        )
        return

    # Parser le style
    if "|" in raw:
        parts = raw.split("|", 1)
        prompt = parts[0].strip()
        style  = parts[1].strip().lower()
    else:
        prompt = raw
        style  = "realistic"

    if style not in STYLES:
        await update.message.reply_text(
            f"❌ Style `{style}` inconnu. Tape `/styles` pour voir les styles disponibles.",
            parse_mode="Markdown",
        )
        return

    label, model, w, h = STYLES[style]
    style_suffix = STYLE_PROMPTS[style]
    full_prompt = f"{prompt}, {style_suffix}"

    wait_msg = await update.message.reply_text(
        f"{label} en cours…\n`{prompt}`",
        parse_mode="Markdown",
    )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, full_prompt, model, w, h)

        await update.message.reply_photo(
            photo=image_bytes,
            caption=f"{label} — *{prompt}*",
            parse_mode="Markdown",
        )
        log.info("Image [%s] envoyée pour : %s", style, prompt)

    except Exception as e:
        log.error("Erreur : %s", e)
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass


async def unknown(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Commande inconnue. Tape /help pour voir les commandes disponibles."
    )


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    log.info("Démarrage de JARVIS Bot (Pollinations.ai)…")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("help",    help_cmd))
    app.add_handler(CommandHandler("styles",  styles_cmd))
    app.add_handler(CommandHandler("image",   generate_image))
    app.add_handler(CommandHandler("imagine", imagine))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    log.info("Bot en écoute. Ctrl+C pour arrêter.")
    app.run_polling(poll_interval=1)


if __name__ == "__main__":
    main()
