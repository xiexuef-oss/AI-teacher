import 'dart:convert';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/core/adaptive_split.dart';
import 'package:tutor_student/core/theme.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

Finder key(String name) => find.byKey(ValueKey(name));

Future<void> open(
  WidgetTester tester,
  AppHarness h, {
  Size size = tabletLandscape,
  String origin = 'practice',
  String? reviewItemId,
  double textScale = 1,
  ThemeData? theme,
  String? questionId,
}) async {
  useSize(tester, size);
  await tester.pumpWidget(
    h.solvePage(
      origin: origin,
      reviewItemId: reviewItemId,
      textScale: textScale,
      theme: theme,
      questionId: questionId ?? '',
    ),
  );
  await settle(tester);
}

Future<void> choose(WidgetTester tester, String option) async {
  await tester.tap(key('option.$option'));
  await tester.pump();
}

double paneWidth(WidgetTester tester, String name) =>
    tester.getSize(key(name)).width;

void main() {
  late AppHarness h;
  setUp(() => h = AppHarness());

  group('布局断点', () {
    testWidgets('≥900：题目 42% / 草稿 58%，并排', (tester) async {
      await open(tester, h);

      final left = tester.getRect(key('split.primary'));
      final right = tester.getRect(key('split.secondary'));
      expect(left.top, right.top);
      expect(left.right, lessThanOrEqualTo(right.left));
      final usable = tabletLandscape.width - 24;
      expect(left.width / usable, closeTo(0.42, 0.005));
      expect(key('solve.questionPane'), findsOneWidget);
      expect(key('solve.scratchPane'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('分隔条可以拖动，范围限制在 35%–60%', (tester) async {
      await open(tester, h);
      final usable = tabletLandscape.width - 24;
      double fraction() => paneWidth(tester, 'split.primary') / usable;

      await tester.drag(key('split.divider'), const Offset(-900, 0));
      await tester.pump();
      expect(fraction(), closeTo(AdaptiveSplit.minFraction, 0.005));

      await tester.drag(key('split.divider'), const Offset(1400, 0));
      await tester.pump();
      expect(fraction(), closeTo(AdaptiveSplit.maxFraction, 0.005));

      await tester.drag(key('split.divider'), const Offset(-200, 0));
      await tester.pump();
      expect(fraction(), inInclusiveRange(0.35, 0.60));
      await teardownTree(tester);
    });

    testWidgets('键盘左右键微调分隔条', (tester) async {
      await open(tester, h);
      final before = paneWidth(tester, 'split.primary');
      await tester.tap(key('split.divider'));
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
      await tester.pump();
      expect(paneWidth(tester, 'split.primary'), greaterThan(before));
      await teardownTree(tester);
    });

    testWidgets('600–899 横屏：仍然并排，但分隔条不能拖', (tester) async {
      await open(tester, h, size: mediumLandscape);

      expect(
        tester.getRect(key('split.primary')).top,
        tester.getRect(key('split.secondary')).top,
      );
      final before = paneWidth(tester, 'split.primary');
      await tester.drag(
        key('split.divider'),
        const Offset(-200, 0),
        warnIfMissed: false,
      );
      await tester.pump();
      expect(paneWidth(tester, 'split.primary'), before);
      await teardownTree(tester);
    });

    testWidgets('600–899 竖屏：上下排列', (tester) async {
      await open(tester, h, size: const Size(700, 1000));

      final top = tester.getRect(key('split.primary'));
      final bottom = tester.getRect(key('split.secondary'));
      expect(top.bottom, lessThanOrEqualTo(bottom.top));
      expect(top.width, bottom.width);
      await teardownTree(tester);
    });

    testWidgets('<600：单栏，底部切换"题目/草稿"，切换时草稿不丢', (tester) async {
      await open(tester, h, size: phone);
      expect(key('split.tabs'), findsOneWidget);

      await tester.tap(find.text('草稿'));
      await settle(tester, frames: 2);
      final gesture = await tester.startGesture(
        const Offset(200, 300),
        kind: PointerDeviceKind.stylus,
      );
      await gesture.moveBy(const Offset(60, 40));
      await gesture.up();
      await settle(tester, frames: 2);
      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNotNull,
        reason: '画了一笔',
      );

      await tester.tap(find.text('题目'));
      await settle(tester, frames: 2);
      await tester.tap(find.text('草稿'));
      await settle(tester, frames: 2);
      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNotNull,
        reason: '切换之后笔迹还在',
      );
      await teardownTree(tester);
    });

    for (final size in [
      tabletLandscape,
      tabletPortrait,
      mediumLandscape,
      phone,
    ]) {
      testWidgets(
        '字体放大 1.5 倍不溢出：${size.width.toInt()}×${size.height.toInt()}',
        (tester) async {
          await open(tester, h, size: size, textScale: 1.5);
          await tester.tap(key('option.B'));
          await settle(tester, frames: 3);
          expect(tester.takeException(), isNull);
          await teardownTree(tester);
        },
      );
    }

    testWidgets('深色主题能正常显示', (tester) async {
      await open(tester, h, theme: AppTheme.dark());
      expect(find.textContaining('二次函数'), findsWidgets);
      expect(tester.takeException(), isNull);
      await teardownTree(tester);
    });
  });

  group('作答', () {
    testWidgets('顶栏显示学科、题型和保存状态；不选就不能提交', (tester) async {
      await open(tester, h);

      expect(find.textContaining('数学 · 单选题 · 难度 2'), findsOneWidget);
      expect(
        find.descendant(
          of: key('solve.saveStatus'),
          matching: find.text('已保存 · 已同步'),
        ),
        findsOneWidget,
      );
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
      );
      await teardownTree(tester);
    });

    testWidgets('题干里的公式能渲染，来源标明是自编工程样题', (tester) async {
      await open(tester, h);
      expect(find.textContaining('自编工程样题'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await teardownTree(tester);
    });

    testWidgets('选一个选项后可以提交；答错后看到判定和下一步', (tester) async {
      await open(tester, h);

      await tester.tap(key('option.A'));
      await settle(tester, frames: 2);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNotNull,
      );

      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('这次没答对'), findsOneWidget);
      expect(find.text('这是练习反馈，不是官方阅卷分数。'), findsOneWidget);
      expect(key('action.standard'), findsOneWidget);
      expect(key('action.retry'), findsOneWidget);
      expect(key('action.understood'), findsOneWidget);
      expect(key('action.submit'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('提交之后答案区变成只读', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('你提交的答案'), findsOneWidget);
      final tile = tester.widget<InkWell>(key('option.B'));
      expect(tile.onTap, isNull);
      await teardownTree(tester);
    });

    testWidgets('判不出来：显示"待确认"，并说明不计入正确率', (tester) async {
      h.backend.submitFixture = 'submit_uncertain';
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('待确认'), findsOneWidget);
      expect(find.text('这次不算对，也不算错，不会计入正确率。'), findsOneWidget);
      expect(find.text('答对了'), findsNothing);
      expect(find.text('这次没答对'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('答对了：显示"答对了"', (tester) async {
      h.backend.submitFixture = 'submit_correct';
      await open(tester, h);
      await choose(tester, 'B');
      await tester.tap(key('action.submit'));
      await settle(tester);
      expect(find.text('答对了'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('再试一次：新建作答，答案清空，回到作答状态', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.retry'));
      await settle(tester);

      expect(key('action.submit'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
      );
      expect(h.backend.attemptsCreated, 2);
      await teardownTree(tester);
    });
  });

  group('提示与解析', () {
    testWidgets('给点提示：每次一层，按钮上显示进度', (tester) async {
      await open(tester, h);
      expect(find.text('给点提示（0/3）'), findsOneWidget);

      await tester.tap(key('action.hint'));
      await settle(tester);

      expect(find.textContaining('提示 第 1/3 层'), findsOneWidget);
      expect(find.text('给点提示（1/3）'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('提交前"我想直接看解析"：先确认；取消则什么都不泄露', (tester) async {
      await open(tester, h);

      await tester.tap(key('action.giveUp'));
      await settle(tester, frames: 3);
      expect(find.text('现在就看解析吗？'), findsOneWidget);
      expect(find.textContaining('不再算“独立作答”'), findsOneWidget);

      await tester.tap(key('dialog.giveUp.cancel'));
      await settle(tester, frames: 3);
      expect(find.text('常规解法'), findsNothing);
      expect(find.textContaining('答案：'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('确认之后才显示解析，带逐项分析', (tester) async {
      await open(tester, h);
      await tester.tap(key('action.giveUp'));
      await settle(tester, frames: 3);
      await tester.tap(key('dialog.giveUp.confirm'));
      await settle(tester);

      expect(find.text('常规解法'), findsWidgets);
      expect(find.text('逐项分析'), findsOneWidget);
      expect(find.text('答案：'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('快速解法：显示适用条件和不适用的情形', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.fast'));
      await settle(tester);

      expect(find.text('适用条件'), findsOneWidget);
      expect(find.text('不适用的情形'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('看图理解：图解出现在时间线里，滑块可以拖', (tester) async {
      await open(tester, h);

      await tester.tap(key('action.visual'));
      await settle(tester);

      expect(key('visual.canvas'), findsOneWidget);
      expect(key('visual.slider.a'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('"还是不懂"：换种讲法的内容带来源标注（AI 生成）', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.confused'));
      await settle(tester);

      expect(find.text('换种讲法'), findsOneWidget);
      expect(find.textContaining('AI 生成'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('"我懂了"：给出复测安排并结束这次学习', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.understood'));
      await settle(tester);

      expect(find.textContaining('已经安排了复测'), findsOneWidget);
      expect(key('action.done'), findsOneWidget);
      expect(key('action.retry'), findsNothing);
      await teardownTree(tester);
    });
  });

  group('复测', () {
    testWidgets('提交前没有提示和解析按钮，并说明原因', (tester) async {
      await open(tester, h, origin: 'review', reviewItemId: 'review-item-1');

      expect(find.textContaining('这是间隔复测'), findsOneWidget);
      expect(key('action.hint'), findsNothing);
      expect(key('action.visual'), findsNothing);
      expect(key('action.giveUp'), findsNothing);
      expect(key('action.submit'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('提交之后出现复测结果和解析按钮', (tester) async {
      h.backend.submitFixture = 'submit_correct';
      await open(tester, h, origin: 'review', reviewItemId: 'review-item-1');
      await choose(tester, 'B');
      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('这次复测通过了'), findsOneWidget);
      expect(key('action.standard'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('断网与冲突', () {
    testWidgets('断网：顶栏变成"未同步"，出现重试按钮，草稿照常保存在本机', (tester) async {
      await open(tester, h);
      h.backend.offline = true;

      await tester.tap(key('option.C'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      expect(
        find.descendant(
          of: key('solve.saveStatus'),
          matching: find.text('已存在本机 · 未同步'),
        ),
        findsOneWidget,
      );
      expect(key('banner.retry'), findsOneWidget);
      expect(h.store.data.keys.any((k) => k.contains('/draft/')), isTrue);

      h.backend.offline = false;
      await tester.tap(key('banner.retry'));
      await settle(tester);
      expect(
        find.descendant(
          of: key('solve.saveStatus'),
          matching: find.text('已保存 · 已同步'),
        ),
        findsOneWidget,
      );
      await teardownTree(tester);
    });

    testWidgets('断网时提交：说明原因，答案还在', (tester) async {
      await open(tester, h);
      await choose(tester, 'C');
      h.backend.offline = true;

      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.textContaining('连不上服务'), findsWidgets);
      expect(key('action.submit'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('版本冲突：同时展示两边的内容，选"保留我的"之后恢复', (tester) async {
      await open(tester, h);
      await tester.tap(key('option.A'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);
      h.backend
        ..serverRevision = 5
        ..serverAnswer = {
          'selected_options': ['D'],
        };

      await tester.tap(key('option.B'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      expect(find.text('这份草稿在别处有了更新'), findsOneWidget);
      expect(find.textContaining('你这边：选了 B'), findsOneWidget);
      expect(find.textContaining('云端的：选了 D'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
        reason: '有冲突先解决',
      );

      await tester.tap(key('banner.keepLocal'));
      await settle(tester);
      expect(find.text('这份草稿在别处有了更新'), findsNothing);
      expect(h.backend.serverAnswer, {
        'selected_options': ['B'],
      });
      await teardownTree(tester);
    });

    testWidgets('版本冲突：选"用云端的"，本地选项换成云端的', (tester) async {
      await open(tester, h);
      await tester.tap(key('option.A'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);
      h.backend
        ..serverRevision = 5
        ..serverAnswer = {
          'selected_options': ['D'],
        };
      await tester.tap(key('option.B'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      await tester.tap(key('banner.useServer'));
      await settle(tester);

      expect(find.text('这份草稿在别处有了更新'), findsNothing);
      expect(
        find.byIcon(Icons.check_circle),
        findsOneWidget,
        reason: '只有被选中的 D 带对勾',
      );
      await teardownTree(tester);
    });

    testWidgets('登录失效：保留草稿并给出"重新登录"', (tester) async {
      await open(tester, h);
      h.backend.failNext = (401, 'unauthenticated');

      await tester.tap(key('option.C'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      expect(find.textContaining('登录已经失效'), findsOneWidget);
      expect(key('banner.relogin'), findsOneWidget);
      expect(h.store.data.keys.any((k) => k.contains('/draft/')), isTrue);
      await teardownTree(tester);
    });

    testWidgets('没有网络又没有缓存：显示错误和重试，不白屏', (tester) async {
      final offline = AppHarness();
      offline.backend.offline = true;
      await open(tester, offline);

      expect(find.textContaining('连不上服务'), findsOneWidget);
      expect(find.text('重试'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('填空题', () {
    Future<void> openFill(WidgetTester tester) async {
      final fillHarness = AppHarness(
        backend: FakeBackend()
          ..installLearningFlow(questionFixture: 'question_fill'),
      );
      await open(
        tester,
        fillHarness,
        questionId: Fixtures.load().value('question_fill')['id'] as String,
      );
    }

    testWidgets('输入框带单位提示；输入后才能提交', (tester) async {
      await openFill(tester);

      expect(find.text('需要写单位'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
      );
      await tester.enterText(key('blank.b1'), '5 m/s²');
      await settle(tester, frames: 2);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNotNull,
      );
      await teardownTree(tester);
    });

    testWidgets('符号栏把符号插到光标处，并同步到答案', (tester) async {
      await openFill(tester);
      await tester.enterText(key('blank.b1'), '5');
      await tester.pump();

      await tester.tap(key('symbol.²'));
      await tester.pump();

      expect(tester.widget<TextField>(key('blank.b1')).controller!.text, '5²');
      await teardownTree(tester);
    });

    testWidgets('符号按钮不小于 44×44', (tester) async {
      await openFill(tester);
      for (final symbol in ['√', 'π', '²', '≤', '∞']) {
        final size = tester.getSize(key('symbol.$symbol'));
        expect(size.width, greaterThanOrEqualTo(44), reason: symbol);
        expect(size.height, greaterThanOrEqualTo(44), reason: symbol);
      }
      await teardownTree(tester);
    });
  });

  group('触控目标', () {
    testWidgets('底栏和选项的点击区域不小于 44×44', (tester) async {
      await open(tester, h);
      for (final name in [
        'action.submit',
        'action.hint',
        'action.visual',
        'option.A',
        'option.D',
      ]) {
        final size = tester.getSize(key(name));
        expect(size.width, greaterThanOrEqualTo(44), reason: name);
        expect(size.height, greaterThanOrEqualTo(44), reason: name);
      }
      await teardownTree(tester);
    });
  });

  group('草稿画布', () {
    Future<void> stroke(
      WidgetTester tester, {
      PointerDeviceKind kind = PointerDeviceKind.stylus,
      Offset from = const Offset(900, 300),
    }) async {
      final gesture = await tester.startGesture(from, kind: kind);
      await gesture.moveBy(const Offset(40, 20));
      await gesture.moveBy(const Offset(40, 20));
      await gesture.up();
      await tester.pump();
    }

    testWidgets('手写笔画一笔：撤销键亮起；2 秒后落到本机', (tester) async {
      await open(tester, h);
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNull);

      await stroke(tester);

      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNotNull);
      await tester.pump(const Duration(seconds: 3));
      await settle(tester, frames: 3);
      final saved = h.store.data.entries.firstWhere(
        (e) => e.key.contains('/draft/'),
      );
      final json = jsonDecode(saved.value) as Map<String, dynamic>;
      expect(
        ((json['strokes'] as Map)['pages'] as List).first['strokes'],
        isNotEmpty,
      );
      await teardownTree(tester);
    });

    testWidgets('见过手写笔之后，手指不再书写（防手掌误触）', (tester) async {
      await open(tester, h);
      await stroke(tester);
      await tester.tap(key('ink.undo'));
      await tester.pump();
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNull);

      await stroke(tester, kind: PointerDeviceKind.touch);

      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNull,
        reason: '手指的一笔被忽略',
      );
      await teardownTree(tester);
    });

    testWidgets('没用过手写笔时手指可以写；"移动"工具下任何输入都不写', (tester) async {
      await open(tester, h);
      await stroke(tester, kind: PointerDeviceKind.touch);
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNotNull);

      await tester.tap(key('ink.tool.hand'));
      await tester.tap(key('ink.undo'));
      await tester.pump();
      await stroke(tester, kind: PointerDeviceKind.touch);
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNull);
      await teardownTree(tester);
    });

    testWidgets('橡皮擦掉一笔；撤销找回', (tester) async {
      await open(tester, h);
      await stroke(tester);
      await tester.tap(key('ink.tool.eraser'));
      await tester.pump();

      final gesture = await tester.startGesture(
        const Offset(920, 310),
        kind: PointerDeviceKind.stylus,
      );
      await gesture.up();
      await tester.pump();
      await tester.tap(key('ink.undo'));
      await tester.pump();

      expect(
        tester.widget<IconButton>(key('ink.redo')).onPressed,
        isNotNull,
        reason: '撤销了擦除，所以可以重做',
      );
      await teardownTree(tester);
    });

    testWidgets('清空要二次确认；取消不清，确认才清，并且可以撤销', (tester) async {
      await open(tester, h);
      await stroke(tester);

      await tester.tap(key('ink.clear'));
      await settle(tester, frames: 3);
      expect(find.text('清空草稿？'), findsOneWidget);
      await tester.tap(key('ink.clear.cancel'));
      await settle(tester, frames: 3);
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNotNull,
        reason: '还有笔迹',
      );

      await tester.tap(key('ink.clear'));
      await settle(tester, frames: 3);
      await tester.tap(key('ink.clear.confirm'));
      await settle(tester, frames: 3);
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNull,
        reason: '清空了',
      );

      await tester.tap(key('ink.undo'));
      await tester.pump();
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNotNull,
        reason: '撤销找回',
      );
      await teardownTree(tester);
    });

    testWidgets('可以加页，也可以换颜色和粗细', (tester) async {
      await open(tester, h);
      await tester.ensureVisible(key('ink.addPage'));
      await tester.pump();
      await tester.tap(key('ink.addPage'));
      await tester.pump();
      expect(key('ink.page.1'), findsOneWidget);

      await tester.tap(key('ink.color.blue'));
      await tester.tap(key('ink.width.thick'));
      await tester.pump();
      expect(find.byIcon(Icons.check), findsWidgets);
      await teardownTree(tester);
    });

    testWidgets('导出图片：生成 PNG 预览', (tester) async {
      await open(tester, h);
      await stroke(tester);

      await tester.runAsync(() async {
        await tester.tap(key('ink.export'));
        await Future<void>.delayed(const Duration(milliseconds: 600));
      });
      await settle(tester, frames: 4);

      expect(find.text('草稿图片'), findsOneWidget);
      expect(key('ink.export.preview'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('重新打开同一道题：笔迹和答案从本机恢复，不重复开会话', (tester) async {
      await open(tester, h);
      await tester.tap(key('option.C'));
      await stroke(tester);
      await tester.pump(const Duration(seconds: 6));
      await settle(tester);
      await teardownTree(tester);
      final sessions = h.backend.sessionsCreated;

      await tester.pumpWidget(h.solvePage());
      await settle(tester);

      expect(h.backend.sessionsCreated, sessions);
      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNull,
        reason: '恢复出来的内容没有撤销历史',
      );
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNotNull,
        reason: '但笔迹在',
      );
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNotNull,
        reason: '选项也恢复了',
      );
      await teardownTree(tester);
    });
  });

  group('解答题', () {
    late AppHarness w;
    late String writtenId;

    setUp(() {
      final backend = FakeBackend()
        ..submitFixture = 'submit_written'
        ..installAppBasics()
        ..installLearningFlow(questionFixture: 'question_written');
      w = AppHarness(backend: backend);
      writtenId = Fixtures.load().value('question_written')['id'] as String;
    });

    Future<void> openWritten(
      WidgetTester tester, {
      Size size = tabletLandscape,
      double textScale = 1,
    }) => open(
      tester,
      w,
      size: size,
      questionId: writtenId,
      textScale: textScale,
    );

    Future<void> write(WidgetTester tester, String part, String text) async {
      await tester.enterText(key('part.$part'), text);
      await tester.pump();
    }

    /// 滚到看得见再点（滚动之后要等一帧，位置才会更新）。
    Future<void> tapKey(WidgetTester tester, String name) async {
      await tester.ensureVisible(key(name));
      await tester.pump();
      await tester.tap(key(name));
      await tester.pump();
    }

    Future<void> submit(WidgetTester tester) async {
      await tapKey(tester, 'action.submit');
      await settle(tester, frames: 12);
    }

    List<String> pointKeys() =>
        ((Fixtures.load().value('self_check_pending')['points'] as List)
                .cast<Map<String, dynamic>>())
            .map((p) => p['key'] as String)
            .toList();

    testWidgets('每个小问一个输入框，先说明不自动评分；没写之前不能提交', (tester) async {
      await openWritten(tester);

      expect(key('part.1'), findsOneWidget);
      expect(key('part.2'), findsOneWidget);
      expect(find.textContaining('不自动评分'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
      );
      expect(key('selfcheck.card'), findsNothing, reason: '提交之前不给要点');
      await teardownTree(tester);
    });

    testWidgets('提交之前页面上看不到任何自查要点的内容', (tester) async {
      await openWritten(tester);
      await write(tester, '1', '对称轴是 x=a');

      final points =
          (Fixtures.load().value('self_check_pending')['points'] as List)
              .cast<Map<String, dynamic>>();
      expect(w.backend.requestsTo('GET', '/self-check'), isEmpty);
      for (final point in points) {
        expect(find.textContaining(point['text'] as String), findsNothing);
      }
      await teardownTree(tester);
    });

    testWidgets('写了才能提交；提交后出现对照自查，没有对错', (tester) async {
      await openWritten(tester);
      await write(tester, '1', '对称轴是 x=a，开口向上');
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNotNull,
      );

      await submit(tester);

      expect(key('selfcheck.card'), findsOneWidget);
      for (final k in pointKeys()) {
        await tester.ensureVisible(key('selfcheck.point.$k'));
        await tester.pump();
        expect(key('selfcheck.point.$k'), findsOneWidget, reason: k);
      }
      await tester.dragUntilVisible(
        find.text('这道题不自动评分'),
        key('solve.questionPane'),
        const Offset(0, -300),
      );
      expect(find.text('这道题不自动评分'), findsOneWidget);
      expect(find.text('待确认'), findsNothing, reason: '不是"没能判定"');
      expect(find.text('回答正确'), findsNothing);
      expect(find.textContaining('官方'), findsWidgets);
      await teardownTree(tester);
    });

    testWidgets('提交之后自动滚到自查要点的顶部', (tester) async {
      await openWritten(tester, size: tabletPortrait);
      await write(tester, '1', '写了第一问');

      await submit(tester);
      await settle(tester, frames: 12);

      final top = tester.getTopLeft(key('selfcheck.card')).dy;
      expect(top, greaterThanOrEqualTo(0));
      expect(top, lessThan(tabletPortrait.height / 2), reason: '卡片顶部在视口上半部分');
      await teardownTree(tester);
    });

    testWidgets('标完所有要点才能保存；保存后只显示计数，没有分数', (tester) async {
      await openWritten(tester);
      await write(tester, '1', '写了第一问');
      await submit(tester);
      FilledButton saveButton() =>
          tester.widget<FilledButton>(key('selfcheck.save'));
      expect(saveButton().onPressed, isNull);

      final keys = pointKeys();
      for (final k in keys.skip(1)) {
        await tapKey(tester, 'selfcheck.$k.done');
      }
      expect(saveButton().onPressed, isNull, reason: '还差一条');
      await tapKey(tester, 'selfcheck.${keys.first}.missed');
      expect(saveButton().onPressed, isNotNull);

      await tapKey(tester, 'selfcheck.save');
      await settle(tester, frames: 6);

      final summary = tester.widget<Text>(key('selfcheck.summary')).data!;
      expect(summary, contains('做到了 ${keys.length - 1}'));
      expect(summary, contains('没做到 1'));
      expect(summary, contains('共 ${keys.length} 条'));
      expect(summary, isNot(contains('%')));
      expect(
        find.textContaining(RegExp(r'\d+\s*分(?!之)')),
        findsNothing,
        reason: '不出现"几分"',
      );
      expect(w.backend.selfCheckMarks, hasLength(keys.length));
      // 保存之后没有改动，就不能再保存；改一条才行
      expect(saveButton().onPressed, isNull);
      await tapKey(tester, 'selfcheck.${keys.first}.partial');
      expect(saveButton().onPressed, isNotNull);
      await teardownTree(tester);
    });

    testWidgets('取要点失败时给出重试，作答仍是已提交', (tester) async {
      await openWritten(tester);
      await write(tester, '1', '写了第一问');
      w.backend.failNextOn('/self-check', 503, 'service_unavailable');

      await submit(tester);

      expect(key('selfcheck.card'), findsOneWidget);
      expect(key('selfcheck.retry'), findsOneWidget);
      expect(key('selfcheck.save'), findsNothing);

      await tapKey(tester, 'selfcheck.retry');
      await settle(tester, frames: 6);
      expect(key('selfcheck.retry'), findsNothing);
      expect(key('selfcheck.point.${pointKeys().first}'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('提交之后的输入框是只读的，写的内容还在', (tester) async {
      await openWritten(tester);
      await write(tester, '2', '最小值 -1');
      await submit(tester);
      await tester.dragUntilVisible(
        key('part.2'),
        key('solve.questionPane'),
        const Offset(0, 300),
      );

      final field = tester.widget<TextField>(key('part.2'));
      expect(field.enabled, isFalse);
      expect(field.controller!.text, '最小值 -1');
      await teardownTree(tester);
    });

    for (final size in [tabletLandscape, tabletPortrait, phone]) {
      testWidgets(
        '字体放大 1.5 倍不溢出：${size.width.toInt()}×${size.height.toInt()}',
        (tester) async {
          await openWritten(tester, size: size, textScale: 1.5);
          await write(tester, '1', '写了第一问');
          await submit(tester);
          for (final k in pointKeys()) {
            await tapKey(tester, 'selfcheck.$k.done');
          }
          await tester.ensureVisible(key('selfcheck.save'));
          await settle(tester, frames: 3);
          expect(
            tester.widget<FilledButton>(key('selfcheck.save')).onPressed,
            isNotNull,
            reason: '都标完了，能保存',
          );
          expect(tester.takeException(), isNull);
          await teardownTree(tester);
        },
      );
    }

    testWidgets('自查的每个选项点得到：触控目标不小于 48', (tester) async {
      await openWritten(tester);
      await write(tester, '1', '写了第一问');
      await submit(tester);

      final k = pointKeys().first;
      for (final level in ['done', 'partial', 'missed']) {
        await tester.ensureVisible(key('selfcheck.$k.$level'));
        await tester.pump();
        final size = tester.getSize(key('selfcheck.$k.$level'));
        expect(
          size.height,
          greaterThanOrEqualTo(AppTheme.minTarget),
          reason: level,
        );
      }
      await teardownTree(tester);
    });
  });
}
