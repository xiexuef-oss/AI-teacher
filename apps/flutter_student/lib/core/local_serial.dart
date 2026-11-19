import 'storage.dart';

/// Short local read/validate/single-key-write transactions. Not a cross-process
/// lock and not a multi-key commit. HTTP must remain outside this queue.
class LocalSerial {
  static final Expando<Map<String, Future<void>>> _queues = Expando();
  static Future<T> run<T>(
    KeyValueStore store,
    String owner,
    Future<T> Function() action,
  ) {
    final queues = _queues[store] ??= {};
    final previous = queues[owner] ?? Future<void>.value();
    final next = previous.then((_) => action());
    queues[owner] = next.then<void>(
      (_) {},
      onError: (Object _, StackTrace _) {},
    );
    return next;
  }
}
