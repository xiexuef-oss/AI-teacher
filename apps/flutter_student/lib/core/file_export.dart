
import 'package:file_saver/file_saver.dart';
import 'package:flutter/foundation.dart';

Future<String> saveDataFile(
  Uint8List bytes, {
  required String name,
  required String extension,
  required MimeType mimeType,
}) async {
  if (kIsWeb) {
    await FileSaver.instance.saveFile(
      name: name,
      bytes: bytes,
      fileExtension: extension,
      mimeType: mimeType,
    );
    return '已发起下载，请在浏览器下载列表中确认。';
  }
  final path = await FileSaver.instance.saveAs(
    name: name,
    bytes: bytes,
    fileExtension: extension,
    mimeType: mimeType,
  );
  return path == null ? '已取消保存' : '文件已保存到你选择的位置。';
}
