"""自编导入测试材料，不读取或分发仓库中的第三方试卷。"""

import io
import zipfile

from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject


def text_pdf(*pages: str, encrypted: bool = False, compressed: bool = False) -> bytes:
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        lines = ["BT /F1 12 Tf 40 750 Td"]
        for i, line in enumerate(text.splitlines()):
            if i:
                lines.append("0 -20 Td")
            line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"({line}) Tj")
        lines.append("ET")
        stream.set_data("\n".join(lines).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(
            stream.flate_encode() if compressed else stream
        )
    if encrypted:
        writer.encrypt("fixture-only-password")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def png_image(size=(320, 80)) -> bytes:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((8, 8), "1. Self authored question", fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def scanned_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    image = Image.open(io.BytesIO(png_image())).convert("RGB")
    obj = DecodedStreamObject()
    obj.set_data(image.tobytes())
    obj.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(image.width),
            NameObject("/Height"): NumberObject(image.height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(obj)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"q 320 0 0 80 40 600 cm /Im1 Do Q")
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def docx_document(body: str, *, image: bool = False, macro: bool = False) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><w:body>'
            + body
            + "</w:body></w:document>",
        )
        if image:
            z.writestr("word/media/image1.png", png_image())
            z.writestr(
                "word/_rels/document.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/></Relationships>',
            )
        if macro:
            z.writestr("word/vbaProject.bin", b"fixture-not-executable")
    return out.getvalue()
