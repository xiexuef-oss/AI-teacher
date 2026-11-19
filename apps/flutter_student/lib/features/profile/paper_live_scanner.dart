import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

final paperLiveScannerProvider =
    Provider<Future<String?> Function(BuildContext)>(
      (_) =>
          (context) => Navigator.of(context).push<String>(
            MaterialPageRoute(builder: (_) => const _PaperLiveScanner()),
          ),
    );

class _PaperLiveScanner extends StatefulWidget {
  const _PaperLiveScanner();

  @override
  State<_PaperLiveScanner> createState() => _PaperLiveScannerState();
}

class _PaperLiveScannerState extends State<_PaperLiveScanner> {
  static final _token = RegExp(r'^[0-9a-f]{32}$');
  bool _completed = false;
  bool _multiple = false;

  void _detect(BarcodeCapture capture) {
    if (_completed || !mounted || ModalRoute.of(context)?.isCurrent != true) {
      return;
    }
    final tokens = {
      for (final barcode in capture.barcodes)
        if (barcode.format == BarcodeFormat.qrCode)
          if (barcode.rawValue case final String value
              when _token.hasMatch(value))
            value,
    };
    if (tokens.length == 1) {
      _completed = true;
      Navigator.of(context).pop(tokens.single);
    } else if (_multiple != (tokens.length > 1)) {
      setState(() => _multiple = tokens.length > 1);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('纸包相机扫码')),
    body: SafeArea(
      child: Column(
        children: [
          Expanded(
            child: MobileScanner(
              onDetect: _detect,
              tapToFocus: true,
              errorBuilder: (_, _) =>
                  const Center(child: Text('无法打开相机。请检查相机权限，或返回从照片读码。')),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              _multiple ? '画面中有多个纸包二维码，请只对准一个。' : '对准纸张上的二维码，识别后自动返回。',
            ),
          ),
        ],
      ),
    ),
  );
}
