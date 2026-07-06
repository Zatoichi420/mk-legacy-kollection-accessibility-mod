import asyncio
import io
import os
import sys
from PIL import Image
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter


async def pil_to_software_bitmap(img: Image.Image):
    # Encode as PNG in memory - BitmapDecoder expects an encoded image
    # stream (PNG/JPEG/etc.), not a raw pixel buffer.
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    png_bytes = buf.getvalue()

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()
    return bitmap


async def ocr_pil_image(img: Image.Image):
    bitmap = await pil_to_software_bitmap(img)
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        print("No OCR engine available.")
        return None
    result = await engine.recognize_async(bitmap)
    return result


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "capture_test_output.png"
    path = os.path.abspath(path)
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0

    img = Image.open(path)
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)

    result = asyncio.run(ocr_pil_image(img))
    if result is None:
        return
    print(f"(scale={scale}) Full recognized text:\n{result.text}\n")
    for line in result.lines:
        print(f"LINE: {line.text!r}")


if __name__ == "__main__":
    main()
