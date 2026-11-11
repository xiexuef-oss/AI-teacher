import 'dart:convert';

import 'package:test/test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

typedef Seen = ({
  String method,
  Uri uri,
  Map<String, String> headers,
  String? body
});

class FakeTransport implements ApiTransport {
  final List<Seen> seen = [];
  RawResponse Function(Seen request)? onRequest;
  Object? failWith;

  @override
  Future<RawResponse> send({
    required String method,
    required Uri uri,
    required Map<String, String> headers,
    String? body,
  }) async {
    final request = (method: method, uri: uri, headers: headers, body: body);
    seen.add(request);
    if (failWith != null) throw failWith!;
    return onRequest!(request);
  }
}

RawResponse jsonResponse(int status, Object body) =>
    RawResponse(statusCode: status, body: jsonEncode(body));

void main() {
  late FakeTransport transport;
  late ApiCore core;

  setUp(() {
    transport = FakeTransport()
      ..onRequest = (_) => jsonResponse(200, {
            'data': {'ok': true}
          });
    core = ApiCore(
      baseUrl: 'http://127.0.0.1:8000',
      transport: transport,
      tokenProvider: () async => 'secret-token',
    );
  });

  group('成功', () {
    test('取出 data', () async {
      final data = await core.send('GET', '/health');
      expect(data, {'ok': true});
    });

    test('地址拼在 /api/v1 下，路径带前缀的 baseUrl 也一样', () async {
      await core.send('GET', '/profile');
      expect(transport.seen.single.uri.toString(),
          'http://127.0.0.1:8000/api/v1/profile');

      final prefixed =
          ApiCore(baseUrl: 'https://example.test/tutor/', transport: transport);
      await prefixed.send('GET', '/profile');
      expect(transport.seen.last.uri.toString(),
          'https://example.test/tutor/api/v1/profile');
    });

    test('空的查询参数不进地址，非空的会编码', () async {
      await core.send('GET', '/questions',
          query: {'subject': null, 'cursor': 'a b&c=d', 'limit': '5'});
      expect(transport.seen.single.uri.queryParameters,
          {'cursor': 'a b&c=d', 'limit': '5'});

      await core.send('GET', '/questions', query: {'subject': null});
      expect(transport.seen.last.uri.hasQuery, isFalse);
    });
  });

  group('请求头', () {
    test('带上学生自己的 bearer、幂等键和请求 ID', () async {
      await core.send('POST', '/sessions',
          body: {'a': 1}, idempotencyKey: 'key-12345678', requestId: 'req-1');
      final headers = transport.seen.single.headers;
      expect(headers['Authorization'], 'Bearer secret-token');
      expect(headers['Idempotency-Key'], 'key-12345678');
      expect(headers['X-Request-Id'], 'req-1');
      expect(headers['Content-Type'], startsWith('application/json'));
      expect(transport.seen.single.body, '{"a":1}');
    });

    test('公开接口不带 token；没有请求体就没有 Content-Type', () async {
      await core.send('GET', '/health', authenticated: false);
      final headers = transport.seen.single.headers;
      expect(headers.containsKey('Authorization'), isFalse);
      expect(headers.containsKey('Content-Type'), isFalse);
      expect(headers.containsKey('Idempotency-Key'), isFalse);
    });

    test('没有 token 时不发 Authorization', () async {
      final anonymous =
          ApiCore(baseUrl: 'http://127.0.0.1:8000', transport: transport);
      await anonymous.send('GET', '/profile');
      expect(
          transport.seen.single.headers.containsKey('Authorization'), isFalse);
    });
  });

  group('失败', () {
    test('错误信封变成 ApiException，保留错误码、详情和请求 ID', () async {
      transport.onRequest = (_) => jsonResponse(409, {
            'error': {
              'code': 'draft_revision_conflict',
              'message': '草稿在别处已有更新',
              'details': {'server_revision': 3},
              'request_id': 'req-9',
            },
          });
      await expectLater(
        core.send('PUT', '/attempts/x/draft'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 409)
            .having((e) => e.code, 'code', 'draft_revision_conflict')
            .having((e) => e.details['server_revision'], 'details', 3)
            .having((e) => e.requestId, 'requestId', 'req-9')
            .having((e) => e.isNetwork, 'isNetwork', isFalse)),
      );
    });

    test('连不上服务是网络错误（状态码 0）', () async {
      transport.failWith = Exception('Connection refused');
      await expectLater(
        core.send('GET', '/profile'),
        throwsA(isA<ApiException>()
            .having((e) => e.isNetwork, 'isNetwork', isTrue)
            .having((e) => e.code, 'code', 'network_error')),
      );
    });

    test('服务返回了不是 JSON 的内容', () async {
      transport.onRequest = (_) =>
          const RawResponse(statusCode: 502, body: '<html>Bad gateway</html>');
      await expectLater(
        core.send('GET', '/profile'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 502)
            .having((e) => e.code, 'code', 'invalid_response')),
      );
    });

    test('2xx 但没有 data 也是异常，不返回 null 糊弄过去', () async {
      transport.onRequest = (_) => jsonResponse(200, {'oops': 1});
      await expectLater(
        core.send('GET', '/profile'),
        throwsA(isA<ApiException>()
            .having((e) => e.code, 'code', 'invalid_response')),
      );
    });
  });
}
