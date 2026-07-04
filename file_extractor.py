"""
文件解析器 - 使用 MarkItDown + OCR 引擎处理各种格式文件
支持: PDF, Word, PowerPoint, Excel, 图片(OCR), HTML, CSV, JSON, Markdown 等
集成 chunker 语义分块，支持大文件的智能检索
文件类型分流：图片→OCR，PDF→先 MarkItDown 后 OCR 兜底，其他→MarkItDown
"""

import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from markitdown import MarkItDown
from chunker import chunk_markdown, match_chunks, is_small_file, SMALL_FILE_THRESHOLD
from config_manager import MAX_UPLOAD_SIZE
from ocr_engine import (
    ocr_image_bytes, ocr_pdf_scanned,
    is_image_file, is_pdf_file, is_ocr_available
)

logger = logging.getLogger(__name__)

_lock = threading.RLock()
_converter = None

# 支持的文件格式
SUPPORTED_EXTENSIONS = {
    '.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif',
    '.html', '.htm', '.csv', '.json', '.xml', '.txt', '.md',
    '.rtf', '.epub', '.zip'
}

# 文件大小限制 (统一来源: config_manager.MAX_UPLOAD_SIZE)
MAX_FILE_SIZE = MAX_UPLOAD_SIZE

# 扫描版 PDF 检测阈值（前 N 页平均文本字符数低于此值判定为扫描版）
SCAN_PDF_TEXT_THRESHOLD = 50


def _get_converter():
    """懒加载 MarkItDown 实例（线程安全）"""
    global _converter
    if _converter is None:
        with _lock:
            if _converter is None:
                _converter = MarkItDown()
    return _converter


def is_supported(filename):
    """检查文件格式是否支持"""
    ext = os.path.splitext(filename)[1].lower()
    return ext in SUPPORTED_EXTENSIONS


def get_supported_extensions():
    """返回支持的文件扩展名列表"""
    return sorted(SUPPORTED_EXTENSIONS)


def _is_scanned_pdf(temp_path):
    """
    判断 PDF 是否为扫描版（无文本层）。
    检查前 3 页的文本量，如果每页平均 < 50 字符则判定为扫描版。
    """
    try:
        import pdfplumber
        with pdfplumber.open(temp_path) as pdf:
            pages_to_check = min(3, len(pdf.pages))
            if pages_to_check == 0:
                return True
            total_chars = 0
            for i in range(pages_to_check):
                text = pdf.pages[i].extract_text() or ""
                total_chars += len(text.strip())
            avg_chars = total_chars / pages_to_check
            return avg_chars < SCAN_PDF_TEXT_THRESHOLD
    except ImportError:
        # pdfplumber 不可用，默认走 MarkItDown
        return False
    except Exception:
        return False


def _extract_image(file_bytes, filename, file_id=None, user_id=None, provider="", provider_file_id="", upload_mode="local"):
    """图片文件 → OCR 引擎识别"""
    if not is_ocr_available():
        return {
            "success": False,
            "error": "OCR 引擎不可用，请安装 rapidocr-onnxruntime: pip install rapidocr-onnxruntime",
            "filename": filename
        }

    text = ocr_image_bytes(file_bytes, filename)
    if not text.strip():
        return {
            "success": False,
            "error": "OCR 未能识别出文字，可能是图片质量太低或内容无文字",
            "filename": filename
        }

    return _build_result(text, filename, file_id, user_id, provider, provider_file_id, upload_mode)


def _extract_pdf(temp_path, filename, file_id=None, user_id=None, provider="", provider_file_id="", upload_mode="local"):
    """PDF 文件 → 先 MarkItDown，结果为空则 OCR 兜底"""
    try:
        converter = _get_converter()
        result = converter.convert_local(temp_path)
        text = result.text_content or ""

        if text.strip():
            # MarkItDown 成功提取到文本
            return _build_result(text, filename, file_id, user_id, provider, provider_file_id, upload_mode)

        # MarkItDown 结果为空 → 可能是扫描版 PDF
        logger.debug("PDF MarkItDown 结果为空，检测是否为扫描版: %s", filename)

    except Exception as e:
        logger.warning("PDF MarkItDown 解析失败: %s", e)

    # OCR 兜底
    if not is_ocr_available():
        return {
            "success": False,
            "error": "PDF 无法提取文本（可能是扫描版），且 OCR 引擎不可用。请安装: pip install rapidocr-onnxruntime",
            "filename": filename
        }

    logger.debug("使用 OCR 处理扫描版 PDF: %s", filename)
    text = ocr_pdf_scanned(temp_path)
    if not text.strip():
        return {
            "success": False,
            "error": "PDF 解析和 OCR 均未能提取到文字",
            "filename": filename
        }

    return _build_result(text, filename, file_id, user_id, provider, provider_file_id, upload_mode)


def _extract_generic(temp_path, filename, file_id=None, user_id=None, provider="", provider_file_id="", upload_mode="local"):
    """其他文件 → MarkItDown"""
    try:
        converter = _get_converter()
        result = converter.convert_local(temp_path)
        text = result.text_content or ""

        if not text.strip():
            return {
                "success": False,
                "error": "文件解析结果为空",
                "filename": filename
            }

        return _build_result(text, filename, file_id, user_id, provider, provider_file_id, upload_mode)

    except Exception as e:
        return {
            "success": False,
            "error": f"文件解析失败: {str(e)}",
            "filename": filename
        }


def _build_result(text, filename, file_id=None, user_id=None, provider="", provider_file_id="", upload_mode="local"):
    """统一构建返回结果（小文件全文 / 大文件分块）"""
    if is_small_file(text):
        # 小文件：不分块，直接存全文到数据库（若有 user_id）
        if user_id:
            from database import create_document, save_chunks, delete_document, find_document_by_filename
            existing = find_document_by_filename(user_id, filename)
            if existing:
                return {
                    "success": False,
                    "error": f"文件 \"{filename}\" 已存在，请勿重复上传",
                    "filename": filename,
                    "duplicate": True,
                    "existing_document_id": existing["id"]
                }
            doc_id = create_document(user_id, filename, file_size=len(text.encode("utf-8")), chunk_count=1,
                                     provider=provider, provider_file_id=provider_file_id, upload_mode=upload_mode)
            if doc_id is None:
                return {
                    "success": False,
                    "error": f"文件 \"{filename}\" 已存在，请勿重复上传",
                    "filename": filename,
                    "duplicate": True
                }
            # 小文件存为一个特殊 chunk
            try:
                save_chunks(doc_id, [{"text": text, "heading": "全文", "hierarchy": []}])
            except Exception as e:
                print(f"[FileExtractor] 小文件分块保存失败，回滚文档记录: {e}")
                delete_document(doc_id, user_id)
                return {
                    "success": False,
                    "error": f"文件解析成功但存储失败: {str(e)}",
                    "filename": filename
                }
            return {
                "success": True,
                "text": text,
                "filename": filename,
                "is_large": False,
                "document_id": doc_id
            }
        return {
            "success": True,
            "text": text,
            "filename": filename,
            "is_large": False,
            "file_id": None
        }

    # 大文件：分块
    chunks = chunk_markdown(text)

    if user_id:
        # 持久化到数据库（同步保存分块 + 计算向量，确保检索立即可用）
        from database import create_document, save_chunks, delete_document, find_document_by_filename
        existing = find_document_by_filename(user_id, filename)
        if existing:
            return {
                "success": False,
                "error": f"文件 \"{filename}\" 已存在，请勿重复上传",
                "filename": filename,
                "duplicate": True,
                "existing_document_id": existing["id"]
            }
        doc_id = create_document(
            user_id, filename,
            file_size=len(text.encode("utf-8")),
            chunk_count=len(chunks),
            provider=provider,
            provider_file_id=provider_file_id,
            upload_mode=upload_mode
        )
        if doc_id is None:
            return {
                "success": False,
                "error": f"文件 \"{filename}\" 已存在，请勿重复上传",
                "filename": filename,
                "duplicate": True
            }
        try:
            save_chunks(doc_id, chunks)
        except Exception as e:
            print(f"[FileExtractor] 大文件分块保存失败，回滚文档记录: {e}")
            delete_document(doc_id, user_id)
            return {
                "success": False,
                "error": f"文件解析成功但存储失败: {str(e)}",
                "filename": filename
            }

        preview_text = text[:3000].rstrip()
        return {
            "success": True,
            "text": f"(文件较大，已分为 {len(chunks)} 个段落，请描述你想了解的内容)",
            "filename": filename,
            "is_large": True,
            "document_id": doc_id,
            "chunk_count": len(chunks),
            "preview": preview_text
        }

    # 无 user_id（未登录路径）— 走原有内存缓存逻辑
    if file_id:
        _cache_put(file_id, chunks, filename)

    preview_text = text[:3000].rstrip()
    return {
        "success": True,
        "text": f"(文件较大，已分为 {len(chunks)} 个段落，请描述你想了解的内容)",
        "filename": filename,
        "is_large": True,
        "file_id": file_id,
        "chunk_count": len(chunks),
        "preview": preview_text
    }


# ============================================================
# 主入口
# ============================================================

def extract_text_only(file_storage):
    """
    聊天附件专用：只解析文件全文，不分块、不入库、不缓存。
    返回 {"success": True, "text": ..., "filename": ...} 或错误。
    """
    filename = file_storage.filename
    if not filename:
        return {"success": False, "error": "文件名为空", "filename": ""}
    if not is_supported(filename):
        ext = os.path.splitext(filename)[1] or '(无扩展名)'
        return {"success": False, "error": f"不支持的文件格式: {ext}", "filename": filename}

    file_bytes = file_storage.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        size_mb = len(file_bytes) / (1024 * 1024)
        return {"success": False, "error": f"文件过大 ({size_mb:.1f}MB)", "filename": filename}
    if len(file_bytes) == 0:
        return {"success": False, "error": "文件为空", "filename": filename}

    # 图片 → OCR
    if is_image_file(filename):
        if not is_ocr_available():
            return {"success": False, "error": "OCR 引擎不可用", "filename": filename}
        text = ocr_image_bytes(file_bytes, filename)
        if not text.strip():
            return {"success": False, "error": "OCR 未能识别出文字", "filename": filename}
        return {"success": True, "text": text, "filename": filename}

    # 其他文件 → 临时文件 + MarkItDown
    temp_dir = tempfile.mkdtemp(prefix="llm_chat_")
    temp_path = os.path.join(temp_dir, filename)
    try:
        with open(temp_path, "wb") as f:
            f.write(file_bytes)

        converter = _get_converter()
        result = converter.convert_local(temp_path)
        text = result.text_content or ""

        # PDF 兜底：MarkItDown 结果为空时尝试 OCR
        if not text.strip() and is_pdf_file(filename):
            if is_ocr_available():
                text = ocr_pdf_scanned(temp_path)

        if not text.strip():
            return {"success": False, "error": "文件解析结果为空", "filename": filename}

        return {"success": True, "text": text, "filename": filename}
    except Exception as e:
        return {"success": False, "error": f"文件解析失败: {str(e)}", "filename": filename}
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
        except OSError:
            pass



def extract_and_cache_chunks(file_storage, user_id=None, provider="", provider_file_id="", upload_mode="local"):
    """
    解析文件并缓存分块结果。
    文件类型分流：
      - 图片 → OCR 引擎
      - PDF → MarkItDown，结果为空则 OCR 兜底
      - 其他 → MarkItDown

    user_id: 如果提供，则持久化到数据库；否则走内存缓存（兼容旧逻辑）。
    """
    import uuid
    file_id = uuid.uuid4().hex[:12]

    filename = file_storage.filename
    if not filename:
        return {"success": False, "error": "文件名为空", "filename": ""}

    if not is_supported(filename):
        ext = os.path.splitext(filename)[1] or '(无扩展名)'
        return {"success": False, "error": f"不支持的文件格式: {ext}", "filename": filename}

    file_bytes = file_storage.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        size_mb = len(file_bytes) / (1024 * 1024)
        return {"success": False, "error": f"文件过大 ({size_mb:.1f}MB)", "filename": filename}

    if len(file_bytes) == 0:
        return {"success": False, "error": "文件为空", "filename": filename}

    # 文件类型分流
    if is_image_file(filename):
        # 图片 → 直接 OCR
        return _extract_image(file_bytes, filename, file_id, user_id,
                              provider=provider, provider_file_id=provider_file_id, upload_mode=upload_mode)

    if is_pdf_file(filename):
        # PDF → 保存临时文件 → MarkItDown + OCR 兜底
        temp_dir = tempfile.mkdtemp(prefix="llm_chat_")
        temp_path = os.path.join(temp_dir, filename)
        try:
            with open(temp_path, "wb") as f:
                f.write(file_bytes)
            return _extract_pdf(temp_path, filename, file_id, user_id,
                                provider=provider, provider_file_id=provider_file_id, upload_mode=upload_mode)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except OSError:
                pass

    # 其他文件 → MarkItDown
    temp_dir = tempfile.mkdtemp(prefix="llm_chat_")
    temp_path = os.path.join(temp_dir, filename)
    try:
        with open(temp_path, "wb") as f:
            f.write(file_bytes)
        return _extract_generic(temp_path, filename, file_id, user_id,
                                provider=provider, provider_file_id=provider_file_id, upload_mode=upload_mode)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
        except OSError:
            pass


def extract_from_file(file_storage):
    """
    从 Flask FileStorage 对象提取文本内容（简化版，用于兼容旧接口）。
    """
    result = extract_and_cache_chunks(file_storage)
    if result.get("success"):
        return {
            "success": True,
            "text": result.get("text", ""),
            "filename": result.get("filename", "")
        }
    return result


# ============================================================
# 分块检索 — TTL + LRU 缓存（兼容旧接口）
# ============================================================

_CACHE_TTL = 3600        # 条目存活时间：1 小时（秒）
_CACHE_MAX_SIZE = 50     # 最大缓存条目数（LRU 淘汰）

_chunk_cache: OrderedDict = OrderedDict()   # key → {chunks, filename, expire_at}
_chunk_cache_lock = threading.RLock()


def _cache_put(file_id: str, chunks, filename: str):
    """写入缓存，维护 LRU 顺序与 TTL"""
    expire_at = time.monotonic() + _CACHE_TTL
    with _chunk_cache_lock:
        # 若 key 已存在，先移除（保证最新在末尾）
        _chunk_cache.pop(file_id, None)
        _chunk_cache[file_id] = {"chunks": chunks, "filename": filename, "expire_at": expire_at}
        # 超出容量时淘汰最旧条目
        while len(_chunk_cache) > _CACHE_MAX_SIZE:
            _chunk_cache.popitem(last=False)


def _cache_get(file_id: str):
    """读取缓存；已过期则删除并返回 None"""
    with _chunk_cache_lock:
        entry = _chunk_cache.get(file_id)
        if entry is None:
            return None
        if time.monotonic() > entry["expire_at"]:
            _chunk_cache.pop(file_id, None)
            return None
        # LRU：移到末尾
        _chunk_cache.move_to_end(file_id)
        return entry


def search_cached_chunks(file_id=None, document_id=None, document_ids=None, query="", user_id=None, top_k=5):
    """
    检索与查询相关的文档分块。
    优先使用向量语义检索（若 document_id(s) 存在），回退到关键词匹配。

    支持单文档 (document_id) 或多文档 (document_ids 数组) 批量检索。
    """
    from database import get_document, get_chunks_by_document, search_chunks_by_embedding
    from cache_manager import get_embedding

    # 防御性校验 top_k
    try:
        top_k = max(1, min(int(top_k or 5), 50))
    except (TypeError, ValueError):
        top_k = 5

    # 归一化 document_ids（过滤非字符串和空值）
    ids = []
    if document_ids:
        ids = [str(d) for d in document_ids if d and isinstance(d, str) and len(d) <= 100]
        if len(ids) > 50:
            ids = ids[:50]
    elif document_id:
        ids = [document_id]

    # 空查询：直接返回前 N 个分块作为预览
    if not query:
        all_preview_chunks = []
        for did in ids:
            try:
                chunks = get_chunks_by_document(did)
                for c in chunks[:max(1, top_k // max(1, len(ids)))]:
                    all_preview_chunks.append(c)
            except Exception as e:
                print(f"[Search] 获取文档分块异常: {did} - {e}")
        if all_preview_chunks:
            context_parts = []
            for m in all_preview_chunks[:top_k]:
                hierarchy_str = " > ".join(m.get("hierarchy", [])) if m.get("hierarchy") else "正文"
                context_parts.append(f"[{hierarchy_str}]\n{m['text']}")
            context = "\n\n---\n\n".join(context_parts)
            return context, None
        # 尝试旧版缓存路径
        if file_id:
            entry = _cache_get(file_id)
            if entry:
                chunks = entry["chunks"]
                preview_chunks = chunks[:top_k]
                context_parts = []
                for m in preview_chunks:
                    hierarchy_str = " > ".join(m.get("hierarchy", [])) if m.get("hierarchy") else "正文"
                    context_parts.append(f"[{hierarchy_str}]\n{m['text']}")
                context = "\n\n---\n\n".join(context_parts)
                return context, None
        return None, "查询内容为空"

    # 新版：基于 document_id(s) 的向量检索
    if ids:
        # 验证权限（DB 异常时跳过该文档而非崩溃）
        valid_ids = []
        for did in ids:
            try:
                doc = get_document(did, user_id)
                if doc:
                    valid_ids.append(did)
                else:
                    print(f"[Search] 文档不存在或无权限: {did}")
            except Exception as e:
                print(f"[Search] 验证文档权限异常，跳过: {did} - {e}")

        if not valid_ids:
            return None, "文档不存在或无权限"

        query_vector = get_embedding(query)
        if query_vector:
            results = search_chunks_by_embedding(query_vector, document_ids=valid_ids, top_k=top_k)
        else:
            results = []

        # 向量检索无结果时，回退到关键词匹配（兼容 embedding 为 NULL 的旧数据）
        if not results:
            chunk_doc_map = {}  # (text, heading) → document_id
            all_chunks = []
            for did in valid_ids:
                chunks = get_chunks_by_document(did)
                for c in chunks:
                    chunk_doc_map[(c.get("text", ""), c.get("heading", ""))] = did
                all_chunks.extend(chunks)
            from chunker import match_chunks
            results = match_chunks(all_chunks, query, max_results=top_k)
            for r in results:
                key = (r.get("text", ""), r.get("heading", ""))
                r["document_id"] = chunk_doc_map.get(key, valid_ids[0])

        if not results:
            return None, "未找到与问题相关的内容"

        # 预加载文档名映射（用于多文档来源标注）
        doc_name_map = {}
        if len(valid_ids) > 1:
            for did in valid_ids:
                try:
                    doc = get_document(did, user_id)
                    if doc:
                        doc_name_map[did] = doc.get("filename", did[:8])
                except Exception:
                    doc_name_map[did] = did[:8]

        context_parts = []
        for m in results:
            hierarchy_str = " > ".join(m.get("hierarchy", [])) if m.get("hierarchy") else "正文"
            score_info = f" (相关度: {m.get('score', 0):.2f})" if m.get("score") else ""
            # 多文档时标注来源文件名
            doc_label = ""
            if len(valid_ids) > 1 and m.get("document_id"):
                fname = doc_name_map.get(m["document_id"], m["document_id"][:8])
                doc_label = f" [来源: {fname}]"
            context_parts.append(f"[{hierarchy_str}]{doc_label}{score_info}\n{m['text']}")

        context = "\n\n---\n\n".join(context_parts)
        return context, None

    # 旧版：内存缓存 + 关键词匹配（兼容路径）
    entry = _cache_get(file_id)
    if not entry:
        return None, "文件缓存已过期，请重新上传"

    chunks = entry["chunks"]
    from chunker import match_chunks
    matched = match_chunks(chunks, query, max_results=top_k)

    if not matched:
        return None, "未找到与问题相关的内容"

    context_parts = []
    for m in matched:
        hierarchy_str = " > ".join(m["hierarchy"]) if m["hierarchy"] else "正文"
        context_parts.append(f"[{hierarchy_str}]\n{m['text']}")

    context = "\n\n---\n\n".join(context_parts)
    return context, None


def clear_chunk_cache(file_id=None):
    """清除分块缓存"""
    with _chunk_cache_lock:
        if file_id:
            _chunk_cache.pop(file_id, None)
        else:
            _chunk_cache.clear()
