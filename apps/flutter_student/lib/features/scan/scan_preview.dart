import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';

/// Owns this page's preview only. Picker and system filesystem caches are separate.
class ScanPreview {
  Uint8List? bytes;
  MemoryImage? provider;

  void replace(Uint8List value) {
    clear();
    bytes = value;
    provider = MemoryImage(value);
  }

  void clear() {
    final previous = provider;
    provider = null;
    bytes = null;
    if (previous != null) unawaited(previous.evict());
  }
}
