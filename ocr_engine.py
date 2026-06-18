"""
OCR 引擎封装 - 使用 RapidOCR 进行图片/扫描版 PDF 文字识别
作为 MarkItDown 的补充，处理纯图片和扫描版 PDF
"""

import os
import tempfile
import threading

_lock = threading.RLock()
_engine = None
_ocr_available = None


def _get_engine():
    """懒加载 RapidOCR 实例（线程安全）"""
    global _engine, _ocr_available
    if _engine is not None:
        return _engine
    if _ocr_available is False:
        return None
    with _lock:
        if _engine is not None:
            return _engine
        try:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR()
            _ocr_available = True
            return _engine
        except ImportError:
            _ocr_available = False
            return None


def is_ocr_available():
    """检查 OCR 引擎是否可用"""
    _get_engine()
    return _ocr_available is True


def ocr_image_bytes(image_bytes, filename="image"):
    """
    识别图片字节流中的文字。

    Args:
        image_bytes: 图片的二进制内容
        filename: 原始文件名（用于临时文件命名）

    Returns:
        str: 识别出的文字，失败返回空字符串
    """
    engine = _get_engine()
    if engine is None:
        return ""

    temp_dir = tempfile.mkdtemp(prefix="llm_ocr_")
    ext = os.path.splitext(filename)[1] or ".png"
    temp_path = os.path.join(temp_dir, f"ocr_input{ext}")

    try:
        with open(temp_path, "wb") as f:
            f.write(image_bytes)

        result, _ = engine(temp_path)
        if result is None:
            return ""

        # result = [[bbox, text, confidence], ...]
        lines = [item[1] for item in result if item[1] and item[1].strip()]
        return "\n".join(lines)

    except Exception as e:
        print(f"[OCR] 图片识别失败: {e}")
        return ""

    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
        except OSError:
            pass


def ocr_pdf_scanned(pdf_path):
    """
    扫描版 PDF → 逐页 OCR → 合并文本。

    Args:
        pdf_path: PDF 文件路径

    Returns:
        str: 识别出的文字，失败返回空字符串
    """
    engine = _get_engine()
    if engine is None:
        return ""

    try:
        import pdfplumber
    except ImportError:
        print("[OCR] pdfplumber 未安装，无法处理扫描版 PDF")
        return ""

    page_texts = []
    temp_dir = tempfile.mkdtemp(prefix="llm_ocr_")

    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            # 限制最多处理 50 页
            max_pages = min(total_pages, 50)

            for i in range(max_pages):
                page = pdf.pages[i]
                # 将页面转为图片 (200 DPI)
                img = page.to_image(resolution=200)
                img_path = os.path.join(temp_dir, f"page_{i}.png")
                img.save(img_path, format="PNG")

                # OCR 识别
                result, _ = engine(img_path)
                if result:
                    lines = [item[1] for item in result if item[1] and item[1].strip()]
                    text = "\n".join(lines)
                    if text.strip():
                        page_texts.append(f"--- 第 {i + 1} 页 ---\n{text}")

                # 清理临时图片
                try:
                    os.remove(img_path)
                except OSError:
                    pass

            if total_pages > max_pages:
                page_texts.append(f"\n...(共 {total_pages} 页，已识别前 {max_pages} 页)")

    except Exception as e:
        print(f"[OCR] 扫描版 PDF 识别失败: {e}")

    finally:
        try:
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
        except OSError:
            pass

    return "\n\n".join(page_texts)


def is_image_file(filename):
    """判断文件是否为图片格式"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif'}


def is_pdf_file(filename):
    """判断文件是否为 PDF"""
    return os.path.splitext(filename)[1].lower() == '.pdf'
