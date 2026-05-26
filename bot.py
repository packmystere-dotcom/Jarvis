"""
JARVIS Telegram Bot — Génération d'images avec Pollinations.ai (gratuit, sans clé)
"""

import asyncio
import logging
import os
import random
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

TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
GEMINI_API_KEY  = os.environ["GEMINI_API_KEY"]
CHANNEL_ID      = os.environ.get("CHANNEL_ID", "")  # ex: @moncanal ou -100xxxxxxxxx

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&model={model}&nologo=true"
GEMINI_URL       = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/gemini-2.0-flash:generateContent"
)

MAX_RETRIES = 3
RETRY_DELAY = 5

STYLES = {
    "realistic": ("🌄 Réaliste",  "flux", 1024, 1024),
    "anime":     ("🎌 Anime",     "flux", 1024, 1024),
    "pixel":     ("👾 Pixel Art", "flux", 1024, 1024),
    "3d":        ("🧊 3D Render", "flux", 1024, 1024),
    "sketch":    ("✏️ Sketch",    "flux", 1024, 1024),
    "portrait":  ("🖼️ Portrait", "flux",  832, 1216),
    "landscape": ("🏞️ Paysage",  "flux", 1216,  832),
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
    "a giant robot fighting a sea monster",
    "an ancient temple hidden in a waterfall",
    "a witch flying over a haunted village",
    "a time traveler standing in ancient Rome",
    "a mermaid city deep in the ocean",
]

# ─── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ─── HELPERS ──────────────────────────────────────────────────────────────────

async def _call_pollinations(client: httpx.AsyncClient, prompt: str, model: str = "flux", w: int = 1024, h: int = 1024) -> bytes:
    url = POLLINATIONS_URL.format(prompt=quote(prompt), model=model, w=w, h=h)
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


async def _call_gemini(client: httpx.AsyncClient, system: str, user: str) -> str:
    payload = {
        "contents": [{"parts": [{"text": user}]}],
        "systemInstruction": {"parts": [{"text": system}]},
        "generationConfig": {"maxOutputTokens": 300},
    }
    url = f"{GEMINI_URL}?key={GEMINI_API_KEY}"
    resp = await client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


async def _post_to_channel(ctx, image_bytes: bytes, caption: str):
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
        log.warning("Impossible de poster sur le canal : %s", e)

# ─── COMMANDES ────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user.first_name
    msg = (
        f"👋 Salut *{user}* ! Bienvenue sur *JARVIS Image Bot* 🤖\n\n"
        "Je génère des images de ouf en quelques secondes, gratuitement et sans limite !\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎨 *Commandes disponibles :*\n\n"
        "• `/image <description>` — génère une image\n"
        "• `/imagine <description> | <style>` — génère avec un style\n"
        "• `/améliore <description>` — l'IA améliore ton prompt avant de générer\n"
        "• `/random` — génère une image surprise\n"
        "• `/styles` — liste les styles disponibles\n"
        "• `/help` — affiche cette aide\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 *Exemples :*\n"
        "`/image un chat astronaute`\n"
        "`/imagine un château hanté | anime`\n"
        "`/améliore dragon feu`\n\n"
        "_Propulsé par Pollinations.ai & Gemini_ 🚀"
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
            "⚠️ Merci de fournir une description.\n_Exemple :_ `/image un chat astronaute`",
            parse_mode="Markdown",
        )
        return

    wait_msg = await update.message.reply_text(f"🎨 Génération en cours…\n`{prompt}`", parse_mode="Markdown")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, prompt)
        await update.message.reply_photo(photo=image_bytes, caption=f"🖼️ *{prompt}*", parse_mode="Markdown")
        await _post_to_channel(ctx, image_bytes, prompt)
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
            "⚠️ Utilisation : `/imagine <description> | <style>`\nTape `/styles` pour voir les styles.",
            parse_mode="Markdown",
        )
        return

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
    full_prompt = f"{prompt}, {STYLE_PROMPTS[style]}"
    wait_msg = await update.message.reply_text(f"{label} en cours…\n`{prompt}`", parse_mode="Markdown")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, full_prompt, model, w, h)
        await update.message.reply_photo(photo=image_bytes, caption=f"{label} — *{prompt}*", parse_mode="Markdown")
        await _post_to_channel(ctx, image_bytes, f"{prompt} ({style})")
        log.info("Image [%s] envoyée pour : %s", style, prompt)
    except Exception as e:
        log.error("Erreur : %s", e)
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass


async def ameliore(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(ctx.args).strip() if ctx.args else ""
    if not prompt:
        await update.message.reply_text(
            "⚠️ Utilisation : `/améliore <description>`\n_Exemple :_ `/améliore dragon feu`",
            parse_mode="Markdown",
        )
        return

    wait_msg = await update.message.reply_text(f"✨ Amélioration du prompt en cours…\n`{prompt}`", parse_mode="Markdown")

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            system = (
                "Tu es un expert en génération d'images IA. "
                "Transforme le prompt utilisateur en un prompt détaillé et épique en anglais, "
                "avec style, éclairage, ambiance, détails visuels. "
                "Réponds UNIQUEMENT avec le prompt amélioré, rien d'autre, pas d'explication."
            )
            improved = await _call_gemini(client, system, prompt)
            log.info("Prompt amélioré : %s → %s", prompt, improved)

            await wait_msg.edit_text(
                f"✨ *Prompt amélioré :*\n`{improved}`\n\n🎨 Génération en cours…",
                parse_mode="Markdown",
            )

            image_bytes = await _call_pollinations(client, improved)

        await update.message.reply_photo(
            photo=image_bytes,
            caption=f"✨ *{prompt}*\n\n_Prompt IA :_ `{improved[:200]}…`" if len(improved) > 200 else f"✨ *{prompt}*\n\n_Prompt IA :_ `{improved}`",
            parse_mode="Markdown",
        )
        await _post_to_channel(ctx, image_bytes, f"✨ {prompt}")

    except Exception as e:
        log.error("Erreur ameliore : %s", e)
        await update.message.reply_text(f"❌ Erreur : {e}")
    finally:
        try:
            await wait_msg.delete()
        except Exception:
            pass


async def random_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    theme = random.choice(RANDOM_THEMES)
    style_key = random.choice(list(STYLES.keys()))
    label, model, w, h = STYLES[style_key]
    full_prompt = f"{theme}, {STYLE_PROMPTS[style_key]}"

    wait_msg = await update.message.reply_text(
        f"🎲 Image surprise en cours… {label}",
        parse_mode="Markdown",
    )

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            image_bytes = await _call_pollinations(client, full_prompt, model, w, h)

        await update.message.reply_photo(
            photo=image_bytes,
            caption=f"🎲 *Image surprise !*\n_{theme}_ — {label}",
            parse_mode="Markdown",
        )
        await _post_to_channel(ctx, image_bytes, f"🎲 {theme}")
        log.info("Image random envoyée : %s [%s]", theme, style_key)

    except Exception as e:
        log.error("Erreur random : %s", e)
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
    log.info("Démarrage de JARVIS Bot…")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("help",     help_cmd))
    app.add_handler(CommandHandler("styles",   styles_cmd))
    app.add_handler(CommandHandler("image",    generate_image))
    app.add_handler(CommandHandler("imagine",  imagine))
    app.add_handler(CommandHandler("ameliore", ameliore))
    app.add_handler(CommandHandler("random",   random_image))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))
    log.info("Bot en écoute. Ctrl+C pour arrêter.")
    app.run_polling(poll_interval=1)


if __name__ == "__main__":
    main()
