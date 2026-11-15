import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app.dart';
import 'core/providers.dart';
import 'core/storage.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = await SharedPrefsStore.open();
  runApp(
    ProviderScope(
      // 请求失败时不自动重试：断网由各页面自己处理并给"重试"按钮，免得后台悄悄反复打服务
      retry: (retryCount, error) => null,
      overrides: [keyValueStoreProvider.overrideWithValue(store)],
      child: const TutorApp(),
    ),
  );
}
