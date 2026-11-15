/// 生成的客户端所依赖的运行时：传输层、错误类型、请求组装。
///
/// 这个文件是手写的，不随契约变化。客户端从不持有任何模型供应商的密钥；
/// 这里只负责把学生自己的 bearer 带给后端。
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// 服务端返回的错误信封，或根本到不了服务端的网络错误（[statusCode] 为 0）。
class ApiException implements Exception {
  const ApiException({
    required this.statusCode,
    required this.code,
    required this.message,
    this.details = const {},
    this.requestId,
  });

  /// 连接失败、超时等：没有收到服务端的任何响应。
  factory ApiException.network(Object cause) => ApiException(
        statusCode: 0,
        code: 'network_error',
        message: '无法连接到服务（$cause）',
      );

  final int statusCode;

  /// 机器可读的错误码，例如 `draft_revision_conflict`。
  final String code;
  final String message;
  final Map<String, dynamic> details;
  final String? requestId;

  bool get isNetwork => statusCode == 0;

  @override
  String toString() => 'ApiException($statusCode $code: $message)';
}

class RawResponse {
  const RawResponse(
      {required this.statusCode, required this.body, this.headers = const {}});

  final int statusCode;
  final String body;
  final Map<String, String> headers;
}

/// 实际发请求的那一层。测试里用假的实现替换。
abstract interface class ApiTransport {
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  });
}

/// 基于 package:http 的传输层，移动端、桌面端与 Web 通用。
class HttpTransport implements ApiTransport {
  HttpTransport(
      {http.Client? client, this.timeout = const Duration(seconds: 20)})
      : _client = client ?? http.Client();

  final http.Client _client;
  final Duration timeout;

  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final request = http.Request(method, uri)..headers.addAll(headers);
    if (body != null) request.body = body;
    final streamed = await _client.send(request).timeout(timeout);
    final response = await http.Response.fromStream(streamed).timeout(timeout);
    return RawResponse(
      statusCode: response.statusCode,
      body: utf8.decode(response.bodyBytes, allowMalformed: true),
      headers: response.headers,
    );
  }

  void close() => _client.close();
}

typedef TokenProvider = FutureOr<String?> Function();

/// 把一次契约操作变成 HTTP 请求，并把响应信封拆开：成功返回 `data`，失败抛 [ApiException]。
class ApiCore {
  ApiCore(
      {required String baseUrl,
      required ApiTransport transport,
      TokenProvider? tokenProvider})
      : _base = Uri.parse(baseUrl),
        _transport = transport,
        _tokenProvider = tokenProvider;

  static const String apiPrefix = '/api/v1';

  final Uri _base;
  final ApiTransport _transport;
  final TokenProvider? _tokenProvider;

  Uri _uri(String path, Map<String, String?> query) {
    final basePath = _base.path.endsWith('/')
        ? _base.path.substring(0, _base.path.length - 1)
        : _base.path;
    final present = <String, String>{
      for (final entry in query.entries)
        if (entry.value != null) entry.key: entry.value!,
    };
    return _base.replace(
      path: '$basePath$apiPrefix$path',
      queryParameters: present.isEmpty ? null : present,
    );
  }

  Future<Object?> send(
    String method,
    String path, {
    Map<String, String?> query = const {},
    Object? body,
    String? idempotencyKey,
    String? requestId,
    bool authenticated = true,
  }) async {
    final headers = <String, String>{'Accept': 'application/json'};
    if (body != null) {
      headers['Content-Type'] = 'application/json; charset=utf-8';
    }
    if (idempotencyKey != null) headers['Idempotency-Key'] = idempotencyKey;
    if (requestId != null) headers['X-Request-Id'] = requestId;
    if (authenticated) {
      final token = await _tokenProvider?.call();
      if (token != null && token.isNotEmpty) {
        headers['Authorization'] = 'Bearer $token';
      }
    }

    final RawResponse response;
    try {
      response = await _transport.send(
        method: method,
        uri: _uri(path, query),
        headers: headers,
        body: body == null ? null : jsonEncode(body),
      );
    } on ApiException {
      rethrow;
    } catch (error) {
      throw ApiException.network(error);
    }

    Object? decoded;
    try {
      decoded = response.body.isEmpty ? null : jsonDecode(response.body);
    } on FormatException {
      decoded = null;
    }

    final ok = response.statusCode >= 200 && response.statusCode < 300;
    if (ok && decoded is Map<String, dynamic> && decoded.containsKey('data')) {
      return decoded['data'];
    }
    final error = decoded is Map<String, dynamic> ? decoded['error'] : null;
    if (!ok && error is Map<String, dynamic>) {
      final details = error['details'];
      throw ApiException(
        statusCode: response.statusCode,
        code: error['code'] as String? ?? 'http_error',
        message: error['message'] as String? ?? '请求没有成功',
        details: details is Map ? Map<String, dynamic>.from(details) : const {},
        requestId: error['request_id'] as String?,
      );
    }
    throw ApiException(
      statusCode: response.statusCode,
      code: 'invalid_response',
      message: '服务返回了无法识别的响应',
    );
  }
}
