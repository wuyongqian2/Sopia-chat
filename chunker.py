"""
Markdown 语义分块器 - 按标题层级将长文本切分为语义块
用于大文件的 RAG 检索增强：分块 → 关键词匹配 → 注入相关块
"""

import re

# 小文件阈值：低于此长度直接全文注入，不分块
SMALL_FILE_THRESHOLD = 15000

# 单块最大字符数（防止某个章节过长）
MAX_CHUNK_SIZE = 8000

# 关键词匹配时返回的最大块数
MAX_MATCHED_CHUNKS = 5


def chunk_markdown(md_text: str) -> list:
    """
    将 Markdown 文本按标题层级切分为语义块。

    Args:
        md_text: MarkItDown 解析后的 Markdown 文本

    Returns:
        list[dict]: [
            {
                "text": "块文本内容",
                "hierarchy": ["一级标题", "二级标题"],
                "heading": "当前块的标题",
                "level": 1,  # 标题层级 (1-6, 0=无标题)
                "index": 0   # 块序号
            },
            ...
        ]
    """
    if not md_text or not md_text.strip():
        return []

    # 预处理：保护代码块不被标题分割
    code_blocks = []
    protected_text = md_text

    def _save_code_block(match):
        idx = len(code_blocks)
        code_blocks.append(match.group(0))
        return f"\n__CODE_BLOCK_{idx}__\n"

    protected_text = re.sub(
        r'```[\s\S]*?```',
        _save_code_block,
        protected_text
    )

    # 按标题分割
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    matches = list(heading_pattern.finditer(protected_text))

    chunks = []
    current_hierarchy = []  # 跟踪标题层级栈
    chunk_index = 0

    if not matches:
        # 没有标题 → 整篇作为一个块
        restored = _restore_code_blocks(protected_text, code_blocks)
        if restored.strip():
            chunks.append({
                "text": restored.strip(),
                "hierarchy": [],
                "heading": "",
                "level": 0,
                "index": chunk_index
            })
        return chunks

    # 处理标题前的无标题内容
    preamble = protected_text[:matches[0].start()].strip()
    if preamble:
        restored = _restore_code_blocks(preamble, code_blocks)
        if restored.strip():
            chunks.append({
                "text": restored.strip(),
                "hierarchy": [],
                "heading": "",
                "level": 0,
                "index": chunk_index
            })
            chunk_index += 1

    # 逐标题切分
    for i, match in enumerate(matches):
        level = len(match.group(1))  # # = 1, ## = 2, ...
        heading = match.group(2).strip()

        # 计算当前块的文本范围
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(protected_text)
        block_text = protected_text[start:end].strip()

        # 更新层级栈：弹出同级或更低级的标题
        while current_hierarchy and current_hierarchy[-1][0] >= level:
            current_hierarchy.pop()
        current_hierarchy.append((level, heading))

        # 构建层级路径
        hierarchy = [h[1] for h in current_hierarchy]

        # 恢复代码块
        restored = _restore_code_blocks(block_text, code_blocks)

        # 如果块太大，按段落拆分
        sub_chunks = _split_large_chunk(restored, MAX_CHUNK_SIZE)
        for sub_text in sub_chunks:
            if sub_text.strip():
                chunks.append({
                    "text": sub_text.strip(),
                    "hierarchy": hierarchy[:],
                    "heading": heading,
                    "level": level,
                    "index": chunk_index
                })
                chunk_index += 1

    return chunks


def _restore_code_blocks(text: str, code_blocks: list) -> str:
    """恢复被保护的代码块"""
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"__CODE_BLOCK_{idx}__", block)
    return text


def _split_large_chunk(text: str, max_size: int, context_anchor: bool = True) -> list:
    """
    将过大的块按段落拆分，携带前一段最后一句作为上下文锚点。

    Args:
        text: 待拆分的文本
        max_size: 单块最大字符数
        context_anchor: 是否启用上下文锚点（默认开启）
    """
    if len(text) <= max_size:
        return [text]

    paragraphs = re.split(r'\n\n+', text)
    result = []
    current = ""
    prev_anchor = ""  # 前一段的最后一句，作为下一块的上下文锚点

    for para in paragraphs:
        # 提取本段最后一句，作为下一块的锚点
        anchor = ""
        if context_anchor:
            sentences = re.split(r'(?<=[。；.;\n])\s*', para.strip())
            # 取最后一句（至少 10 字才算有效上下文，过滤列表序号等噪声）
            if sentences:
                last = sentences[-1].strip()
                if len(last) >= 10:
                    anchor = last

        trial = current + "\n\n" + para if current else para

        if len(trial) > max_size and current:
            result.append(current)
            # 新块开头带上前一段的锚点句作为上下文提示
            if prev_anchor:
                current = f"…{prev_anchor}\n\n{para}"
            else:
                current = para
        else:
            current = trial

        prev_anchor = anchor

    if current:
        result.append(current)

    return result


def match_chunks(chunks: list, query: str, max_results: int = MAX_MATCHED_CHUNKS) -> list:
    """
    基于关键词匹配从分块中检索相关块。

    Args:
        chunks: chunk_markdown 返回的分块列表
        query: 用户查询/问题
        max_results: 最多返回的块数

    Returns:
        list[dict]: 按相关度排序的匹配块，每块新增 "score" 字段
    """
    if not chunks or not query:
        return chunks[:max_results] if chunks else []

    # 提取查询关键词（中文按字/词切分，英文按空格切分）
    keywords = _extract_keywords(query)
    if not keywords:
        return chunks[:max_results]

    # 计算每个块的相关度分数
    scored = []
    for chunk in chunks:
        text_lower = chunk["text"].lower()
        heading_lower = chunk["heading"].lower()

        score = 0
        for kw in keywords:
            kw_lower = kw.lower()
            # 标题匹配权重更高
            if kw_lower in heading_lower:
                score += 3
            # 正文匹配
            count = text_lower.count(kw_lower)
            score += min(count, 5)  # 单词最多加 5 分，防止长文垄断

        if score > 0:
            scored.append({**chunk, "score": score})

    # 按分数降序排列
    scored.sort(key=lambda x: x["score"], reverse=True)

    # 如果没有匹配到任何块，返回前 N 个块（保持顺序）
    if not scored:
        return [{**c, "score": 0} for c in chunks[:max_results]]

    return scored[:max_results]


def _extract_keywords(text: str) -> list:
    """
    从文本中提取关键词。
    中文：按字符 + 连续中文词提取
    英文：按空格分词
    """
    keywords = []

    # 提取英文单词（3+ 字符）
    en_words = re.findall(r'[a-zA-Z]{3,}', text)
    keywords.extend(en_words)

    # 提取中文连续字符（2+ 字）
    cn_words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    keywords.extend(cn_words)

    # 提取中英文混合的关键术语
    mixed = re.findall(r'[a-zA-Z\u4e00-\u9fff]+', text)
    keywords.extend([w for w in mixed if len(w) >= 2])

    # 去重
    seen = set()
    unique = []
    for kw in keywords:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            unique.append(kw)

    return unique


def is_small_file(text: str) -> bool:
    """判断文件是否为小文件（可直接全文注入）"""
    return len(text) <= SMALL_FILE_THRESHOLD
