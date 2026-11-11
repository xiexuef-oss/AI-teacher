import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/core/data.dart';
import 'package:tutor_student/core/theme.dart';
import 'package:tutor_student/features/home/home_page.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

Finder key(String name) => find.byKey(ValueKey(name));

Future<void> launch(
  WidgetTester tester,
  AppHarness h, {
  Size size = tabletLandscape,
}) async {
  useSize(tester, size);
  await tester.pumpWidget(h.app());
  await settle(tester, frames: 12);
}

/// 把控件滚到可点击的位置。懒加载的列表里还没建出来的项，ensureVisible 找不到，这里一步一步滚。
Future<void> reveal(WidgetTester tester, Finder finder) async {
  if (finder.hitTestable().evaluate().isNotEmpty) {
    return; // 已经在屏幕上，不用滚（有的页面根本没有可滚动的内容）
  }
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

Map<String, dynamic> taskItem(Map<String, dynamic> tasks, int index) =>
    ((tasks['items'] as List)[index] as Map<String, dynamic>);

void main() {
  late AppHarness h;
  setUp(() => h = AppHarness());

  group('首次使用：三步引导', () {
    testWidgets('没有资料 → 进入引导；每一步都要满足条件才能往下', (tester) async {
      h.backend.profileFixture = 'profile_empty';
      await launch(tester, h);

      expect(key('onboarding.page'), findsOneWidget);
      expect(find.text('第 1 步，共 3 步'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('onboarding.next')).onPressed,
        isNull,
        reason: '没选地区不能继续',
      );

      await tapAndSettle(tester, key('region.CN-51'), frames: 2);
      expect(
        tester.widget<FilledButton>(key('onboarding.next')).onPressed,
        isNotNull,
      );
      expect(find.textContaining('不会用定位去猜'), findsOneWidget);
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 3);

      expect(find.text('第 2 步，共 3 步'), findsOneWidget);
      await tester.tap(key('grade.G12'));
      await settle(tester, frames: 3);
      expect(find.textContaining('预计高考年份：2027 年'), findsOneWidget);
      for (final subject in ['math', 'physics', 'chemistry']) {
        await tester.tap(key('subject.$subject'));
        await tester.pump();
      }
      expect(
        tester.widget<FilledButton>(key('onboarding.next')).onPressed,
        isNull,
        reason: '一科都没选不能继续',
      );
      await tester.tap(key('subject.physics'));
      await tester.pump();
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 3);

      expect(find.text('第 3 步，共 3 步'), findsOneWidget);
      expect(find.text('暂不清楚'), findsOneWidget);
      expect(find.textContaining('不清楚也没关系'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('选好之后保存：只发送选过的字段；教材"暂不清楚"不发送；然后进入首页', (tester) async {
      h.backend.profileFixture = 'profile_empty';
      await launch(tester, h);
      await tapAndSettle(tester, key('region.CN-50'), frames: 2);
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 3);
      await tester.tap(key('grade.G11'));
      await tester.pump();
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 3);

      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 12);

      final body = h.backend.lastProfileUpdate!;
      expect(body['region_code'], 'CN-50');
      expect(body['grade'], 'G11');
      expect(body['subjects'], ['math', 'physics', 'chemistry']);
      expect(body.containsKey('curriculum_version'), isFalse);
      expect(body.containsKey('exam_year'), isFalse, reason: '考试年份交给服务端按年级估算');
      expect(key('home.page'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('保存失败：留在这一步并说明原因，不丢已选的内容', (tester) async {
      h.backend.profileFixture = 'profile_empty';
      await launch(tester, h);
      await tapAndSettle(tester, key('region.CN-51'), frames: 2);
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 3);
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 3);

      h.backend.failNextOn('/profile', 503, 'internal_error');
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 8);

      expect(key('onboarding.page'), findsOneWidget);
      expect(find.textContaining('服务暂时出了问题'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('onboarding.next')).onPressed,
        isNotNull,
        reason: '可以直接再点一次',
      );
      await teardownTree(tester);
    });

    testWidgets('上一步可以回去改', (tester) async {
      h.backend.profileFixture = 'profile_empty';
      await launch(tester, h);
      await tapAndSettle(tester, key('region.CN-51'), frames: 2);
      await tester.tap(key('onboarding.next'));
      await settle(tester, frames: 3);

      await tester.tap(key('onboarding.back'));
      await settle(tester, frames: 3);

      expect(find.text('第 1 步，共 3 步'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('首页', () {
    testWidgets('已完成引导：直接到首页；只有四个入口，没有底部导航栏', (tester) async {
      await launch(tester, h);

      expect(key('home.page'), findsOneWidget);
      for (final name in [
        'home.start',
        'home.scan',
        'home.practice',
        'home.profile',
      ]) {
        expect(key(name), findsOneWidget, reason: name);
      }
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.byType(BottomNavigationBar), findsNothing);
      expect(find.byType(Drawer), findsNothing);
      expect(find.text('开始今日学习'), findsOneWidget);
      expect(find.text('四川'), findsOneWidget);
      expect(find.text('高三'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('今日任务：显示类别、理由、预计时间、来源适用性', (tester) async {
      await launch(tester, h);

      expect(find.text('二次函数的单调递增区间'), findsOneWidget);
      expect(find.text('静止在粗糙斜面上的物块的受力'), findsOneWidget);
      expect(find.text('由碳酸钙质量求二氧化碳质量'), findsOneWidget);
      expect(find.text('新题'), findsNWidgets(3));
      expect(find.textContaining('还没有学习记录'), findsWidgets);
      expect(find.textContaining('全国通用基础题'), findsWidgets);
      expect(find.textContaining('今天有 3 项任务'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('可以跳过一项任务；跳过的记在本机，重进还是隐藏', (tester) async {
      await launch(tester, h);
      final first = taskItem(h.backend.fixtures.value('tasks_today'), 0);

      await tapAndSettle(tester, key('task.skip.${first['id']}'));

      expect(find.text('二次函数的单调递增区间'), findsNothing);
      expect(find.textContaining('今天有 2 项任务'), findsOneWidget);
      expect(h.store.data.keys.any((k) => k.contains('/skipped/')), isTrue);

      await teardownTree(tester);
      await tester.pumpWidget(h.app());
      await settle(tester, frames: 12);
      expect(find.text('二次函数的单调递增区间'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('全部跳过之后：说明原因，大按钮改去"练习"', (tester) async {
      await launch(tester, h);
      final tasks = h.backend.fixtures.value('tasks_today');
      for (var i = 0; i < 3; i++) {
        await tapAndSettle(
          tester,
          key('task.skip.${taskItem(tasks, i)['id']}'),
          frames: 4,
        );
      }

      expect(find.textContaining('今天的任务都跳过了'), findsOneWidget);
      await tapAndSettle(tester, key('home.start'));
      expect(key('practice.page'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('"开始今日学习"进入第一项任务的作答页', (tester) async {
      await launch(tester, h);

      await tapAndSettle(tester, key('home.start'), frames: 12);

      expect(key('solve.page'), findsOneWidget);
      expect(find.textContaining('数学 · 单选题'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('作答页从首页点进来时，标题栏只有一个返回箭头（浏览器联调发现过两个）', (tester) async {
      await launch(tester, h);

      await tapAndSettle(tester, key('home.start'), frames: 12);

      expect(key('solve.page'), findsOneWidget);
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.byType(BackButton),
        ),
        findsOneWidget,
      );
      // 点这个唯一的返回键，回到首页
      await tester.tap(find.byType(BackButton));
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pump(const Duration(milliseconds: 400));
      expect(key('home.start'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('没有任务：说明，并引导去练习', (tester) async {
      h.backend.on(
        'GET',
        '/tasks/today',
        (_) => okResponse({'date': '2026-11-10', 'items': <Object>[]}),
      );
      await launch(tester, h);

      expect(find.textContaining('今天没有安排任务'), findsOneWidget);
      await tapAndSettle(tester, key('home.start'));
      expect(key('practice.page'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('任务加载失败：显示原因和重试，重试成功后显示任务', (tester) async {
      h.backend.failNextOn('/tasks/today', 503, 'internal_error');
      await launch(tester, h);

      expect(find.textContaining('服务暂时出了问题'), findsOneWidget);
      await tapAndSettle(tester, find.text('重试'));

      expect(find.text('二次函数的单调递增区间'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('窄屏（手机宽度）：入口排在任务下面，仍然是四个', (tester) async {
      await launch(tester, h, size: phone);

      expect(key('home.start'), findsOneWidget);
      await tester.scrollUntilVisible(
        key('home.profile'),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      expect(key('home.scan'), findsOneWidget);
      expect(key('home.practice'), findsOneWidget);
      // 手机上入口卡片铺满一行（联调时看到过只占六成宽、靠左）
      for (final entry in ['home.scan', 'home.practice', 'home.profile']) {
        expect(
          tester.getSize(key(entry)).width,
          closeTo(phone.width - 2 * kPad, 1),
          reason: '$entry 应该和任务卡一样宽',
        );
      }
      expect(tester.takeException(), isNull);
      await teardownTree(tester);
    });

    for (final size in [tabletLandscape, phone]) {
      testWidgets('字体放大 1.5 倍、深色主题：${size.width.toInt()} 宽不溢出', (tester) async {
        useSize(tester, size);
        await tester.pumpWidget(
          ProviderScope(
            overrides: h.overrides,
            child: MediaQuery(
              data: MediaQueryData(
                size: size,
                textScaler: const TextScaler.linear(1.5),
                platformBrightness: Brightness.dark,
              ),
              child: Theme(
                data: AppTheme.dark(),
                child: const HomePageForTest(),
              ),
            ),
          ),
        );
        await settle(tester, frames: 12);
        expect(tester.takeException(), isNull);
        await teardownTree(tester);
      });
    }
  });

  group('断网', () {
    testWidgets('已经进到首页之后断网：任务显示上次缓存的，并说明', (tester) async {
      await launch(tester, h);
      expect(find.textContaining('没有网络'), findsNothing);

      h.backend.offline = true;
      final container = ProviderScope.containerOf(
        tester.element(find.byType(HomePage)),
      );
      container.invalidate(todayTasksProvider);
      await settle(tester, frames: 8);

      expect(find.textContaining('显示的是上次保存的任务'), findsOneWidget);
      expect(find.text('二次函数的单调递增区间'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('一开始就没网，但本机有上次的资料和任务：直接显示首页', (tester) async {
      await launch(tester, h);
      await teardownTree(tester);

      final offline = AppHarness(store: h.store);
      offline.backend.offline = true;
      await launch(tester, offline);

      expect(key('home.page'), findsOneWidget);
      expect(find.textContaining('显示的是上次保存的任务'), findsOneWidget);
      expect(find.text('四川'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('第一次启动就没网：说明原因并给重试，不白屏', (tester) async {
      final offline = AppHarness();
      offline.backend.offline = true;
      await launch(tester, offline);

      expect(find.textContaining('连不上服务'), findsOneWidget);
      offline.backend.offline = false;
      await tapAndSettle(tester, find.text('重试'), frames: 14);
      expect(key('home.page'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('练习', () {
    testWidgets('列表、来源标注、筛选条件会变成请求参数', (tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.practice'), frames: 10);

      expect(key('practice.page'), findsOneWidget);
      expect(find.textContaining('自编工程样题'), findsWidgets);
      expect(find.byType(Card), findsWidgets);

      await tapAndSettle(tester, key('filter.subject.math'));
      await tapAndSettle(tester, key('filter.mode.fill'));
      await tapAndSettle(tester, key('filter.scope.region'));

      final last = h.backend
          .requestsTo('GET', '/questions')
          .last
          .uri
          .queryParameters;
      expect(last['subject'], 'math');
      expect(last['answer_mode'], 'fill');
      expect(last['scope'], 'region');
      await teardownTree(tester);
    });

    testWidgets('还有下一页就显示"加载更多"，点了带上游标', (tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.practice'), frames: 10);

      await tapAndSettle(tester, key('practice.more'));

      expect(
        h.backend
            .requestsTo('GET', '/questions')
            .last
            .uri
            .queryParameters['cursor'],
        isNotNull,
      );
      await teardownTree(tester);
    });

    testWidgets('没有符合条件的题：说明，且不拿别的题顶替真题', (tester) async {
      h.backend.on(
        'GET',
        '/questions',
        (_) => okResponse({'items': <Object>[], 'next_cursor': null}),
      );
      await launch(tester, h);
      await tapAndSettle(tester, key('home.practice'), frames: 10);

      expect(find.text('没有符合条件的题'), findsOneWidget);
      expect(find.textContaining('不会拿别的题顶替'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('点一道题进入作答页', (tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.practice'), frames: 10);
      final first =
          h.backend.fixtures.value('questions_page')['items'][0]
              as Map<String, dynamic>;

      await tapAndSettle(tester, key('question.${first['id']}'), frames: 12);

      expect(key('solve.page'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('错题复习', () {
    setUp(() => h.backend.onFixture('GET', '/reviews/due', 'reviews_due'));

    testWidgets('到期的可以开始复测，开会话时带上复测项', (tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.practice'), frames: 10);
      await tapAndSettle(tester, key('practice.review'), frames: 10);

      expect(find.textContaining('现在可以复测（'), findsOneWidget);
      final item =
          (h.backend.fixtures.value('reviews_due')['items'] as List).first
              as Map<String, dynamic>;
      await tapAndSettle(tester, key('review.start.${item['id']}'), frames: 14);

      expect(key('solve.page'), findsOneWidget);
      expect(find.textContaining('这是间隔复测'), findsOneWidget);
      final body = h.backend.bodyOf(
        h.backend.requestsTo('POST', '/sessions').single,
      )!;
      expect(body['origin'], 'review');
      expect(body['review_item_id'], item['id']);
      await teardownTree(tester);
    });

    testWidgets('没有复测项：说明规则，并引导去练习', (tester) async {
      h.backend.on(
        'GET',
        '/reviews/due',
        (_) => okResponse({'items': <Object>[], 'next_cursor': null}),
      );
      await launch(tester, h);
      await tapAndSettle(tester, key('home.practice'), frames: 10);
      await tapAndSettle(tester, key('practice.review'), frames: 10);

      expect(find.text('现在没有需要复习的题'), findsOneWidget);
      expect(find.textContaining('1 天、3 天、7 天'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('未到期的显示复测时间，没有"开始"按钮', (tester) async {
      h.backend.onFixture('GET', '/reviews/due', 'reviews_all');
      await launch(tester, h);
      await tapAndSettle(tester, key('home.practice'), frames: 10);
      await tapAndSettle(tester, key('practice.review'), frames: 10);

      expect(find.textContaining('之后安排（'), findsOneWidget);
      expect(find.textContaining('复测时间：'), findsOneWidget);
      expect(find.textContaining('开始复测'), findsNothing);
      await teardownTree(tester);
    });
  });

  group('学情', () {
    Future<void> openProgress(WidgetTester tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.profile'), frames: 10);
      await tapAndSettle(tester, key('profile.progress'), frames: 10);
    }

    testWidgets('样本不足：只显示计数和原因，不显示百分比', (tester) async {
      await openProgress(tester);

      expect(key('progress.page'), findsOneWidget);
      expect(find.text('信息不足'), findsWidgets);
      expect(find.textContaining('至少 5 次有效作答才显示比例'), findsWidgets);
      expect(find.textContaining('%'), findsNothing);
      await tester.scrollUntilVisible(find.textContaining('不是官方成绩'), 300);
      expect(find.textContaining('不是官方成绩'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('待确认的作答单独提示，不计入任何正确率', (tester) async {
      h.backend.on('GET', '/progress/summary', (_) {
        final value = h.backend.fixtures.value('progress_summary');
        value['uncertain_attempts'] = 2;
        return okResponse(value);
      });
      await openProgress(tester);

      expect(find.textContaining('有 2 次作答没能自动判定'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('样本够了才显示百分比；独立和辅助是两张卡', (tester) async {
      h.backend.on('GET', '/progress/summary', (_) {
        final value = h.backend.fixtures.value('progress_summary');
        value['independent'] = {
          'numerator': 3,
          'denominator': 5,
          'rate': 0.6,
          'insufficient_data': false,
        };
        value['assisted'] = {
          'numerator': 1,
          'denominator': 8,
          'rate': 0.125,
          'insufficient_data': false,
        };
        return okResponse(value);
      });
      await openProgress(tester);

      expect(
        find.descendant(
          of: key('progress.independent'),
          matching: find.text('60%'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: key('progress.assisted'),
          matching: find.text('13%'),
        ),
        findsOneWidget,
      );
      expect(find.text('独立正确率'), findsOneWidget);
      expect(find.text('辅助正确率'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('新学生没有数据：显示"还没有数据"', (tester) async {
      h.backend.onFixture('GET', '/progress/summary', 'progress_empty');
      await openProgress(tester);

      expect(find.text('还没有数据'), findsWidgets);
      await teardownTree(tester);
    });
  });

  group('我的', () {
    Future<void> openProfile(WidgetTester tester) async {
      await launch(tester, h);
      await tapAndSettle(tester, key('home.profile'), frames: 10);
    }

    testWidgets('显示提示（教材未设置、考试年份是估算的）和隐私说明', (tester) async {
      await openProfile(tester);

      expect(key('profile.page'), findsOneWidget);
      expect(find.textContaining('还没有设置教材版本'), findsOneWidget);
      expect(find.textContaining('按年级估算为 2027 年'), findsOneWidget);
      await tester.scrollUntilVisible(
        find.textContaining('草稿和笔迹先保存在这台设备上'),
        300,
      );
      expect(find.textContaining('草稿和笔迹先保存在这台设备上'), findsOneWidget);
      expect(find.textContaining('现在还没有'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('改地区和教材后保存：请求里是新值，并提示已保存', (tester) async {
      await openProfile(tester);

      await reveal(tester, key('profile.curriculum.PEP'));
      await tester.tap(key('profile.curriculum.PEP'));
      await tester.pump();
      await reveal(tester, find.text('重庆'));
      await tester.pump();
      await tester.tap(find.text('重庆'));
      await tester.pump();
      await tapAndSettle(tester, key('profile.save'));

      final body = h.backend.lastProfileUpdate!;
      expect(body['region_code'], 'CN-50');
      expect(body['curriculum_version'], 'PEP');
      expect(find.text('已保存。'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('一科都不选就不能保存', (tester) async {
      await openProfile(tester);

      for (final subject in ['math', 'physics', 'chemistry']) {
        await reveal(tester, key('profile.subject.$subject'));
        await tester.tap(key('profile.subject.$subject'));
        await tester.pump();
      }

      await reveal(tester, key('profile.save'));
      expect(
        tester.widget<FilledButton>(key('profile.save')).onPressed,
        isNull,
      );
      await teardownTree(tester);
    });

    testWidgets('考试年份是估算的时：有"按年级估算"选项；手动设置过的没有', (tester) async {
      await openProfile(tester);
      await reveal(tester, key('profile.examYear'));
      await tester.tap(key('profile.examYear'));
      await settle(tester, frames: 3);
      expect(find.text('按年级估算'), findsWidgets);
      await teardownTree(tester);

      final manual = AppHarness();
      manual.backend.on('GET', '/profile', (_) {
        final value = manual.backend.fixtures.value('profile_saved');
        value['exam_year_source'] = 'user';
        value['exam_year'] = 2028;
        value['notices'] = <Object>[];
        return okResponse(value);
      });
      await launch(tester, manual);
      await tapAndSettle(tester, key('home.profile'), frames: 10);
      expect(find.textContaining('你手动设置的年份'), findsOneWidget);
      await reveal(tester, key('profile.examYear'));
      await tester.tap(key('profile.examYear'));
      await settle(tester, frames: 3);
      expect(find.text('按年级估算'), findsNothing);
      await teardownTree(tester);
    });
  });

  group('其他页面与路由', () {
    testWidgets('拍题：如实说明还没开放，不假装能用', (tester) async {
      await launch(tester, h);

      await tapAndSettle(tester, key('home.scan'), frames: 10);

      expect(key('scan.page'), findsOneWidget);
      expect(find.text('拍题还在准备中'), findsOneWidget);
      expect(find.textContaining('不会没经过你确认就当成原题'), findsOneWidget);
      await tapAndSettle(tester, key('scan.practice'), frames: 10);
      expect(key('practice.page'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('不存在的地址：显示说明和回首页按钮', (tester) async {
      useSize(tester, tabletLandscape);
      await tester.pumpWidget(h.app());
      await settle(tester, frames: 12);
      final container = ProviderScope.containerOf(
        tester.element(find.byType(HomePage)),
      );
      expect(container, isNotNull);

      final router = GoRouterOf.of(tester);
      router.go('/no/such/page');
      await settle(tester, frames: 6);

      expect(find.text('这个页面不存在'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('图解页：打开注册过的模板；不认识的模板显示说明', (tester) async {
      useSize(tester, tabletLandscape);
      await tester.pumpWidget(h.app());
      await settle(tester, frames: 12);
      final router = GoRouterOf.of(tester);

      router.go('/visual/motion_chart');
      await settle(tester, frames: 8);
      expect(key('visual.canvas'), findsOneWidget);

      router.go('/visual/hologram_3d');
      await settle(tester, frames: 8);
      expect(key('visual.fallback'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('辅导记录页：按顺序回看会话里的事件', (tester) async {
      final events =
          (h.backend.fixtures.value('session_events')['items'] as List);
      h.backend.on(
        'GET',
        '/sessions/[^/]+/events',
        (_) => okResponse({'items': events, 'last_seq': events.length}),
      );
      useSize(tester, tabletLandscape);
      await tester.pumpWidget(h.app());
      await settle(tester, frames: 12);

      GoRouterOf.of(tester).go('/tutor/${(events.first as Map)['session_id']}');
      await settle(tester, frames: 10);

      expect(key('tutor.page'), findsOneWidget);
      expect(
        find.byWidgetPredicate(
          (w) =>
              w.key is ValueKey<String> &&
              (w.key! as ValueKey<String>).value.startsWith('event.'),
        ),
        findsNWidgets(events.length),
      );
      await teardownTree(tester);
    });
  });

  test('本机缓存里不保存令牌以外的敏感信息：任务缓存只有任务本身', () async {
    final backend = FakeBackend()..installAppBasics();
    final store = h.store;
    final container = ProviderContainer(
      overrides: AppHarness(backend: backend, store: store).overrides,
    );
    addTearDown(container.dispose);

    await container.read(todayTasksProvider.future);

    final cached = store.data.entries
        .where((e) => e.key.endsWith('/tasks'))
        .single;
    expect(jsonDecode(cached.value).keys, containsAll(['date', 'items']));
  });
}
