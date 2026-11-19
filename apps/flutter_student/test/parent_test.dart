import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/core/data.dart';
import 'package:tutor_student/core/providers.dart';
import 'package:tutor_student/features/parent/parent_home_page.dart';
import 'package:tutor_student/features/parent/parent_weekly_page.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

Finder key(String name) => find.byKey(ValueKey(name));

/// 家长周报与授权（PRD P0 第 8 条、US-06）。
///
/// 家长只看汇总：学生明确授权、可以撤销。这里的家长是本地身份 Mock（监护授权方案 Q-03 还没有冻结），
/// 不是真实账号。
Future<void> launch(
  WidgetTester tester,
  AppHarness h, {
  Size size = tabletLandscape,
}) async {
  useSize(tester, size);
  await tester.pumpWidget(h.app());
  await settle(tester, frames: 12);
}

Future<void> reveal(WidgetTester tester, Finder finder) async {
  if (finder.hitTestable().evaluate().isNotEmpty) return;
  await tester.scrollUntilVisible(
    finder,
    200,
    scrollable: find.byType(Scrollable).first,
    maxScrolls: 40,
  );
  await tester.pump();
}

Future<void> tapAndSettle(
  WidgetTester tester,
  Finder finder, {
  int frames = 8,
}) async {
  await reveal(tester, finder);
  await tester.pump();
  await tester.tap(finder);
  await settle(tester, frames: frames);
}

/// 样例里那位已授权学生的 ID。样例由 tools/export_dart_fixtures.py 导出，每次导出的 ID 都不一样，不能写死。
final String studentId =
    ((Fixtures.load().value('parent_students')['items'] as List).first
            as Map<String, dynamic>)['student_id']
        as String;

String textOf(WidgetTester tester, String name) =>
    tester.widget<Text>(key(name)).data!;

void main() {
  late AppHarness h;
  late Fixtures fixtures;

  setUp(() {
    h = AppHarness();
    fixtures = h.backend.fixtures;
  });

  /// 家长打开应用，已经绑定了一位学生。
  Future<void> openParentHome(WidgetTester tester, {bool linked = true}) async {
    h.signInAs(role: 'parent');
    h.backend.parentLinked = linked;
    await launch(tester, h);
  }

  Future<void> openWeekly(WidgetTester tester) async {
    await openParentHome(tester);
    await tapAndSettle(tester, key('parent.student.$studentId'));
  }

  group('家长启动与首页', () {
    testWidgets('家长身份启动：直接进家长页，不去学生的引导和首页，也不请求学生资料', (tester) async {
      await openParentHome(tester);

      expect(key('parent.home'), findsOneWidget);
      expect(key('home.practice'), findsNothing);
      expect(key('onboarding.page'), findsNothing);
      expect(h.backend.requestsTo('GET', '/profile'), isEmpty);
      expect(h.backend.identitiesCreated, 0, reason: '用本机已有的凭据，不领新身份');
      await teardownTree(tester);
    });

    testWidgets('列出已授权的学生（没有称呼就用编号），点进去看周报', (tester) async {
      await openParentHome(tester);

      expect(find.text('学生 ${studentId.substring(0, 8)}'), findsOneWidget);
      await tapAndSettle(tester, key('parent.student.$studentId'));

      expect(key('parent.weekly.page'), findsOneWidget);
      expect(h.backend.weeklyWeeks, [null], reason: '默认是当前这一周');
      await teardownTree(tester);
    });

    testWidgets('学生设置了称呼就显示称呼', (tester) async {
      h.signInAs(role: 'parent');
      h.backend.parentLinked = true;
      h.backend.on('GET', '/parents/students', (_) {
        final value = fixtures.value('parent_students');
        ((value['items'] as List).first as Map)['display_name'] = '小明';
        return okResponse(value);
      });
      await launch(tester, h);

      expect(find.text('小明'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('还没有授权的学生：说明怎么拿到邀请码，页面上没有任何学生数据', (tester) async {
      await openParentHome(tester, linked: false);

      expect(key('parent.empty'), findsOneWidget);
      expect(find.textContaining('邀请码'), findsWidgets);
      expect(find.textContaining('生成'), findsWidgets);
      await teardownTree(tester);
    });

    testWidgets('页面上说清楚：只看汇总、学生可以随时撤销、不是真实账号', (tester) async {
      await openParentHome(tester);

      expect(find.textContaining('汇总'), findsWidgets);
      expect(find.textContaining('撤销'), findsWidgets);
      expect(find.textContaining('原型'), findsWidgets);
      await teardownTree(tester);
    });
  });

  group('家长输入邀请码', () {
    testWidgets('没填之前不能绑定；填了按规范化内容发出去（带幂等键），成功后出现这位学生', (tester) async {
      await openParentHome(tester, linked: false);
      expect(tester.widget<FilledButton>(key('parent.link')).onPressed, isNull);

      await tester.enterText(key('parent.code'), 'abcde-23456');
      await tester.pump();
      await tapAndSettle(tester, key('parent.link'));

      final request = h.backend.requestsTo('POST', '/parents/links').single;
      expect(jsonDecode(request.body!), {'code': 'ABCDE23456'});
      expect(request.headers['Idempotency-Key'], isNotNull);
      expect(key('parent.linked'), findsOneWidget);
      expect(find.text('学生 ${studentId.substring(0, 8)}'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('邀请码带空格和小写也能绑定；幂等键是合法的，而且里面没有邀请码', (tester) async {
      await openParentHome(tester, linked: false);

      await tester.enterText(key('parent.code'), 'abcde 23456');
      await tester.pump();
      await tapAndSettle(tester, key('parent.link'));

      final request = h.backend.requestsTo('POST', '/parents/links').single;
      expect(jsonDecode(request.body!), {'code': 'ABCDE23456'});
      final idempotencyKey = request.headers['Idempotency-Key']!;
      expect(
        RegExp(r'^[A-Za-z0-9._:-]{8,128}$').hasMatch(idempotencyKey),
        isTrue,
      );
      expect(idempotencyKey.toLowerCase(), isNot(contains('abcde')));
      expect(key('parent.linked'), findsOneWidget, reason: '没有被服务端当成坏请求');
      await teardownTree(tester);
    });

    testWidgets('绑定失败和成功的提示会被读屏软件读出来，而且不并进输入框的朗读文字', (tester) async {
      final semantics = tester.ensureSemantics();
      await openParentHome(tester, linked: false);

      // 真实浏览器里发现过：提示的文字被并进了输入框的 aria-label，出现时不会被读出来
      Future<void> expectAnnounced(Finder finder, String words) async {
        final data = tester.getSemantics(finder).getSemanticsData();
        expect(data.flagsCollection.isLiveRegion, isTrue);
        expect(data.label, contains(words));
        expect(data.label, isNot(contains('输入学生给你的邀请码')));
      }

      await tester.enterText(key('parent.code'), 'ZZZZZZZZZZ');
      await tester.pump();
      await tapAndSettle(tester, key('parent.link'));
      await expectAnnounced(find.textContaining('邀请码不对，或者已经过期'), '邀请码不对');

      await tester.enterText(key('parent.code'), 'ABCDE23456');
      await tester.pump();
      await tapAndSettle(tester, key('parent.link'));
      await expectAnnounced(key('parent.linked'), '原绑定操作已确认');

      semantics.dispose();
      await teardownTree(tester);
    });

    testWidgets('邀请码不对：一句话说明，不区分是过期、用过还是写错', (tester) async {
      await openParentHome(tester, linked: false);

      await tester.enterText(key('parent.code'), 'ZZZZZZZZZZ');
      await tester.pump();
      await tapAndSettle(tester, key('parent.link'));

      expect(find.textContaining('邀请码不对，或者已经过期、已经被用过'), findsOneWidget);
      expect(key('parent.linked'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('已经绑定着这位学生：说明，不当成失败', (tester) async {
      await openParentHome(tester);

      await tester.enterText(key('parent.code'), 'ABCDE23456');
      await tester.pump();
      await tapAndSettle(tester, key('parent.link'));

      expect(find.textContaining('已经绑定着这位学生'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('周报', () {
    testWidgets('只有汇总：学习天数、练习、作答，四个比例和按科目', (tester) async {
      final weekly = h.backend.fixtures.value('parent_weekly');
      await openWeekly(tester);

      expect(textOf(tester, 'parent.weekly.range'), '11月9日 – 11月15日');
      expect(find.text('这一周还没结束'), findsOneWidget);
      expect(
        textOf(tester, 'parent.weekly.activeDays'),
        '${weekly['active_days']} 天',
      );
      expect(
        textOf(tester, 'parent.weekly.sessions'),
        '${weekly['sessions_count']} 次',
      );
      expect(
        textOf(tester, 'parent.weekly.attempts'),
        '${weekly['attempts_count']} 份',
      );
      for (final name in ['independent', 'assisted', 'hint', 'retest']) {
        expect(key('parent.weekly.$name'), findsOneWidget, reason: name);
      }
      expect(find.text('按科目'), findsOneWidget);
      expect(find.textContaining('不是官方成绩'), findsWidgets);
      await teardownTree(tester);
    });

    testWidgets('样本不足时只给计数、不显示百分比；够了才显示', (tester) async {
      await openWeekly(tester);
      expect(find.text('信息不足'), findsWidgets);
      expect(find.textContaining('%'), findsNothing);
      await teardownTree(tester);

      h = AppHarness();
      h.backend.weeklyTweak = (weekly) {
        weekly['independent'] = {
          'numerator': 3,
          'denominator': 5,
          'rate': 0.6,
          'insufficient_data': false,
        };
        return weekly;
      };
      await openWeekly(tester);
      expect(
        find.descendant(
          of: key('parent.weekly.independent'),
          matching: find.text('60%'),
        ),
        findsOneWidget,
      );
      await teardownTree(tester);
    });

    for (final (trend, words) in [
      ('up', '比上一周高了'),
      ('down', '比上一周低了'),
      ('flat', '和上一周差不多'),
      ('unknown', '暂时比不了'),
    ]) {
      testWidgets('趋势 $trend：只用中性的话说，没有排名或评语', (tester) async {
        h.backend.weeklyTweak = (weekly) {
          weekly['independent_trend'] = trend;
          return weekly;
        };
        await openWeekly(tester);

        expect(textOf(tester, 'parent.weekly.trend'), contains(words));
        await teardownTree(tester);
      });
    }

    testWidgets('这一周没有学习记录：明说，不当成出错', (tester) async {
      h.backend.weeklyTweak = (weekly) {
        weekly['sessions_count'] = 0;
        weekly['attempts_count'] = 0;
        weekly['active_days'] = 0;
        return weekly;
      };
      await openWeekly(tester);

      expect(key('parent.weekly.empty'), findsOneWidget);
      expect(find.textContaining('这一周还没有学习记录'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('解答题、实验题和证明题只说提交了几份，并说明它们不进比例', (tester) async {
      h.backend.weeklyTweak = (weekly) {
        weekly['written_attempts'] = 2;
        return weekly;
      };
      await openWeekly(tester);

      expect(find.textContaining('解答题、实验题和证明题 2 份'), findsOneWidget);
      expect(find.textContaining('不自动评分'), findsWidgets);
      expect(find.textContaining('不计入上面的比例'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('翻周：上一周带着 week_start；当前这一周不能再往后翻', (tester) async {
      await openWeekly(tester);
      expect(
        tester.widget<OutlinedButton>(key('parent.weekly.next')).onPressed,
        isNull,
      );

      h.backend.weeklyFixture = 'parent_weekly_last_week';
      await tapAndSettle(tester, key('parent.weekly.previous'));

      expect(h.backend.weeklyWeeks, [null, '2026-11-02']);
      expect(textOf(tester, 'parent.weekly.range'), '11月2日 – 11月8日');
      expect(find.text('这一周已经结束'), findsOneWidget);
      expect(
        tester.widget<OutlinedButton>(key('parent.weekly.next')).onPressed,
        isNotNull,
      );

      h.backend.weeklyFixture = 'parent_weekly';
      await tapAndSettle(tester, key('parent.weekly.next'));
      expect(h.backend.weeklyWeeks.last, '2026-11-09');
      await teardownTree(tester);
    });

    testWidgets('历史周报按版本读取，失去授权后隐藏旧统计', (tester) async {
      await openWeekly(tester);
      h.backend.weeklyFixture = 'parent_weekly_last_week';
      await tapAndSettle(tester, key('parent.weekly.previous'));
      final report = h.backend.fixtures.value('parent_weekly_last_week');
      final revisions = <String?>[];
      h.backend.on(
        'GET',
        '/parents/students/${report['student_id']}/weekly-snapshots/2026-11-02',
        (request) {
          final revision = request.uri.queryParameters['revision'];
          revisions.add(revision);
          return revision == '1'
              ? errorResponse(404, 'not_found')
              : okResponse({'revision': 2, 'report': report});
        },
      );
      await tapAndSettle(tester, find.text('查看周报历史版本'));
      expect(find.text('当前查看第 2 版'), findsOneWidget);
      await tapAndSettle(tester, find.text('查看上一版'));
      expect(revisions, [null, '1']);
      expect(find.text('这份历史周报不可用'), findsOneWidget);
      expect(key('parent.weekly.independent'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('授权已经撤销（或没绑定）：只说明这一件事，页面上没有任何数据', (tester) async {
      h.backend.weeklyError = (404, 'not_found');
      await openWeekly(tester);

      expect(key('parent.weekly.unauthorized'), findsOneWidget);
      expect(find.textContaining('授权已经撤销'), findsOneWidget);
      expect(key('parent.weekly.independent'), findsNothing);
      await tapAndSettle(tester, key('parent.weekly.back'));
      expect(key('parent.home'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('返回键：从家长首页点进来就回到首页；直接打开周报（没有上一页）也回到首页', (tester) async {
      await openWeekly(tester);
      await tapAndSettle(tester, key('parent.weekly.appBarBack'));
      expect(key('parent.home'), findsOneWidget);
      expect(key('parent.weekly.page'), findsNothing);

      // go 会换掉整个页面栈，周报页成了第一页，没有上一页可退
      GoRouterOf.of(tester).go('/parent/weekly/$studentId');
      await settle(tester, frames: 8);
      expect(key('parent.weekly.page'), findsOneWidget);
      await tapAndSettle(tester, key('parent.weekly.appBarBack'));
      expect(key('parent.home'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('三个计数说清楚数的是什么', (tester) async {
      await openWeekly(tester);

      expect(find.text('有作答的天数'), findsOneWidget);
      expect(find.text('开始的练习'), findsOneWidget);
      expect(find.text('提交作答'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('网络出错：给重试，不显示旧数据', (tester) async {
      h.backend.weeklyError = (503, 'service_unavailable');
      await openWeekly(tester);

      expect(find.text('重试'), findsOneWidget);
      expect(key('parent.weekly.independent'), findsNothing);

      h.backend.weeklyError = null;
      await tapAndSettle(tester, find.text('重试'));
      expect(key('parent.weekly.independent'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('屏幕很高也从顶部开始排，不在中间悬着（首页和周报）', (tester) async {
      h.signInAs(role: 'parent');
      useSize(tester, const Size(800, 2000));

      await tester.pumpWidget(h.page(const ParentHomePage()));
      await settle(tester, frames: 12);
      final homeTop = tester
          .getTopLeft(find.textContaining('你能看到的只有学生授权给你的'))
          .dy;
      expect(homeTop, lessThan(120), reason: '紧挨着标题栏，而不是垂直居中');

      await tester.pumpWidget(h.page(ParentWeeklyPage(studentId: studentId)));
      await settle(tester, frames: 12);
      final weeklyTop = tester.getTopLeft(key('parent.weekly.range')).dy;
      expect(weeklyTop, lessThan(200), reason: '周报也是');
      await teardownTree(tester);
    });

    for (final size in [tabletLandscape, tabletPortrait, phone]) {
      testWidgets(
        '字体放大 1.5 倍不溢出：${size.width.toInt()}×${size.height.toInt()}',
        (tester) async {
          h.signInAs(role: 'parent');
          useSize(tester, size);

          await tester.pumpWidget(
            h.page(const ParentHomePage(), textScale: 1.5),
          );
          await settle(tester, frames: 12);
          expect(tester.takeException(), isNull);

          await tester.pumpWidget(
            h.page(ParentWeeklyPage(studentId: studentId), textScale: 1.5),
          );
          await settle(tester, frames: 12);
          await tester.scrollUntilVisible(
            find.textContaining('不是官方成绩').first,
            300,
            scrollable: find.byType(Scrollable).first,
          );
          expect(tester.takeException(), isNull);
          await teardownTree(tester);
        },
      );
    }
  });

  group('学生一侧：授权与撤销', () {
    Future<void> openProfile(WidgetTester tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.profile'), frames: 10);
    }

    testWidgets('我的页里有"家长查看"：说清楚家长只看汇总、可以撤销', (tester) async {
      await openProfile(tester);

      await reveal(tester, key('parent.access'));
      expect(find.textContaining('只能看到你授权的'), findsWidgets);
      expect(find.textContaining('随时撤销'), findsWidgets);
      expect(find.textContaining('还没有授权任何家长'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('生成邀请码：弹出十位码和有效期；带幂等键；之后能看到"有一个还没用掉的邀请码"', (tester) async {
      await openProfile(tester);

      await tapAndSettle(tester, key('parent.invite'));

      final code = fixtures.value('parent_invite')['code'] as String;
      expect(
        textOf(tester, 'parent.invite.code'),
        '${code.substring(0, 5)} ${code.substring(5)}',
      );
      expect(find.textContaining('失效'), findsWidgets);
      expect(find.textContaining('重新生成会让'), findsOneWidget);
      final request = h.backend.requestsTo('POST', '/me/parent-invites').single;
      expect(request.headers['Idempotency-Key'], isNotNull);

      await tapAndSettle(tester, key('parent.invite.close'));
      await reveal(tester, key('parent.access'));
      expect(key('parent.pending'), findsOneWidget);
      expect(find.textContaining(code), findsNothing, reason: '关掉之后码不会再出现');
      await teardownTree(tester);
    });

    testWidgets('授权列表：撤销要先确认；确认后请求发出去、这一行消失', (tester) async {
      h.backend.parentLinks = [
        ...(fixtures.value('parent_links')['links'] as List)
            .cast<Map<String, dynamic>>(),
      ];
      final linkId = h.backend.parentLinks.single['id'] as String;
      await openProfile(tester);
      await reveal(tester, key('parent.link.$linkId'));

      await tapAndSettle(tester, key('parent.revoke.$linkId'));
      expect(find.textContaining('立刻就看不到你的周报'), findsOneWidget);
      await tapAndSettle(tester, key('dialog.revoke.cancel'));
      expect(h.backend.revokes, 0, reason: '取消就什么都不发');

      await tapAndSettle(tester, key('parent.revoke.$linkId'));
      await tapAndSettle(tester, key('dialog.revoke.confirm'));

      final request = h.backend
          .requestsTo('POST', '/me/parent-links/$linkId/revoke')
          .single;
      expect(request.headers['Idempotency-Key'], isNotNull);
      expect(key('parent.link.$linkId'), findsNothing);
      expect(find.textContaining('还没有授权任何家长'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('称呼：不填就不发', (tester) async {
      await openProfile(tester);
      await tapAndSettle(tester, key('profile.save'));

      expect(h.backend.lastProfileUpdate!.containsKey('display_name'), isFalse);
      await teardownTree(tester);
    });

    testWidgets('称呼：填了和资料一起保存，两头的空格不要', (tester) async {
      await openProfile(tester);

      await tester.enterText(key('profile.displayName'), '  小明 ');
      await tester.pump();
      await tapAndSettle(tester, key('profile.save'));

      expect(h.backend.lastProfileUpdate!['display_name'], '小明');
      await teardownTree(tester);
    });
  });

  group('本机演示：切换身份', () {
    testWidgets('学生切到家长：用新的家长身份，学生的身份收起来；再切回来还是原来那个学生', (tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.profile'), frames: 10);
      final studentUser = h.store.data['auth.userId']!;
      expect(h.backend.identitiesCreated, 1);
      // 学生的数据（资料、今日任务、授权列表）：首页压在"我的"下面，两页都开着
      int studentCalls() => h.backend
          .requestsTo('GET', r'/api/v1/(profile|tasks/today|me/parent-links)$')
          .length;
      // 先滚到按钮：授权区被画出来时会自己取一次授权列表，这一次不算切身份引起的
      await reveal(tester, key('profile.switchToParent'));
      await settle(tester);
      final before = studentCalls();
      expect(before, greaterThan(2), reason: '资料、今日任务、授权列表都取过了');

      await tapAndSettle(tester, key('profile.switchToParent'), frames: 12);

      expect(key('parent.home'), findsOneWidget);
      expect(studentCalls(), before, reason: '切身份的那一刻，学生的数据不能拿着家长的凭据去重新请求');
      expect(h.store.data['auth.role'], 'parent');
      expect(h.store.data['auth.userId'], FakeBackend.parentUserId);
      expect(h.store.data['auth.other.role'], 'student');
      expect(h.store.data['auth.other.userId'], studentUser);
      expect(h.backend.identitiesCreated, 2);
      final parentCalls = h.backend
          .requestsTo('GET', r'/parents/students$')
          .length;
      expect(parentCalls, greaterThan(0));

      await tapAndSettle(tester, key('parent.switchToStudent'), frames: 14);

      expect(
        h.backend.requestsTo('GET', r'/parents/students$').length,
        parentCalls,
        reason: '切回学生的那一刻，家长的数据也不能拿着学生的凭据去重新请求',
      );
      expect(key('home.practice'), findsOneWidget);
      expect(h.store.data['auth.role'], isNot('parent'));
      expect(h.store.data['auth.userId'], studentUser, reason: '回到原来的学生');
      expect(h.backend.identitiesCreated, 2, reason: '切回来不再领新身份');
      expect(h.store.data['auth.other.role'], 'parent');
      await teardownTree(tester);
    });

    testWidgets('领不到新身份（断网）：什么都不改，留在原来的页面并说明', (tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.profile'), frames: 10);
      final studentUser = h.store.data['auth.userId'];
      h.backend.failNextOn('/dev/local-identities', 503, 'service_unavailable');

      await tapAndSettle(tester, key('profile.switchToParent'), frames: 12);

      expect(key('parent.home'), findsNothing);
      expect(key('parent.access'), findsOneWidget, reason: '还在"我的"页');
      expect(find.text('出错了'), findsOneWidget);
      expect(h.store.data['auth.role'], 'student');
      expect(h.store.data['auth.userId'], studentUser);
      expect(h.store.data.containsKey('auth.other.userId'), isFalse);
      await teardownTree(tester);
    });

    test('登录失效后重新领身份：角色不变，收起来的另一个身份不动', () async {
      h.signInAs(role: 'parent');
      h.store.data['auth.other.token'] = 'student-token';
      h.store.data['auth.other.userId'] = 'student-user';
      h.store.data['auth.other.role'] = 'student';
      final container = ProviderContainer(
        retry: (count, error) => null,
        overrides: h.overrides,
      );
      addTearDown(container.dispose);
      await container.read(authProvider.future);

      await container.read(authProvider.notifier).relogin();

      expect(container.read(authProvider).requireValue.role, LocalRole.parent);
      final request = h.backend.requestsTo('POST', '/dev/local-identities');
      expect(request.single.uri.queryParameters['role'], 'parent');
      expect(h.store.data['auth.role'], 'parent');
      expect(h.store.data['auth.other.userId'], 'student-user');
    });
  });

  group('身份和页面对不上', () {
    testWidgets('家长打开学生的页面：说明一句，不去请求学生的数据；给一个去处', (tester) async {
      await openParentHome(tester);
      final before = h.backend.requests.length;

      GoRouterOf.of(tester).go('/home');
      await settle(tester, frames: 8);

      expect(key('auth.wrongRole'), findsOneWidget);
      expect(key('home.practice'), findsNothing);
      expect(h.backend.requests.length, before, reason: '一个请求也不发');

      await tapAndSettle(tester, key('auth.wrongRole.go'));
      expect(key('parent.home'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('学生打开家长的页面：说明一句，不去请求家长的接口；回到学生首页', (tester) async {
      await launch(tester, h);

      GoRouterOf.of(tester).go('/parent');
      await settle(tester, frames: 8);

      expect(key('auth.wrongRole'), findsOneWidget);
      expect(key('parent.home'), findsNothing);
      expect(h.backend.requestsTo('GET', '/parents'), isEmpty);

      await tapAndSettle(tester, key('auth.wrongRole.go'), frames: 12);
      expect(key('home.practice'), findsOneWidget);
      await teardownTree(tester);
    });

    test('家长身份下读学生的数据：直接失败，一个请求也不发；学生身份读家长的数据也一样', () async {
      Future<void> expectWrongSession(
        AppHarness harness,
        List<Future<Object?> Function(ProviderContainer)> reads,
      ) async {
        final container = ProviderContainer(
          retry: (count, error) => null,
          overrides: harness.overrides,
        );
        addTearDown(container.dispose);
        await container.read(authProvider.future);
        for (final read in reads) {
          await expectLater(read(container), throwsA(isA<WrongSession>()));
        }
        expect(harness.backend.requests, isEmpty);
      }

      h.signInAs(role: 'parent');
      await expectWrongSession(h, [
        (c) => c.read(profileProvider.future),
        (c) => c.read(todayTasksProvider.future),
        (c) => c.read(reviewsProvider.future),
        (c) => c.read(progressProvider.future),
        (c) => c.read(sessionEventsProvider('s-1').future),
        (c) => c.read(parentLinksProvider.future),
      ]);

      final student = AppHarness()..signInAs(role: 'student', userId: 'u-1');
      await expectWrongSession(student, [
        (c) => c.read(parentStudentsProvider.future),
        (c) => c.read(
          parentWeeklyProvider((studentId: studentId, weekStart: null)).future,
        ),
      ]);
    });

    testWidgets('以前存下的身份没有记角色：按学生处理，不重新领身份', (tester) async {
      h.store.data['auth.token'] = 'old-token';
      h.store.data['auth.userId'] = 'old-user';

      await launch(tester, h);

      expect(key('home.practice'), findsOneWidget);
      expect(h.backend.identitiesCreated, 0);
      await teardownTree(tester);
    });
  });
}
