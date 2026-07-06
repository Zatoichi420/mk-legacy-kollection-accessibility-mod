import asyncio
import os
import sys
from winsdk.windows.media.ocr import OcrEngine
from winsdk.windows.graphics.imaging import BitmapDecoder
from winsdk.windows.storage import StorageFile, FileAccessMode


async def ocr_image(path):
    file = await StorageFile.get_file_from_path_async(path)
    stream = await file.open_async(FileAccessMode.READ)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        print("No OCR engine available for user profile languages.")
        return None

    result = await engine.recognize_async(bitmap)
    return result


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "capture_test_output.png"
    path = os.path.abspath(path)
    result = asyncio.run(ocr_image(path))
    if result is None:
        return
    print(f"Full recognized text:\n{result.text}\n")
    print("--- lines with bounding boxes ---")
    for line in result.lines:
        words_info = []
        for word in line.words:
            rect = word.bounding_rect
            words_info.append(f"{word.text!r}@({rect.x:.0f},{rect.y:.0f},{rect.width:.0f}x{rect.height:.0f})")
        print(f"LINE: {line.text!r}  words: {words_info}")


if __name__ == "__main__":
    main()
