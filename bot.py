import os
import logging
import tempfile
import asyncio
from PIL import Image, ImageOps
from pyrogram import Client, filters
import fitz  # PyMuPDF
from PyPDF2 import PdfWriter

# ==== SETUP ====
API_ID = 1234567  # <<<--- Apna API_ID yaha daale (my.telegram.org se)
API_HASH = "your_real_api_hash"  # <<<--- Apna API_HASH daale (my.telegram.org se)
BOT_TOKEN = "8489119024:AAEHTivjIaozGbF3PgJwIa2r3j85-qxQemQ"
MAX_SIZE_MB = 45    # Telegram 50MB se thoda kam
MIN_DPI = 60

logging.basicConfig(level=logging.INFO)

bot = Client(
    "invertpdf-bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# PDF filter (har pyrogram version me chalega)
def is_pdf(_, __, message):
    return (
        bool(message.document) and (
            (message.document.mime_type and "pdf" in message.document.mime_type.lower())
            or (message.document.file_name and message.document.file_name.lower().endswith(".pdf"))
        )
    )
pdf_filter = filters.create(is_pdf)

class ProgressHolder:
    def __init__(self):
        self.progress = 0
        self.done = False

def get_adaptive_dpi(file_size_mb):
    if file_size_mb < 5:
        return 150
    elif file_size_mb < 20:
        return 120
    elif file_size_mb < 50:
        return 90
    else:
        return MIN_DPI

def invert_pdf(input_pdf, output_pdf, dpi, progress_holder):
    with fitz.open(input_pdf) as doc:
        img_folder = tempfile.mkdtemp()
        total = len(doc)
        image_list = []
        for i, page in enumerate(doc.pages()):
            img_path = os.path.join(img_folder, f"page_{i:04d}.png")
            pix = page.get_pixmap(dpi=dpi)
            pix.save(img_path)
            image_list.append(img_path)
            progress_holder.progress = int((i+1)/total*40)
        inverted_imgs = []
        for i, imgf in enumerate(image_list):
            img = Image.open(imgf)
            inv_img = ImageOps.invert(img.convert("RGB"))
            inv_path = imgf.replace(".png", "_inv.png")
            inv_img.save(inv_path)
            inverted_imgs.append(inv_path)
            img.close()
            progress_holder.progress = 40 + int((i+1)/total*30)
        cover = Image.open(inverted_imgs[0]).convert("RGB")
        rest = [Image.open(f).convert("RGB") for f in inverted_imgs[1:]]
        cover.save(output_pdf, save_all=True, append_images=rest)
        progress_holder.progress = 90
        for f in image_list + inverted_imgs:
            os.remove(f)
        os.rmdir(img_folder)
        progress_holder.progress = 100
        progress_holder.done = True

def split_pdf(input_pdf, max_size_mb=MAX_SIZE_MB):
    with fitz.open(input_pdf) as doc:
        page_count = len(doc)
        temp_files = []
        temp_dir = tempfile.mkdtemp()
        part = 1
        idx = 0
        while idx < page_count:
            writer = PdfWriter()
            page_in_part = 0
            size_estimate = 0
            while idx < page_count and size_estimate < (max_size_mb * 1024 * 1024):
                page = doc[idx]
                writer.add_page(fitz.open(stream=page.get_pdf_bytes()))
                buf = page.get_pixmap(matrix=fitz.Matrix(0.3, 0.3)).tobytes("png")
                size_estimate += len(buf)
                idx += 1
                page_in_part += 1
                if size_estimate > (max_size_mb * 1024 * 1024):
                    break
            out_path = os.path.join(temp_dir, f"part_{part}.pdf")
            with open(out_path, "wb") as fout:
                writer.write(fout)
            temp_files.append(out_path)
            part += 1
    return temp_files

@bot.on_message(filters.command("start"))
async def handle_start(client, msg):
    await msg.reply(
        "🙏 Ram Ram Bhai!\n"
        "Harsh ka banaya bot me swagat hai 🚩\n"
        "Apna PDF file bheje aur mai uska color invert karke dedunga! "
        "Size bada hua toh split karke bhi de sakta hoon.\n"
        "Aapka kaam progress ke saath update hota rahega har 4 sec! 😎"
    )

@bot.on_message(pdf_filter)
async def handle_pdf(client, msg):
    await msg.reply("PDF mil gaya! Download kar raha hoon...")
    pdf_file = await msg.download()
    size_mb = os.path.getsize(pdf_file) / (1024 * 1024)
    dpi = get_adaptive_dpi(size_mb)
    await msg.reply(f"PDF size: {size_mb:.1f} MB, DPI set: {dpi}")
    progress_holder = ProgressHolder()

    async def progress_updater(progress_msg):
        last_progress = -1
        while not progress_holder.done:
            current_progress = progress_holder.progress
            if current_progress != last_progress:
                await progress_msg.edit_text(f"Processing... {current_progress}% complete")
                last_progress = current_progress
            await asyncio.sleep(4)
        if last_progress != 100:
            await progress_msg.edit_text("Processing... 100% complete! 🚩")

    try:
        progress_msg = await msg.reply("Processing... 0% complete")
        updater_task = asyncio.create_task(progress_updater(progress_msg))

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as fout:
            fout.close()
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, invert_pdf, pdf_file, fout.name, dpi, progress_holder
            )
            out_size_mb = os.path.getsize(fout.name) / (1024 * 1024)
            if out_size_mb > MAX_SIZE_MB:
                parts = split_pdf(fout.name)
                await progress_msg.reply(
                    "Sorry, Telegram file size limit ke wajah se PDF split karna pada. "
                    'Merge karne ke liye "https://www.ilovepdf.com/desktop" use kar sakte hain. Thanks for understanding!'
                )
                for i, pf in enumerate(parts, 1):
                    await msg.reply_document(pf, caption=f"Inverted PDF (Part {i})")
                    os.remove(pf)
            else:
                await msg.reply_document(fout.name, caption="Color-inverted PDF ready hai bhai! 🙏")
            os.remove(fout.name)
        await updater_task
    except Exception as e:
        await msg.reply(f"Error: {str(e)}\nTry chhota/simple PDF ya image!")
    finally:
        try:
            os.remove(pdf_file)
        except:
            pass

if __name__ == "__main__":
    print("🚩 Ultimate Telegram PDF Inverter by Harsh | Jarvis Mode")
    bot.run()
