import 'dart:typed_data';

class ScanImageInfo {
  const ScanImageInfo(this.mime, this.width, this.height);
  final String mime;
  final int width;
  final int height;
}

/// Bounded header inspection before invoking a raster decoder on any platform.
/// This checks structure and dimensions; the platform codec still validates data.
ScanImageInfo inspectScanImage(Uint8List b) {
  Never invalid() =>
      throw const FormatException('请选择完整的静态PNG/JPEG图片，最大5MB、1200万像素');
  if (b.length > 5 * 1024 * 1024 || b.length < 24) invalid();
  ScanImageInfo bounded(String mime, int w, int h) {
    if (w <= 0 || h <= 0 || w > 12000000 || h > 12000000 || w * h > 12000000) {
      invalid();
    }
    return ScanImageInfo(mime, w, h);
  }

  final data = ByteData.sublistView(b);
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (List.generate(8, (i) => b[i] == signature[i]).every((v) => v)) {
    ScanImageInfo? info;
    bool idat = false;
    int offset = 8;
    while (offset + 12 <= b.length) {
      final length = data.getUint32(offset);
      if (length > b.length - offset - 12) invalid();
      final type = String.fromCharCodes(b.sublist(offset + 4, offset + 8));
      if (offset == 8 && (type != 'IHDR' || length != 13)) invalid();
      if (type == 'IHDR') {
        if (info != null || length != 13) invalid();
        info = bounded(
          'image/png',
          data.getUint32(offset + 8),
          data.getUint32(offset + 12),
        );
        if (b[offset + 18] != 0 || b[offset + 19] != 0 || b[offset + 20] > 1) {
          invalid();
        }
      }
      if (type == 'acTL' || type == 'fcTL' || type == 'fdAT') invalid();
      if (type == 'IDAT') idat = true;
      offset += length + 12;
      if (type == 'IEND') {
        if (length != 0 || !idat || info == null || offset != b.length) {
          invalid();
        }
        return info;
      }
    }
    invalid();
  }
  if (b[0] != 255 || b[1] != 216 || b[b.length - 2] != 255 || b.last != 217) {
    invalid();
  }
  ScanImageInfo? info;
  int offset = 2;
  while (offset < b.length - 2) {
    if (b[offset++] != 255) invalid();
    while (offset < b.length && b[offset] == 255) {
      offset++;
    }
    if (offset + 3 > b.length) invalid();
    final marker = b[offset++];
    final length = data.getUint16(offset);
    if (length < 2 || length > b.length - offset) invalid();
    if (marker == 0xe2 &&
        length >= 6 &&
        String.fromCharCodes(b.sublist(offset + 2, offset + 6)) ==
            'MPF\u0000') {
      invalid();
    }
    final sof =
        marker >= 0xc0 &&
        marker <= 0xcf &&
        marker != 0xc4 &&
        marker != 0xc8 &&
        marker != 0xcc;
    if (sof) {
      if (info != null ||
          ![0xc0, 0xc1, 0xc2].contains(marker) ||
          length < 11 ||
          b[offset + 2] != 8) {
        invalid();
      }
      final components = b[offset + 7];
      if (components < 1 || components > 4 || length != 8 + components * 3) {
        invalid();
      }
      info = bounded(
        'image/jpeg',
        data.getUint16(offset + 5),
        data.getUint16(offset + 3),
      );
    }
    if (marker == 0xda) {
      if (info == null || length < 6 || offset + length >= b.length - 1) {
        invalid();
      }
      return info;
    }
    offset += length;
  }
  invalid();
}
