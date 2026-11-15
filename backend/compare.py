"""Compare two versions of a file. No web code in here: bytes in, a plain dictionary out.

Text, Word, PowerPoint and PDF files are turned into lines of text and compared line by line (changed lines also
show which words changed). Excel files are compared cell by cell. Pictures are compared pixel by pixel. Any other
file is compared by size and checksum.
"""
import base64
import difflib
import hashlib
import io
import re
from typing import Dict, List, Optional, Tuple

TEXT_EXTS = {"txt", "md", "csv", "tsv", "json", "xml", "html", "htm", "css", "js", "ts", "py", "java", "c", "cpp", "h",
             "cs", "go", "rs", "rb", "php", "sql", "yml", "yaml", "toml", "ini", "cfg", "log", "sh", "bat", "ps1", "rtf"}
IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
MAX_LINES = 20000            # more lines than this are cut before comparing
MAX_ROWS = 1500              # rows sent back to the screen
CONTEXT = 2                  # unchanged lines kept around every change
MAX_CELLS = 200000


def ext_of(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# ------------------------------------------------------------------ turning files into lines
def _lines_text(data: bytes) -> List[str]:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(enc).splitlines()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", "replace").splitlines()


def _looks_like_text(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _lines_docx(data: bytes) -> List[str]:
    import docx
    d = docx.Document(io.BytesIO(data))
    out: List[str] = []
    body = d.element.body
    paragraphs = {p._p: p for p in d.paragraphs}
    tables = {t._tbl: t for t in d.tables}
    for el in body.iterchildren():
        if el in paragraphs:
            p = paragraphs[el]
            style = p.style.name if p.style is not None else ""
            text = p.text
            if style.lower().startswith("heading") and text.strip():
                text = "[%s] %s" % (style, text)
            out.append(text)
        elif el in tables:
            for row in tables[el].rows:
                out.append("[table] " + " | ".join(c.text.replace("\n", " ") for c in row.cells))
    return out


def _lines_pptx(data: bytes) -> List[str]:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    out: List[str] = []
    for i, slide in enumerate(prs.slides, 1):
        out.append("--- Slide %d ---" % i)
        for shape in slide.shapes:
            if shape.has_text_frame:
                for p in shape.text_frame.paragraphs:
                    out.append("".join(r.text for r in p.runs))
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    out.append("[table] " + " | ".join(c.text for c in row.cells))
    return out


def _lines_pdf(data: bytes) -> List[str]:
    import fitz
    out: List[str] = []
    with fitz.open(stream=data, filetype="pdf") as pdf:
        for i, page in enumerate(pdf, 1):
            out.append("--- Page %d ---" % i)
            out.extend(l.rstrip() for l in page.get_text().splitlines())
    return out


# ------------------------------------------------------------------ the line comparison
_TOKEN = re.compile(r"\s+|\w+|[^\w\s]")


def _segments(a: str, b: str) -> Tuple[list, list]:
    """Mark which words of two changed lines differ: ([[text, changed], ...], [[text, changed], ...])."""
    if len(a) > 2000 or len(b) > 2000:
        return [[a, True]], [[b, True]]
    ta, tb = _TOKEN.findall(a), _TOKEN.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    sa: list = []
    sb: list = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            sa.append(["".join(ta[i1:i2]), False])
            sb.append(["".join(tb[j1:j2]), False])
        else:
            if i2 > i1:
                sa.append(["".join(ta[i1:i2]), True])
            if j2 > j1:
                sb.append(["".join(tb[j1:j2]), True])
    return sa, sb


def _pair_block(la, lb, i1, i2, j1, j2, replace: bool):
    """Inside a block of changed lines, pair each old line with the new line that looks most like it (in order).
    Lines left without a partner are shown as removed or added. Yields (kind, a_index, b_index)."""
    na, nb = i2 - i1, j2 - j1
    if not replace:
        for i in range(i1, i2):
            yield "del", i, None
        for j in range(j1, j2):
            yield "add", None, j
        return
    if na * nb > 10000:                                   # a very large block: pair by position
        pair = min(na, nb)
        for k in range(pair):
            yield "chg", i1 + k, j1 + k
        for i in range(i1 + pair, i2):
            yield "del", i, None
        for j in range(j1 + pair, j2):
            yield "add", None, j
        return
    j = j1
    for i in range(i1, i2):
        best, best_j = 0.0, None
        for jj in range(j, j2):
            ratio = difflib.SequenceMatcher(None, la[i], lb[jj], autojunk=False).ratio()
            if ratio > best:
                best, best_j = ratio, jj
        if best_j is not None and best >= 0.45:
            for jj in range(j, best_j):
                yield "add", None, jj
            yield "chg", i, best_j
            j = best_j + 1
        else:
            yield "del", i, None
    for jj in range(j, j2):
        yield "add", None, jj


def diff_lines(la: List[str], lb: List[str]) -> dict:
    cut = len(la) > MAX_LINES or len(lb) > MAX_LINES
    la, lb = la[:MAX_LINES], lb[:MAX_LINES]
    sm = difflib.SequenceMatcher(None, la, lb, autojunk=False)
    rows: List[dict] = []
    added = removed = changed = 0
    ops = sm.get_opcodes()
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            span = i2 - i1
            first, last = n == 0, n == len(ops) - 1
            keep_head = 0 if first else CONTEXT
            keep_tail = 0 if last else CONTEXT
            if span <= keep_head + keep_tail + 1:
                idx = list(range(span))
            else:
                idx = list(range(keep_head)) + [None] + list(range(span - keep_tail, span))
            for k in idx:
                if k is None:
                    rows.append({"tag": "skip", "count": span - keep_head - keep_tail})
                else:
                    rows.append({"tag": "equal", "a_no": i1 + k + 1, "b_no": j1 + k + 1, "a": la[i1 + k], "b": lb[j1 + k]})
        else:
            for kind, i, j in _pair_block(la, lb, i1, i2, j1, j2, tag == "replace"):
                if kind == "chg":
                    sa, sb = _segments(la[i], lb[j])
                    rows.append({"tag": "chg", "a_no": i + 1, "b_no": j + 1, "a": la[i], "b": lb[j], "a_seg": sa, "b_seg": sb})
                    changed += 1
                elif kind == "del":
                    rows.append({"tag": "del", "a_no": i + 1, "b_no": None, "a": la[i], "b": ""})
                    removed += 1
                else:
                    rows.append({"tag": "add", "a_no": None, "b_no": j + 1, "a": "", "b": lb[j]})
                    added += 1
    truncated = cut or len(rows) > MAX_ROWS
    return {"rows": rows[:MAX_ROWS], "truncated": truncated,
            "stats": {"added": added, "removed": removed, "changed": changed},
            "identical": added == removed == changed == 0}


# ------------------------------------------------------------------ Excel
def _cell_map(data: bytes) -> Dict[Tuple[str, str], object]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=False)
    cells: Dict[Tuple[str, str], object] = {}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None and c.value != "":
                    cells[(ws.title, c.coordinate)] = c.value
                    if len(cells) > MAX_CELLS:
                        return cells
    return cells


def _cell_key(k: Tuple[str, str]):
    m = re.match(r"([A-Z]+)(\d+)", k[1])
    col = 0
    for ch in m.group(1):
        col = col * 26 + ord(ch) - 64
    return (k[0], int(m.group(2)), col)


def diff_sheets(a: bytes, b: bytes) -> dict:
    ca, cb = _cell_map(a), _cell_map(b)
    rows: List[dict] = []
    added = removed = changed = 0
    for k in sorted(set(ca) | set(cb), key=_cell_key):
        va, vb = ca.get(k), cb.get(k)
        if va == vb:
            continue
        label = "%s!%s" % k
        if va is None:
            rows.append({"tag": "add", "label": label, "a": "", "b": str(vb)})
            added += 1
        elif vb is None:
            rows.append({"tag": "del", "label": label, "a": str(va), "b": ""})
            removed += 1
        else:
            sa, sb = _segments(str(va), str(vb))
            rows.append({"tag": "chg", "label": label, "a": str(va), "b": str(vb), "a_seg": sa, "b_seg": sb})
            changed += 1
    return {"rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS,
            "stats": {"added": added, "removed": removed, "changed": changed},
            "identical": not rows}


# ------------------------------------------------------------------ pictures
def diff_images(a: bytes, b: bytes) -> dict:
    from PIL import Image, ImageChops
    ia = Image.open(io.BytesIO(a))
    ib = Image.open(io.BytesIO(b))
    ia.load()
    ib.load()
    out = {"dims_a": list(ia.size), "dims_b": list(ib.size), "same_dimensions": ia.size == ib.size,
           "changed_percent": None, "diff_image": None}
    if ia.size != ib.size:
        out["identical"] = False
        return out
    ra, rb = ia.convert("RGBA"), ib.convert("RGBA")
    delta = ImageChops.difference(ra, rb).convert("L")
    mask = delta.point(lambda v: 255 if v > 24 else 0)
    changed = sum(1 for v in mask.getdata() if v) if mask.getbbox() else 0
    total = ia.size[0] * ia.size[1]
    out["changed_percent"] = round(100.0 * changed / total, 2) if total else 0.0
    out["identical"] = changed == 0 and ImageChops.difference(ra, rb).getbbox() is None
    if changed:
        base = rb.convert("RGB").point(lambda v: 90 + v * 100 // 255)           # the newer picture, faded
        red = Image.new("RGB", base.size, (230, 40, 60))
        shown = Image.composite(red, base, mask)
        shown.thumbnail((900, 900))
        buf = io.BytesIO()
        shown.save(buf, "PNG")
        out["diff_image"] = base64.b64encode(buf.getvalue()).decode()
    return out


# ------------------------------------------------------------------ entry point
def compare_files(name: str, a: bytes, b: bytes) -> dict:
    """Return {"kind", "identical", "stats", "rows", ...} describing how b differs from a."""
    ext = ext_of(name)
    base = {"size_a": len(a), "size_b": len(b),
            "sha_a": hashlib.sha256(a).hexdigest(), "sha_b": hashlib.sha256(b).hexdigest()}
    try:
        if ext == "docx":
            return {**base, "kind": "document", **diff_lines(_lines_docx(a), _lines_docx(b))}
        if ext == "pptx":
            return {**base, "kind": "slides", **diff_lines(_lines_pptx(a), _lines_pptx(b))}
        if ext == "pdf":
            return {**base, "kind": "pdf", **diff_lines(_lines_pdf(a), _lines_pdf(b))}
        if ext in ("xlsx", "xlsm"):
            return {**base, "kind": "sheet", **diff_sheets(a, b)}
        if ext in IMAGE_EXTS:
            return {**base, "kind": "image", **diff_images(a, b)}
        if ext in TEXT_EXTS or (_looks_like_text(a) and _looks_like_text(b)):
            return {**base, "kind": "text", **diff_lines(_lines_text(a), _lines_text(b))}
    except Exception:                                  # a damaged file: fall back to the plain comparison below
        pass
    first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
    if first is None and len(a) != len(b):
        first = min(len(a), len(b))
    return {**base, "kind": "binary", "identical": a == b, "first_difference": first}
