# -*- coding: utf-8 -*-
# func/database/commet/parser.py
# 文档解析（移植自 Comet app/core/rag/parser.py）：提取各类文件为纯文本

import io

import chardet

from func.log.default_log import DefaultLog


class CatLearnParser:
    """文档解析：PDF / Word(docx) / Markdown / 纯文本 / HTML → 纯文本"""

    SUPPORTED_EXTS = {".pdf", ".docx", ".md", ".markdown", ".txt", ".html", ".htm"}

    def __init__(self):
        self.log = DefaultLog().getLogger()

    @staticmethod
    def _decode_text(content: bytes) -> str:
        detected = chardet.detect(content)
        encoding = detected.get("encoding") or "utf-8"
        try:
            return content.decode(encoding, errors="ignore")
        except (LookupError, UnicodeDecodeError):
            return content.decode("utf-8", errors="ignore")

    def decode_text(self, content: bytes) -> str:
        return self._decode_text(content)

    def parse_document(self, file_ext: str, content: bytes) -> str:
        """按扩展名解析二进制内容为纯文本，不支持的类型返回空串"""
        ext = (file_ext or "").lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        try:
            if ext == ".pdf":
                return self._parse_pdf(content)
            if ext == ".docx":
                return self._parse_docx(content)
            if ext in (".md", ".markdown"):
                return self._parse_markdown(content)
            if ext in (".html", ".htm"):
                return self._parse_html(content)
            if ext == ".txt":
                return self._decode_text(content)
        except Exception as e:
            self.log.warning(f"解析文档失败 ({ext}): {e}")
            return ""
        return ""

    @staticmethod
    def _parse_pdf(content: bytes) -> str:
        import fitz  # pymupdf
        parts = []
        with fitz.open(stream=content, filetype="pdf") as doc:
            for page in doc:
                parts.append(page.get_text())
        return "\n".join(parts)

    @staticmethod
    def _parse_docx(content: bytes) -> str:
        from docx import Document as DocxDocument
        doc = DocxDocument(io.BytesIO(content))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    @staticmethod
    def _parse_markdown(content: bytes) -> str:
        import markdown
        from lxml import html as lhtml
        raw = content.decode("utf-8", errors="ignore")
        html = markdown.markdown(raw)
        doc = lhtml.fromstring(html)
        return doc.text_content()

    @staticmethod
    def _parse_html(content: bytes) -> str:
        from lxml import html as lhtml
        soup = lhtml.fromstring(content.decode("utf-8", errors="ignore"))
        for tag in soup.xpath("//script | //style"):
            tag.getparent().remove(tag)
        return soup.text_content()
